"""復号（純粋関数）。入力はパルス列 [(start_ms, duration_ms), ...]、出力は id または X1 URL。
マイク・ファイルI/Oに依存しない。tests/test_decode.py でテストする。

モードマーカーで2方式に分岐する:
  marker=0 (MODE_ID)     : id 8bit 固定長（本線。無変更）
  marker=1 (MODE_DIRECT) : X1＝URL直接符号化（可変長。フィールド解釈は src/x1.py に委譲）
"""
from dataclasses import dataclass
from . import config
from . import x1


class DecodeError(Exception):
    pass


@dataclass
class Frame:
    mode: int
    payload_bits: list  # [0/1, ...] MSB first（モードマーカー以降のデータビット）
    id: int | None = None       # mode==MODE_ID のとき復元された id
    # X1（mode==MODE_DIRECT）用。id モードでは None のまま。
    url: str | None = None          # checksum OK のとき復元した完全 URL（scheme://body）
    body: str | None = None         # 復元した本体文字列（checksum NG でも参考表示用）
    scheme: str | None = None       # "https" / "http"
    checksum_ok: bool | None = None  # X1 のときのみ True/False。id モードでは None


def classify_pulse(duration_ms: float) -> str:
    """ONパルス長から種別を判定。gapは見ない（手動演奏対応の核心）。"""
    if duration_ms >= config.PREAMBLE_MIN_MS:
        return "preamble"
    if duration_ms >= config.SHORT_LONG_BOUNDARY_MS:
        return "long"   # bit 1
    return "short"      # bit 0


def _kind_to_bit(kind: str) -> int:
    """種別 → ビット（long=1, それ以外=0）。"""
    return 1 if kind == "long" else 0


def decode_pulses(pulses: list[tuple[float, float]]) -> Frame:
    """パルス列 → Frame。プリアンブル(2連続のpreamble級ON)以降をモードマーカーで分岐して読む。

    必要なパルスがまだ揃っていなければ DecodeError を投げる（受信ループはこれを「未完」と解釈し待つ）。
    """
    kinds = [classify_pulse(d) for _, d in pulses]

    # プリアンブル検出: preamble が2回連続する位置を探す
    start = None
    for i in range(len(kinds) - 1):
        if kinds[i] == "preamble" and kinds[i + 1] == "preamble":
            start = i + 2
            break
    if start is None:
        raise DecodeError("preamble not found")

    avail = kinds[start:]
    if len(avail) < 1:
        raise DecodeError("incomplete frame: missing mode marker")
    # 先頭=モードマーカー。これでフレーム長（固定 or 可変）が変わる。
    mode = _kind_to_bit(avail[0])
    if mode == config.MODE_ID:
        return _decode_id(avail)
    return _decode_x1(avail)


def _decode_id(avail: list[str]) -> Frame:
    """marker=0（idモード・固定 8bit）の復号。従来挙動を維持する。"""
    need = 1 + config.ID_BITS  # モードマーカー + ペイロード
    data = avail[:need]
    if len(data) < need:
        raise DecodeError(f"incomplete frame: got {len(data)}/{need} bits")
    if any(k == "preamble" for k in data):
        raise DecodeError("unexpected preamble inside frame")

    payload = [_kind_to_bit(k) for k in data[1:]]
    value = 0
    for b in payload:               # MSB first
        value = (value << 1) | b
    return Frame(mode=config.MODE_ID, payload_bits=payload, id=value)


def _decode_x1(avail: list[str]) -> Frame:
    """marker=1（X1・可変長）の復号。フィールド解釈と checksum 検証は x1.py に委譲する。

    まず scheme+length を読んで全長を確定し、必要パルスが揃ってから本体を解く。
    checksum NG でも DecodeError にはせず Frame を返す（全ビット受信済み＝復号は成功・整合検査だけ失敗）。
    """
    # marker + scheme + length が揃うまでは length を読めない＝未完として待つ。
    need_header = 1 + x1.X1_HEADER_BITS
    if len(avail) < need_header:
        raise DecodeError(f"incomplete X1 header: got {len(avail)}/{need_header} pulses")
    if any(k == "preamble" for k in avail[:need_header]):
        raise DecodeError("unexpected preamble inside X1 header")

    bits = [_kind_to_bit(k) for k in avail]
    payload_all = bits[1:]                       # marker を除いたデータビット
    length = x1.read_length(payload_all)
    need_total = 1 + x1.payload_bit_count(length)  # marker + scheme+length+chars+checksum
    if len(avail) < need_total:
        raise DecodeError(f"incomplete X1 frame: got {len(avail)}/{need_total} pulses")
    if any(k == "preamble" for k in avail[:need_total]):
        raise DecodeError("unexpected preamble inside X1 frame")

    payload = bits[1:need_total]
    fields = x1.decode_x1_fields(payload)
    return Frame(mode=config.MODE_DIRECT, payload_bits=payload,
                 url=fields.url, body=fields.body, scheme=fields.scheme,
                 checksum_ok=fields.checksum_ok)
