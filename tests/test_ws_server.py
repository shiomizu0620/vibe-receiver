"""WsServer の配信テスト（段1）。

実際に WebSocket サーバーを専用スレッドで起動し、クライアントを1つ繋いで broadcast が
JSON で届くことを確認する。websockets 未導入の環境では skip（offline 受信は影響を受けない）。
"""
import asyncio
import json

import pytest

pytest.importorskip("websockets")  # offline パス/他テストは websockets 無しでも動く

import websockets  # noqa: E402

from src.ws_server import WsServer  # noqa: E402

# 既定(8765)と衝突しないようテスト専用ポートを使う。
_TEST_PORT = 8799


async def _connect_and_collect(server: WsServer, events: list[dict]) -> list[dict]:
    """クライアントを繋ぎ、登録後に events を broadcast して順に受信して返す。"""
    async with websockets.connect(f"ws://localhost:{_TEST_PORT}") as client:
        await asyncio.sleep(0.1)  # サーバー側がクライアントを集合へ登録するのを待つ
        for ev in events:
            server.broadcast(ev)  # 受信スレッド相当（テスト本体）から投げる
        received = []
        for _ in range(len(events)):
            raw = await asyncio.wait_for(client.recv(), timeout=3.0)
            received.append(json.loads(raw))
        return received


def test_broadcast_reaches_client():
    """接続中クライアントへ各イベントが JSON で順に届く。"""
    server = WsServer(port=_TEST_PORT)
    server.start()
    try:
        sent = [
            {"type": "listening"},
            {"type": "preamble"},
            {"type": "bit", "value": 1},
            {"type": "decoded", "id": 42},
            {"type": "url", "url": "https://example.com"},
            {"type": "open", "url": "https://example.com"},
        ]
        got = asyncio.run(_connect_and_collect(server, sent))
    finally:
        server.stop()
    assert got == sent


def test_broadcast_without_clients_is_safe():
    """クライアント未接続でも broadcast は例外を投げない（受信を止めない契約）。"""
    server = WsServer(port=_TEST_PORT)
    server.start()
    try:
        server.broadcast({"type": "listening"})  # 誰も居なくても落ちない
    finally:
        server.stop()


def test_stop_is_idempotent():
    """未起動・多重 stop が安全（finally で何度呼ばれても良い）。"""
    server = WsServer(port=_TEST_PORT)
    server.stop()        # 未起動でも安全
    server.start()
    server.stop()
    server.stop()        # 多重でも安全
