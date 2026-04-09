from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

from .config import InputConfig
from .state import LevelState, StreamState


@dataclass
class AudioMeter:
    """Compute RMS/peak from numpy audio buffers per channel."""

    def compute_levels(self, data: np.ndarray) -> LevelState:
        if data.size == 0:
            return LevelState()
        # normalize assuming float32 -1..1 or int16
        if np.issubdtype(data.dtype, np.integer):
            max_val = np.iinfo(data.dtype).max
            normalized = data.astype(np.float32) / max_val
        else:
            normalized = data.astype(np.float32)
        
        # Handle stereo (2D array with shape [frames, channels]) or mono
        if normalized.ndim == 2 and normalized.shape[1] >= 2:
            left = normalized[:, 0]
            right = normalized[:, 1]
        else:
            # Mono - use same values for both channels
            flat = normalized.flatten()
            left = flat
            right = flat
        
        rms_left = float(np.sqrt(np.mean(np.square(left))))
        rms_right = float(np.sqrt(np.mean(np.square(right))))
        peak_left = float(np.max(np.abs(left)))
        peak_right = float(np.max(np.abs(right)))
        
        return LevelState(
            rms_left=rms_left,
            rms_right=rms_right,
            peak_left=peak_left,
            peak_right=peak_right,
        )


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
        self._output_stream: Optional[sd.OutputStream] = None
        self._monitor_enabled = False
        self._consumers: list[AudioConsumer] = []
        self._lock = Lock()
        self._stream_lock = Lock()
        self._running = Event()
        self._thread: Optional[Thread] = None
        self._device_status = "idle"
        self._last_device_error: Optional[str] = None
        self._overflow_count = 0
        self._last_stream_status = None
        self._stream_channels = self._input_cfg.channels

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
        # Stop monitor output
        self.set_monitor(False)
        # Signal the stream to stop - _run_loop will handle cleanup
        with self._stream_lock:
            if self._stream:
                try:
                    self._stream.stop()
                except Exception:
                    pass
        # Wait for the thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None

    def add_consumer(self, consumer: AudioConsumer) -> None:
        with self._lock:
            self._consumers.append(consumer)

    def remove_consumer(self, consumer: AudioConsumer) -> None:
        with self._lock:
            if consumer in self._consumers:
                self._consumers.remove(consumer)

    def update_input(self, input_cfg: InputConfig) -> None:
        # Check if we need to restart (device or sample rate changed)
        needs_restart = (
            input_cfg.alsa_device != self._input_cfg.alsa_device
            or input_cfg.sample_rate != self._input_cfg.sample_rate
            or input_cfg.channels != self._input_cfg.channels
        )
        was_monitoring = self._monitor_enabled
        was_running = self._running.is_set()
        if needs_restart and was_running:
            self.stop()
        if was_monitoring and not was_running:
            self.set_monitor(False)
        self._input_cfg = input_cfg
        self._clipper.enabled = input_cfg.limiter_enabled
        self._clipper.drive = input_cfg.limiter_drive
        
        if needs_restart and was_running:
            self.start()
        if was_monitoring:
            self.set_monitor(True)

    def set_monitor(self, enabled: bool) -> bool:
        """Enable/disable audio monitoring (send processed audio to same device output)."""
        if enabled and not self._monitor_enabled:
            try:
                self._output_stream = sd.OutputStream(
                    samplerate=self._input_cfg.sample_rate,
                    channels=self._input_cfg.channels,
                    dtype="float32",
                    device=self._input_cfg.alsa_device or None,
                )
                self._output_stream.start()
                self._monitor_enabled = True
            except Exception as exc:
                self._state.last_error = f"Monitor error: {exc}"
                self._monitor_enabled = False
        elif not enabled and self._monitor_enabled:
            self._monitor_enabled = False
            if self._output_stream:
                try:
                    self._output_stream.stop()
                    self._output_stream.close()
                except Exception:
                    pass
                self._output_stream = None
        return self._monitor_enabled

    def _callback(self, indata, frames, time, status) -> None:  # noqa: ANN001
        if status:
            self._last_stream_status = str(status)
            if getattr(status, "input_overflow", False):
                self._overflow_count += 1
                logger.debug("Audio: %s", status)
            else:
                logger.warning("Audio: %s", status)
        if indata.size > 0:
            input_peak = float(np.max(np.abs(indata)))
            self._state.input_clip = input_peak >= 0.99
        else:
            self._state.input_clip = False
        working = indata
        if (
            working.ndim == 2
            and working.shape[1] == 1
            and self._input_cfg.channels == 2
        ):
            working = np.repeat(working, 2, axis=1)
        self._gain.gain_db = self._state.gain_db
        gained = self._gain.apply(working)
        clipped = self._clipper.apply(gained)
        levels = self._meter.compute_levels(clipped)
        self._state.levels = levels
        
        # Send to monitor output if enabled
        if self._monitor_enabled and self._output_stream:
            try:
                self._output_stream.write(clipped)
            except Exception:
                pass  # Ignore output errors
        
        with self._lock:
            consumers = list(self._consumers)
        for consumer in consumers:
            try:
                consumer(clipped)
            except Exception:  # pragma: no cover - consumer errors are non-fatal
                continue

    def _run_loop(self) -> None:
        while self._running.is_set():
            stream = None
            try:
                channels = self._input_cfg.channels
                if self._input_cfg.alsa_device is not None:
                    try:
                        dev = sd.query_devices(self._input_cfg.alsa_device)
                        max_ch = int(dev.get("max_input_channels") or 0)
                        if max_ch <= 0:
                            raise ValueError("Device has no input channels")
                        if channels > max_ch:
                            channels = max_ch
                            self._last_device_error = "Input is mono, using 1 channel"
                    except Exception as exc:
                        self._device_status = "reconnecting"
                        self._last_device_error = str(exc)
                        self._state.levels = LevelState()
                        self._state.input_clip = False
                        time.sleep(2)
                        continue
                self._stream_channels = channels
                stream = sd.InputStream(
                    samplerate=self._input_cfg.sample_rate,
                    channels=channels,
                    dtype="float32",
                    device=self._input_cfg.alsa_device or None,
                    blocksize=1024,
                    latency="high",
                    callback=self._callback,
                    finished_callback=self._on_finished,
                )
                with self._stream_lock:
                    self._stream = stream
                stream.start()
                self._state.last_error = None
                self._device_status = "connected"
                self._last_device_error = None
                logger.info("Audio device '%s' connected (%d ch, %d Hz)", self._input_cfg.alsa_device, channels, self._input_cfg.sample_rate)
                while self._running.is_set() and stream.active:
                    time.sleep(0.5)
            except Exception as exc:  # pragma: no cover - runtime only
                self._state.last_error = f"audio device error: {exc}"
                self._device_status = "error"
                self._last_device_error = str(exc)
                logger.warning("Audio device error: %s", exc)
                self._state.levels = LevelState()
                self._state.input_clip = False
            finally:
                with self._stream_lock:
                    self._stream = None
                if stream:
                    try:
                        stream.stop()
                        stream.close()
                    except Exception:
                        pass
            if self._running.is_set():
                self._device_status = "reconnecting"
                logger.info("Audio device disconnected, reconnecting...")
                time.sleep(2)

    def _on_finished(self) -> None:
        self._state.last_error = "audio stream stopped"
        self._device_status = "disconnected"

    def device_status(self) -> dict:
        device_default_rate = None
        sample_rate_mismatch = False
        try:
            if self._input_cfg.alsa_device is not None:
                dev = sd.query_devices(self._input_cfg.alsa_device)
                device_default_rate = dev.get("default_samplerate")
                if device_default_rate:
                    sample_rate_mismatch = int(device_default_rate) != int(self._input_cfg.sample_rate)
        except Exception:
            device_default_rate = None
            sample_rate_mismatch = False
        return {
            "status": self._device_status,
            "last_error": self._last_device_error,
            "last_stream_status": self._last_stream_status,
            "overflow_count": self._overflow_count,
            "device_default_rate": device_default_rate,
            "sample_rate_mismatch": sample_rate_mismatch,
            "device": self._input_cfg.alsa_device,
            "sample_rate": self._input_cfg.sample_rate,
            "channels": self._input_cfg.channels,
            "stream_channels": self._stream_channels,
            "limiter_enabled": self._clipper.enabled,
            "limiter_drive": self._clipper.drive,
            "monitor_enabled": self._monitor_enabled,
        }
