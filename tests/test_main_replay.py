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


def test_receiver_resyncs_after_botched_send():
    """受信ループ: 送信を途中までで止めても、叩き直せば終了・再起動なしで次が通る。

    プリアンブル＋数bitで中断した打ち損じがバッファに残ったまま新しいフレームを流すと、
    最新のプリアンブルへ同期し直して復号する（「ミスったら毎回終了」を無くす自動リセット）。
    """
    ids = []
    recv = Receiver(on_frame=lambda f: ids.append(f.id))

    for pulse in build_frame_pulses([255])[:5]:  # プリアンブル2+モード1+2bit=5パルスで中断
        recv.feed(pulse)
    assert ids == []  # フレーム未完なので何も確定しない（打ち損じがバッファに残る）

    for pulse in build_frame_pulses([7]):  # 改めて最初から叩き直す
        recv.feed(pulse)
    assert ids == [7]


def test_build_frame_pulses_frame_length():
    """1フレームのパルス数 = FRAME_PULSES（プリアンブル2 + モード1 + 8bit = 11）。"""
    assert len(build_frame_pulses([42])) == FRAME_PULSES
