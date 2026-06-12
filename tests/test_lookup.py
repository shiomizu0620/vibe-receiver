"""lookup.py の offline 経路のテスト（ネット・third-party 不要）。

Supabase 接続部（lookup_url のオンライン本線）は実接続が要るので自動テストにはしない
（手動確認は scripts/lookup_check.py）。ここでは --offline 用の固定辞書と get_lookup の配線だけ検証する。
これらの経路は supabase / python-dotenv を import しないので、未インストールでもパスする。
"""
from src.config import OFFLINE_URLS
from src.lookup import (
    get_lookup,
    lookup_url,
    offline_lookup_url,
)


def test_offline_known_ids_return_urls():
    """会場デモで使う代表 id（42, 7）は固定辞書で URL が引ける。"""
    url_42 = offline_lookup_url(42)
    assert url_42 == OFFLINE_URLS[42]
    # デモ保険なので中身が空でない（http で始まる）こと。
    assert url_42.startswith("http")
    assert offline_lookup_url(7) == OFFLINE_URLS[7]


def test_offline_unknown_id_returns_none():
    """未登録 id では None を返す（落ちない）。"""
    assert 123 not in OFFLINE_URLS
    assert offline_lookup_url(123) is None


def test_get_lookup_offline_uses_dict():
    """get_lookup(offline=True) は固定辞書ベースの関数を返す。"""
    fn = get_lookup(offline=True)
    assert fn is offline_lookup_url
    assert fn(42) == OFFLINE_URLS[42]
    assert fn(123) is None


def test_get_lookup_online_returns_lookup_url_without_calling():
    """get_lookup(offline=False) は本線 lookup_url を返すだけ（ネット呼び出しはしない）。"""
    assert get_lookup(offline=False) is lookup_url
