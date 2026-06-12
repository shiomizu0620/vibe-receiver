"""Supabase 逆引きの手動確認スクリプト（実接続が要るので自動テストにはしない）。

    python -m scripts.lookup_check 42         # id=42 を Supabase で逆引き
    python -m scripts.lookup_check 42 7 99    # 複数 id をまとめて確認

.env の SUPABASE_URL / SUPABASE_ANON_KEY を使う（anon key のみ・SELECT 逆引きのみ）。鍵は表示しない。
登録済み id なら実 URL が、未登録/取得失敗なら None（理由は stderr）が表示される。
"""
import pathlib
import sys

# `python scripts/lookup_check.py` 直叩きでも src.* を解決できるようにリポジトリ root を通す。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.lookup import lookup_url  # noqa: E402  （sys.path 設定後に import する）


def main(argv=None) -> int:
    """引数の id を順に Supabase で逆引きして表示する。終了コード: 正常=0 / 引数不正=2。"""
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        print("usage: python -m scripts.lookup_check <id> [<id> ...]", file=sys.stderr)
        return 2
    rc = 0
    for arg in argv:
        try:
            mid = int(arg)
        except ValueError:
            print(f"id は整数で指定してください: {arg!r}", file=sys.stderr)
            rc = 2
            continue
        url = lookup_url(mid)
        if url is None:
            print(f"id={mid}: 未登録 または 取得失敗（None）")
        else:
            print(f"id={mid}: {url}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
