from __future__ import annotations

import logging
import subprocess
import time
from threading import Event, Thread
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class WebradioPlayer:
    """Plays a web radio stream URL through the audio output when monitoring is off."""

    def __init__(
        self,
        url: str = "",
        sample_rate: int = 44100,
        channels: int = 2,
        device=None,
    ) -> None:
        self._url = url
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = device
        self._process: Optional[subprocess.Popen] = None
        self._output_stream: Optional[sd.OutputStream] = None
        self._thread: Optional[Thread] = None
        self._running = Event()
        self._retry_count = 0
        self._last_error: Optional[str] = None

    @property
    def playing(self) -> bool:
        return self._running.is_set() and self._output_stream is not None

    @property
    def url(self) -> str:
        return self._url

    def update_url(self, url: str) -> None:
        was_running = self._running.is_set()
        if was_running:
            self.stop()
        self._url = url
        if was_running and url:
            self.start()

    def update_device(self, device, sample_rate: int, channels: int) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._channels = channels

    def start(self) -> None:
        if self._running.is_set() or not self._url:
            return
        self._running.set()
        self._retry_count = 0
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running.is_set():
            return
        self._running.clear()
        proc = self._process
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._process = None
        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    def _run_loop(self) -> None:
        while self._running.is_set():
            try:
                self._play_stream()
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("Webradio playback error: %s", exc)
            finally:
                self._cleanup()
            if self._running.is_set():
                self._retry_count += 1
                delay = min(1 * (2 ** min(self._retry_count - 1, 4)), 30)
                logger.info("Webradio retry #%d in %ds", self._retry_count, delay)
                end = time.monotonic() + delay
                while self._running.is_set() and time.monotonic() < end:
                    time.sleep(0.5)

    def _play_stream(self) -> None:
        if not self._url:
            return
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "10",
            "-i", self._url,
            "-f", "f32le",
            "-ac", str(self._channels),
            "-ar", str(self._sample_rate),
            "pipe:1",
        ]
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        self._process = process
        output_stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=self._channels,
            dtype="float32",
            device=self._device,
        )
        output_stream.start()
        self._output_stream = output_stream
        self._retry_count = 0
        self._last_error = None
        logger.info("Webradio playing: %s", self._url)

        bytes_per_frame = self._channels * 4  # float32 = 4 bytes
        chunk_frames = self._sample_rate // 25  # ~40ms chunks
        chunk_bytes = chunk_frames * bytes_per_frame
        stdout = process.stdout
        if not stdout:
            return

        consecutive_errors = 0
        max_consecutive_errors = 5

        while self._running.is_set():
            data = stdout.read(chunk_bytes)
            if not data:
                break
            samples = np.frombuffer(data, dtype=np.float32)
            if len(samples) >= self._channels:
                usable = len(samples) - len(samples) % self._channels
                frames = samples[:usable].reshape(-1, self._channels)
                try:
                    output_stream.write(frames)
                    consecutive_errors = 0
                except Exception as exc:
                    consecutive_errors += 1
                    if consecutive_errors == 1:
                        logger.warning("Audio write error (transient): %s", exc)
                    if consecutive_errors >= max_consecutive_errors:
                        # Try to recreate the output stream once before giving up
                        logger.warning("Sustained audio errors (%d), recreating output stream", consecutive_errors)
                        try:
                            output_stream.stop()
                            output_stream.close()
                        except Exception:
                            pass
                        try:
                            output_stream = sd.OutputStream(
                                samplerate=self._sample_rate,
                                channels=self._channels,
                                dtype="float32",
                                device=self._device,
                            )
                            output_stream.start()
                            self._output_stream = output_stream
                            consecutive_errors = 0
                            logger.info("Output stream recreated successfully")
                        except Exception:
                            logger.warning("Failed to recreate output stream, restarting playback")
                            break

    def _cleanup(self) -> None:
        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

    def status(self) -> dict:
        return {
            "playing": self.playing,
            "url": self._url,
            "retry_count": self._retry_count,
            "last_error": self._last_error,
        }
