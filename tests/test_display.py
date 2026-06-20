"""display.py の演出ロジックのテスト（端末・実ブラウザ不要）。

Console を StringIO に流して出力テキストを検証し、ブラウザを開く処理はスタブ opener で記録する。
タイプライターは typing_speed=0 で即時化。実際の受信結線（on_pulse + Receiver.feed + on_frame）を
そのまま使い、replay 用パルス列から end-to-end で演出が出ることを確かめる。
"""
import io

from rich.console import Console

from src.decode import Frame
from src.display import (
    LONG_GLYPH,
    SHORT_GLYPH,
    Display,
    bits_to_glyphs,
    glyph_for_bit,
    kind_to_bit,
)
from src.main import Receiver, build_frame_pulses, build_x1_frame_pulses


def _make_display(no_open=False, lookup=None, fun_sites=None, fun_picker=None):
    """StringIO 出力＋スタブ opener の Display を作る。戻り値: (display, buf, opened)。"""
    buf = io.StringIO()
    # force_terminal=False で ANSI を抑えた素のテキストにして assert しやすくする。
    console = Console(file=buf, force_terminal=False, width=100)
    opened: list[str] = []
    if lookup is None:
        lookup = {42: "https://example.com"}.get
    if fun_picker is None:
        def fun_picker(sites):  # テストは決定的に先頭を選ぶ
            return sites[0]
    display = Display(console=console, lookup=lookup, opener=opened.append,
                      no_open=no_open, typing_speed=0,
                      fun_sites=fun_sites, fun_picker=fun_picker)
    return display, buf, opened


def _drive_pulses(display, recv, pulses):
    """main と同じ結線でパルス列を流す（on_pulse=ライブ演出, feed=復号→on_frame）。"""
    for pulse in pulses:
        display.on_pulse(pulse)
        recv.feed(pulse)


def _drive(display, recv, ids):
    """id 列から replay 用パルスを流す。"""
    _drive_pulses(display, recv, build_frame_pulses(ids))


def test_glyph_mapping():
    """記号対応: 0/短→●, 1/長→━（issue 指定）。"""
    assert glyph_for_bit(0) == SHORT_GLYPH == "●"
    assert glyph_for_bit(1) == LONG_GLYPH == "━"
    assert kind_to_bit("long") == 1
    assert kind_to_bit("short") == 0
    assert kind_to_bit("preamble") == 0  # ビットではないが既定で 0 扱い
    # 42 = 0b00101010
    assert bits_to_glyphs([0, 0, 1, 0, 1, 0, 1, 0]) == "● ● ━ ● ━ ● ━ ●"


def test_full_frame_shows_preamble_id_url_and_opens():
    """1フレーム通すと 受信開始→id→URL が出て、ブラウザが開かれる。"""
    display, buf, opened = _make_display(no_open=False)
    recv = Receiver(on_frame=display.on_frame)
    _drive(display, recv, [42])
    out = buf.getvalue()
    assert "受信開始" in out          # プリアンブル検出表示
    assert "42" in out                # 復元した id
    assert "https://example.com" in out  # タイプライターで出した URL
    assert SHORT_GLYPH in out and LONG_GLYPH in out  # ライブのビット記号
    assert opened == ["https://example.com"]  # URL 解決後にオープン


def test_no_open_shows_url_but_does_not_open():
    """--no-open 相当: URL は表示するがブラウザは開かない。"""
    display, buf, opened = _make_display(no_open=True)
    recv = Receiver(on_frame=display.on_frame)
    _drive(display, recv, [42])
    out = buf.getvalue()
    assert "https://example.com" in out
    assert opened == []


def test_unknown_id_is_not_opened():
    """未登録 id では「未登録」を表示し、ブラウザは開かない。"""
    display, buf, opened = _make_display(no_open=False, lookup=lambda i: None)
    recv = Receiver(on_frame=display.on_frame)
    _drive(display, recv, [99])
    out = buf.getvalue()
    assert "未登録" in out
    assert opened == []


def test_x1_checksum_ok_opens_url():
    """X1（marker=1）checksum OK → 復元 URL がタイプ表示され、そのままオープンされる。"""
    display, buf, opened = _make_display(no_open=False)
    recv = Receiver(on_frame=display.on_frame)
    _drive_pulses(display, recv, build_x1_frame_pulses("github.com"))
    out = buf.getvalue()
    assert "X1" in out                          # X1 受信パネル
    assert "https://github.com" in out          # タイプライターで出した URL
    assert opened == ["https://github.com"]


def test_x1_checksum_ng_opens_fun_site():
    """X1 checksum NG（ビット反転）→ 運命のサイトが開く（FUN_SITES から決定的に先頭）。"""
    display, buf, opened = _make_display(
        no_open=False, fun_sites=["https://fate.example/roll"],
        fun_picker=lambda sites: sites[0])
    recv = Receiver(on_frame=display.on_frame)
    _drive_pulses(display, recv, build_x1_frame_pulses("github.com", corrupt_bits=3))
    out = buf.getvalue()
    assert "運命" in out                         # 「運命のサイトへ🎲」表示
    assert "https://github.com" not in out       # 壊れたので本来の URL は開かない
    assert opened == ["https://fate.example/roll"]


def test_unknown_mode_frame_is_not_opened():
    """将来拡張の未対応モード（mode=2 等）は演出のみでオープンしない。"""
    display, buf, opened = _make_display(no_open=False)
    display.on_frame(Frame(mode=2, payload_bits=[1, 0, 1, 0]))
    out = buf.getvalue()
    assert "mode=2" in out
    assert opened == []
