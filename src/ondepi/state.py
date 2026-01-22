from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class LevelState:
    rms: float = 0.0
    peak: float = 0.0


@dataclass
class StreamState:
    streaming: bool = False
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None
    levels: LevelState = field(default_factory=LevelState)
    gain_db: float = 0.0
    retry_count: int = 0
    last_retry_at: Optional[datetime] = None
    last_exit_code: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "streaming": self.streaming,
            "last_error": self.last_error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "levels": {
                "rms": self.levels.rms,
                "peak": self.levels.peak,
            },
            "gain_db": self.gain_db,
            "retry_count": self.retry_count,
            "last_retry_at": self.last_retry_at.isoformat() if self.last_retry_at else None,
            "last_exit_code": self.last_exit_code,
        }
