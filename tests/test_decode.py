"""マイク不要の復号テスト。パルス列は (start_ms, duration_ms)。startは判定に使われない。"""
import pytest
from src.decode import decode_pulses, DecodeError
from src import config


def make_pulses(bits, jitter=None):
    """プリアンブル + モードマーカー(0) + bits のパルス列を生成。jitterで手動演奏のブレを模擬。"""
    durs = [config.PREAMBLE_ON_MS, config.PREAMBLE_ON_MS, config.SHORT_MS]  # マーカー=0
    durs += [config.LONG_MS if b else config.SHORT_MS for b in bits]
    if jitter:
        durs = [d + j for d, j in zip(durs, jitter)]
    t, out = 0.0, []
    for d in durs:
        out.append((t, d)); t += d + config.GAP_MS
    return out


def test_decode_id_42():
    bits = [0, 0, 1, 0, 1, 0, 1, 0]  # 42 = 00101010
    assert decode_pulses(make_pulses(bits)).id == 42


def test_decode_id_0_and_255():
    assert decode_pulses(make_pulses([0] * 8)).id == 0
    assert decode_pulses(make_pulses([1] * 8)).id == 255


def test_manual_performance_jitter():
    """手動演奏: パルス長が±80msブレても境界300msで正しく判定される。"""
    bits = [1, 0, 1, 1, 0, 0, 1, 0]  # 178
    jitter = [50, -60, 80, -70, 60, 80, -60, 70, -50, 60, -70]
    assert decode_pulses(make_pulses(bits, jitter)).id == 178


def test_no_preamble_raises():
    pulses = [(0, config.SHORT_MS), (300, config.LONG_MS)]
    with pytest.raises(DecodeError):
        decode_pulses(pulses)


def test_incomplete_frame_raises():
    pulses = make_pulses([0, 1, 0])[: 2 + 1 + 3]  # 3bitで途切れ
    with pytest.raises(DecodeError):
        decode_pulses(pulses)
