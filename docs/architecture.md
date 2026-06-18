# OndePi Architecture

OndePi is a **full-duplex audio appliance**. Concurrently, by design, it:

1. **Captures** the audio-interface input, processes it, and (when live) streams
   it to a server mount (`icecast://…/input`, plain Icecast source protocol).
2. **Plays** a configured webradio URL to the audio-interface **output**, which
   feeds a hardware **FM transmitter** (and the headphone jack). This runs even
   when not streaming.

The output can be switched from webradio to a live **input monitor** (hear the
captured input) via the monitor toggle — that's the only thing that changes the
output source; it is independent of streaming state.

## Components (`src/ondepi/`)
- **AudioEngine** (`audio.py`) — owns the single `sd.InputStream`. In the
  realtime callback it copies the buffer, applies gain + a soft-clip limiter
  (in place), computes meters, optionally writes the monitor output, and hands
  frames to consumers. The callback is kept allocation-/log-free; input
  overflows (xruns) are counted and logged by a non-RT watcher. Capture
  `latency`/`blocksize` are configurable (a too-small buffer = xrun clicks).
- **Streamer** (`streamer.py`) — spawns ffmpeg (`f32le` on stdin → encoded to
  the Icecast mount). A bounded ring buffer (`_AudioChunkBuffer`) + a writer
  thread decouple the realtime callback from blocking pipe I/O. A monitor thread
  owns connection state: a grace period to confirm connect, post-connect error
  + **stall** detection, `-rw_timeout` so a black-holed uplink fails fast, and a
  `stream_phase` lifecycle (`stopped/connecting/live/stalled/error`). Reconnect
  uses jittered backoff and is coupled to the connectivity doctor (waits for the
  uplink instead of burning attempts into a dead network). The source password
  is redacted from status/logs.
- **UplinkChecker / net_probe** (`uplink.py`, `net_probe.py`) — the connectivity
  doctor: layered probe (public-anchor-by-IP → DNS → server TCP) producing a
  structured `UplinkState` with a reason (`ok/no_internet/dns_failed/
  server_unreachable`) instead of a single opaque bool.
- **WebradioPlayer** (`webradio.py`) — ffmpeg decodes the webradio URL to a
  `sd.OutputStream` (→ FM). Reconnects on failure.
- **State** (`state.py`) — shared in-memory `StreamState` (levels, gain,
  stream_phase, uplink, retry/error). Serialised via `as_dict()` for the API.
- **API** (`api.py`) — FastAPI control/monitoring. Serves the web UI, exposes
  `/api/status`, `/api/levels`, `/api/config` (password masked; blank save keeps
  current), `/api/stream/*`, `/api/gain`, `/api/monitor`, `/api/listen` (per-
  client mp3 of the output bus, capped). A background thread restarts the stream
  on device reconnect.
- **Serial** (`serial_bridge.py`, `serial_device.py`) — JSON-line protocol to
  the M5Stack (the primary field UI): pushes levels (~10 Hz) + status (phase,
  uplink reason, error), receives start/stop/gain/ping.
- **Config** (`config.py`) — TOML dataclasses. Loading is tolerant of unknown
  keys (a stale/removed field never bricks startup). `to_dict()` returns copies.

## Data flow
```
input → AudioEngine callback ─┬─ meters → State → API/Serial
                              ├─ monitor OutputStream → interface out → FM (when monitoring)
                              └─ ring buffer → writer → ffmpeg stdin → Icecast /input (when live)

webradio URL → ffmpeg → OutputStream → interface out → FM (when not monitoring)
```

## Control flow
Web UI / M5Stack / CLI → API → Streamer (start/stop) · AudioEngine (gain,
monitor) · State. The connectivity doctor and the device-reconnect watcher run
as background threads.

## Deployment
Runs under systemd (`ondepi.service`) as a checkout in `/opt/OndePi`. The unit
grants `LimitRTPRIO`/`LimitMEMLOCK` and sets `WorkingDirectory` (the web UI is
served relative to it). Logging is configured from `general.log_level` and goes
to journald.
