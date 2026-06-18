from __future__ import annotations

import logging
from fastapi import FastAPI, HTTPException
import threading
import time
import queue
import subprocess
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import AppConfig
from .state import StreamState
from .audio import AudioEngine
from .streamer import Streamer
from .uplink import UplinkChecker
from .webradio import WebradioPlayer
import sounddevice as sd

logger = logging.getLogger(__name__)
import numpy as np
from .config import save_config, validate_config, validation_errors, validation_issues

# Each /api/listen client spawns its own mp3 encoder ffmpeg; cap concurrency so
# opening the page in many tabs can't exhaust a Pi.
MAX_LISTENERS = 3


class ApiService:
    def __init__(
        self,
        config: AppConfig,
        state: StreamState,
        streamer: Streamer,
        audio_engine: AudioEngine | None = None,
        config_path: str | None = None,
        uplink_checker: UplinkChecker | None = None,
        webradio_player: WebradioPlayer | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._streamer = streamer
        self._audio_engine = audio_engine
        self._config_path = config_path
        self._uplink_checker = uplink_checker
        self._webradio = webradio_player
        self._audio_monitor_stop = False
        self._audio_monitor_thread = None
        self._listen_lock = threading.Lock()
        self._listen_count = 0
        self.app = FastAPI(title="OndePi")
        self._register_routes()

    def _register_routes(self) -> None:
        app = self.app

        @app.get("/api/status")
        def status() -> dict:
            errors = validation_errors(self._config)
            return {
                "state": self._state.as_dict(),
                "stream": self._streamer.status(),
                "device": self._audio_engine.device_status() if self._audio_engine else None,
                "webradio": self._webradio.status() if self._webradio else None,
                "config": {
                    "valid": len(errors) == 0,
                    "errors": errors,
                    "issues": validation_issues(self._config),
                },
            }

        @app.get("/api/levels")
        def levels() -> dict:
            """Lightweight endpoint for fast meter updates."""
            limiter_active = False
            if self._audio_engine:
                # Limiter is "active" if enabled and peak is high
                max_peak = max(self._state.levels.peak_left, self._state.levels.peak_right)
                limiter_active = (
                    self._audio_engine._clipper.enabled
                    and max_peak > 0.7
                )
            return {
                "rms_left": self._state.levels.rms_left,
                "rms_right": self._state.levels.rms_right,
                "peak_left": self._state.levels.peak_left,
                "peak_right": self._state.levels.peak_right,
                "limiter_active": limiter_active,
                "input_clip": self._state.input_clip,
                "gain_db": self._state.gain_db,
            }

        @app.get("/api/devices")
        def list_devices() -> dict:
            devices = []
            current_device = None
            if self._config and self._config.input.alsa_device:
                current_device = self._config.input.alsa_device
            for idx, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    devices.append(
                        {
                            "id": idx,
                            "name": dev["name"],
                            "channels": dev["max_input_channels"],
                        }
                    )
            return {"devices": devices, "current": current_device}

        @app.post("/api/test-input")
        def test_input() -> dict:
            # The audio engine already holds the (exclusive) input device, so we
            # cannot open a second recording stream (the old code did and failed
            # with "device busy"). Sample the live meters instead — this works
            # whether idle, monitoring, or streaming.
            if not self._audio_engine:
                raise HTTPException(status_code=503, detail="Audio engine not running")
            if self._audio_engine.device_status().get("status") != "connected":
                raise HTTPException(status_code=409, detail="Input device not connected")
            rms = 0.0
            peak = 0.0
            for _ in range(10):  # ~0.5 s window of live levels
                lv = self._state.levels
                rms = max(rms, (lv.rms_left + lv.rms_right) / 2.0)
                peak = max(peak, lv.peak_left, lv.peak_right)
                time.sleep(0.05)
            return {"rms": rms, "peak": peak}

        @app.post("/api/stream/start")
        def start() -> dict:
            try:
                self._streamer.start()
            except Exception as exc:  # pragma: no cover - runtime only
                self._state.last_error = str(exc)
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return {"ok": True}

        @app.post("/api/stream/stop")
        def stop() -> dict:
            self._streamer.stop()
            return {"ok": True}

        @app.get("/api/config")
        def get_config() -> dict:
            # Never send the source password to clients; report only whether one
            # is set so the UI can show "leave blank to keep".
            data = self._config.to_dict()
            stream = data.get("stream", {})
            stream["password_set"] = bool(stream.get("password"))
            stream["password"] = ""
            return data

        @app.put("/api/config")
        def update_config(payload: dict) -> dict:
            if not self._config_path:
                raise HTTPException(status_code=500, detail="Config path not set")
            try:
                updated = AppConfig.from_dict(payload)
                # Blank password = "keep current" (the UI never receives it).
                if not updated.stream.password:
                    updated.stream.password = self._config.stream.password
                validate_config(updated)
                save_config(updated, self._config_path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            self._config = updated
            self._streamer.update_config(updated)
            if self._audio_engine:
                self._audio_engine.update_input(updated.input)
            if self._uplink_checker:
                self._uplink_checker.update_config(updated.stream)
            if self._webradio:
                old_url = self._webradio.url
                self._webradio.update_device(
                    updated.input.alsa_device or None,
                    updated.input.sample_rate,
                    updated.input.channels,
                )
                if updated.webradio.url != old_url:
                    self._webradio.update_url(updated.webradio.url)
            return {"ok": True}

        @app.patch("/api/config")
        def patch_config(payload: dict) -> dict:
            if not self._config_path:
                raise HTTPException(status_code=500, detail="Config path not set")
            try:
                merged = _merge_dicts(self._config.to_dict(), payload)
                updated = AppConfig.from_dict(merged)
                # Blank password = "keep current" (the UI never receives it).
                if not updated.stream.password:
                    updated.stream.password = self._config.stream.password
                validate_config(updated)
                save_config(updated, self._config_path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            self._config = updated
            self._streamer.update_config(updated)
            if self._audio_engine:
                self._audio_engine.update_input(updated.input)
            if self._uplink_checker:
                self._uplink_checker.update_config(updated.stream)
            if self._webradio:
                old_url = self._webradio.url
                self._webradio.update_device(
                    updated.input.alsa_device or None,
                    updated.input.sample_rate,
                    updated.input.channels,
                )
                if updated.webradio.url != old_url:
                    self._webradio.update_url(updated.webradio.url)
            return {"ok": True}

        @app.post("/api/gain")
        def set_gain(payload: dict) -> dict:
            gain_db = payload.get("gain_db")
            if not isinstance(gain_db, (int, float)):
                raise HTTPException(status_code=400, detail="gain_db must be number")
            self._state.gain_db = float(gain_db)
            return {"ok": True, "gain_db": self._state.gain_db}

        @app.post("/api/monitor")
        def set_monitor(payload: dict) -> dict:
            enabled = payload.get("enabled", False)
            actual = False
            if enabled:
                # Switch the output from webradio to live input monitor.
                if self._webradio:
                    self._webradio.stop()
                if self._audio_engine:
                    actual = self._audio_engine.set_monitor(True)
                if not actual:
                    # Monitor failed to open — don't leave the output (and FM)
                    # silent; bring webradio back.
                    logger.warning("Monitor enable failed; restoring webradio")
                    if self._webradio and self._config.webradio.url:
                        self._webradio.start()
            else:
                # Switch the output back to webradio.
                if self._audio_engine:
                    self._audio_engine.set_monitor(False)
                if self._webradio and self._config.webradio.url:
                    self._webradio.start()
            return {"ok": True, "enabled": actual}

        @app.get("/api/listen")
        def listen_output():
            with self._listen_lock:
                if self._listen_count >= MAX_LISTENERS:
                    raise HTTPException(status_code=429, detail="Too many listeners")
                self._listen_count += 1
            sr = self._config.input.sample_rate
            ch = self._config.input.channels
            audio_q: queue.Queue = queue.Queue(maxsize=100)

            def on_output(frames: np.ndarray):
                try:
                    audio_q.put_nowait(frames.copy())
                except queue.Full:
                    pass

            if self._audio_engine:
                self._audio_engine.add_output_consumer(on_output)
            if self._webradio:
                self._webradio.add_output_consumer(on_output)

            def generate():
                proc = subprocess.Popen(
                    [
                        "ffmpeg", "-hide_banner", "-loglevel", "error",
                        "-f", "f32le", "-ar", str(sr), "-ac", str(ch),
                        "-i", "pipe:0",
                        "-f", "mp3", "-b:a", "128k",
                        "pipe:1",
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                stop = threading.Event()
                silence = np.zeros(
                    (sr // 25, ch), dtype=np.float32
                ).tobytes()

                def feed():
                    try:
                        while not stop.is_set():
                            try:
                                chunk = audio_q.get(timeout=0.5)
                            except queue.Empty:
                                proc.stdin.write(silence)
                                proc.stdin.flush()
                                continue
                            proc.stdin.write(chunk.tobytes())
                            proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
                    finally:
                        try:
                            proc.stdin.close()
                        except Exception:
                            pass

                threading.Thread(target=feed, daemon=True).start()

                try:
                    while True:
                        data = proc.stdout.read(4096)
                        if not data:
                            break
                        yield data
                finally:
                    stop.set()
                    if self._audio_engine:
                        self._audio_engine.remove_output_consumer(on_output)
                    if self._webradio:
                        self._webradio.remove_output_consumer(on_output)
                    with self._listen_lock:
                        self._listen_count = max(0, self._listen_count - 1)
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass

            return StreamingResponse(
                generate(),
                media_type="audio/mpeg",
                headers={"Cache-Control": "no-cache"},
            )

        app.mount("/", StaticFiles(directory="web", html=True), name="web")

        @app.on_event("startup")
        def startup() -> None:
            if self._audio_engine:
                self._audio_engine.start()
            # Start webradio if URL configured (monitoring off by default)
            if self._webradio and self._config.webradio.url:
                self._webradio.start()
            if not self._audio_monitor_thread:
                self._audio_monitor_stop = False
                self._audio_monitor_thread = threading.Thread(
                    target=self._monitor_audio_device,
                    daemon=True,
                )
                self._audio_monitor_thread.start()

        @app.on_event("shutdown")
        def shutdown() -> None:
            self._audio_monitor_stop = True
            if self._audio_monitor_thread:
                self._audio_monitor_thread.join(timeout=2.0)
            if self._webradio:
                self._webradio.stop()
            if self._audio_engine:
                self._audio_engine.stop()

        @app.get("/", response_class=HTMLResponse)
        def root() -> HTMLResponse:
            return HTMLResponse("", status_code=307, headers={"Location": "/index.html"})

    def _monitor_audio_device(self) -> None:
        while not self._audio_monitor_stop:
            if not self._audio_engine:
                time.sleep(1)
                continue
            device_status = self._audio_engine.device_status()
            connected = device_status.get("status") == "connected"
            if not connected and self._state.streaming:
                logger.warning("Audio device disconnected while streaming, stopping stream")
                self._state.last_error = "Audio device disconnected, streaming paused"
                self._streamer.stop()
            # Only auto-restart if device reconnected, user still wants streaming,
            # and the streamer isn't already running or retrying on its own
            if (connected and
                self._state.streaming_requested and
                not self._state.streaming and
                not self._streamer.is_busy):
                logger.info("Audio device reconnected, auto-restarting stream")
                try:
                    self._streamer.start()
                except Exception as exc:
                    logger.error("Auto-restart failed: %s", exc)
                    self._state.last_error = str(exc)
            # NOTE: webradio playback is NOT gated on streaming — it feeds the
            # audio-interface output → hardware FM transmitter and must keep
            # running during a live stream. Webradio vs input-monitor on the
            # output is switched only by the monitor toggle (set_monitor).
            time.sleep(1)


def _merge_dicts(base: dict, patch: dict) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
