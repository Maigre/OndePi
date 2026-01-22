from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from .config import InputConfig
from .state import LevelState, StreamState


@dataclass
class AudioMeter:
    """Compute RMS/peak from numpy audio buffers."""

    def compute_levels(self, data: np.ndarray) -> LevelState:
        if data.size == 0:
            return LevelState()
        # normalize assuming float32 -1..1 or int16
        if np.issubdtype(data.dtype, np.integer):
            max_val = np.iinfo(data.dtype).max
            normalized = data.astype(np.float32) / max_val
        else:
            normalized = data.astype(np.float32)
        rms = float(np.sqrt(np.mean(np.square(normalized))))
        peak = float(np.max(np.abs(normalized)))
        return LevelState(rms=rms, peak=peak)


@dataclass
class GainController:
    gain_db: float = 0.0

    def apply(self, data: np.ndarray) -> np.ndarray:
        if self.gain_db == 0.0:
            return data
        gain = 10 ** (self.gain_db / 20)
        result = data.astype(np.float32) * gain
        return result


@dataclass
class SoftClipper:
    enabled: bool = True
    drive: float = 1.5

    def apply(self, data: np.ndarray) -> np.ndarray:
        if not self.enabled:
            return data
        return np.tanh(self.drive * data).astype(np.float32)


@dataclass
class AudioStatus:
    last_levels: Optional[LevelState] = None


AudioConsumer = Callable[[np.ndarray], None]


class AudioEngine:
    def __init__(self, input_cfg: InputConfig, state: StreamState) -> None:
        self._input_cfg = input_cfg
        self._state = state
        self._meter = AudioMeter()
        self._gain = GainController()
        self._clipper = SoftClipper()
        self._stream: Optional[sd.InputStream] = None
        self._consumers: list[AudioConsumer] = []
        self._lock = Lock()
        self._running = Event()
        self._thread: Optional[Thread] = None
        self._device_status = "idle"
        self._last_device_error: Optional[str] = None

    def start(self) -> None:
        if self._running.is_set():
            return
        self._clipper.enabled = self._input_cfg.limiter_enabled
        self._clipper.drive = self._input_cfg.limiter_drive
        self._running.set()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def add_consumer(self, consumer: AudioConsumer) -> None:
        with self._lock:
            self._consumers.append(consumer)

    def remove_consumer(self, consumer: AudioConsumer) -> None:
        with self._lock:
            if consumer in self._consumers:
                self._consumers.remove(consumer)

    def update_input(self, input_cfg: InputConfig) -> None:
        self._input_cfg = input_cfg
        self._clipper.enabled = input_cfg.limiter_enabled
        self._clipper.drive = input_cfg.limiter_drive
        if self._stream:
            self.stop()
            self.start()

    def _callback(self, indata, frames, time, status) -> None:  # noqa: ANN001
        if status:
            self._state.last_error = str(status)
        self._gain.gain_db = self._state.gain_db
        gained = self._gain.apply(indata)
        clipped = self._clipper.apply(gained)
        levels = self._meter.compute_levels(clipped)
        self._state.levels = levels
        with self._lock:
            consumers = list(self._consumers)
        for consumer in consumers:
            try:
                consumer(clipped)
            except Exception:  # pragma: no cover - consumer errors are non-fatal
                continue

    def _run_loop(self) -> None:
        while self._running.is_set():
            try:
                self._stream = sd.InputStream(
                    samplerate=self._input_cfg.sample_rate,
                    channels=self._input_cfg.channels,
                    dtype="float32",
                    device=self._input_cfg.alsa_device or None,
                    callback=self._callback,
                    finished_callback=self._on_finished,
                )
                self._stream.start()
                self._state.last_error = None
                self._device_status = "connected"
                self._last_device_error = None
                while self._running.is_set() and self._stream and self._stream.active:
                    self._running.wait(0.5)
            except Exception as exc:  # pragma: no cover - runtime only
                self._state.last_error = f"audio device error: {exc}"
                self._device_status = "error"
                self._last_device_error = str(exc)
            finally:
                if self._stream:
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = None
            if self._running.is_set():
                self._device_status = "reconnecting"
                self._running.wait(2)

    def _on_finished(self) -> None:
        self._state.last_error = "audio stream stopped"
        self._device_status = "disconnected"

    def device_status(self) -> dict:
        return {
            "status": self._device_status,
            "last_error": self._last_device_error,
            "device": self._input_cfg.alsa_device,
            "sample_rate": self._input_cfg.sample_rate,
            "channels": self._input_cfg.channels,
            "limiter_enabled": self._clipper.enabled,
            "limiter_drive": self._clipper.drive,
        }
