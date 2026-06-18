"""WsServer の配信テスト（段1）。

実際に WebSocket サーバーを専用スレッドで起動し、クライアントを1つ繋いで broadcast が
JSON で届くことを確認する。websockets 未導入の環境では skip（offline 受信は影響を受けない）。
"""
import asyncio
import json
import socket

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
    server.start()
    try:
        server.broadcast({"type": "listening"})  # 誰も居なくても落ちない
    finally:
        server.stop()


def test_stop_is_idempotent():
    """未起動・多重 stop が安全（finally で何度呼ばれても良い）。"""
    server = WsServer(host=_HOST, port=_free_port())
    server.stop()        # 未起動でも安全
    server.start()
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
