"""replay 経由の受信ループ通しテスト（マイク不要）。

ReplayChannel → Receiver.feed → decode の結合を、センサー無し・実時間待ちなし（speed=0）で検証する。
R6 完了条件「id=42 が end-to-end で表示され、続けて次のメッセージも受けられる」を直接確認する。
"""
from src.channels import ReplayChannel
from src.config import FRAME_PULSES
from src.main import Receiver, build_frame_pulses


def test_replay_continuous_two_messages():
    """ReplayChannel → Receiver → decode で id=42 の後、続けて id=7 も受信できる（受信ループ）。"""
    ids = []
    recv = Receiver(on_frame=lambda f: ids.append(f.id))
    ch = ReplayChannel(build_frame_pulses([42, 7]), speed=0)  # speed=0: 待たずに即時再生
    ch.start(recv.feed)
    ch.join()
    assert ids == [42, 7]


def test_decode_failure_is_skipped_then_recovers():
    """プリアンブル無しのゴミパルスでは落ちず（スキップ）、その後の正規フレームは復号できる。"""
    ids = []
    recv = Receiver(on_frame=lambda f: ids.append(f.id))

    recv.feed((0.0, 150.0))  # プリアンブルにならない短パルス → 例外を投げずスキップ
    assert ids == []

    for pulse in build_frame_pulses([42]):  # 続けて正規フレームを流すと id が得られる
        recv.feed(pulse)
    assert ids == [42]


def test_build_frame_pulses_frame_length():
    """1フレームのパルス数 = FRAME_PULSES（プリアンブル2 + モード1 + 8bit = 11）。"""
    assert len(build_frame_pulses([42])) == FRAME_PULSES
