"""パイプライン結合・受信ループ（R6）。

    python -m src.main --channel replay          # マイク無しで通し（id=42,7 を連続受信）
    python -m src.main --channel mic             # 内蔵マイクで受信（閾値/デバイスは config の既定が効く）
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

from src import config, x1
from src.channels import ReplayChannel
from src.decode import DecodeError, decode_pulses
from src.display import Display
from src.lookup import get_lookup


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
            if len(self._buffer) > config.MAX_BUFFER_PULSES:
                # ノイズだけが流れ続けても無限に伸びないよう末尾だけ残す。
                # 形成中プリアンブルは末尾に残るので、有効フレームの取りこぼしにはならない。
                self._buffer = self._buffer[-config.MAX_BUFFER_PULSES:]
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


def build_x1_frame_pulses(url, t0=0.0, corrupt_bits=0):
    """URL から X1（marker=1）replay 用パルス列を生成する（デモ・テスト用）。

    送信側（X1-send）はまだ無いので、受信デコーダを単体で通すための参照エンコードを兼ねる。
    並びは build_frame_pulses と同じ: プリアンブル×2 → marker(long=1) → scheme+length+chars+checksum。
    corrupt_bits>0 で chars 以降のビットを指定本数だけ反転し、わざと checksum NG を起こす
    （length は壊さないので decode は正しい長さで本体を読み、checksum だけが食い違う＝運命サイト発動）。
    """
    bits = [config.MODE_DIRECT] + x1.encode_x1_bits(url)  # 先頭にモードマーカー(=1)を付ける
    if corrupt_bits:
        flip_start = 1 + config.X1_SCHEME_BITS + config.X1_LENGTH_BITS  # chars 領域の先頭
        for i in range(flip_start, min(flip_start + corrupt_bits, len(bits))):
            bits[i] ^= 1
    pulses: list[tuple[float, float]] = []
    t = float(t0)
    for _ in range(config.PREAMBLE_REPEAT):
        pulses.append((t, float(config.PREAMBLE_ON_MS)))
        t += config.PREAMBLE_ON_MS + config.PREAMBLE_OFF_MS
    for bit in bits:
        dur = float(config.LONG_MS if bit else config.SHORT_MS)
        pulses.append((t, dur))
        t += dur + config.GAP_MS
    return pulses


def _parse_ids(spec: str) -> list[int]:
    """'42,7' のようなカンマ区切り文字列を id のリストに変換する。"""
    return [int(part) for part in spec.split(",") if part.strip() != ""]


def _non_negative_int(text: str) -> int:
    """0 以上の整数だけ受け付ける argparse 用 type（負値は「反転0本＝無補正」と紛らわしいので弾く）。"""
    value = int(text)  # 数値でなければ argparse が ArgumentTypeError 相当に変換する
    if value < 0:
        raise argparse.ArgumentTypeError(f"0 以上で指定してください（受け取った値: {value}）")
    return value


def _build_channel(args):
    """--channel と各オプションから Channel を組み立てて返す。"""
    if args.channel == "replay":
        if args.x1_url is not None:
            # X1（URL直接モード）を流す。--x1-corrupt N で checksum NG を意図的に作れる（運命サイトのデモ）。
            # 空文字（--x1-url ""）も「X1 指定あり」として扱う（is not None で id モードへ落とさない）。
            pulses = build_x1_frame_pulses(args.x1_url, corrupt_bits=args.x1_corrupt)
        else:
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
    ap.add_argument("--x1-url", type=str, default=None,
                    help="replay で X1（URL直接モード）を流す短URL（例 github.com）。指定時は --ids より優先")
    ap.add_argument("--x1-corrupt", type=_non_negative_int, default=0, metavar="N",
                    help="X1 フレームの本体ビットを N 本（0以上）反転して checksum NG を起こす（運命サイトのデモ用）")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="replay の再生速度（1.0=実時間, 0=即時, >1=早送り）")
    # mic 用。device/threshold の既定は R8 確定値を config.py から流す（CLI で渡せば従来どおり上書き）。
    # lo/hi/fs/min-duration はまだ仮値（帯域チューニングは別途）。
    ap.add_argument("--device", type=int, default=config.MIC_DEVICE_DEFAULT,
                    help=f"入力デバイス番号（mic, 既定 {config.MIC_DEVICE_DEFAULT}=システム既定入力）")
    ap.add_argument("--fs", type=int, default=44100, help="サンプリング周波数（mic）")
    ap.add_argument("--lo", type=float, default=100.0, help="バンドパス下限Hz（mic, 仮値）")
    ap.add_argument("--hi", type=float, default=400.0, help="バンドパス上限Hz（mic, 仮値）")
    ap.add_argument("--threshold", type=float, default=config.MIC_THRESHOLD_DEFAULT,
                    help=f"包絡線の閾値（mic, 既定 {config.MIC_THRESHOLD_DEFAULT}）")
    ap.add_argument("--min-duration-ms", type=float, default=30.0, help="デバウンス長（mic）")
    ap.add_argument("--no-open", action="store_true",
                    help="URL を表示するだけでブラウザを開かない")
    ap.add_argument("--offline", action="store_true",
                    help="Supabase に繋がずローカル固定辞書で逆引き（会場 Wi-Fi 死亡時のデモ保険）")
    # WebSocket 配信（段1）: 付けるとブラウザ演出HTMLへ進行イベントをリアルタイム配信する。
    ap.add_argument("--serve", action="store_true",
                    help="WebSocket サーバーを起動し、受信進行をブラウザ演出へ配信する")
    ap.add_argument("--ws-host", type=str, default=config.WS_HOST,
                    help=f"WebSocket バインドホスト（既定 {config.WS_HOST}）")
    ap.add_argument("--ws-port", type=int, default=config.WS_PORT,
                    help=f"WebSocket ポート（既定 {config.WS_PORT}）")
    args = ap.parse_args(argv)

    # Windows の既定コンソールが cp932 でも演出の記号で落ちないよう、出力を UTF-8 にしておく。
    # （対応端末では絵文字級も化けず出る。reconfigure 非対応の stdout でも握りつぶして続行する。）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    channel = _build_channel(args)
    # --serve 時のみ WebSocket サーバーを起動（websockets 依存も serve 時のみ要求する）。
    # broadcast を Display.on_event に渡すと、進行イベントがブラウザ演出へも流れる
    # （既存の rich 演出は消さず、配信を「追加」するだけ。受信はブロックしない別スレッド）。
    ws_server = None
    ws_broadcast = None  # 起動成功時のみ Display に渡す配信フック（失敗時は None＝配信しない）
    display = None
    # サーバー起動後にチャンネル初期化（mic 等）が失敗してもポート/スレッドを確実に解放できるよう、
    # 起動～受信ループ全体を try/finally で囲む。
    try:
        if args.serve:
            from src.ws_server import WsServer
            ws_server = WsServer(host=args.ws_host, port=args.ws_port)
            if ws_server.start():
                ws_broadcast = ws_server.broadcast  # listen 成功時だけ配信を有効化
                print(f"[main] --serve: WebSocket 配信 ws://{args.ws_host}:{args.ws_port} で待受中",
                      file=sys.stderr)
                _print_browser_hint(args)
            else:
                # listen 失敗（ポート競合など）。ブラウザ配信は無効だが受信・ターミナル演出は続行する。
                err = ws_server.start_error
                print(f"[main] --serve: WebSocket サーバーを起動できませんでした"
                      f"（ws://{args.ws_host}:{args.ws_port}: {err}）。"
                      "ブラウザ配信なしで続行します。", file=sys.stderr)
        # 演出層。lookup は --offline でローカル辞書／既定で Supabase 逆引きを選ぶ（webbrowser は Display が内部で持つ）。
        display = Display(lookup=get_lookup(offline=args.offline), no_open=args.no_open,
                          on_event=ws_broadcast)
        receiver = Receiver(on_frame=display.on_frame)

        # チャンネルからの ON パルスを「ライブ演出(on_pulse)」と「復号(receiver.feed)」へ分配する。
        # on_pulse を先に呼ぶことで、最後のビット記号が並んだ直後に id 確定表示が続く順序になる。
        def on_pulse(pulse) -> None:
            display.on_pulse(pulse)
            receiver.feed(pulse)

        # 振幅ストリーム（段2）: --serve 成功時だけ level イベントをブラウザへ配信する。
        # チャンネル側で 0..1 正規化・間引き済みの値が届くので、ここは JSON に包んで投げるだけ。
        # 配信が無効（None）ならチャンネルは level を一切計算しない。
        on_level = None
        if ws_broadcast is not None:
            def on_level(v) -> None:
                ws_broadcast({"type": config.WS_EVENT_LEVEL, "v": round(float(v), 3)})

        display.show_header(args.channel)
        if args.offline:
            # 逆引き元がローカル辞書であることを明示（オンライン本線と取り違えないように）。
            print("[main] --offline: ローカル固定辞書で逆引きします（Supabase へは接続しません）",
                  file=sys.stderr)
        channel.start(on_pulse, on_level=on_level)
        # 受信ループ: 何メッセージでも待ち受ける。実処理はチャンネルのワーカースレッドが on_pulse 経由で進める。
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        if display is not None:
            display.show_footer()
    finally:
        channel.stop()
        if ws_server is not None:
            ws_server.stop()


def _print_browser_hint(args) -> None:
    """ブラウザの開き方を案内する。既定アドレス以外なら接続先をクエリで合わせる方法も示す。"""
    if args.ws_host == config.WS_HOST and args.ws_port == config.WS_PORT:
        print("[main] ブラウザで web/index.html を開いてください", file=sys.stderr)
    else:
        # web/index.html は既定で localhost:8765 へ繋ぐので、非既定時はクエリで接続先を指定する。
        print(f"[main] ブラウザで web/index.html を開いてください"
              f"（接続先を合わせるには ?wsHost={args.ws_host}&wsPort={args.ws_port} を付与）",
              file=sys.stderr)


if __name__ == "__main__":
    main()
