"""チャンネル共通のDSP部品（純粋関数）。

生信号 → パルス列 への変換に使う部品を提供する。
マイクやファイルI/Oは持たず、入力はすべて numpy 配列とサンプリング周波数。

ここには PROTOCOL.md の定数（150/450/700ms 等）は入らない:
それらは「パルス長 → 短/長/プリアンブル」を判定する decode.py 側の仕事であり、
DSP はあくまで「閾値以上の ON 区間を (start_ms, duration_ms) として切り出す」までを担う。
帯域(lo/hi)・閾値(threshold)はチャンネル固有パラメータなので、ハードコードせず引数で受ける
（CLAUDE.md のアーキテクチャ方針）。
"""
import numpy as np
from scipy import signal as sp_signal


def bandpass(signal, fs, lo, hi, order=4):
    """[lo, hi] Hz のバターワース・バンドパス（ゼロ位相）。

    sosfiltfilt で前後双方向に掛けるため位相遅れがなく、ON区間の時間が保たれる
    （パルス長で 0/1 を判定するこのプロトコルでは時間の正確さが命）。
    """
    if fs <= 0:
        raise ValueError(f"fs must be > 0; got fs={fs}")
    sig = np.asarray(signal, dtype=float)
    nyq = fs / 2.0
    if not 0 < lo < hi < nyq:
        raise ValueError(f"need 0 < lo < hi < fs/2 ({nyq}); got lo={lo}, hi={hi}")
    sos = sp_signal.butter(order, [lo, hi], btype="band", fs=fs, output="sos")
    return sp_signal.sosfiltfilt(sos, sig)


def envelope(signal, fs, smooth_ms=10.0):
    """整流（絶対値）＋移動平均で音量の包絡線を返す。

    移動平均は対称カーネル（mode="same"）なので位相遅れがなく、
    立ち上がり/立ち下がりが同じだけ滑らかになる → ON区間長が保たれる。
    smooth_ms はキャリアのリップルを均す時定数（パルス長 150ms より十分小さく取る）。
    """
    if fs <= 0:
        raise ValueError(f"fs must be > 0; got fs={fs}")
    sig = np.asarray(signal, dtype=float)
    win = max(1, int(round(smooth_ms * 1e-3 * fs)))
    kernel = np.ones(win) / win
    return np.convolve(np.abs(sig), kernel, mode="same")


def to_pulses(envelope, fs, threshold, min_duration_ms=0.0):
    """包絡線を閾値で ON/OFF 化し、ON区間を [(start_ms, duration_ms), ...] で返す。

    出力形式は decode.decode_pulses の入力（PulseEvent 相当）に一致する。
    min_duration_ms 未満の短い ON はノイズとして捨てる（既定 0 = 捨てない）。
    """
    if fs <= 0:
        raise ValueError(f"fs must be > 0; got fs={fs}")
    env = np.asarray(envelope, dtype=float)
    on = env >= threshold
    # 両端を False でパディングし、境界に張り付いた ON もエッジとして拾う
    padded = np.concatenate(([False], on, [False]))
    edges = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(edges == 1)    # 最初の ON サンプルの index
    ends = np.flatnonzero(edges == -1)     # ON が切れた最初のサンプルの index

    pulses = []
    for s, e in zip(starts, ends):
        duration_ms = (e - s) / fs * 1000.0
        if duration_ms < min_duration_ms:
            continue
        start_ms = s / fs * 1000.0
        pulses.append((start_ms, duration_ms))
    return pulses
