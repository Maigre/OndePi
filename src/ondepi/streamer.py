from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional
from urllib.parse import quote

from .audio import AudioEngine
from .config import AppConfig
from .state import StreamState

logger = logging.getLogger(__name__)


@dataclass
class StreamProcess:
    command: List[str]
    process: subprocess.Popen


class Streamer:
    def __init__(
        self,
        config: AppConfig,
        state: StreamState,
        audio_engine: Optional[AudioEngine] = None,
    ) -> None:
        self._config = config
        self._state = state
        self._audio_engine = audio_engine
        self._process: Optional[StreamProcess] = None
        self._audio_consumer = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_requested = False
        self._last_stderr = None

    def build_ffmpeg_command(self) -> List[str]:
        stream = self._config.stream
        input_cfg = self._config.input

        if not stream.server or not stream.mount:
            raise ValueError("Stream server and mount must be configured")

        username = quote(stream.username)
        password = quote(stream.password)
        mount = stream.mount.lstrip("/")
        output_url = f"icecast://{username}:{password}@{stream.server}:{stream.port}/{mount}"

        if self._audio_engine:
            audio_input = "pipe:0"
            input_args = [
                "-f",
                "f32le",
                "-ac",
                str(input_cfg.channels),
                "-ar",
                str(input_cfg.sample_rate),
                "-i",
                audio_input,
            ]
        else:
            audio_input = f"alsa:{input_cfg.alsa_device}"
            input_args = [
                "-f",
                "alsa",
                "-ac",
                str(input_cfg.channels),
                "-ar",
                str(input_cfg.sample_rate),
                "-i",
                audio_input,
            ]

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            *input_args,
            "-vn",
        ]
        cmd += [
            "-acodec",
            _codec_for_format(stream.format),
            "-b:a",
            f"{stream.bitrate_kbps}k",
            "-f",
            stream.format,
            "-content_type",
            _content_type_for_format(stream.format),
            output_url,
        ]
        return cmd

    def start(self) -> None:
        if self._process is not None:
            return
        self._stop_requested = False
        self._state.streaming_requested = True
        self._state.retry_count = 0
        self._state.last_retry_at = None
        self._state.last_exit_code = None
        self._last_stderr = None
        self._start_process(is_retry=False)

    def stop(self) -> None:
        # Clear these first to prevent auto-restart race conditions
        self._stop_requested = True
        self._state.streaming_requested = False

        # Capture reference — monitor thread may set self._process = None concurrently
        proc = self._process
        if not proc:
            return
        self._cleanup_audio()
        try:
            proc.process.terminate()
            proc.process.wait(timeout=5)
            self._state.last_exit_code = proc.process.returncode
        except Exception:
            pass
        self._process = None
        self._state.streaming = False
        self._state.started_at = None

    def status(self) -> dict:
        output_url = None
        if self._config.stream.server and self._config.stream.mount:
            output_url = _masked_output_url(self._config.stream)
        return {
            "running": self._process is not None,
            "command": self._process.command if self._process else None,
            "input": "audio-engine" if self._audio_engine else "alsa",
            "input_device": None if self._audio_engine else self._config.input.alsa_device,
            "output_url": output_url,
            "retry_count": self._state.retry_count,
            "last_exit_code": self._state.last_exit_code,
            "last_error": self._state.last_error,
            "last_stderr": self._last_stderr,
        }

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def _start_process(self, is_retry: bool) -> None:
        command = self.build_ffmpeg_command()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if self._audio_engine else None,
        )
        self._process = StreamProcess(command=command, process=process)
        self._state.started_at = datetime.utcnow()
        if not is_retry:
            self._state.last_error = None
        if self._audio_engine and process.stdin:
            self._audio_consumer = self._build_audio_consumer(process.stdin)
            self._audio_engine.add_consumer(self._audio_consumer)
        self._start_monitor()

    def _start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
        self._monitor_thread.start()

    def _monitor_process(self) -> None:
        if not self._process:
            return
        process = self._process.process

        # Collect stderr lines in real-time so we can detect connection
        # failures even when ffmpeg doesn't exit (piped stdin keeps it alive).
        stderr_lines: deque[str] = deque(maxlen=50)
        stderr_error = threading.Event()

        def _read_stderr() -> None:
            assert process.stderr is not None
            try:
                for raw in process.stderr:
                    line = raw.decode("utf-8", errors="ignore").rstrip()
                    if line:
                        stderr_lines.append(line)
                        logger.debug("ffmpeg: %s", line)
                        low = line.lower()
                        if any(kw in low for kw in (
                            "error", "401", "403", "refused",
                            "unauthorized", "fail", "denied",
                        )):
                            stderr_error.set()
            except Exception:
                pass

        reader = threading.Thread(target=_read_stderr, daemon=True)
        reader.start()

        # Grace period: wait for either process exit or stderr error signal.
        grace = 5.0
        deadline = time.monotonic() + grace
        connected = True
        while time.monotonic() < deadline:
            if process.poll() is not None:
                connected = False
                break
            if stderr_error.is_set():
                # ffmpeg reported an error — kill it since it won't exit on its own
                logger.warning("ffmpeg output error detected, terminating")
                connected = False
                try:
                    process.terminate()
                except Exception:
                    pass
                break
            time.sleep(0.25)

        if connected:
            self._state.streaming = True

        process.wait()
        reader.join(timeout=2.0)

        exit_code = process.returncode
        stderr = "\n".join(stderr_lines)
        self._last_stderr = stderr or None
        self._cleanup_audio()
        self._process = None
        self._state.streaming = False
        self._state.started_at = None
        self._state.last_exit_code = exit_code

        if self._stop_requested:
            return

        message = f"ffmpeg exited with code {exit_code}"
        if stderr:
            message = f"{message}: {stderr.splitlines()[-1]}"
        self._state.last_error = message

        if not self._config.general.reconnect:
            return

        if self._config.general.retry_max_attempts and (
            self._state.retry_count >= self._config.general.retry_max_attempts
        ):
            return

        self._state.retry_count += 1
        self._state.last_retry_at = datetime.utcnow()
        delay = _retry_delay(
            self._state.retry_count,
            self._config.general.retry_initial_delay_seconds,
            self._config.general.retry_max_delay_seconds,
        )
        time.sleep(delay)
        if self._stop_requested:
            return
        self._start_process(is_retry=True)

    def _build_audio_consumer(self, stdin) -> Callable:
        def _consumer(chunk):
            try:
                stdin.write(chunk.astype("float32").tobytes())
            except Exception:
                if self._state.last_error != "Audio pipeline broken":
                    logger.warning("Audio consumer write failed (ffmpeg stdin broken)")
                self._state.last_error = "Audio pipeline broken"

        return _consumer

    def _cleanup_audio(self) -> None:
        if self._audio_engine and self._audio_consumer:
            self._audio_engine.remove_consumer(self._audio_consumer)
            self._audio_consumer = None
        if self._process and self._process.process.stdin:
            try:
                self._process.process.stdin.close()
            except Exception:
                pass


def _codec_for_format(fmt: str) -> str:
    value = fmt.lower()
    if value == "mp3":
        return "libmp3lame"
    if value == "aac":
        return "aac"
    if value == "opus":
        return "libopus"
    return value


def _content_type_for_format(fmt: str) -> str:
    value = fmt.lower()
    if value == "mp3":
        return "audio/mpeg"
    if value == "aac":
        return "audio/aac"
    if value == "opus":
        return "audio/ogg"
    return value


def _masked_output_url(stream) -> str:
    username = quote(stream.username)
    mount = stream.mount.lstrip("/")
    return f"icecast://{username}:******@{stream.server}:{stream.port}/{mount}"


def _retry_delay(attempt: int, initial: int, maximum: int) -> int:
    delay = initial * (2 ** max(attempt - 1, 0))
    if maximum > 0:
        return min(delay, maximum)
    return delay
