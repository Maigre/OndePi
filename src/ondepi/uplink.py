"""Connectivity doctor — periodically probes reachability of the source server.

Replaces the old single raw-TCP probe (which couldn't tell "server down" apart
from "DNS broken" or "no internet") with a layered check that publishes a
structured :class:`UplinkState` so the UI/serial can show *why* the uplink is
red, not just that it is.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Optional

from .config import StreamConfig
from .net_probe import (
    check_internet,
    classify_uplink,
    resolve_host,
    tcp_connect,
)
from .state import StreamState, UplinkState

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 10.0  # seconds between checks
CONNECT_TIMEOUT = 5.0  # TCP connect timeout
RESOLVE_TIMEOUT = 5.0  # DNS resolution timeout (bounded; dead resolvers hang)


class UplinkChecker:
    """Background thread that diagnoses connectivity to the source server."""

    def __init__(self, config: StreamConfig, state: StreamState) -> None:
        self._config = config
        self._state = state
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()
        self._last_reason: Optional[str] = None

    def update_config(self, config: StreamConfig) -> None:
        self._config = config

    def start(self) -> None:
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="uplink-checker"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def check(self) -> UplinkState:
        """Run one layered probe and return the structured result.

        Fast path: try the server first; only spend time probing public anchors
        when the server is unreachable (i.e. when we actually need to classify
        the failure).
        """
        server = self._config.server
        port = self._config.port
        report = UplinkState(checked_at=datetime.utcnow())

        if not server:
            report.reason = "not_configured"
            return report

        ip = resolve_host(server, RESOLVE_TIMEOUT)
        report.dns_ok = ip is not None
        report.resolved_ip = ip

        if ip is not None:
            ok, latency = tcp_connect(ip, port, CONNECT_TIMEOUT)
            report.server_tcp_ok = ok
            report.latency_ms = round(latency, 1) if latency is not None else None

        if report.server_tcp_ok:
            report.ok = True
            report.internet_ok = True
            report.reason = "ok"
        else:
            report.internet_ok = check_internet(CONNECT_TIMEOUT)
            report.ok = False
            report.reason = classify_uplink(
                dns_ok=bool(report.dns_ok),
                server_tcp_ok=False,
                internet_ok=report.internet_ok,
            )
        return report

    def _publish(self, report: UplinkState) -> None:
        self._state.uplink = report
        self._state.uplink_ok = report.ok
        if report.reason != self._last_reason:
            logger.info(
                "Uplink %s (reason=%s, ip=%s, latency=%sms)",
                "OK" if report.ok else "DOWN",
                report.reason,
                report.resolved_ip,
                report.latency_ms,
            )
            self._last_reason = report.reason

    def _loop(self) -> None:
        while self._running:
            try:
                self._publish(self.check())
            except Exception as exc:  # never let the doctor thread die
                logger.warning("Uplink check error: %s", exc)
            if self._stop_event.wait(timeout=CHECK_INTERVAL):
                break
