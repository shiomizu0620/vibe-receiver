"""MicChannel の手動確認スクリプト（実マイクが要るので自動テストにはしない）。

    python src/mic_test.py

5秒間マイク録音し、検出した PulseEvent を [(start_ms, duration_ms), ...] で表示する。
Ctrl+C で途中終了できる。閾値・帯域・デバイスはオプションで上書きできる（R8 のチューニング用）。
"""
import argparse
import pathlib
import sys
import time

# `python src/mic_test.py` 直叩きでも src.* を解決できるようにリポジトリ root を通す
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.channels.mic import MicChannel  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="マイクのパルス検出を数秒ためす")
    ap.add_argument("--device", type=int, default=None,
                    help="入力デバイス番号（python src/list_devices.py で確認）")
    ap.add_argument("--seconds", type=float, default=5.0, help="録音秒数（既定5）")
    ap.add_argument("--fs", type=int, default=44100)
    ap.add_argument("--lo", type=float, default=100.0, help="バンドパス下限Hz（仮値）")
    ap.add_argument("--hi", type=float, default=400.0, help="バンドパス上限Hz（仮値）")
    ap.add_argument("--threshold", type=float, default=0.02, help="包絡線の閾値（仮値）")
    ap.add_argument("--min-duration-ms", type=float, default=30.0, help="デバウンス長")
    args = ap.parse_args()

    pulses = []

    def on_pulse(ev):
        pulses.append(ev)
        print(f"  検出: start={ev.start_ms:8.1f}ms  duration={ev.duration_ms:7.1f}ms")

    ch = MicChannel(
        device=args.device, fs=args.fs, lo=args.lo, hi=args.hi,
        threshold=args.threshold, min_duration_ms=args.min_duration_ms,
    )

    print(f"録音開始: {args.seconds:.0f}秒間。スマホを振動させるか机を叩いてください（Ctrl+Cで中断）")
    ch.start(on_pulse)
    try:
        time.sleep(args.seconds)
    except KeyboardInterrupt:
        print("\n中断しました")
    finally:
        ch.stop()  # 残りのバッファも処理してから止まる

    result = [(round(p.start_ms, 1), round(p.duration_ms, 1)) for p in pulses]
    print()
    print(f"検出パルス列: {result}")
    print(f"パルス数: {len(result)}")
    if not result:
        print("ヒント: 0個でした。--threshold を下げる（例 0.005）か、")
        print("        --lo/--hi を実機の振動周波数に合わせてください。")
        print("        入力デバイスは python src/list_devices.py で確認できます。")


if __name__ == "__main__":
    main()
