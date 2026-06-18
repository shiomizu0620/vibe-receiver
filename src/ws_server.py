"""WebSocket 配信サーバー（段1: ブラウザ演出のリアルタイム駆動）。

受信パイプライン（チャンネル → decode → display）の進行イベントを、ブラウザの演出HTMLへ
WebSocket で配信する。**受信処理を一切ブロックしない**よう、asyncio のイベントループを
専用のデーモンスレッドで回し、broadcast() はそのループへスレッド安全に「投げるだけ」にする。

CLAUDE.md のアーキテクチャ方針との関係:
- decode/display/lookup はチャンネルを知らない。このサーバーも「進行イベント(dict)を配るだけ」で、
  どのチャンネルか・どんな演出かは知らない。main が Display.on_event を broadcast に結線する。
- 既存のターミナル演出(rich)はそのまま動く。これは演出を「消さずに追加」する別経路の配信。

配信するイベント JSON（main / display が broadcast する種類。詳細は display.py / main.py）:
    {"type":"listening"}                 # 待機開始
    {"type":"preamble"}                  # プリアンブル検出
    {"type":"bit","value":0|1}           # データビット確定（1個ずつ・MSB first）
    {"type":"decoded","id":42}           # id 確定
    {"type":"url","url":"https://..."}   # 逆引き結果
    {"type":"open","url":"https://..."}  # オープン
"""
import asyncio
import json
import logging
import threading

import websockets

from . import config

_LOGGER = logging.getLogger(__name__)


class WsServer:
    """接続中のクライアント全員へ JSON イベントを配信する WebSocket サーバー。

    使い方:
        ws = WsServer()                      # 既定 ws://localhost:8765
        ws.start()                           # 非ブロッキング（専用スレッドで起動）
        ws.broadcast({"type": "listening"})  # どのスレッドから呼んでもよい・待たない
        ws.stop()                            # 終了（未起動でも多重呼び出しでも安全）

    broadcast() は送信完了を待たず（run_coroutine_threadsafe で投げるだけ）、受信ループ側を
    一切ブロックしない。クライアントが居なければ何もしない。
    """

    def __init__(self, host: str = config.WS_HOST, port: int = config.WS_PORT):
        self._host = host
        self._port = port
        self._clients: set = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()           # listen 成否が確定したら set
        self._stop_future: asyncio.Future | None = None
        self._serving = False                     # listen に成功して配信できる状態か
        self._start_error: Exception | None = None  # listen 失敗の原因（ポート競合など）

    @property
    def is_serving(self) -> bool:
        """listen に成功して配信中なら True（呼び出し元の成功表示の判定に使う）。"""
        return self._serving

    @property
    def start_error(self) -> Exception | None:
        """listen 失敗時の例外（成功なら None）。"""
        return self._start_error

    @property
    def client_count(self) -> int:
        """現在接続中のクライアント数。"""
        return len(self._clients)

    # ---- ライフサイクル -------------------------------------------------------

    def start(self, timeout: float = 5.0) -> bool:
        """専用スレッドでイベントループを起動し、listen 成否が確定するまで待つ。

        戻り値は配信できる状態になったか（True=配信中 / False=起動失敗・タイムアウト）。
        listen に失敗しても例外にはしない。ブラウザ配信が無いだけで、ターミナル演出と受信は
        続行できるため、呼び出し元（main）が戻り値を見て案内を出し分けられるようにする。
        """
        if self._thread is not None and self._thread.is_alive():
            return self._serving
        self._ready.clear()
        self._serving = False
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="ws-server", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self._serving

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve())
        finally:
            loop.close()
            self._loop = None  # 停止後の broadcast/stop が閉じたループを触らないように

    async def _serve(self) -> None:
        self._stop_future = self._loop.create_future()
        try:
            async with websockets.serve(self._handler, self._host, self._port):
                self._serving = True         # listen 成功
                self._ready.set()            # 成否確定を start() に通知
                await self._stop_future      # stop() が解決するまで起動し続ける
        except Exception as exc:             # listen 失敗（ポート競合など）
            if not self._serving:            # 起動前の失敗だけを start エラーとして記録
                self._start_error = exc
                _LOGGER.debug("WebSocket サーバーの起動に失敗", exc_info=True)
        finally:
            self._serving = False
            self._ready.set()                # 失敗時も start() を解放する

    async def _handler(self, websocket, path=None) -> None:
        """1クライアント分の接続。集合に登録し、切断まで保持する。

        段1ではクライアントからの受信は使わないが、async for で受け流すことで
        接続を維持し、ping/pong などはライブラリ任せにする。path 引数は
        websockets のバージョン差（旧 API は (websocket, path)）を吸収するため。
        """
        self._clients.add(websocket)
        try:
            async for _ in websocket:
                pass  # クライアント→サーバー方向は段1では未使用（受け流す）
        except websockets.ConnectionClosed:
            pass      # 正常・異常いずれの切断もここで収束（finally で集合から除去）
        except Exception:
            # 想定外の例外は静かに消さず debug ログに残す（挙動は変えず調査可能にする）。
            _LOGGER.debug("WebSocket ハンドラで予期しない例外", exc_info=True)
        finally:
            self._clients.discard(websocket)

    def stop(self, timeout: float = 5.0) -> None:
        """サーバーを止める。未起動でも多重呼び出しでも安全。"""
        loop = self._loop
        fut = self._stop_future
        if loop is not None and not loop.is_closed() and fut is not None:
            loop.call_soon_threadsafe(lambda: None if fut.done() else fut.set_result(None))
        if self._thread is not None:
            self._thread.join(timeout)
            # タイムアウトで止まり切らない場合は参照を残し、次回の stop で再 join できるようにする。
            if not self._thread.is_alive():
                self._thread = None

    # ---- 配信 -----------------------------------------------------------------

    def broadcast(self, event: dict) -> None:
        """全クライアントへ event を JSON 配信する。どのスレッドから呼んでもよい・待たない。"""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        message = json.dumps(event)
        # 受信スレッドはここで投げるだけ。実送信はサーバーのイベントループ上で行われる。
        coro = self._send_all(message)
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            # is_running() 確認後に stop() が loop を閉じた競合。coroutine を閉じて
            # 「投げるだけ（落とさない）」契約を守る（未 await の警告も防ぐ）。
            coro.close()
            _LOGGER.debug("broadcast のスケジュールに失敗（loop 停止）", exc_info=True)

    async def _send_all(self, message: str) -> None:
        if not self._clients:
            return
        # 送信中に切断したクライアントで全体が巻き添えにならないよう return_exceptions=True。
        await asyncio.gather(
            *(client.send(message) for client in list(self._clients)),
            return_exceptions=True,
        )
