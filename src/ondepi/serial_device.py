from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Optional

import serial

from .config import SerialConfig

logger = logging.getLogger(__name__)


class SerialDevice:
    """JSON-line serial protocol handler with auto-reconnection.

    Sends newline-delimited JSON events to M5Stack and receives commands.
    Automatically reconnects if the serial port disappears or errors out.
    """

    def __init__(self, config: SerialConfig, on_message: Callable[[dict], None]) -> None:
        self._config = config
        self._on_message = on_message
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._serial: Optional[serial.Serial] = None
        self._lock = threading.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def port(self) -> str:
        return self._config.port

    def start(self) -> None:
        if not self._config.port:
            logger.info("Serial port not configured, skipping serial device")
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="serial-device")
        self._thread.start()
        logger.info("Serial device started on %s @ %d", self._config.port, self._config.baudrate)

    def stop(self) -> None:
        self._running = False
        self._close()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def send(self, payload: dict) -> None:
        """Send a JSON-line message to the serial device."""
        with self._lock:
            if not self._serial or not self._connected:
                return
            try:
                data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
                self._serial.write(data)
                self._serial.flush()
            except (serial.SerialException, OSError) as exc:
                logger.warning("Serial write error: %s", exc)
                self._connected = False
                # Close the port so the reader thread wakes up immediately
                ser = self._serial
                self._serial = None
                if ser:
                    try:
                        ser.close()
                    except Exception:
                        pass

    def _connect(self) -> bool:
        """Try to open the serial port. Returns True on success."""
        try:
            self._close()
            ser = serial.Serial()
            ser.port = self._config.port
            ser.baudrate = self._config.baudrate
            ser.timeout = 0.1  # Short timeout for responsive reading
            ser.dtr = False  # Don't reset ESP32 on connect
            ser.rts = False
            ser.open()
            # Flush any stale data in buffers
            ser.reset_input_buffer()
            with self._lock:
                self._serial = ser
                self._connected = True
            logger.info("Serial connected: %s", self._config.port)
            return True
        except (serial.SerialException, OSError) as exc:
            logger.debug("Serial connect failed: %s", exc)
            return False

    def _close(self) -> None:
        with self._lock:
            self._connected = False
            ser = self._serial
            self._serial = None
        if ser:
            try:
                ser.close()
            except Exception:
                pass

    def _run(self) -> None:
        """Main serial loop with auto-reconnection."""
        while self._running:
            if not self._connected:
                if not self._connect():
                    time.sleep(2.0)  # Retry connection every 2s
                    continue

            try:
                self._read_loop()
            except (serial.SerialException, OSError) as exc:
                logger.warning("Serial error: %s, will reconnect", exc)
                self._close()
                time.sleep(1.0)
            except Exception as exc:
                logger.error("Unexpected serial error: %s", exc, exc_info=True)
                self._close()
                time.sleep(2.0)

    def _read_loop(self) -> None:
        """Read lines from serial until disconnected or stopped."""
        while self._running and self._connected:
            with self._lock:
                ser = self._serial
            if not ser or not ser.is_open:
                break

            try:
                line = ser.readline().decode("utf-8", errors="replace").strip()
            except (serial.SerialException, OSError):
                raise
            except Exception:
                continue

            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Invalid JSON from serial: %s", line[:100])
                continue

            try:
                self._on_message(message)
            except Exception as exc:
                logger.warning("Serial message handler error: %s", exc)
