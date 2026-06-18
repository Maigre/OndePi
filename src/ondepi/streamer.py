from __future__ import annotations

import logging
import os
import random
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, List, Optional
from urllib.parse import quote

import numpy as np

from .audio import AudioEngine
from .config import AppConfig
from .state import StreamState

logger = logging.getLogger(__name__)

# ffmpeg AVIO read/write timeout for the Icecast output (microseconds). Without
# it, a black-holed / half-open uplink keeps ffmpeg "alive" (and the indicator
# falsely "streaming") until the kernel TCP timeout — tens of seconds. With it,
# ffmpeg errors out promptly and the retry loop reconnects.
OUTPUT_RW_TIMEOUT_US = 15_000_000

# Stall detection: if audio is backing up (buffer >= this fraction of capacity)
# and the writer hasn't drained anything into ffmpeg for STALL_TIMEOUT seconds,
# the uplink is wedged even though ffmpeg hasn't exited — force a reconnect.
STALL_BUFFER_FRACTION = 0.5
STALL_TIMEOUT = 8.0

# When the connectivity doctor reports the uplink down, wait up to this long for
# it to recover before reconnecting anyway (so a stuck doctor never blocks
# reconnect forever).
RECONNECT_UPLINK_MAX_WAIT = 60.0

# Backoff jitter spread (±) to avoid lock-step reconnect storms.
RETRY_JITTER = 0.2


@dataclass
class StreamProcess:
    command: List[str]
    process: subprocess.Popen


