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
class UplinkState:
    """Layered connectivity-doctor result (see net_probe.classify_uplink)."""

    ok: Optional[bool] = None
    internet_ok: Optional[bool] = None
    dns_ok: Optional[bool] = None
    server_tcp_ok: Optional[bool] = None
    resolved_ip: Optional[str] = None
    latency_ms: Optional[float] = None
    reason: Optional[str] = None  # ok|no_internet|dns_failed|server_unreachable|not_configured
    checked_at: Optional[datetime] = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "internet_ok": self.internet_ok,
            "dns_ok": self.dns_ok,
            "server_tcp_ok": self.server_tcp_ok,
            "resolved_ip": self.resolved_ip,
            "latency_ms": self.latency_ms,
            "reason": self.reason,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


# Streaming lifecycle phases — a single source of truth for the UI/serial so the
# indicator reflects reality rather than "ffmpeg process exists".
#   stopped    — not requested / idle
#   connecting — ffmpeg launched, not yet confirmed flowing (or retrying)
#   live       — connected and audio is flowing to the server
#   stalled    — connected but no data is reaching the server (uplink wedged)
#   error      — failed and not (currently) retrying
STREAM_PHASES = ("stopped", "connecting", "live", "stalled", "error")


@dataclass
class StreamState:
    streaming: bool = False
    streaming_requested: bool = False
    stream_phase: str = "stopped"
    last_error: Optional[str] = None
    started_at: Optional[datetime] = None
    levels: LevelState = field(default_factory=LevelState)
    gain_db: float = 0.0
    input_clip: bool = False
    retry_count: int = 0
    last_retry_at: Optional[datetime] = None
    last_exit_code: Optional[int] = None
    uplink_ok: Optional[bool] = None
    uplink: UplinkState = field(default_factory=UplinkState)

    def as_dict(self) -> dict:
        return {
            "streaming": self.streaming,
            "streaming_requested": self.streaming_requested,
            "stream_phase": self.stream_phase,
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
            "uplink_ok": self.uplink_ok,
            "uplink": self.uplink.as_dict(),
        }
