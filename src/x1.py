"""X1（URL直接符号化モード・PROTOCOL v1.1 / marker=1）の純粋ロジック。

decode.py を framing（プリアンブル検出・パルス数の管理）に専念させ、ここには
「ビット列 ↔ フィールド」変換・6bit文字テーブル・CRC-8 を閉じ込める。マイク・I/O 非依存。

フレーム（marker の後ろ、すべて MSB first）:
    [scheme 1bit] [length 6bit] [chars: length×6bit] [checksum 8bit]

checksum は **chars の 6bit インデックス列（各 0..63 を 1 バイトとみなす）** に対する CRC-8。
送信側（X1-send / 担当A）はこの x1_checksum を **そのまま** ミラーすること（唯一の参照点）:

    CRC-8: poly=0x07, init=0x00, 反射なし(no reflection), 最終XORなし。
    例) indices=[6, 8, 19, 7, 20, 1, 26, 2, ...] に対し crc8(indices)。

「6bit インデックス列」を対象にしたのは、送るシンボルそのものに対して計算でき、
表外・予約インデックス（ASCII に無い値）でも一意に定まり頑健なため（小文字前提のデモ URL では
本体文字列の ASCII バイト列と実質同じ役割になる）。
"""
from dataclasses import dataclass

from . import config

# インデックス → 文字（予約は None）。config の唯一の正をそのまま使う。
IDX_TO_CHAR = list(config.X1_CHAR_TABLE)
# 文字 → インデックス（予約 None は除外）。encode と scheme 判定で使う。
CHAR_TO_IDX = {ch: i for i, ch in enumerate(IDX_TO_CHAR) if ch is not None}

# marker の後ろ、length を読むのに最低限必要なビット数（scheme + length）。
X1_HEADER_BITS = config.X1_SCHEME_BITS + config.X1_LENGTH_BITS
# scheme 文字列 → ビット（X1_SCHEMES の逆引き）。encode 用。
_SCHEME_TO_BIT = {name: bit for bit, name in config.X1_SCHEMES.items()}


class X1Error(Exception):
    """X1 のエンコード/デコードで仕様外の入力に当たったとき。"""


@dataclass
class X1Fields:
    """marker=1 フレームの復号結果。checksum NG でも本体は参考表示用に復元する。"""
    scheme: str            # "https" / "http"
    length: int            # 文字数
    indices: list          # chars の 6bit インデックス列
    body: str              # 復元した本体文字列（表外/予約 idx は '?' 代替）
    checksum_recv: int     # フレームに載っていた checksum
    checksum_calc: int     # indices から計算した checksum
    checksum_ok: bool      # 両者一致なら True
    url: str | None        # checksum_ok のとき scheme://body、NG なら None


def crc8(values, poly: int = config.X1_CRC_POLY) -> int:
    """各値を 1 バイト（0..255）として MSB first で流す CRC-8（init=0, 反射/最終XORなし）。

    送信側がそのまま移植できるよう、外部ライブラリを使わない素直なビット演算で書く。
    """
    crc = 0
    for v in values:
        crc ^= int(v) & 0xFF
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def x1_checksum(indices) -> int:
    """X1 の checksum（6bit インデックス列に対する CRC-8）。送受信の唯一の正。"""
    return crc8(indices)


def _int_to_bits(value: int, width: int) -> list:
    """整数 → MSB first のビット列（width 桁）。"""
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def _bits_to_int(bits) -> int:
    """MSB first のビット列 → 整数。"""
    value = 0
    for b in bits:
        value = (value << 1) | (b & 1)
    return value


def split_scheme(url: str) -> tuple[str, str]:
    """URL を (scheme, body) に分ける。スキーム省略時は https 既定。"""
    for bit, name in config.X1_SCHEMES.items():
        prefix = f"{name}://"
        if url.startswith(prefix):
            return name, url[len(prefix):]
    return config.X1_SCHEMES[0], url  # スキーム無しは https 既定


def encode_x1_bits(url: str) -> list:
    """URL → X1 フレームの **marker を除いた** ビット列（scheme+length+chars+checksum）。

    受信側のテスト/replay 用エンコーダ（decode の逆）。送信側 encoder の参照実装も兼ねる。
    表外文字・長さ超過は X1Error（デモ URL は小文字テーブル内に収める前提）。
    """
    scheme_name, body = split_scheme(url)
    try:
        indices = [CHAR_TO_IDX[ch] for ch in body]
    except KeyError as exc:
        raise X1Error(f"X1 文字テーブルに無い文字です: {exc.args[0]!r}（小文字 URL のみ対応）") from exc
    if len(indices) > config.X1_MAX_LENGTH:
        raise X1Error(f"本体が長すぎます（{len(indices)} > {config.X1_MAX_LENGTH}）")

    bits: list = []
    bits += _int_to_bits(_SCHEME_TO_BIT[scheme_name], config.X1_SCHEME_BITS)
    bits += _int_to_bits(len(indices), config.X1_LENGTH_BITS)
    for idx in indices:
        bits += _int_to_bits(idx, config.X1_CHAR_BITS)
    bits += _int_to_bits(x1_checksum(indices), config.X1_CHECKSUM_BITS)
    return bits


def payload_bit_count(length: int) -> int:
    """length 文字の X1 ペイロード（marker 除く）の総ビット数。"""
    return (config.X1_SCHEME_BITS + config.X1_LENGTH_BITS
            + config.X1_CHAR_BITS * length + config.X1_CHECKSUM_BITS)


def read_length(data_bits) -> int:
    """marker を除いたビット列の先頭（scheme+length）から length を読む。"""
    start = config.X1_SCHEME_BITS
    return _bits_to_int(data_bits[start:start + config.X1_LENGTH_BITS])


def decode_x1_fields(data_bits) -> X1Fields:
    """marker を除いた **ちょうど 1 フレーム分** のビット列を X1Fields に復号する。

    data_bits の長さは payload_bit_count(length) に一致している前提（framing は decode 側の責務）。
    checksum NG でも例外にせず checksum_ok=False の X1Fields を返す（呼び出し側が運命サイトへ分岐）。
    """
    pos = 0
    scheme_bit = _bits_to_int(data_bits[pos:pos + config.X1_SCHEME_BITS])
    pos += config.X1_SCHEME_BITS
    length = _bits_to_int(data_bits[pos:pos + config.X1_LENGTH_BITS])
    pos += config.X1_LENGTH_BITS

    indices = []
    for _ in range(length):
        indices.append(_bits_to_int(data_bits[pos:pos + config.X1_CHAR_BITS]))
        pos += config.X1_CHAR_BITS
    checksum_recv = _bits_to_int(data_bits[pos:pos + config.X1_CHECKSUM_BITS])

    scheme = config.X1_SCHEMES.get(scheme_bit, config.X1_SCHEMES[0])
    # 表外/予約インデックスは '?' で埋める（正常フレームでは出ない。壊れたフレームの参考表示用）。
    body = "".join(
        IDX_TO_CHAR[i] if 0 <= i < len(IDX_TO_CHAR) and IDX_TO_CHAR[i] is not None else "?"
        for i in indices
    )
    checksum_calc = x1_checksum(indices)
    checksum_ok = checksum_recv == checksum_calc
    url = f"{scheme}://{body}" if checksum_ok else None
    return X1Fields(
        scheme=scheme, length=length, indices=indices, body=body,
        checksum_recv=checksum_recv, checksum_calc=checksum_calc,
        checksum_ok=checksum_ok, url=url,
    )
