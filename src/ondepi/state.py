from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LevelState:
    rms_left: float = 0.0
    rms_right: float = 0.0
    peak_left: float = 0.0
    peak_right: float = 0.0


@dataclass
class StreamState:
    streaming: bool = False
    streaming_requested: bool = False
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None
    levels: LevelState = field(default_factory=LevelState)
    gain_db: float = 0.0
    input_clip: bool = False
    retry_count: int = 0
    last_retry_at: Optional[datetime] = None
    last_exit_code: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "streaming": self.streaming,
            "streaming_requested": self.streaming_requested,
            "last_error": self.last_error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "levels": {
                "rms_left": self.levels.rms_left,
                "rms_right": self.levels.rms_right,
                "peak_left": self.levels.peak_left,
                "peak_right": self.levels.peak_right,
            },
            "gain_db": self.gain_db,
            "input_clip": self.input_clip,
            "retry_count": self.retry_count,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "last_exit_code": self.last_exit_code,
        }
