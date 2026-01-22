from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import serial


@dataclass
class SerialConfig:
    port: str
    baudrate: int = 115200


class SerialDevice:
    """Simple JSON-line serial protocol handler.

    Incoming messages: {"action": "start"|"stop"|"gain", "value": float}
    Outgoing messages: {"status": "...", "levels": {"rms":..,"peak":..}}
    """

    def __init__(self, config: SerialConfig, on_message: Callable[[dict], None]) -> None:
        self._config = config
        self._on_message = on_message
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._serial: Optional[serial.Serial] = None

    def start(self) -> None:
        if not self._config.port:
            return
        self._serial = serial.Serial(self._config.port, self._config.baudrate, timeout=1)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._serial:
            self._serial.close()

    def send(self, payload: dict) -> None:
        if not self._serial:
            return
        data = (json.dumps(payload) + "\n").encode("utf-8")
        self._serial.write(data)

    def _run(self) -> None:
        if not self._serial:
            return
        while self._running:
            line = self._serial.readline().decode("utf-8").strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._on_message(message)
