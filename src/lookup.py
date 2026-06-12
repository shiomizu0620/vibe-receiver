"""id → URL 逆引き（R9: Supabase 本実装）。

Supabase の urls テーブルから id→url を引く（anon key・SELECT のみ）。会場 Wi-Fi 死亡時の
デモ保険として、--offline でローカル固定辞書に切り替えられる（main が get_lookup で選択する）。

呼び出し側（display.py / main.py）が知るのは「lookup(message_id) -> str | None」という単項関数だけ。
R6 スタブからインターフェースを据え置いたので、display.py は無修正で動く。
  - lookup_url(message_id)         : オンライン本線（Supabase 逆引き）
  - offline_lookup_url(message_id) : ローカル固定辞書（デモ保険）
  - get_lookup(offline=...)        : main がフラグに応じてどちらかを返すファクトリ

セキュリティ方針（CLAUDE.md）: anon key のみ使用。service_role key は使わない・置かない。
鍵は .env から読み（gitignore 済み）、表示・ログにも出さない。
"""
import os
import sys
from collections.abc import Callable

# Supabase 側のテーブル / 列名（id を引いて url を得る逆引き）。
_TABLE = "urls"
_ID_COLUMN = "id"
_URL_COLUMN = "url"

# --offline 用のローカル固定辞書（会場 Wi-Fi 死亡時のデモ保険）。
# 本線は Supabase 逆引きだが、デモで使う代表 id（42, 7）はここでも引けるようにしておく。
_OFFLINE_URLS = {
    42: "https://example.com",
    7: "https://www.anthropic.com",
    0: "https://example.com/zero",
    255: "https://example.com/max",
}

# Supabase クライアントは初回アクセス時に1度だけ生成してキャッシュする（毎回 .env を読まない）。
_client = None


def offline_lookup_url(message_id: int) -> str | None:
    """ローカル固定辞書から URL を引く（--offline 用）。未登録なら None。"""
    return _OFFLINE_URLS.get(message_id)


def _get_client():
    """Supabase クライアントを遅延生成して返す（モジュールにキャッシュ）。

    supabase / python-dotenv の import はここでだけ行う。offline パスやテストでは読み込まれないので、
    これらが未インストールでも offline 受信は動く。env 未設定なら RuntimeError を投げる。
    """
    global _client
    if _client is None:
        from dotenv import load_dotenv
        from supabase import create_client

        load_dotenv()  # .env を環境変数に展開（既存の環境変数は上書きしない）
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_ANON_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_ANON_KEY が未設定です"
                "（.env を確認するか --offline を使用してください）"
            )
        _client = create_client(url, key)
    return _client


def lookup_url(message_id: int) -> str | None:
    """Supabase の urls テーブルから message_id の URL を引く。未登録/失敗なら None。

    anon key で SELECT 逆引きのみ。ネット断・DB エラー・env 未設定でも**落とさず** None を返す
    （受信ループを止めないため）。原因は stderr に日本語で出す（鍵は出力しない）。
    """
    try:
        client = _get_client()
        resp = (
            client.table(_TABLE)
            .select(_URL_COLUMN)
            .eq(_ID_COLUMN, message_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        return rows[0].get(_URL_COLUMN)
    except Exception as exc:  # ネット/DB/設定いずれの失敗でも受信は続行する
        print(
            f"[lookup] Supabase 逆引きに失敗しました（id={message_id}）: {exc}",
            file=sys.stderr,
        )
        return None


def get_lookup(offline: bool = False) -> Callable[[int], str | None]:
    """offline フラグに応じて lookup 関数（message_id -> str | None）を返す。main から使う。"""
    return offline_lookup_url if offline else lookup_url
