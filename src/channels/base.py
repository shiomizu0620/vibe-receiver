"""Channel 抽象基底クラスと PulseEvent。

センサーごとの差異は「生信号 → パルス列」の変換器（Channel）に閉じ込める。
Channel は ON パルスを検出するたびに PulseEvent を1個ずつ on_pulse コールバックへ流す。
decode/display/lookup はどのチャンネルかを知らない（CLAUDE.md のアーキテクチャ方針）。
"""
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import NamedTuple


class PulseEvent(NamedTuple):
    """ON 区間1つ。start_ms=立ち上がり時刻, duration_ms=ON継続長（どちらもミリ秒）。

    NamedTuple なので tuple そのものとして振る舞い、decode.decode_pulses が期待する
    (start_ms, duration_ms) 形式と完全一致する（出力形式を decode の入力に合わせる規約）。
    そのため decode 側を一切変更せずに、PulseEvent 列をそのまま渡せる。
    """
    start_ms: float
    duration_ms: float


# on_pulse(event) を PulseEvent 1個ごとに呼ぶコールバックの型
OnPulse = Callable[[PulseEvent], None]


class Channel(ABC):
    """生信号 → PulseEvent 列 の変換器の抽象基底。

    使い方:
        ch.start(on_pulse)   # 受信開始。ON パルス検出のたび on_pulse(event) が呼ばれる
        ch.stop()            # 受信停止

    start() は非ブロッキング（すぐ返る）で、PulseEvent は内部のストリーム/スレッドから
    流れてくる。decode 以降はこのクラスの実体（mic / piezo / replay 等）を知らない。
    """

    @abstractmethod
    def start(self, on_pulse: OnPulse) -> None:
        """受信を開始し、PulseEvent を1個ずつ on_pulse に流す。"""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """受信を停止する。未開始でも、多重に呼んでも安全に動くこと。"""
        raise NotImplementedError
