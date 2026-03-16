"""Bridge between the OndePi application and the M5Stack serial device.

Periodically sends levels (~10 Hz) and status (~1 Hz) to the M5Stack,
and dispatches incoming commands (start/stop/gain) to the appropriate
application components.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from .audio import AudioEngine
from .config import SerialConfig
from .serial_device import SerialDevice
from .state import StreamState
from .streamer import Streamer

logger = logging.getLogger(__name__)

# How often we push levels data to the M5Stack (seconds)
LEVELS_INTERVAL = 0.1  # ~10 Hz — smooth VU meters on M5Stack

# How often we push status data (seconds)
STATUS_INTERVAL = 1.0

# How often we send a heartbeat/pong if no other traffic (seconds)
HEARTBEAT_INTERVAL = 5.0


class SerialBridge:
    """Bridges OndePi state ↔ M5Stack serial device.

    Responsibilities:
    - Periodically pushes levels, status, and gain events to M5Stack.
    - Receives commands from M5Stack (start/stop/gain/ping) and dispatches.
    """

    def __init__(
        self,
        config: SerialConfig,
        state: StreamState,
        streamer: Streamer,
        audio_engine: Optional[AudioEngine] = None,
    ) -> None:
        self._state = state
        self._streamer = streamer
        self._audio_engine = audio_engine
        self._device = SerialDevice(config, self._on_message)
        self._sender_thread: Optional[threading.Thread] = None
        self._running = False
        self._last_gain_sent: Optional[float] = None

    @property
    def connected(self) -> bool:
        return self._device.connected

    @property
    def port(self) -> str:
        return self._device.port

    def start(self) -> None:
        """Start the serial device and the periodic sender thread."""
        self._device.start()
        if not self._device.port:
            return  # No port configured
        self._running = True
        self._sender_thread = threading.Thread(
            target=self._sender_loop, daemon=True, name="serial-sender"
        )
        self._sender_thread.start()

    def stop(self) -> None:
        """Stop sender thread and serial device."""
        self._running = False
        if self._sender_thread:
            self._sender_thread.join(timeout=3.0)
            self._sender_thread = None
        self._device.stop()

    # -------------------------------------------------------------------------
    # Incoming commands from M5Stack
    # -------------------------------------------------------------------------

    def _on_message(self, message: dict) -> None:
        """Handle a parsed JSON message from M5Stack."""
        action = message.get("action", "")

        if action == "start":
            logger.info("Serial: start command received")
            try:
                self._streamer.start()
            except Exception as exc:
                logger.error("Serial: start failed: %s", exc)
                self._state.last_error = str(exc)

        elif action == "stop":
            logger.info("Serial: stop command received")
            try:
                self._streamer.stop()
            except Exception as exc:
                logger.error("Serial: stop failed: %s", exc)
                self._state.last_error = str(exc)

        elif action == "gain":
            value = message.get("value")
            if isinstance(value, (int, float)):
                logger.debug("Serial: gain command: %.1f dB", value)
                self._state.gain_db = float(value)
                # Echo gain back to confirm
                self._send_gain()

        elif action == "ping":
            logger.debug("Serial: ping received")
            # Respond with current status immediately
            self._send_status()
            self._send_gain()

        else:
            logger.debug("Serial: unknown action '%s'", action)

    # -------------------------------------------------------------------------
    # Outgoing events to M5Stack
    # -------------------------------------------------------------------------

    def _send_levels(self) -> None:
        """Push current audio levels to M5Stack."""
        levels = self._state.levels
        limiter_active = False
        if self._audio_engine:
            max_peak = max(levels.peak_left, levels.peak_right)
            limiter_active = (
                self._audio_engine._clipper.enabled and max_peak > 0.7
            )

        self._device.send({
            "type": "levels",
            "left_rms": round(levels.rms_left, 4),
            "right_rms": round(levels.rms_right, 4),
            "left_peak": round(levels.peak_left, 4),
            "right_peak": round(levels.peak_right, 4),
            "clipping": self._state.input_clip,
            "limiting": limiter_active,
        })

    def _send_status(self) -> None:
        """Push current stream status to M5Stack."""
        duration = 0
        if self._state.streaming and self._state.started_at:
            duration = int((datetime.utcnow() - self._state.started_at).total_seconds())

        # Send errors while streaming, or when a start was requested but failed
        error = ""
        if self._state.last_error and (self._state.streaming or self._state.streaming_requested):
            error = self._state.last_error

        self._device.send({
            "type": "status",
            "streaming": self._state.streaming,
            "duration": duration,
            "error": error,
            "uplink_ok": self._state.uplink_ok,
        })

    def _send_gain(self) -> None:
        """Push current gain value to M5Stack."""
        self._device.send({
            "type": "gain",
            "value": round(self._state.gain_db, 1),
        })

    # -------------------------------------------------------------------------
    # Periodic sender loop
    # -------------------------------------------------------------------------

    def _sender_loop(self) -> None:
        """Periodically push levels and status to M5Stack."""
        last_levels = 0.0
        last_status = 0.0
        last_heartbeat = 0.0

        while self._running:
            now = time.monotonic()

            if not self._device.connected:
                time.sleep(0.5)
                last_levels = last_status = last_heartbeat = 0.0
                self._last_gain_sent = None  # Reset on disconnect
                continue

            # Send levels at ~10 Hz
            if now - last_levels >= LEVELS_INTERVAL:
                self._send_levels()
                last_levels = now

                # Check for gain changes at same rate as levels (responsive to web UI changes)
                current_gain = self._state.gain_db
                if self._last_gain_sent is None or abs(current_gain - self._last_gain_sent) > 0.01:
                    self._send_gain()
                    self._last_gain_sent = current_gain

            # Send status at ~1 Hz
            if now - last_status >= STATUS_INTERVAL:
                self._send_status()
                last_status = now

            # Heartbeat
            if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                last_heartbeat = now

            # Sleep to avoid busy-looping — aim for ~10 Hz tick rate
            time.sleep(0.05)
