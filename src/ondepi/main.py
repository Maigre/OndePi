from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from .api import ApiService
from .audio import AudioEngine
from .azuracast import AzuraCastClient
from .config import (
    DEFAULT_EXAMPLE_PATH,
    DEFAULT_CONFIG_PATH,
    ensure_config,
    interactive_setup,
    load_config,
    validation_errors,
)
from .state import StreamState
from .streamer import Streamer


def main() -> None:
    parser = argparse.ArgumentParser(description="OndePi live source")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config file")
    args = parser.parse_args()

    config_path = Path(args.config)
    created = ensure_config(config_path, DEFAULT_EXAMPLE_PATH)
    if created:
        print(f"Created default config at {config_path}.")

    config = load_config(config_path, validate=False)
    if created and sys.stdin.isatty():
        try:
            config = interactive_setup(config, config_path)
        except Exception as exc:  # pragma: no cover - interactive only
            print(f"Setup error: {exc}")

    errors = validation_errors(config)
    if errors:
        print("Config validation errors detected:")
        for error in errors:
            print(f"- {error}")
    state = StreamState()
    azuracast = AzuraCastClient(config.azuracast)
    streamer = Streamer(config, state, azuracast=azuracast)
    audio_engine = AudioEngine(config.input, state)
    api = ApiService(
        config,
        state,
        streamer,
        audio_engine=audio_engine,
        config_path=str(config_path),
    )

    uvicorn.run(api.app, host=config.web.bind, port=config.web.port)


if __name__ == "__main__":
    main()
