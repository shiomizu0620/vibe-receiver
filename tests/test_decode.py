"""マイク不要の復号テスト。パルス列は (start_ms, duration_ms)。startは判定に使われない。"""
import pytest
from src.decode import decode_pulses, DecodeError
from src import config
from src.main import build_x1_frame_pulses


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


def test_resync_to_latest_preamble_after_botched_send():
    """送信ミス（プリアンブル＋数bitで中断）後に叩き直すと、最新フレームへ同期し直す。

    古い打ち損じ（プリアンブル対＋途中まで）がバッファに残っていても、最後のプリアンブル対を
    採るので新しいフレームを読む。最初の対にロックしていた頃は再送が通らなかった回帰防止。
    """
    botched = make_pulses([1, 0])[:2 + 1 + 2]  # プリアンブル2+モード+2bitで中断した打ち損じ
    fresh = make_pulses([0, 0, 1, 0, 1, 0, 1, 0])  # 改めて最初から id=42 を叩き直す
    assert decode_pulses(botched + fresh).id == 42


def test_no_preamble_raises():
    pulses = [(0, config.SHORT_MS), (300, config.LONG_MS)]
    with pytest.raises(DecodeError):
        decode_pulses(pulses)


def test_incomplete_frame_raises():
    pulses = make_pulses([0, 1, 0])[: 2 + 1 + 3]  # 3bitで途切れ
    with pytest.raises(DecodeError):
        decode_pulses(pulses)


# ---- X1（URL直接モード・marker=1）-------------------------------------------

def test_decode_x1_ok():
    """正しい X1 フレーム → checksum OK で URL が復元される。"""
    frame = decode_pulses(build_x1_frame_pulses("github.com"))
    assert frame.mode == config.MODE_DIRECT
    assert frame.checksum_ok is True
    assert frame.url == "https://github.com"
    assert frame.id is None  # id モードのフィールドは埋まらない


def test_decode_x1_http_scheme():
    """scheme=1（http）の X1 フレームも復元できる。"""
    frame = decode_pulses(build_x1_frame_pulses("http://a.io/x?q=1"))
    assert frame.checksum_ok is True
    assert frame.scheme == "http"
    assert frame.url == "http://a.io/x?q=1"


def test_decode_x1_corrupted_checksum_ng():
    """本体ビットを数本反転 → checksum NG（復号自体は成功し Frame は返る）。"""
    frame = decode_pulses(build_x1_frame_pulses("github.com", corrupt_bits=3))
    assert frame.mode == config.MODE_DIRECT
    assert frame.checksum_ok is False
    assert frame.url is None
    assert frame.body is not None  # 参考表示用に本体は復元されている


def test_decode_x1_incomplete_waits():
    """X1 フレームが途中までしか無ければ DecodeError（受信ループは未完として待つ）。"""
    pulses = build_x1_frame_pulses("github.com")
    with pytest.raises(DecodeError):
        decode_pulses(pulses[:6])  # プリアンブル+数パルスのみ


def test_id_mode_unchanged_alongside_x1():
    """X1 追加後も marker=0（idモード）の復号は従来どおり（回帰なし）。"""
    bits = [0, 0, 1, 0, 1, 0, 1, 0]  # 42
    assert decode_pulses(make_pulses(bits)).id == 42
