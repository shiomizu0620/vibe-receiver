"""ReplayChannel: あらかじめ与えたパルス列を再生するダミーチャンネル。

センサーなしで「チャンネル → decode → id」の通し検証や UI 開発を可能にする（R3 の核）。
本物のチャンネル（mic 等）と同じ Channel インターフェースで PulseEvent を流すため、
decode/display/main から見れば mic と区別がつかない。
"""
import threading
import time
from collections.abc import Iterable

from .base import Channel, OnLevel, OnPulse, PulseEvent


class ReplayChannel(Channel):
    """パルス列 [(start_ms, duration_ms), ...] を実時間どおりに再生する。

    各パルスは start_ms のタイミングで on_pulse に流れる（速度は speed 倍）。
        speed=1.0 → 実時間どおり（既定）
        speed>1.0 → 早送り
        speed=0   → 待たずに即時に全部流す（テスト用）

    段2: on_level を渡すと、合成的な振幅(0..1)も流す。ON 開始で 1.0、ON 終了で 0.0 を
    出すだけ（ステップ波形なので連続値より疎で十分）。本物の包絡線は持たないが、ブラウザの
    オシロは ON のとき波形が大きく・OFF で静まる、を実時間で再現できる。

    start() は非ブロッキング: 再生は内部スレッドで進む。自然完了を待つには join()、
    途中で止めるには stop() を使う。
    """

    def __init__(self, pulses: Iterable[tuple[float, float]], speed: float = 1.0):
        if speed < 0:
            raise ValueError(f"speed must be >= 0; got {speed}")
        self._pulses = [PulseEvent(float(s), float(d)) for s, d in pulses]
        self._speed = float(speed)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self, on_pulse: OnPulse, on_level: OnLevel | None = None) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("ReplayChannel is already started")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, args=(on_pulse, on_level), daemon=True
        )
        self._thread.start()

    def _run(self, on_pulse: OnPulse, on_level: OnLevel | None) -> None:
        t0 = time.monotonic()
        for ev in self._pulses:
            if self._stop_event.is_set():
                return
            if self._speed > 0:
                target = t0 + (ev.start_ms / 1000.0) / self._speed
                delay = target - time.monotonic()
                # stop されたら割り込んで終了（True が返る）
                if delay > 0 and self._stop_event.wait(delay):
                    return
            on_pulse(ev)
            if on_level is not None:
                on_level(1.0)  # ON 開始 → 波形を高く
                if self._speed > 0:
                    # ON 継続ぶん待ってから立ち下げる（合成包絡線の OFF）。次パルスの start
                    # は duration+gap 後なので、ここで待っても on_pulse のタイミングは不変。
                    off_target = t0 + ((ev.start_ms + ev.duration_ms) / 1000.0) / self._speed
                    delay = off_target - time.monotonic()
                    if delay > 0 and self._stop_event.wait(delay):
                        return
                on_level(0.0)  # OFF → 波形を静める（idle）

    def join(self, timeout: float | None = None) -> None:
        """再生が自然に完了するまで待つ（テスト・ワンショット再生用）。"""
        if self._thread is not None:
            self._thread.join(timeout)

    def stop(self) -> None:
        """再生を止める。未開始でも、多重に呼んでも安全。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
