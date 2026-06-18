"""ターミナル演出（R7）。受信の流れを rich で「見える化」する表示層。

    プリアンブル検出 → 「受信開始」パネル
    各 ON パルス到着 → ●(短/0) / ━(長/1) が1つずつ並ぶライブ演出
    フレーム確定     → 復元した id とビット列を表示
    URL 解決         → URL をタイプライター風に1文字ずつ出してから webbrowser で開く

設計（CLAUDE.md のアーキテクチャ方針）:
- ここは **チャンネルを知らない**。PulseEvent 列（on_pulse）と確定 Frame（on_frame）しか見ない。
  main がチャンネルのコールバックを on_pulse と Receiver.feed に分配するので、mic でも replay でも同じ演出になる。
- id→URL の解決（lookup）とブラウザを開く処理（opener）は **注入**する。
  既定は src.lookup.lookup_url と webbrowser.open。テストではスタブを差し込めるので、
  実 DB・実ブラウザ無しで演出ロジックを検証できる（演出に artificial な遅延を入れる部分も速度0でテスト可）。
- ビット表示は decode と同じ判定基準を使う（src.decode.classify_pulse の再利用＝二重実装しない）。
  ライブ行はチャンネルから届く「生のパルス」を順に描くだけの飾りで、id の真値は必ず decode（on_frame の Frame）に従う。
"""
import time
import webbrowser

from rich.box import SQUARE
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import config
from .decode import classify_pulse
from .lookup import lookup_url

# ビット記号（PROTOCOL.md: 短 150ms=0 / 長 450ms=1）。issue 指定どおり ●=0, ━=1。
SHORT_GLYPH = "●"   # 短い振動 = bit 0
LONG_GLYPH = "━"    # 長い振動 = bit 1

_BIT_STYLE = {0: "bold cyan", 1: "bold yellow"}

# Windows の既定コンソール（cp932）では絵文字や rich 既定の角丸ボックス(╭╮)が encode できず落ちる。
# 演出に使う記号は cp932 でも出せるものだけにし（● ━ │ ─ → は安全）、Panel も SQUARE ボックスを使う。
_BOX = SQUARE


def glyph_for_bit(bit: int) -> str:
    """ビット値 → 記号（0→●, 1→━）。"""
    return LONG_GLYPH if bit else SHORT_GLYPH


def kind_to_bit(kind: str) -> int:
    """classify_pulse の種別 → ビット値（long→1, それ以外→0）。"""
    return 1 if kind == "long" else 0


def bits_to_glyphs(bits) -> str:
    """ビット列 → 記号列（スペース区切り）。確定表示でのビット確認用。"""
    return " ".join(glyph_for_bit(b) for b in bits)


