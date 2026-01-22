# OndePi Architecture

## Components
- **Audio**: capture from ALSA, compute RMS/peak, apply gain.
- **Streamer**: ffmpeg process to Icecast/AzuraCast live source.
- **State**: shared in-memory status (streaming, errors, levels, gain).
- **API**: FastAPI HTTP endpoints for control and monitoring.
- **Web UI**: minimal dashboard (dark mode), talks to API.
- **Serial**: JSON-line protocol for M5Stack/dial.

## Data flow
1. ALSA input -> Audio meter -> Gain -> Encoder (ffmpeg)
2. Encoder -> Icecast live source
3. Status/levels -> API -> Web UI + Serial device

## Control flow
- Web UI / Serial -> API -> Streamer (start/stop) + State (gain)

## Notes
- Metadata updates for AzuraCast are a pending item; see `docs/azuracast_metadata.md`.
