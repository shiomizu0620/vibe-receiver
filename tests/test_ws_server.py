"""WsServer の配信テスト（段1）。

実際に WebSocket サーバーを専用スレッドで起動し、クライアントを1つ繋いで broadcast が
JSON で届くことを確認する。websockets 未導入の環境では skip（offline 受信は影響を受けない）。
"""
import asyncio
import json
import socket
import threading

import pytest

pytest.importorskip("websockets")  # offline パス/他テストは websockets 無しでも動く

import websockets  # noqa: E402

from src.ws_server import WsServer  # noqa: E402

_HOST = "127.0.0.1"


def _free_port(host: str = _HOST) -> int:
    """OS に空きポートを割り当ててもらう（固定ポートの衝突・並列実行のフレークを避ける）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


async def _connect_and_collect(server: WsServer, port: int, events: list[dict]) -> list[dict]:
    """クライアントを繋ぎ、サーバー登録を条件待ちしてから events を broadcast して受信する。"""
    async with websockets.connect(f"ws://{_HOST}:{port}") as client:
        # 固定 sleep ではなく、サーバーがクライアントを登録するまで条件待ち（タイムアウト付き）。
        deadline = asyncio.get_running_loop().time() + 2.0
        while server.client_count == 0 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        assert server.client_count >= 1, "クライアント登録がタイムアウトしました"
        for ev in events:
            server.broadcast(ev)  # 受信スレッド相当（テスト本体）から投げる
        received = []
        for _ in range(len(events)):
            raw = await asyncio.wait_for(client.recv(), timeout=3.0)
            received.append(json.loads(raw))
        return received


def test_broadcast_reaches_client():
    """接続中クライアントへ各イベントが JSON で順に届く。"""
    port = _free_port()
    server = WsServer(host=_HOST, port=port)
    assert server.start() is True  # listen 成功を戻り値で確認
    try:
        sent = [
            {"type": "listening"},
            {"type": "preamble"},
            {"type": "bit", "value": 1},
            {"type": "decoded", "id": 42},
            {"type": "url", "url": "https://example.com"},
            {"type": "open", "url": "https://example.com"},
        ]
        got = asyncio.run(_connect_and_collect(server, port, sent))
    finally:
        server.stop()
    assert got == sent


def test_broadcast_without_clients_is_safe():
    """クライアント未接続でも broadcast は例外を投げない（受信を止めない契約）。"""
    server = WsServer(host=_HOST, port=_free_port())
    assert server.start() is True  # 起動失敗を no-op 経路と取り違えないよう前提を固定
    try:
        server.broadcast({"type": "listening"})  # 誰も居なくても落ちない
    finally:
        server.stop()


def test_stop_is_idempotent():
    """未起動・多重 stop が安全（finally で何度呼ばれても良い）。"""
    server = WsServer(host=_HOST, port=_free_port())
    server.stop()        # 未起動でも安全
    assert server.start() is True
    server.stop()
    server.stop()        # 多重でも安全


def test_start_failure_is_reported():
    """ポート競合などで listen 失敗時は start() が False を返し、成功扱いにしない。"""
    port = _free_port()
    first = WsServer(host=_HOST, port=port)
    assert first.start() is True
    try:
        clash = WsServer(host=_HOST, port=port)  # 同じポートには listen できない
        assert clash.start() is False
        assert clash.is_serving is False
        assert clash.start_error is not None
        clash.stop()
    finally:
        first.stop()


async def _send_messages(port: int, messages: list) -> None:
    """クライアントを繋ぎ、messages を順に送る（quit コマンド等のクライアント→サーバー方向）。

    各要素は str ならそのまま、dict なら JSON 化して送る（壊れた JSON のテストにも使えるよう）。
    """
    async with websockets.connect(f"ws://{_HOST}:{port}") as client:
        for msg in messages:
            await client.send(msg if isinstance(msg, str) else json.dumps(msg))
        await asyncio.sleep(0.1)  # サーバー側スレッドが処理する猶予


def test_quit_command_invokes_callback():
    """クライアントが {"type":"quit"} を送ると on_quit コールバックが呼ばれる。"""
    port = _free_port()
    quit_event = threading.Event()  # set はスレッド安全（サーバーのループスレッドから呼ばれる）
    server = WsServer(host=_HOST, port=port, on_quit=quit_event.set)
    assert server.start() is True
    try:
        asyncio.run(_send_messages(port, [{"type": "quit"}]))
        assert quit_event.wait(2.0), "quit を送っても on_quit が呼ばれなかった"
    finally:
        server.stop()


def test_non_quit_messages_are_ignored():
    """quit 以外・壊れた JSON ではコールバックを呼ばず受け流す（接続も切らない）。"""
    port = _free_port()
    quit_event = threading.Event()
    server = WsServer(host=_HOST, port=port, on_quit=quit_event.set)
    assert server.start() is True
    try:
        asyncio.run(_send_messages(port, [{"type": "listening"}, "not json", {"foo": "bar"}]))
        assert not quit_event.is_set(), "quit 以外のメッセージで on_quit が誤って呼ばれた"
    finally:
        server.stop()


async def _wait_clients(server: WsServer, n: int, timeout: float = 2.0) -> None:
    """server.client_count が n 以上になるまで条件待ち（固定 sleep のフレーク回避）。"""
    deadline = asyncio.get_running_loop().time() + timeout
    while server.client_count < n and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    assert server.client_count >= n, f"クライアント数 {n} 到達がタイムアウトしました"


def test_disconnect_invokes_no_clients_callback():
    """全クライアント切断後、猶予を過ぎても繋ぎ直さなければ on_no_clients が呼ばれる。"""
    port = _free_port()
    gone = threading.Event()
    server = WsServer(host=_HOST, port=port, on_no_clients=gone.set, no_clients_grace=0.2)
    assert server.start() is True
    try:
        async def _connect_then_close():
            async with websockets.connect(f"ws://{_HOST}:{port}"):
                await _wait_clients(server, 1)
            # with を抜けてクローズ → サーバー側で猶予タイマーが張られる
        asyncio.run(_connect_then_close())
        assert gone.wait(2.0), "切断後に on_no_clients が呼ばれなかった"
    finally:
        server.stop()


def test_reconnect_within_grace_does_not_fire():
    """猶予内に繋ぎ直れば（ページ更新相当）on_no_clients は発火しない。"""
    port = _free_port()
    gone = threading.Event()
    server = WsServer(host=_HOST, port=port, on_no_clients=gone.set, no_clients_grace=0.6)
    assert server.start() is True
    try:
        async def _close_then_reconnect():
            async with websockets.connect(f"ws://{_HOST}:{port}"):  # 1本目
                await _wait_clients(server, 1)
            # 切断 → 猶予タイマー開始。猶予(0.6s)内に2本目を繋ぐ＝更新相当
            async with websockets.connect(f"ws://{_HOST}:{port}"):  # 2本目
                await _wait_clients(server, 1)
                await asyncio.sleep(0.9)  # 猶予を超えて保持（この間に発火しないこと）
        asyncio.run(_close_then_reconnect())
        assert not gone.is_set(), "更新相当の再接続後に on_no_clients が誤発火した"
    finally:
        server.stop()


def test_reconnect_then_disconnect_uses_latest_grace():
    """再接続→再切断で、猶予は「最新の切断」基準になる（古いタイマーが先に発火しない）。

    1本目切断で張ったタイマーを再接続時にキャンセルしないと、それが2本目切断後に
    「最新切断からは猶予未満」のタイミングで発火し、早すぎる on_no_clients を招く。
    時刻はすべて2本目の切断(e2)基準の相対 sleep で測り、CI 速度に依らず判定が崩れないようにする。
    """
    port = _free_port()
    gone = threading.Event()
    grace = 0.6
    server = WsServer(host=_HOST, port=port, on_no_clients=gone.set, no_clients_grace=grace)
    assert server.start() is True
    try:
        async def _close_reconnect_close():
            async with websockets.connect(f"ws://{_HOST}:{port}"):  # 1本目
                await _wait_clients(server, 1)
            # 切断#1 → 旧実装ではここで張ったタイマーが grace 後に発火する
            await asyncio.sleep(0.3)                                  # 猶予(0.6)の途中で
            async with websockets.connect(f"ws://{_HOST}:{port}"):    # 2本目（更新相当）
                await _wait_clients(server, 1)
            # 切断#2(e2) → 修正版は最新切断基準でタイマーを張り直す（発火は e2+grace）
            await asyncio.sleep(0.4)  # e2+0.4。旧タイマー予定(≈切断#1+0.6)は跨ぐが e2+0.6 には未達
        asyncio.run(_close_reconnect_close())
        # e2+0.4 時点で発火していない＝旧タイマーがキャンセルされた証拠
        assert not gone.is_set(), "再切断後、最新切断の猶予前に on_no_clients が誤発火した"
        # 最新切断基準のタイマーはきちんと残っており、猶予を過ぎれば発火する
        assert gone.wait(2.0), "最新切断の猶予経過後も on_no_clients が呼ばれなかった"
    finally:
        server.stop()
