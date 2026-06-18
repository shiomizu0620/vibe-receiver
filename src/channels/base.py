"""Channel 抽象基底クラスと PulseEvent / LevelStream。

センサーごとの差異は「生信号 → パルス列」の変換器（Channel）に閉じ込める。
Channel は ON パルスを検出するたびに PulseEvent を1個ずつ on_pulse コールバックへ流す。
decode/display/lookup はどのチャンネルかを知らない（CLAUDE.md のアーキテクチャ方針）。

段2では、復号とは別経路で「受信中の振幅（包絡線）」を on_level コールバックへ 0..1 で流す
（ブラウザのオシロスコープをリアルタイム駆動する）。振幅の正規化・間引きはチャンネル固有の
DSP 都合（マイク感度・閾値スケール）なので LevelStream に閉じ込め、decode/display は関与しない。
"""
from abc import ABC, abstractmethod
from collections.abc import Callable
from time import monotonic
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
# on_level(v) を 0..1 の正規化振幅ごとに呼ぶコールバックの型（段2: 波形ストリーム）
OnLevel = Callable[[float], None]


class LevelStream:
    """生の振幅サンプルを 0..1 に正規化し、目標レート以下に間引いて on_level へ流す。

    チャンネル共通の「包絡線 → level イベント」変換器。役割は2つ:
      - 間引き: 直近の emit から 1/rate 秒未満なら配信を見送る（送りすぎ防止）。見送る間も
        最大値（ピーク）は保持し、次の emit で取りこぼさない。
      - 正規化: 走行ピークによる自動ゲイン。マイク感度に依らず強い ON ≈ 1.0 に収める。
        floor（無音時に張り付くピーク下限。マイクなら閾値スケール）でノイズを 1.0 に
        誇張しないよう抑える。

    on_level が None のとき push は完全な no-op（配信しない時の計算コストを 0 にする）。
    push はチャンネルのワーカースレッドから順に呼ばれる前提でロックは持たない。
    """

    def __init__(self, on_level: OnLevel | None, rate_hz: float = 40.0,
                 peak_decay: float = 0.9, floor: float = 1e-3):
        self._on_level = on_level
        self._interval = 1.0 / rate_hz if rate_hz > 0 else 0.0
        self._decay = float(peak_decay)
        self._floor = float(floor)
        self._peak = self._floor          # 走行ピーク（自動ゲインの分母）
        self._pending = 0.0               # 間引き中に見た最大（取りこぼし防止）
        self._last_emit: float | None = None  # 直近 emit 時刻（None=未送信＝初回は必ず送る）

    def push(self, value: float, now: float | None = None) -> None:
        """生振幅 value を取り込む。レート的に送ってよければ正規化して on_level を呼ぶ。"""
        if self._on_level is None:
            return
        v = value if value > 0.0 else 0.0
        if v > self._pending:
            self._pending = v
        t = monotonic() if now is None else now
        if self._last_emit is not None and (t - self._last_emit) < self._interval:
            return  # まだ間隔に満たない → 送らず（ピークは _pending に保持済み）
        # 走行ピークを更新して自動ゲイン正規化（無音時は floor まで減衰して張り付く）
        self._peak = max(self._pending, self._peak * self._decay, self._floor)
        norm = self._pending / self._peak if self._peak > 0 else 0.0
        if norm > 1.0:
            norm = 1.0
        self._on_level(norm)
        self._last_emit = t
        self._pending = 0.0  # 次の窓のピークを取り直す


class Channel(ABC):
    """生信号 → PulseEvent 列 の変換器の抽象基底。

    使い方:
        ch.start(on_pulse)              # 受信開始。ON パルス検出のたび on_pulse(event)
        ch.start(on_pulse, on_level)    # 併せて振幅(0..1)を on_level に流す（段2・任意）
        ch.stop()                       # 受信停止

    start() は非ブロッキング（すぐ返る）で、PulseEvent は内部のストリーム/スレッドから
    流れてくる。decode 以降はこのクラスの実体（mic / piezo / replay 等）を知らない。
    on_level は任意（既定 None）で、渡されたチャンネルだけが振幅ストリームを出す。
    """

    @abstractmethod
    def start(self, on_pulse: OnPulse, on_level: OnLevel | None = None) -> None:
        """受信を開始し、PulseEvent を on_pulse に、振幅(0..1)を on_level に流す。"""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """受信を停止する。未開始でも、多重に呼んでも安全に動くこと。"""
        raise NotImplementedError
