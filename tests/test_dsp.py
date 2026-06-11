"""録音不要のDSPテスト。numpy で合成した正弦波バーストから ON区間長を検出できることを確認する。

合成波形 → dsp.bandpass → dsp.envelope → dsp.to_pulses が
PROTOCOL.md の 150ms/450ms/700ms を (start_ms, duration_ms) として正しく切り出し、
さらに decode.classify_pulse が短/長/プリアンブルに分類できることまで通しで確かめる。
"""
import numpy as np
import pytest

from src import dsp, config
from src.decode import classify_pulse

FS = 8000          # サンプリング周波数（>100Hz で検出十分・配列が小さく速い）
CARRIER_HZ = 250   # モーター振動を模した搬送波
LO, HI = 100, 500  # バンドパス帯域（テスト用・搬送波を通す）


def _burst(dur_ms, amp=1.0):
    n = int(round(dur_ms * 1e-3 * FS))
    t = np.arange(n) / FS
    return amp * np.sin(2 * np.pi * CARRIER_HZ * t)


def _silence(dur_ms):
    return np.zeros(int(round(dur_ms * 1e-3 * FS)))


def _build(durations_ms, gap_ms=config.GAP_MS, lead_ms=100.0):
    """各 dur のバーストを gap で区切って連結。期待される ON区間長のリストも返す。"""
    parts = [_silence(lead_ms)]
    for d in durations_ms:
        parts.append(_burst(d))
        parts.append(_silence(gap_ms))
    return np.concatenate(parts)


def _run(sig, threshold_frac=0.5):
    env = dsp.envelope(dsp.bandpass(sig, FS, LO, HI), FS)
    threshold = threshold_frac * float(env.max())
    return dsp.to_pulses(env, FS, threshold)


def test_detects_short_long_preamble_lengths():
    """150/450/700ms バースト列 → 同じ並び・正しい長さのパルスが出る。"""
    expected = [config.SHORT_MS, config.LONG_MS, config.PREAMBLE_ON_MS]  # 150,450,700
    pulses = _run(_build(expected))

    assert len(pulses) == len(expected)
    for (_, dur), want in zip(pulses, expected):
        assert dur == pytest.approx(want, abs=20)  # ±20ms 以内で一致


def test_pulse_lengths_classify_correctly():
    """検出した長さが decode 側で 短/長/プリアンブル に正しく分類される。"""
    pulses = _run(_build([config.SHORT_MS, config.LONG_MS, config.PREAMBLE_ON_MS]))
    kinds = [classify_pulse(dur) for _, dur in pulses]
    assert kinds == ["short", "long", "preamble"]


def test_start_times_are_ordered_and_spaced():
    """start_ms が時間順で、gap 分だけ離れている（境界の時刻も保たれる）。"""
    durs = [config.SHORT_MS, config.LONG_MS, config.SHORT_MS]
    pulses = _run(_build(durs, lead_ms=100.0))

    starts = [s for s, _ in pulses]
    assert starts == sorted(starts)
    assert starts[0] == pytest.approx(100.0, abs=20)  # lead_ms 後に開始
    # 次の開始 ≈ 前の開始 + 前のON長 + gap
    expected_second = starts[0] + durs[0] + config.GAP_MS
    assert starts[1] == pytest.approx(expected_second, abs=20)


def test_silence_yields_no_pulses():
    """無音（閾値以下）からはパルスが出ない。"""
    env = dsp.envelope(dsp.bandpass(_silence(500), FS, LO, HI), FS)
    assert dsp.to_pulses(env, FS, threshold=0.1) == []


def test_min_duration_filters_blips():
    """min_duration_ms 未満の短い ON はノイズとして捨てられる。"""
    sig = _build([config.SHORT_MS, config.LONG_MS])  # 150ms と 450ms
    env = dsp.envelope(dsp.bandpass(sig, FS, LO, HI), FS)
    threshold = 0.5 * float(env.max())
    pulses = dsp.to_pulses(env, FS, threshold, min_duration_ms=300)
    assert len(pulses) == 1                       # 150ms は捨て、450ms だけ残る
    assert pulses[0][1] == pytest.approx(config.LONG_MS, abs=20)
