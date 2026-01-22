from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional
from urllib.parse import quote

from .audio import AudioEngine
from .azuracast import AzuraCastClient
from .config import AppConfig
from .state import StreamState


@dataclass
class StreamProcess:
    command: List[str]
    process: subprocess.Popen


class Streamer:
    def __init__(
        self,
        config: AppConfig,
        state: StreamState,
        azuracast: Optional[AzuraCastClient] = None,
        audio_engine: Optional[AudioEngine] = None,
    ) -> None:
        self._config = config
        self._state = state
        self._azuracast = azuracast
        self._audio_engine = audio_engine
        self._process: Optional[StreamProcess] = None
        self._audio_consumer = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_requested = False
        self._metadata_thread: Optional[threading.Thread] = None
        self._metadata_stop = threading.Event()

    def build_ffmpeg_command(self) -> List[str]:
        stream = self._config.stream
        metadata = self._config.metadata
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
            "-metadata",
            f"title={metadata.track}",
            "-metadata",
            f"artist={metadata.artist}",
            output_url,
        ]
        return cmd

    def start(self) -> None:
        if self._process is not None:
            return
        self._stop_requested = False
        self._state.retry_count = 0
        self._state.last_retry_at = None
        self._state.last_exit_code = None
        self._metadata_stop.clear()
        self._start_process(is_retry=False)

    def stop(self) -> None:
        if not self._process:
            return
        self._stop_requested = True
        self._metadata_stop.set()
        self._cleanup_audio()
        self._process.process.terminate()
        self._process.process.wait(timeout=5)
        self._process = None
        self._state.streaming = False
        if self._azuracast:
            self._azuracast.update_streamer_metadata(self._config.metadata)

    def status(self) -> dict:
        return {
            "running": self._process is not None,
            "command": self._process.command if self._process else None,
            "input": "audio-engine" if self._audio_engine else "alsa",
            "retry_count": self._state.retry_count,
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
        self._state.streaming = True
        self._state.started_at = datetime.utcnow()
        if not is_retry:
            self._state.last_error = None
        if self._audio_engine and process.stdin:
            self._audio_consumer = self._build_audio_consumer(process.stdin)
            self._audio_engine.add_consumer(self._audio_consumer)
        if self._azuracast:
            self._azuracast.update_streamer_metadata(self._config.metadata)
            self._start_metadata_loop()
        self._start_monitor()

    def _start_monitor(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
        self._monitor_thread.start()

    def _start_metadata_loop(self) -> None:
        if not self._azuracast:
            return
        if self._metadata_thread and self._metadata_thread.is_alive():
            return
        self._metadata_thread = threading.Thread(target=self._metadata_loop, daemon=True)
        self._metadata_thread.start()

    def _metadata_loop(self) -> None:
        while not self._metadata_stop.is_set():
            metadata_cfg = self._config.metadata
            if metadata_cfg.push_enabled and self._azuracast:
                error = self._azuracast.update_streamer_metadata_safe(metadata_cfg)
                if error:
                    self._state.last_error = f"metadata update failed: {error}"
                attempts = max(metadata_cfg.retry_attempts, 0)
                delay = max(metadata_cfg.retry_delay_seconds, 0)
                retry_index = 0
                while error and retry_index < attempts and not self._metadata_stop.is_set():
                    if self._metadata_stop.wait(delay):
                        break
                    error = self._azuracast.update_streamer_metadata_safe(metadata_cfg)
                    if error:
                        self._state.last_error = f"metadata update failed: {error}"
                    retry_index += 1
            self._metadata_stop.wait(metadata_cfg.push_interval_seconds)

    def _monitor_process(self) -> None:
        if not self._process:
            return
        process = self._process.process
        process.wait()
        exit_code = process.returncode
        stderr = ""
        if process.stderr:
            try:
                stderr = process.stderr.read().decode("utf-8", errors="ignore").strip()
            except Exception:
                stderr = ""
        self._cleanup_audio()
        self._metadata_stop.set()
        self._process = None
        self._state.streaming = False
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
    return "application/octet-stream"


def _retry_delay(attempt: int, initial: int, maximum: int) -> int:
    delay = initial * (2 ** max(attempt - 1, 0))
    if maximum > 0:
        return min(delay, maximum)
    return delay
