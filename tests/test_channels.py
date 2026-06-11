"""ReplayChannel → decode の通しテスト（センサー不要）。

ReplayChannel が流す PulseEvent を集めて decode.decode_pulses に渡し、id が正しく
復元されることを確認する。これで「チャンネル → 復号」が初めて通しで検証される。
"""
import pytest

from src import config
from src.channels.base import Channel, PulseEvent
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
