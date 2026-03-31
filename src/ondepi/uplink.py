"""Uplink checker — periodically probes the Icecast server to verify connectivity."""

from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

from .config import StreamConfig
from .state import StreamState

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 10.0  # seconds between checks
CONNECT_TIMEOUT = 5.0  # TCP connect timeout


class UplinkChecker:
    """Background thread that tests TCP connectivity to the Icecast server."""

    def __init__(self, config: StreamConfig, state: StreamState) -> None:
        self._config = config
        self._state = state
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = threading.Event()

    def update_config(self, config: StreamConfig) -> None:
        self._config = config

    def start(self) -> None:
        if not self._config.server:
            return
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

    def _check(self) -> bool:
        """Attempt a TCP connection to the Icecast server.

        Only tests raw TCP reachability — FFmpeg's icecast:// output uses
        plain HTTP, so a TLS handshake here would give false negatives.
        """
        server = self._config.server
        port = self._config.port

        if not server:
            return False

        try:
            sock = socket.create_connection((server, port), timeout=CONNECT_TIMEOUT)
            sock.close()
            return True
        except OSError as exc:
            logger.debug("Uplink check failed: %s", exc)
            return False

    def _loop(self) -> None:
        while self._running:
            ok = self._check()
            self._state.uplink_ok = ok
            if self._stop_event.wait(timeout=CHECK_INTERVAL):
                break
