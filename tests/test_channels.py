"""ReplayChannel → decode の通しテスト（センサー不要）。

ReplayChannel が流す PulseEvent を集めて decode.decode_pulses に渡し、id が正しく
復元されることを確認する。これで「チャンネル → 復号」が初めて通しで検証される。
"""
import pytest

from src import config
from src.channels.base import Channel, LevelStream, PulseEvent
from src.channels.replay import ReplayChannel
from src.decode import decode_pulses


def make_pulses(bits):
    """プリアンブル×2 + モードマーカー(0=id) + bits のパルス列を (start_ms, duration_ms) で生成。"""
    durs = [config.PREAMBLE_ON_MS, config.PREAMBLE_ON_MS, config.SHORT_MS]  # マーカー=0
    durs += [config.LONG_MS if b else config.SHORT_MS for b in bits]
    t, out = 0.0, []
    for d in durs:
        out.append((t, d))
        t += d + config.GAP_MS
    return out


def collect(channel):
    """チャンネルを再生し、流れてきた PulseEvent を順に集めて返す（完了まで待つ）。"""
    events = []
    channel.start(events.append)
    channel.join()
    return events


def test_channel_is_abstract():
    """Channel は抽象基底なので直接インスタンス化できない。"""
    with pytest.raises(TypeError):
        Channel()


def test_replay_immediate_decodes_id_42():
    """即時モード: ReplayChannel → decode で id=42 が復元される（R3 完了条件）。"""
    bits = [0, 0, 1, 0, 1, 0, 1, 0]  # 42 = 00101010
    ch = ReplayChannel(make_pulses(bits), speed=0)
    assert decode_pulses(collect(ch)).id == 42


def test_replay_decodes_0_and_255():
    """境界値: 全0→0、全1→255 も通しで復元される。"""
    assert decode_pulses(collect(ReplayChannel(make_pulses([0] * 8), speed=0))).id == 0
    assert decode_pulses(collect(ReplayChannel(make_pulses([1] * 8), speed=0))).id == 255


def test_replay_emits_pulse_events_matching_input():
    """流れてくるのは PulseEvent（=tuple）で、入力パルス列と完全一致する。"""
    pulses = make_pulses([1, 0, 1, 1, 0, 0, 1, 0])
    events = collect(ReplayChannel(pulses, speed=0))
    assert len(events) == len(pulses)
    assert all(isinstance(e, PulseEvent) for e in events)
    assert all(isinstance(e, tuple) for e in events)  # decode が期待する tuple 形式
    assert [tuple(e) for e in events] == pulses


def test_replay_realtime_path_decodes():
    """実時間再生パス（speed>0 でスリープを伴う経路）でも id が復元される。"""
    bits = [0, 0, 1, 0, 1, 0, 1, 0]  # 42
    ch = ReplayChannel(make_pulses(bits), speed=200.0)  # 高速化してテストを軽く保つ
    assert decode_pulses(collect(ch)).id == 42


def test_stop_interrupts_playback():
    """実時間再生を即 stop すると、全パルスは流れずに止まる。"""
    pulses = [(i * 1000.0, 100.0) for i in range(10)]  # 1秒間隔（実時間なら計~9秒）
    ch = ReplayChannel(pulses, speed=1.0)
    events = []
    ch.start(events.append)
    ch.stop()  # 即停止して join
    assert len(events) < len(pulses)


def test_negative_speed_rejected():
    """負の速度は不正。"""
    with pytest.raises(ValueError):
        ReplayChannel(make_pulses([0] * 8), speed=-1.0)


# ---- 段2: 振幅ストリーム（level） ----------------------------------------------

def test_replay_emits_synthetic_level_on_off():
    """on_level を渡すと、各パルスごとに ON=1.0 → OFF=0.0 の合成振幅が流れる。"""
    pulses = make_pulses([1, 0, 1])  # プリアンブル2 + マーカー + 3bit = 6 パルス
    levels = []
    ch = ReplayChannel(pulses, speed=0)
    ch.start(lambda _p: None, on_level=levels.append)
    ch.join()
    # パルス1個につき 1.0, 0.0 の2値。ON だけ・OFF だけを取り出すと全パルス分そろう。
    assert levels[0::2] == [1.0] * len(pulses)
    assert levels[1::2] == [0.0] * len(pulses)


def test_replay_without_on_level_emits_nothing_extra():
    """on_level 省略時は従来どおり（level を出さず PulseEvent だけ）。"""
    pulses = make_pulses([0] * 8)
    events = collect(ReplayChannel(pulses, speed=0))  # collect は on_level を渡さない
    assert [tuple(e) for e in events] == pulses  # 振る舞いは段1と不変


def test_level_stream_throttles_and_autogains():
    """LevelStream は目標レート以下に間引き、走行ピークで 0..1 に自動正規化する。"""
    out = []
    ls = LevelStream(out.append, rate_hz=10.0, peak_decay=0.5, floor=0.1)  # interval=0.1s
    ls.push(1.0, now=0.00)   # 初回は必ず emit。強信号なので 1.0
    ls.push(0.5, now=0.05)   # 間隔(0.1s)未満 → 間引かれ出ない（ピーク0.5は保持される）
    ls.push(0.2, now=0.15)   # 間隔OK → 保持したピーク0.5を自動ゲインで 1.0 として出す
    ls.push(0.05, now=0.30)  # 弱信号 → floor 基準で 1.0 未満
    assert len(out) == 3                 # 2番目は間引かれた
    assert out[0] == 1.0 and out[1] == 1.0
    assert 0.0 < out[2] < 0.5            # 弱信号は低く出る
    assert all(0.0 <= v <= 1.0 for v in out)


def test_level_stream_noop_without_callback():
    """on_level が None なら push は完全な no-op（配信無効時のコスト0）。"""
    ls = LevelStream(None)
    ls.push(1.0)
    ls.push(0.5, now=99.0)  # 例外を投げず、何も起きない
