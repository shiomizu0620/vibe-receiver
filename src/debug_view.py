"""受信デバッグ可視化（実マイクが要るので自動テストにはしない）。

    python src/debug_view.py --demo          # マイク無し・合成波形で確認
    python src/debug_view.py --seconds 5      # 5秒録音して可視化

1回の受信について「なぜそのパルス長/個数になったか」を波形レベルで目で追うためのツール。
縦4段で 生波形 / バンドパス後 / 包絡線+閾値 / 検出ON区間(短長判定) を1画面に並べる。

DSP は src.dsp の純粋関数を再利用し（処理を二重に書かない）、短/長/プリアンブルの判定は
src.decode.classify_pulse を再利用する。帯域・閾値・デバイスは mic_test.py と同じ調整軸を
オプションで上書きできる（R8 のチューニング用）。
"""
import argparse
import pathlib
import sys

# `python src/debug_view.py` 直叩きでも src.* を解決できるようにリポジトリ root を通す
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np

from src import config
from src.decode import classify_pulse
from src.dsp import bandpass, envelope, to_pulses

# 各パルス種別の帯の色（包絡線段のハイライト＆全段の薄い重ね描き用）
_KIND_COLOR = {
    "short": "tab:green",      # bit 0
    "long": "tab:orange",      # bit 1
    "preamble": "tab:red",     # プリアンブル
}


def synth_demo_signal(fs, carrier_hz=250.0, noise_amp=0.01, lead_ms=150.0,
                      payload_id=42):
    """マイク無しで動作確認するための合成波形（id=payload_id の理想信号）。

    PROTOCOL.md の並び: プリアンブル [700ms ON, 200ms OFF]×2 → モードマーカー(short)
    → 8bit（MSB first, short=150ms=0 / long=450ms=1）。各ビット間は gap(150ms) で区切る。
    閾値線が「ノイズと信号の間」に見えるよう低振幅ノイズを載せる。
    これはデモ専用の信号生成なので DSP ではなくこのファイルに置く。
    """
    rng = np.random.default_rng(0)

    def burst(dur_ms):
        n = int(round(dur_ms * 1e-3 * fs))
        t = np.arange(n) / fs
        return np.sin(2 * np.pi * carrier_hz * t)

    def silence(dur_ms):
        return np.zeros(int(round(dur_ms * 1e-3 * fs)))

    parts = [silence(lead_ms)]
    # プリアンブル [700ms ON, 200ms OFF] × 2
    for _ in range(config.PREAMBLE_REPEAT):
        parts.append(burst(config.PREAMBLE_ON_MS))
        parts.append(silence(config.PREAMBLE_OFF_MS))

    # モードマーカー(0=idモード=short) + 8bit ペイロード（MSB first）
    bits = [config.MODE_ID]
    bits += [(payload_id >> (config.ID_BITS - 1 - i)) & 1 for i in range(config.ID_BITS)]
    for b in bits:
        parts.append(burst(config.LONG_MS if b else config.SHORT_MS))
        parts.append(silence(config.GAP_MS))

    sig = np.concatenate(parts)
    sig += noise_amp * rng.standard_normal(len(sig))  # 低振幅ノイズ
    return sig


def record_signal(device, fs, seconds):
    """sounddevice で seconds 秒モノラル録音し、1次元 numpy 配列で返す。

    MicChannel は PulseEvent 列しか出さず生波形を返さないので、可視化用に生録音を直接取る。
    sounddevice は実録音時のみ要求する（--demo ではマイク不要にするため遅延 import）。
    """
    try:
        import sounddevice as sd
    except ModuleNotFoundError as e:
        if e.name != "sounddevice":
            raise
        print(f"依存モジュールが見つかりません: {e}")
        print("pip install sounddevice を実行するか、--demo を使ってください。")
        sys.exit(1)

    print(f"録音開始: {seconds:.0f}秒間。スマホを振動させるか机を叩いてください")
    rec = sd.rec(int(round(seconds * fs)), samplerate=fs, channels=1,
                 device=device, dtype="float32")
    sd.wait()
    return rec[:, 0]