class _AudioChunkBuffer:
    def __init__(self, max_frames: int) -> None:
        self._max_frames = max(1, max_frames)
        self._frames = 0
        self._chunks: deque[np.ndarray] = deque()
        self._closed = False
        self._condition = threading.Condition()

    @property
    def frame_count(self) -> int:
        with self._condition:
            return self._frames

    @property
    def max_frames(self) -> int:
        return self._max_frames

    @property
    def is_closed(self) -> bool:
        with self._condition:
            return self._closed

    def put_nowait(self, chunk: np.ndarray) -> bool:
        frames = int(chunk.shape[0]) if chunk.ndim else int(chunk.size)
        with self._condition:
            if self._closed:
                return False
            if frames > self._max_frames or self._frames + frames > self._max_frames:
                return False
            self._chunks.append(chunk)
            self._frames += frames
            self._condition.notify()
            return True

    def get(self, timeout: float) -> Optional[np.ndarray]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._chunks:
                if self._closed:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)
            chunk = self._chunks.popleft()
            self._frames -= int(chunk.shape[0]) if chunk.ndim else int(chunk.size)
            return chunk

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()


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
        self._writer_thread: Optional[threading.Thread] = None
        self._audio_queue: Optional[_AudioChunkBuffer] = None
        self._stop_event = threading.Event()
        self._retrying = False
        self._last_stderr = None
        self._dropped_audio_chunks = 0
        self._dropped_audio_frames = 0
        self._last_drop_log_at = 0.0
        self._last_write_at = 0.0

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
            "-rw_timeout",
            str(OUTPUT_RW_TIMEOUT_US),
            output_url,
        ]
        return cmd

    def start(self) -> None:
        # Stop any existing retry loop / running process first
        logger.info("Stream start requested")
        self._abort_monitor()
        self._stop_event.clear()
        self._retrying = False
        self._dropped_audio_chunks = 0
        self._dropped_audio_frames = 0
        self._last_drop_log_at = 0.0
        self._last_write_at = time.monotonic()
        self._state.streaming_requested = True
        self._state.stream_phase = "connecting"
        self._state.retry_count = 0
        self._state.last_retry_at = None
        self._state.last_exit_code = None
        self._state.last_error = None
        self._last_stderr = None
        self._start_process(is_retry=False)

    def stop(self) -> None:
        logger.info("Stream stop requested")
        self._state.streaming_requested = False
        self._abort_monitor()

    def _abort_monitor(self) -> None:
        """Signal monitor/retry loop to stop and wait for it."""
        logger.debug("Aborting monitor/retry loop")
        self._stop_event.set()
        self._retrying = False
        proc = self._process
        if proc:
            self._cleanup_audio()
            try:
                proc.process.terminate()
                proc.process.wait(timeout=5)
                self._state.last_exit_code = proc.process.returncode
            except Exception:
                pass
            self._process = None
        # Wait for monitor thread to exit (it checks _stop_event)
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)
        self._monitor_thread = None
        self._state.streaming = False
        self._state.stream_phase = "stopped"
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
            "audio_buffer_frames": self._audio_queue.frame_count if self._audio_queue else 0,
            "audio_buffer_capacity_frames": self._audio_queue.max_frames if self._audio_queue else 0,
            "audio_dropped_chunks": self._dropped_audio_chunks,
            "audio_dropped_frames": self._dropped_audio_frames,
            "last_exit_code": self._state.last_exit_code,
            "last_error": self._state.last_error,
            "last_stderr": self._last_stderr,
        }

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def _start_process(self, is_retry: bool) -> None:
        logger.info("Starting ffmpeg process (retry=%s, attempt=%d)",
                    is_retry, self._state.retry_count)
        self._state.stream_phase = "connecting"
        self._last_write_at = time.monotonic()
        command = self.build_ffmpeg_command()
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if self._audio_engine else None,
            bufsize=0 if self._audio_engine else -1,
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
            if self._stop_event.is_set() or process.poll() is not None:
                connected = False
                break
            if stderr_error.is_set():
                # ffmpeg reported an error — kill it since it won't exit on its own
                logger.warning("ffmpeg output error detected during grace period, terminating")
                connected = False
                try:
                    process.terminate()
                except Exception:
                    pass
                break
            time.sleep(0.25)

        stalled = False
        if connected:
            logger.info("ffmpeg connected to Icecast successfully")
            self._state.streaming = True
            self._state.stream_phase = "live"
            # Stay honest after the grace period: keep watching for errors and
            # for an uplink stall (ffmpeg alive but no data reaching the server).
            stalled = self._watch_live(process, stderr_error)
        else:
            logger.warning("ffmpeg did not connect within grace period (stop_event=%s, poll=%s)",
                           self._stop_event.is_set(), process.poll())

        process.wait()
        reader.join(timeout=2.0)

        exit_code = process.returncode
        stderr = "\n".join(stderr_lines)
        self._last_stderr = stderr or None
        self._cleanup_audio()
        self._process = None
        was_streaming = self._state.streaming
        self._state.streaming = False
        self._state.started_at = None
        self._state.last_exit_code = exit_code

        if self._stop_event.is_set():
            logger.info("ffmpeg stopped by user request (exit_code=%s)", exit_code)
            return

        if stalled:
            message = "Uplink stalled — no data reaching the server, reconnecting"
        else:
            message = _parse_ffmpeg_error(exit_code, stderr)
        logger.error("Stream failed (exit_code=%s, was_streaming=%s): %s",
                     exit_code, was_streaming, message)
        if stderr:
            for line in stderr.splitlines():
                logger.warning("  ffmpeg: %s", line)
        self._state.last_error = message

        if not self._config.general.reconnect:
            logger.info("Reconnect disabled, not retrying")
            self._state.stream_phase = "error"
            return

        if self._config.general.retry_max_attempts and (
            self._state.retry_count >= self._config.general.retry_max_attempts
        ):
            logger.warning("Max retry attempts (%d) reached, giving up",
                           self._config.general.retry_max_attempts)
            self._state.stream_phase = "error"
            return

        self._state.retry_count += 1
        self._state.last_retry_at = datetime.utcnow()
        self._state.stream_phase = "connecting"
        self._retrying = True
        delay = _retry_delay(
            self._state.retry_count,
            self._config.general.retry_initial_delay_seconds,
            self._config.general.retry_max_delay_seconds,
        )
        delay *= 1.0 + random.uniform(-RETRY_JITTER, RETRY_JITTER)  # jitter
        logger.info("Retrying in %.1fs (attempt %d)", delay, self._state.retry_count)
        # Interruptible sleep — wakes immediately if stop/restart is requested
        if self._stop_event.wait(timeout=delay):
            logger.info("Retry sleep interrupted by stop event")
            self._retrying = False
            return
        # Weak-uplink coupling: if the connectivity doctor says the uplink is
        # down, don't burn a reconnect into a dead network (which just eats a
        # connect timeout). Wait until it recovers, then reconnect immediately.
        if not self._wait_for_uplink(RECONNECT_UPLINK_MAX_WAIT):
            self._retrying = False
            return
        self._retrying = False
        self._start_process(is_retry=True)

    def _wait_for_uplink(self, max_wait: float) -> bool:
        """Block while the connectivity doctor reports the uplink down.

        Returns False if a stop was requested (caller should bail). ``uplink_ok``
        of None (unknown / no checker) does not block. Capped by ``max_wait`` so
        a stuck/None doctor can never prevent a reconnect attempt.
        """
        if self._state.uplink_ok is not False:
            return True
        logger.info("Uplink down — holding reconnect until it recovers (max %.0fs)", max_wait)
        deadline = time.monotonic() + max_wait
        while self._state.uplink_ok is False:
            if self._stop_event.wait(timeout=1.0):
                return False
            if time.monotonic() >= deadline:
                logger.warning("Uplink still down after %.0fs — reconnecting anyway", max_wait)
                return True
        logger.info("Uplink recovered — reconnecting now")
        return True

    def _watch_live(self, process, stderr_error: threading.Event) -> bool:
        """Watch a connected ffmpeg until it exits, errors, stalls, or we stop.

        Returns True if we terminated ffmpeg because the uplink stalled (so the
        caller can report a stall rather than a generic ffmpeg failure).
        """
        while True:
            if self._stop_event.is_set():
                return False
            if process.poll() is not None:
                return False
            if stderr_error.is_set():
                logger.warning("ffmpeg reported an error after connect — terminating to reconnect")
                self._terminate_process(process)
                return False
            if self._is_stalled():
                q = self._audio_queue
                logger.warning(
                    "Uplink stalled (buffer=%d/%d frames, no drain for >%.0fs) — reconnecting",
                    q.frame_count if q else 0,
                    q.max_frames if q else 0,
                    STALL_TIMEOUT,
                )
                self._state.stream_phase = "stalled"
                self._terminate_process(process)
                return True
            time.sleep(0.5)

    def _is_stalled(self) -> bool:
        """True when audio is backing up but the writer isn't draining ffmpeg."""
        q = self._audio_queue
        if not q:
            return False
        if q.frame_count < STALL_BUFFER_FRACTION * q.max_frames:
            return False
        return (time.monotonic() - self._last_write_at) > STALL_TIMEOUT

    @staticmethod
    def _terminate_process(process) -> None:
        try:
            process.terminate()
        except Exception:
            pass

    def _build_audio_consumer(self, stdin) -> Callable:
        # Use a queue to decouple the real-time audio callback from blocking
        # pipe I/O.  Writing directly to stdin inside the callback stalls the
        # audio thread whenever the pipe buffer is momentarily full, producing
        # audible clicks.
        max_frames = max(
            int(self._config.general.buffer_seconds * self._config.input.sample_rate),
            self._config.input.sample_rate,
        )
        q = _AudioChunkBuffer(max_frames=max_frames)
        self._audio_queue = q
        fd = stdin.fileno()

        def _consumer(chunk):
            if q.put_nowait(chunk):
                return
            self._dropped_audio_chunks += 1
            self._dropped_audio_frames += int(chunk.shape[0]) if chunk.ndim else int(chunk.size)
            now = time.monotonic()
            if now - self._last_drop_log_at >= 5.0:
                logger.warning(
                    "Audio buffer overflow: dropped %d chunks / %d frames (depth=%d/%d frames)",
                    self._dropped_audio_chunks,
                    self._dropped_audio_frames,
                    q.frame_count,
                    q.max_frames,
                )
                self._last_drop_log_at = now

        def _writer():
            written = 0
            self._last_write_at = time.monotonic()
            try:
                while not self._stop_event.is_set():
                    data = q.get(timeout=0.5)
                    if data is None:
                        if q.is_closed:
                            break
                        continue
                    try:
                        # Write directly to the OS file descriptor —
                        # bypasses Python buffering and avoids an extra
                        # copy when used with memoryview on a contiguous
                        # numpy array.
                        if not data.flags.c_contiguous:
                            data = np.ascontiguousarray(data)
                        view = memoryview(data).cast("B")
                        while view:
                            n = os.write(fd, view)
                            if n <= 0:
                                raise BrokenPipeError("ffmpeg stdin closed")
                            view = view[n:]
                        written += 1
                        # Mark drain progress so the stall detector can tell a
                        # wedged uplink (writer blocked in os.write) from a
                        # healthy one.
                        self._last_write_at = time.monotonic()
                    except Exception as exc:
                        logger.warning("ffmpeg stdin write failed after %d chunks: %s",
                                       written, exc)
                        break
            finally:
                logger.debug("Writer thread exiting (wrote %d chunks, stop_event=%s)",
                             written, self._stop_event.is_set())

        self._writer_thread = threading.Thread(target=_writer, daemon=True)
        self._writer_thread.start()
        return _consumer

    @property
    def is_busy(self) -> bool:
        """True when the streamer is actively streaming or retrying."""
        return self._state.streaming or self._retrying or self._process is not None

    def _cleanup_audio(self) -> None:
        logger.debug("Cleaning up audio pipeline")
        if self._audio_engine and self._audio_consumer:
            self._audio_engine.remove_consumer(self._audio_consumer)
            self._audio_consumer = None
        if self._audio_queue:
            self._audio_queue.close()
        if self._writer_thread and self._writer_thread.is_alive():
            self._writer_thread.join(timeout=3.0)
            if self._writer_thread.is_alive():
                logger.warning("Writer thread did not stop within timeout")
        if self._process and self._process.process.stdin:
            try:
                self._process.process.stdin.close()
            except Exception:
                pass
        self._writer_thread = None
        self._audio_queue = None


def _parse_ffmpeg_error(exit_code: int, stderr: str) -> str:
    """Extract a human-readable error from ffmpeg stderr output."""
    low = stderr.lower() if stderr else ""
    if "401" in low or "unauthorized" in low:
        return "Icecast authentication failed (401) — check username/password"
    if "403" in low or "forbidden" in low:
        return "Icecast access denied (403) — check mount permissions"
    if "404" in low or "not found" in low:
        return "Icecast mount not found (404) — check mount point"
    if "connection refused" in low or "refused" in low:
        return "Connection refused — is the Icecast server running?"
    if "no route" in low or "network is unreachable" in low:
        return "Network unreachable — check internet connection"
    if "name or service not known" in low or "resolve" in low:
        return "DNS lookup failed — check server hostname"
    if "connection timed out" in low or "timed out" in low:
        return "Connection timed out — check server address and port"
    if "already connected" in low or "mount" in low and "in use" in low:
        return "Mount point already in use — another source is connected"
    if stderr:
        last_line = stderr.splitlines()[-1].strip()
        if last_line:
            return last_line
    return f"Stream failed (ffmpeg exit code {exit_code})"


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
