"""MicChannel: 内蔵マイク（本線）。生信号 → PulseEvent 列。

sounddevice の InputStream で連続録音し、dsp.bandpass → envelope → to_pulses で
ON 区間を切り出して on_pulse へ1個ずつ流す。decode/display はこのチャンネルを
知らない（CLAUDE.md のアーキテクチャ方針）。帯域・閾値は仮値で、実音からの確定は R8。

ストリーミング設計:
  - 音声コールバック（PortAudio スレッド）は重い処理を避け、フレームをコピーして
    キューに積むだけ。
  - ワーカースレッドがキューを吸い出して直近の音声を保持する「ローリングバッファ」を作り、
    毎サイクル bandpass→envelope→to_pulses を掛け直す（フィルタは非因果なので毎回まとめて）。
  - バッファ末尾は途中で切れている可能性があるため、guard 区間ぶん OFF を観測して
    「立ち下がりを確かに見た」パルスだけを確定して emit する。
  - 確定して emit したパルスはバッファから捨てる（base を進める）ので、二重 emit しない。
    まだ終わっていないパルスは次サイクルへ持ち越す。
"""
import queue
import threading

import numpy as np
import sounddevice as sd

from ..dsp import bandpass, envelope, to_pulses
from .base import Channel, OnPulse, PulseEvent


class MicChannel(Channel):
    """内蔵マイクから PulseEvent 列を流す本線チャンネル。

    使い方は Channel 抽象の通り:
        ch = MicChannel()
        ch.start(on_pulse)   # 非ブロッキング。ON パルス確定のたび on_pulse(event)
        ch.stop()            # 停止（未開始でも多重呼びでも安全）

    パラメータ（帯域・閾値・デバウンス）はチャンネル固有なのでコンストラクタ引数。
    既定値は仮値で、送信実機の録音から R8 で確定する（CLAUDE.md）。
    on_pulse はワーカースレッドから呼ばれる（ReplayChannel と同じ規約）。
    """

    # ストリーミング処理の内部定数（ms）。すべて GAP_MS(150) より小さく取る。
    _GUARD_MS = 80.0        # この長さ OFF を観測して初めてパルスを「確定」とみなす
    _KEEP_PAD_MS = 50.0     # 持ち越すパルスの立ち上がり手前に残す余白（< GAP_MS）
    _MIN_PROCESS_MS = 200.0  # これだけ溜まるまで DSP を掛けない（フィルタの安定化用）

    def __init__(self, device=None, fs=44100, lo=100.0, hi=400.0,
                 threshold=0.02, min_duration_ms=30.0):
        self.device = device
        self.fs = int(fs)
        self.lo = float(lo)
        self.hi = float(hi)
        self.threshold = float(threshold)
        self.min_duration_ms = float(min_duration_ms)

        # パラメータ不正はここで弾く（ワーカースレッド内の例外は握り潰されるため）
        nyq = self.fs / 2.0
        if not 0 < self.lo < self.hi < nyq:
            raise ValueError(
                f"need 0 < lo < hi < fs/2 ({nyq}); got lo={self.lo}, hi={self.hi}"
            )

        self._q: queue.Queue = queue.Queue()
        self._stream: sd.InputStream | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self, on_pulse: OnPulse) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("MicChannel is already started")
        self._stop_event.clear()
        self._drain_queue()  # 前回分の残りを捨てて再 start に備える

        self._thread = threading.Thread(
            target=self._run, args=(on_pulse,), daemon=True
        )
        # ストリームを先に開始し、成功してからワーカーを起動する。
        # 途中で例外が出たら確実に後始末してワーカーを孤立させない。
        try:
            self._stream = sd.InputStream(
                samplerate=self.fs,
                device=self.device,
                channels=1,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
            self._thread.start()
        except Exception:
            self._stop_event.set()
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            if self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._thread = None
            raise

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        """PortAudio スレッドから呼ばれる。重い処理はせず、モノラル化してキューへ。"""
        # indata は (frames, 1)。バッファは再利用されるので必ず copy する。
        self._q.put(indata[:, 0].copy())

    def _run(self, on_pulse: OnPulse) -> None:
        fs = self.fs
        guard = int(round(self._GUARD_MS * 1e-3 * fs))
        keep_pad = int(round(self._KEEP_PAD_MS * 1e-3 * fs))
        min_process = int(round(self._MIN_PROCESS_MS * 1e-3 * fs))

        buf = np.zeros(0, dtype=float)
        base = 0  # buf[0] のストリーム開始からの絶対サンプル index

        # stop 後もキューに残った分は処理してから抜ける
        while not (self._stop_event.is_set() and self._q.empty()):
            chunk = self._take_samples()
            if chunk is None:
                continue
            buf = np.concatenate([buf, chunk])
            if len(buf) < min_process:
                continue

            env = envelope(bandpass(buf, fs, self.lo, self.hi), fs)
            pulses = to_pulses(env, fs, self.threshold, self.min_duration_ms)

            buf_end = base + len(buf)        # buf の次に来る絶対サンプル
            commit_limit = buf_end - guard   # これより前に終わった ON は確定
            pending_start = None             # 末尾に掛かり未確定の ON 開始（絶対）
            last_emit_end = base             # 直近に emit したパルスの終端（絶対）

            for ls_ms, dur_ms in pulses:
                abs_start = base + int(round(ls_ms * 1e-3 * fs))
                abs_end = abs_start + int(round(dur_ms * 1e-3 * fs))
                if abs_end <= commit_limit:
                    # 立ち下がりを確かに観測 → 確定。start_ms は絶対時刻[ms]
                    on_pulse(PulseEvent(abs_start / fs * 1000.0, dur_ms))
                    last_emit_end = abs_end
                else:
                    # 末尾に掛かっている。以降は必ずこれより後なので持ち越して打ち切り
                    pending_start = abs_start
                    break

            # バッファを詰める: 未確定パルスは残し、確定済みは確実に捨てる
            if pending_start is not None:
                keep_from = max(pending_start - keep_pad, last_emit_end)
            else:
                keep_from = max(commit_limit, last_emit_end)
            drop = keep_from - base
            if drop > 0:
                buf = buf[drop:]
                base = keep_from

    def _take_samples(self):
        """キューから新着サンプルを取り出して連結。なければ None（最大0.1s待つ）。"""
        try:
            first = self._q.get(timeout=0.1)
        except queue.Empty:
            return None
        chunks = [first]
        while True:  # 溜まっている分は一気に取り込み遅延を溜めない
            try:
                chunks.append(self._q.get_nowait())
            except queue.Empty:
                break
        return np.concatenate(chunks)

    def _drain_queue(self) -> None:
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        """受信を停止する。未開始でも、多重に呼んでも安全。"""
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            # タイムアウトで生存していたら参照を残す（再 start 時の二重起動を防ぐ）
            if not self._thread.is_alive():
                self._thread = None
