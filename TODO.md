# OndePi TODO / Ideas

## Streaming & Reliability
- Add per-error retry policy (auth vs network vs device).
- Add manual "Retry now" control in the Web UI.
- Add health endpoint and optional watchdog.

## Audio Pipeline
- Expose limiter settings in UI form with presets.
- Add silence detection + alert when input levels stay near zero.
- Add configurable reconnect delay for audio device.
- Add optional noise gate or auto-gain control.

## Metadata & AzuraCast
- Add "Push metadata now" button.
- Show last successful metadata update time.
- Add metadata status history and retry counters.

## Web UI / UX
- Provide field-level help text and examples.
- Add diff preview before applying PATCH.
- Add dark mode toggle (for daylight readability).
- Add responsive layout tweaks for small screens.

## Serial / M5Stack
- Implement full serial status + controls loop.
- Provide a complete M5Stack sketch with meter display.
- Add JSON protocol versioning.

## Operations
- Add systemd service template and setup guide.
- Add log file rotation and structured logging.
- Add metrics export (Prometheus-style).

## Testing
- Add integration tests for API endpoints.
- Add audio pipeline mock tests.
- Add config migration tests.
