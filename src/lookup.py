"""id → URL 逆引き（R6 スタブ）。

R6 では会場ネットワークやDBに依存せず動かすため、固定辞書で id→URL を引くだけのスタブ。
R9 で supabase-py による実装に**中身だけ**差し替える前提で、インターフェースはここで確定しておく。
  - lookup_url(message_id) -> str | None : message_id に対応する URL を返す。未登録なら None。
main/display はこの関数しか知らないので、R9 で内部実装が変わっても呼び出し側は無修正でよい。
"""

# R9 で Supabase の urls テーブル（SELECT 逆引き）に置き換わる暫定辞書。
_STUB_URLS = {
    42: "https://example.com",
    7: "https://www.anthropic.com",
    0: "https://example.com/zero",
    255: "https://example.com/max",
}


def lookup_url(message_id: int) -> str | None:
    """message_id に対応する URL を返す。未登録なら None。

    R9 で Supabase 逆引き（anon key・SELECT のみ）に差し替える。シグネチャは据え置く。
    """
    return _STUB_URLS.get(message_id)
