"""マイクデバイス一覧を表示する。

    python src/list_devices.py

入力に使えるデバイス（max_input_channels > 0）の番号・名前を表示し、既定の入力デバイスに
* を付ける。ここで出た番号を MicChannel(device=番号) / mic_test.py --device 番号 に渡す。
"""
import sys

import sounddevice as sd


def main():
    # デバイス名にコンソール(cp932等)で表せない文字があっても落ちないよう置換に倒す
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    devices = sd.query_devices()
    try:
        default_in = sd.default.device[0]  # (input, output) の input 側
    except Exception:
        default_in = None

    print("入力デバイス一覧（* = 既定の入力）")
    print(f"{'':1} {'idx':>3}  {'in':>2}  {'rate':>7}  name")
    found = False
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] <= 0:
            continue
        found = True
        mark = "*" if idx == default_in else " "
        rate = int(dev["default_samplerate"])
        print(f"{mark:1} {idx:>3}  {dev['max_input_channels']:>2}  {rate:>7}  {dev['name']}")
    if not found:
        print("（入力デバイスが見つかりません）")


if __name__ == "__main__":
    main()
