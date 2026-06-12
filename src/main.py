"""パイプライン結合・受信ループ（R6）。

    python -m src.main --channel replay          # マイク無しで通し（id=42,7 を連続受信）
    python -m src.main --channel mic --threshold 0.02   # 内蔵マイクで受信
    python src/main.py --channel replay          # 直叩きでも動く（下の sys.path 参照）

チャンネル（mic / replay）→ PulseEvent 列 → decode で id 復元 → lookup スタブで URL 表示、を結合する。
**受信ループ型**: 1メッセージ復号したら終わりではなく、連続して次のメッセージを待ち続ける（Ctrl+C で終了）。
復号失敗（プリアンブル未検出・フレーム未完など）は落ちずにスキップして次を待つ。

CLAUDE.md のアーキテクチャ方針どおり、ここはどのチャンネルかを知らない（PulseEvent 列しか見ない）。
rich のタイプ風演出と webbrowser でのオープンは display.py（R7）、本物の Supabase 逆引きは R9 の担当。
"""
import argparse
import pathlib
import sys
import time

# `python src/main.py` 直叩きでも src.* を解決できるようにリポジトリ root を通す（debug_view.py と同じ）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import config
from src.channels import ReplayChannel
from src.decode import DecodeError, decode_pulses
from src.display import Display
from src.lookup import lookup_url

# バッファ上限: フレーム未完が続いてもノイズで無限に伸びないよう、末尾だけ残してトリムする閾値（定数は config）。
_MAX_BUFFER_PULSES = config.MAX_BUFFER_FRAMES * config.FRAME_PULSES


class Receiver:
    """PulseEvent を1個ずつ受け取り、フレームが揃うたび on_frame を呼ぶ受信ループの心臓部。

    main の待機ループから切り離してあるので、ReplayChannel と組めばマイク無しでテストできる。
    feed はチャンネルのワーカースレッドから（単一スレッドで順に）呼ばれる前提なのでロックは要らない。
    """

    def __init__(self, on_frame):
        self._on_frame = on_frame
        self._buffer: list[tuple[float, float]] = []

    def feed(self, pulse) -> None:
        """ON パルス1個をバッファに足し、フレームが揃えば復号して on_frame に渡す。"""
        # PulseEvent は (start_ms, duration_ms) の NamedTuple。tuple 化して decode の入力形式に揃える。
        self._buffer.append((pulse[0], pulse[1]))
        try:
            frame = decode_pulses(self._buffer)
        except DecodeError:
            # まだフレーム未完 or プリアンブル未検出。落ちずに次のパルスを待つ（受信ループの肝）。
            if len(self._buffer) > _MAX_BUFFER_PULSES:
                # ノイズだけが流れ続けても無限に伸びないよう末尾だけ残す。
                # 形成中プリアンブルは末尾に残るので、有効フレームの取りこぼしにはならない。
                self._buffer = self._buffer[-_MAX_BUFFER_PULSES:]
            return
        # 1メッセージ確定 → バッファを空にして次メッセージの待ち受けへ続行する。
        self._buffer.clear()
        self._on_frame(frame)


def build_frame_pulses(ids, t0=0.0, frame_gap_ms=None):
    """id 列から replay 用パルス列 [(start_ms, duration_ms), ...] を生成する（デモ・テスト用）。

    PROTOCOL.md / debug_view.synth と同じ並び: プリアンブル [700ms ON, 200ms OFF]×2 →
    モードマーカー(short=0=idモード) → 8bit（MSB first, short=150ms=0 / long=450ms=1）。各ビット間は gap。
    複数 id はフレーム間を広めの gap で区切って連結する（連続受信の実証用）。
    decode は ON 長しか見ない（gap は無視）ので、gap 値は実時間再生のタイミングだけに効く。
    """
    if frame_gap_ms is None:
        frame_gap_ms = config.GAP_MS * config.FRAME_GAP_MULTIPLIER  # フレーム境界は広めに空ける
    pulses: list[tuple[float, float]] = []
    t = float(t0)
    for i, mid in enumerate(ids):
        if i > 0:
            t += frame_gap_ms
        # プリアンブル [PREAMBLE_ON, PREAMBLE_OFF] × PREAMBLE_REPEAT
        for _ in range(config.PREAMBLE_REPEAT):
            pulses.append((t, float(config.PREAMBLE_ON_MS)))
            t += config.PREAMBLE_ON_MS + config.PREAMBLE_OFF_MS
        # モードマーカー(MODE_ID=0=short) + 8bit ペイロード（MSB first）
        bits = [config.MODE_ID]
        bits += [(mid >> (config.ID_BITS - 1 - b)) & 1 for b in range(config.ID_BITS)]
        for bit in bits:
            dur = float(config.LONG_MS if bit else config.SHORT_MS)
            pulses.append((t, dur))
            t += dur + config.GAP_MS
    return pulses


