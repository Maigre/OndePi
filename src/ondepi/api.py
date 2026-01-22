from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import AppConfig
from .state import StreamState
from .audio import AudioEngine
from .streamer import Streamer
import sounddevice as sd
import numpy as np
from .config import save_config, validate_config, validation_errors, validation_issues


class ApiService:
    def __init__(
        self,
        config: AppConfig,
        state: StreamState,
        streamer: Streamer,
        audio_engine: AudioEngine | None = None,
        config_path: str | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._streamer = streamer
        self._audio_engine = audio_engine
        self._config_path = config_path
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
                "config": {
                    "valid": len(errors) == 0,
                    "errors": errors,
                    "issues": validation_issues(self._config),
                },
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
                            "alsa": f"hw:{idx},0",
                        }
                    )
            return {"devices": devices, "current": current_device}

        @app.post("/api/test-input")
        def test_input() -> dict:
            try:
                cfg = self._config.input
                frames = int(cfg.sample_rate * 2)
                recording = sd.rec(
                    frames,
                    samplerate=cfg.sample_rate,
                    channels=cfg.channels,
                    dtype="float32",
                    device=cfg.alsa_device or None,
                )
                sd.wait()
                rms = float(np.sqrt(np.mean(np.square(recording))))
                peak = float(np.max(np.abs(recording)))
                return {"rms": rms, "peak": peak}
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc

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
            return self._config.to_dict()

        @app.put("/api/config")
        def update_config(payload: dict) -> dict:
            if not self._config_path:
                raise HTTPException(status_code=500, detail="Config path not set")
            try:
                updated = AppConfig.from_dict(payload)
                validate_config(updated)
                save_config(updated, self._config_path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            self._config = updated
            self._streamer.update_config(updated)
            if self._audio_engine:
                self._audio_engine.update_input(updated.input)
            return {"ok": True}

        @app.patch("/api/config")
        def patch_config(payload: dict) -> dict:
            if not self._config_path:
                raise HTTPException(status_code=500, detail="Config path not set")
            try:
                merged = _merge_dicts(self._config.to_dict(), payload)
                updated = AppConfig.from_dict(merged)
                validate_config(updated)
                save_config(updated, self._config_path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            self._config = updated
            self._streamer.update_config(updated)
            if self._audio_engine:
                self._audio_engine.update_input(updated.input)
            return {"ok": True}

        @app.post("/api/gain")
        def set_gain(payload: dict) -> dict:
            gain_db = payload.get("gain_db")
            if not isinstance(gain_db, (int, float)):
                raise HTTPException(status_code=400, detail="gain_db must be number")
            self._state.gain_db = float(gain_db)
            return {"ok": True, "gain_db": self._state.gain_db}

        app.mount("/", StaticFiles(directory="web", html=True), name="web")

        @app.on_event("startup")
        def startup() -> None:
            if self._audio_engine:
                self._audio_engine.start()

        @app.on_event("shutdown")
        def shutdown() -> None:
            if self._audio_engine:
                self._audio_engine.stop()

        @app.get("/", response_class=HTMLResponse)
        def root() -> HTMLResponse:
            return HTMLResponse("", status_code=307, headers={"Location": "/index.html"})


def _merge_dicts(base: dict, patch: dict) -> dict:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged
