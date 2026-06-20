"""X1（URL直接モード）の純粋ロジックのテスト（マイク・I/O 不要）。

CRC-8 の既知ベクタ・6bit文字テーブル・encode↔decode の round-trip・誤り注入を確認する。
encode_x1_bits は受信側の参照エンコーダ（送信側 X1-send がこれをミラーする想定）。
"""
import pytest

from src import config, x1


def test_crc8_known_vector():
    """CRC-8/SMBUS（poly=0x07, init=0x00, 反射なし, xorout=0x00）の check 値は 0xF4。"""
    assert x1.crc8(list(b"123456789")) == 0xF4
    assert x1.crc8([]) == 0x00  # 空入力は init のまま


def test_char_table_consistency():
    """64種テーブル: a–z / 0–9 / 記号23種 / 予約5。逆引きと往復が一致する。"""
    assert len(config.X1_CHAR_TABLE) == 64
    assert x1.CHAR_TO_IDX["a"] == 0
    assert x1.CHAR_TO_IDX["z"] == 25
    assert x1.CHAR_TO_IDX["0"] == 26
    assert x1.CHAR_TO_IDX["9"] == 35
    assert x1.CHAR_TO_IDX["."] == 36
    assert x1.CHAR_TO_IDX["%"] == 58
    assert config.X1_CHAR_TABLE[59:] == [None] * 5  # 予約は None
    # 割当済みインデックスは文字↔インデックスが往復する
    for idx, ch in enumerate(config.X1_CHAR_TABLE):
        if ch is not None:
            assert x1.CHAR_TO_IDX[ch] == idx


@pytest.mark.parametrize("url,expect_scheme,expect_url", [
    ("github.com", "https", "https://github.com"),          # スキーム省略は https
    ("https://example.com/path", "https", "https://example.com/path"),
    ("http://a.io/x?q=1", "http", "http://a.io/x?q=1"),
    ("", "https", "https://"),                                # 空本体（length=0）の端
])
def test_encode_decode_roundtrip(url, expect_scheme, expect_url):
    """encode → decode で scheme・本体・URL が一致し、checksum OK。"""
    payload = x1.encode_x1_bits(url)              # marker を除いたビット列
    fields = x1.decode_x1_fields(payload)
    assert fields.checksum_ok is True
    assert fields.scheme == expect_scheme
    assert fields.url == expect_url


def test_payload_bit_count_matches_encoded_length():
    """payload_bit_count(length) が実際の encode 長と一致する。"""
    payload = x1.encode_x1_bits("github.com")     # 10 文字
    assert len(payload) == x1.payload_bit_count(10)
    assert x1.read_length(payload) == 10


def test_bit_flip_breaks_checksum():
    """本体ビットを反転すると checksum NG になり url は None（運命サイト行き）。"""
    payload = x1.encode_x1_bits("github.com")
    # chars 領域（scheme+length の後ろ）の1ビットを反転
    flip = config.X1_SCHEME_BITS + config.X1_LENGTH_BITS
    payload[flip] ^= 1
    fields = x1.decode_x1_fields(payload)
    assert fields.checksum_ok is False
    assert fields.url is None
    assert fields.checksum_recv != fields.checksum_calc


def test_encode_rejects_out_of_table_char():
    """テーブル外の文字（大文字など）は X1Error。"""
    with pytest.raises(x1.X1Error):
        x1.encode_x1_bits("GitHub.com")  # 大文字 G,H は未対応


def test_encode_rejects_too_long():
    """X1_MAX_LENGTH を超える本体は X1Error。"""
    with pytest.raises(x1.X1Error):
        x1.encode_x1_bits("a" * (config.X1_MAX_LENGTH + 1))