def _parse_ids(spec: str) -> list[int]:
    """'42,7' のようなカンマ区切り文字列を id のリストに変換する。"""
    return [int(part) for part in spec.split(",") if part.strip() != ""]


def _build_channel(args):
    """--channel と各オプションから Channel を組み立てて返す。"""
    if args.channel == "replay":
        pulses = build_frame_pulses(_parse_ids(args.ids))
        return ReplayChannel(pulses, speed=args.speed)
    # mic: sounddevice 依存は mic 選択時のみ要求する（replay/テストでは読み込まない）
    from src.channels.mic import MicChannel
    return MicChannel(
        device=args.device, fs=args.fs, lo=args.lo, hi=args.hi,
        threshold=args.threshold, min_duration_ms=args.min_duration_ms,
    )


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="バイブコード受信（チャンネル→decode→lookup表示・受信ループ）")
    ap.add_argument("--channel", choices=["replay", "mic"], default="replay",
                    help="入力チャンネル（既定 replay: マイク無しで通し確認できる）")
    # replay 用
    ap.add_argument("--ids", type=str, default="42,7",
                    help="replay で流す id 列（カンマ区切り。連続受信の実証用に既定で2件）")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="replay の再生速度（1.0=実時間, 0=即時, >1=早送り）")
    # mic 用（既定値は MicChannel / debug_view に合わせた仮値。確定は R8）
    ap.add_argument("--device", type=int, default=None, help="入力デバイス番号（mic）")
    ap.add_argument("--fs", type=int, default=44100, help="サンプリング周波数（mic）")
    ap.add_argument("--lo", type=float, default=100.0, help="バンドパス下限Hz（mic, 仮値）")
    ap.add_argument("--hi", type=float, default=400.0, help="バンドパス上限Hz（mic, 仮値）")
    ap.add_argument("--threshold", type=float, default=0.02, help="包絡線の閾値（mic, 仮値）")
    ap.add_argument("--min-duration-ms", type=float, default=30.0, help="デバウンス長（mic）")
    ap.add_argument("--no-open", action="store_true",
                    help="URL を表示するだけでブラウザを開かない")
    args = ap.parse_args(argv)

    # Windows の既定コンソールが cp932 でも演出の記号で落ちないよう、出力を UTF-8 にしておく。
    # （対応端末では絵文字級も化けず出る。reconfigure 非対応の stdout でも握りつぶして続行する。）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    channel = _build_channel(args)
    # 演出層。lookup スタブと webbrowser は Display が内部で持つ（R9 で lookup の中身だけ差し替わる）。
    display = Display(lookup=lookup_url, no_open=args.no_open)
    receiver = Receiver(on_frame=display.on_frame)

    # チャンネルからの ON パルスを「ライブ演出(on_pulse)」と「復号(receiver.feed)」へ分配する。
    # on_pulse を先に呼ぶことで、最後のビット記号が並んだ直後に id 確定表示が続く順序になる。
    def on_pulse(pulse) -> None:
        display.on_pulse(pulse)
        receiver.feed(pulse)

    display.show_header(args.channel)
    channel.start(on_pulse)
    try:
        # 受信ループ: 何メッセージでも待ち受ける。実処理はチャンネルのワーカースレッドが on_pulse 経由で進める。
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        display.show_footer()
    finally:
        channel.stop()


if __name__ == "__main__":
    main()