class Display:
    """受信の演出を司る表示層。on_pulse（パルス到着）と on_frame（フレーム確定）で駆動する。

    使い方（main の結線）:
        display = Display(no_open=args.no_open)
        receiver = Receiver(on_frame=display.on_frame)
        channel.start(lambda p: (display.on_pulse(p), receiver.feed(p)))
    """

    def __init__(self, console: Console | None = None, lookup=lookup_url,
                 opener=webbrowser.open, no_open: bool = False,
                 typing_speed: float = 0.025, on_event=None):
        # console を注入できるようにして、テストでは StringIO に流して出力を検証する。
        self._console = console if console is not None else Console()
        self._lookup = lookup          # id -> url | None（R9 で Supabase 実装に差し替わる）
        self._opener = opener          # url を開く callable（既定 webbrowser.open）
        self._no_open = no_open        # True なら URL 表示のみでブラウザは開かない
        self._typing_speed = typing_speed  # タイプライターの1文字あたり秒（テストは0で即時）
        # 進行イベントの追加配信フック（段1: ブラウザ演出へ WebSocket 送信）。
        # 既定 None なら何もせず、従来どおりターミナル演出だけが動く。dict を1個ずつ渡す。
        # main が --serve 時に WsServer.broadcast を結線する（display は WS を知らない）。
        self._on_event = on_event
        # ライブ演出の状態（1フレーム分）。on_pulse 間で持ち越す軽量ステートマシン。
        self._preamble_run = 0   # 連続して見えたプリアンブル級 ON の数
        self._in_frame = False   # プリアンブル検出後＝フレーム本体を読んでいる最中か
        self._pulse_in_frame = 0  # プリアンブル後に届いたパルス数（1個目=モードマーカー）

    def _emit(self, event: dict) -> None:
        """進行イベントを追加フックへ流す（未設定なら何もしない）。配信失敗で演出を止めない。"""
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:
            pass  # ブラウザ配信の不調でターミナル演出・受信を巻き込まない

    # ---- 起動/終了の飾り（main から呼ぶ） -------------------------------------

    def show_header(self, channel_name: str) -> None:
        """受信待機の見出しを表示する。"""
        self._console.print(Panel.fit(
            f"[bold]バイブコード受信[/]  channel=[cyan]{channel_name}[/]\n"
            "[dim]Ctrl+C で終了[/]",
            title="待機中", border_style="green", box=_BOX))
        self._emit({"type": "listening"})  # 待機開始をブラウザへ

    def show_footer(self) -> None:
        """終了メッセージ。"""
        self._console.print("\n[dim]終了します。[/]")

    # ---- パルス到着ごとの演出 -------------------------------------------------

    def on_pulse(self, pulse) -> None:
        """ON パルス1個（start_ms, duration_ms）が届くたびに呼ばれる。ライブ行を1記号ずつ伸ばす。"""
        kind = classify_pulse(pulse[1])
        if kind == "preamble":
            self._preamble_run += 1
            # プリアンブル級 ON が規定回数そろったらフレーム開始＝「受信開始」を出す。
            if self._preamble_run == config.PREAMBLE_REPEAT:
                self._start_frame()
            return
        # 短/長が来たらプリアンブルの連続は途切れる（decode の検出規則と同じ考え方）。
        self._preamble_run = 0
        if not self._in_frame:
            return  # プリアンブル前のはぐれパルスは演出しない
        self._pulse_in_frame += 1
        if self._pulse_in_frame == 1:
            # 1個目はモードマーカー。ビットではないので控えめに（dim）出す。
            self._console.print(Text(glyph_for_bit(kind_to_bit(kind)),
                                     style="dim"), end="")
            self._console.print(Text(" │ ", style="dim"), end="")
        else:
            bit = kind_to_bit(kind)
            self._console.print(Text(glyph_for_bit(bit) + " ",
                                     style=_BIT_STYLE[bit]), end="")
            # データビット確定（モードマーカーは除く・MSB first で1個ずつ）をブラウザへ。
            self._emit({"type": "bit", "value": bit})

    def _start_frame(self) -> None:
        """プリアンブル検出 → 「受信開始」表示してビット行の描画を始める。"""
        self._in_frame = True
        self._pulse_in_frame = 0
        self._console.print()  # 直前の出力から1行空ける
        self._console.print(Panel.fit("[bold green]受信開始[/]  "
                                       "[dim]プリアンブル検出[/]",
                                       border_style="green", box=_BOX))
        self._console.print("  ", end="")  # ビット行のインデント
        self._emit({"type": "preamble"})   # プリアンブル検出をブラウザへ

    # ---- フレーム確定ごとの演出 -----------------------------------------------

    def on_frame(self, frame) -> None:
        """1フレーム確定時に呼ばれる。id を表示し、URL を解決してタイプライター演出→オープン。"""
        self._console.print()  # ライブ行を閉じる
        if frame.id is None:
            # モードマーカー=1（直接符号化・stretch）。R7 では id モードのみ演出する。
            self._console.print(Panel.fit(
                f"mode={frame.mode}（id モード以外・未対応）",
                border_style="yellow", box=_BOX))
            self._reset()
            return

        glyphs = bits_to_glyphs(frame.payload_bits)
        self._console.print(Panel.fit(
            f"id = [bold white]{frame.id}[/]\n[dim]bits[/] {glyphs}",
            title="復元", border_style="cyan", box=_BOX))
        self._emit({"type": "decoded", "id": frame.id})  # id 確定をブラウザへ

        url = self._lookup(frame.id)
        if url is None:
            self._console.print(f"[yellow]→ id={frame.id} は未登録です[/]\n")
            self._reset()
            return
        self._emit({"type": "url", "url": url})  # 逆引き結果をブラウザへ

        self._console.print("URL ", end="")
        self._typewriter(url)
        self._console.print()
        if self._no_open:
            self._console.print("[dim]→ --no-open: ブラウザは開きません[/]\n")
        else:
            self._console.print("[green]→ ブラウザで開きます[/]\n")
            self._emit({"type": "open", "url": url})  # オープンをブラウザへ
            self._opener(url)
        self._reset()

    def _typewriter(self, text: str) -> None:
        """文字列を1文字ずつ出す。URL を「打ち込んでいる」風に見せる。"""
        for ch in text:
            self._console.print(Text(ch, style="bold underline blue"), end="")
            if self._typing_speed > 0:
                time.sleep(self._typing_speed)

    def _reset(self) -> None:
        """フレーム間でライブ演出の状態を初期化する。"""
        self._preamble_run = 0
        self._in_frame = False
        self._pulse_in_frame = 0