def plot_debug(signal, fs, lo, hi, threshold, min_duration_ms, save=None, title=""):
    """生波形→バンドパス→包絡線+閾値→検出ON区間 を縦4段で可視化する。

    DSP は src.dsp を、短/長/プリアンブル判定は src.decode.classify_pulse を再利用する。
    """
    try:
        import matplotlib
        if save is not None:
            matplotlib.use("Agg")  # 保存のみのときは画面が無くても動くように
        import matplotlib.pyplot as plt
    except ModuleNotFoundError as e:
        print(f"依存モジュールが見つかりません: {e}")
        print("pip install matplotlib を実行してください。")
        sys.exit(1)

    filtered = bandpass(signal, fs, lo, hi)
    env = envelope(filtered, fs)
    pulses = to_pulses(env, fs, threshold, min_duration_ms)

    # 検出結果はターミナルにも残す（画面を見なくても結果が分かる）
    print()
    print(f"検出パルス数: {len(pulses)}")
    for start_ms, dur_ms in pulses:
        kind = classify_pulse(dur_ms)
        print(f"  start={start_ms:8.1f}ms  duration={dur_ms:7.1f}ms  -> {kind}")
    if not pulses:
        print("ヒント: 0個でした。--threshold を下げる（例 0.005）か、")
        print("        --lo/--hi を実機の振動周波数に合わせてください。")

    t_ms = np.arange(len(signal)) / fs * 1000.0

    fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True)
    ax_raw, ax_bp, ax_env, ax_pulse = axes

    # 図中テキストは ASCII/英語（matplotlib 既定フォントに日本語が無く豆腐になるため）。
    # 日本語はコメントとターミナル出力側に置く。
    ax_raw.plot(t_ms, signal, color="0.4", linewidth=0.6)
    ax_raw.set_ylabel("raw")

    ax_bp.plot(t_ms, filtered, color="tab:blue", linewidth=0.6)
    ax_bp.set_ylabel(f"bandpass\n{lo:.0f}-{hi:.0f}Hz")

    ax_env.plot(t_ms, env, color="tab:purple", linewidth=1.0)
    ax_env.axhline(threshold, color="red", linestyle="--", linewidth=1.0,
                   label=f"threshold={threshold:g}")
    ax_env.set_ylabel("envelope")
    ax_env.legend(loc="upper right")

    ax_pulse.plot(t_ms, env, color="tab:purple", linewidth=1.0)
    ax_pulse.set_ylabel("detected ON")
    ax_pulse.set_xlabel("time [ms]")

    # 検出ON区間を帯で重ねる。包絡線段(下2段)は濃いめ＋種別ラベル、上2段は薄く時間合わせ用。
    env_max = float(env.max()) if len(env) else 0.0
    label_y = env_max if env_max > 0 else 1.0
    for start_ms, dur_ms in pulses:
        kind = classify_pulse(dur_ms)
        color = _KIND_COLOR.get(kind, "tab:gray")
        end_ms = start_ms + dur_ms
        for ax in (ax_raw, ax_bp):
            ax.axvspan(start_ms, end_ms, color=color, alpha=0.12)
        for ax in (ax_env, ax_pulse):
            ax.axvspan(start_ms, end_ms, color=color, alpha=0.25)
        ax_pulse.text(start_ms + dur_ms / 2.0, label_y * 1.02,
                      f"{kind}\n{dur_ms:.0f}ms", ha="center", va="bottom",
                      fontsize=8, color=color)

    fig.suptitle(title or "receiver debug view")
    fig.tight_layout()

    if save is not None:
        fig.savefig(save, dpi=120)
        print(f"\n保存しました: {save}")
    else:
        plt.show()


def main():
    ap = argparse.ArgumentParser(description="受信のデバッグ可視化（波形/包絡線/検出パルス）")
    ap.add_argument("--device", type=int, default=None,
                    help="入力デバイス番号（python src/list_devices.py で確認）")
    ap.add_argument("--seconds", type=float, default=5.0, help="録音秒数（既定5）")
    ap.add_argument("--fs", type=int, default=44100)
    ap.add_argument("--lo", type=float, default=100.0, help="バンドパス下限Hz（仮値）")
    ap.add_argument("--hi", type=float, default=400.0, help="バンドパス上限Hz（仮値）")
    ap.add_argument("--threshold", type=float, default=0.02, help="包絡線の閾値（仮値）")
    ap.add_argument("--min-duration-ms", type=float, default=30.0, help="デバウンス長")
    ap.add_argument("--demo", action="store_true",
                    help="マイク無しで合成サンプル波形を表示")
    ap.add_argument("--save", type=str, default=None,
                    help="プロットをPNGに保存（指定時は画面表示しない）")
    args = ap.parse_args()

    if args.demo:
        signal = synth_demo_signal(args.fs)
        title = "receiver debug view (--demo: synthetic id=42)"
    else:
        signal = record_signal(args.device, args.fs, args.seconds)
        title = f"receiver debug view (recorded {args.seconds:.0f}s)"

    plot_debug(signal, args.fs, args.lo, args.hi, args.threshold,
               args.min_duration_ms, save=args.save, title=title)


if __name__ == "__main__":
    main()
