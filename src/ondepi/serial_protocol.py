from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SerialCommand:
    action: str
    value: Optional[float] = None


@dataclass
class SerialStatus:
    streaming: bool
    error: Optional[str]


@dataclass
class SerialLevels:
    rms: float
    peak: float


@dataclass
class SerialGain:
    value: float
