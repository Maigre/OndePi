from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SerialCommand:
    """Incoming command from M5Stack."""
    action: str  # "start", "stop", "gain", "ping"
    value: Optional[float] = None


@dataclass
class SerialStatus:
    """Status event sent to M5Stack."""
    streaming: bool
    error: Optional[str] = None
    duration: int = 0  # seconds
    uplink_ok: Optional[bool] = None


@dataclass
class SerialLevels:
    """Stereo level event sent to M5Stack."""
    left_rms: float = 0.0
    right_rms: float = 0.0
    left_peak: float = 0.0
    right_peak: float = 0.0
    clipping: bool = False
    limiting: bool = False


@dataclass
class SerialGain:
    """Gain event sent to M5Stack."""
    value: float = 0.0
