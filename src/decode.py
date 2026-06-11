"""復号（純粋関数）。入力はパルス列 [(start_ms, duration_ms), ...]、出力は id。
マイク・ファイルI/Oに依存しない。tests/test_decode.py でテストする。"""
from dataclasses import dataclass
from . import config


class DecodeError(Exception):
    pass


@dataclass
class Frame:
    mode: int
    payload_bits: list  # [0/1, ...] MSB first
    id: int | None      # mode==MODE_ID のとき復元された id


def classify_pulse(duration_ms: float) -> str:
    """ONパルス長から種別を判定。gapは見ない（手動演奏対応の核心）。"""
    if duration_ms >= config.PREAMBLE_MIN_MS:
        return "preamble"
    if duration_ms >= config.SHORT_LONG_BOUNDARY_MS:
        return "long"   # bit 1
    return "short"      # bit 0


def decode_pulses(pulses: list[tuple[float, float]]) -> Frame:
    """パルス列 → Frame。プリアンブル(2連続のpreamble級ON)以降を読む。"""
    kinds = [classify_pulse(d) for _, d in pulses]

    # プリアンブル検出: preamble が2回連続する位置を探す
    start = None
    for i in range(len(kinds) - 1):
        if kinds[i] == "preamble" and kinds[i + 1] == "preamble":
            start = i + 2
            break
    if start is None:
        raise DecodeError("preamble not found")

    need = 1 + config.ID_BITS  # モードマーカー + ペイロード
    data = kinds[start:start + need]
    if len(data) < need:
        raise DecodeError(f"incomplete frame: got {len(data)}/{need} bits")
    if any(k == "preamble" for k in data):
        raise DecodeError("unexpected preamble inside frame")

    bits = [1 if k == "long" else 0 for k in data]
    mode, payload = bits[0], bits[1:]

    if mode == config.MODE_ID:
        value = 0
        for b in payload:           # MSB first
            value = (value << 1) | b
        return Frame(mode=mode, payload_bits=payload, id=value)
    return Frame(mode=mode, payload_bits=payload, id=None)  # stretch: 直接符号化
