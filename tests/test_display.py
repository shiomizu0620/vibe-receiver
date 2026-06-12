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
from src.main import Receiver, build_frame_pulses


def _make_display(no_open=False, lookup=None):
    """StringIO 出力＋スタブ opener の Display を作る。戻り値: (display, buf, opened)。"""
    buf = io.StringIO()
    # force_terminal=False で ANSI を抑えた素のテキストにして assert しやすくする。
    console = Console(file=buf, force_terminal=False, width=100)
    opened: list[str] = []
    if lookup is None:
        lookup = {42: "https://example.com"}.get
    display = Display(console=console, lookup=lookup, opener=opened.append,
                      no_open=no_open, typing_speed=0)
    return display, buf, opened


def _drive(display, recv, ids):
    """main と同じ結線でパルスを流す（on_pulse=ライブ演出, feed=復号→on_frame）。"""
    for pulse in build_frame_pulses(ids):
        display.on_pulse(pulse)
        recv.feed(pulse)


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


def test_non_id_mode_frame_is_not_opened():
    """id モード以外（id=None）のフレームは演出のみでオープンしない。"""
    display, buf, opened = _make_display(no_open=False)
    display.on_frame(Frame(mode=1, payload_bits=[1, 0, 1, 0, 1, 0, 1, 0], id=None))
    out = buf.getvalue()
    assert "mode=1" in out
    assert opened == []
