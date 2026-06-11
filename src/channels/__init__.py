"""チャンネル・プラグイン群。

センサーごとの差異は「生信号 → パルス列」の変換器（Channel）に閉じ込める。
decode/display/lookup はどのチャンネルかを知らない（CLAUDE.md のアーキテクチャ方針）。
"""
from .base import Channel, OnPulse, PulseEvent
from .replay import ReplayChannel

__all__ = ["Channel", "OnPulse", "PulseEvent", "ReplayChannel"]
