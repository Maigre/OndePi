# OndePi

OndePi is a headless-friendly live audio source streamer for AzuraCast/Icecast, with a minimal web dashboard and optional serial control (M5Stack/dial).

## What it does
- Streams stereo audio from a USB soundcard to AzuraCast/Icecast live source.
- Runs on Raspberry Pi (headless) and Ubuntu desktop.
- Web UI for start/stop, status, input levels, gain, and config edits.
- Optional serial device control/display (M5Stack/dial).

## Prerequisites
- Python 3.10+
- `ffmpeg` installed on the system
- ALSA-compatible audio device

## Project layout
- `src/ondepi/`: core services and API
- `web/`: simple UI (dark mode)
- `m5stack/`: serial protocol and starter sketch
- `docs/`: architecture and integration notes
- `tests/`: basic unit tests

## Configuration
On first run, OndePi creates `config.toml` from `config.example.toml` if missing.

Open the Web UI to edit settings and select the input device (auto-saved). You can also edit `config.toml` manually.

### Retry behavior
Configure retry behavior in the `[general]` section:
- `retry_initial_delay_seconds`: base delay before reconnect attempts.
- `retry_max_delay_seconds`: cap for exponential backoff.
- `retry_max_attempts`: 0 means unlimited retries.

### Limiter
Limiter settings live in `[input]`:
- `limiter_enabled`: enable soft clip limiter.
- `limiter_drive`: limiter strength.

### AzuraCast metadata
If you want OndePi to force the "Now Playing" metadata when the live source starts/stops, enable the `[azuracast]` section in `config.toml`.

## Quick start
1. Install dependencies (system packages like `ffmpeg` must be installed separately).
2. Run the installer:
	- `./install.sh`
3. Run the server:
	- `ondepi --config config.toml`
4. Open the web UI: `http://<device-ip>:8090`
5. Select your input device, set server credentials, and click **Save Full**.

## CLI
Use the optional CLI to check status or start/stop:
- `ondepi-cli status`
- `ondepi-cli start`
- `ondepi-cli stop`

## Troubleshooting (quick)
- **No audio levels**: confirm the input device and check the live preview meters.
- **Stream fails**: verify server/mount/password and check retry count + last error.
- **Metadata not updating**: enable `[azuracast]` and metadata push settings.
