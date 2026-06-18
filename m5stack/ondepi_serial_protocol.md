# OndePi Serial Protocol

This protocol is shared between the Raspberry Pi (server) and M5Stack Core (hardware interface).

## Framing
- JSON line-delimited
- Each message is a single line terminated by `\n`
- Baud rate: 115200

## Commands (M5Stack → Raspberry Pi)

| Action | Payload | Description |
| --- | --- | --- |
| start | `{ "action": "start" }` | Start streaming |
| stop | `{ "action": "stop" }` | Stop streaming |
| gain | `{ "action": "gain", "value": 2.0 }` | Set gain in dB |
| ping | `{ "action": "ping" }` | Keep-alive heartbeat |

## Events (Raspberry Pi → M5Stack)

| Type | Payload | Description |
| --- | --- | --- |
| status | `{ "type": "status", "streaming": true, "phase": "live", "duration": 3661, "error": null, "uplink_ok": true, "uplink_reason": "ok" }` | Overall status with stream phase, duration and uplink connectivity |
| levels | `{ "type": "levels", "left_rms": 0.2, "right_rms": 0.18, "left_peak": 0.7, "right_peak": 0.65, "clipping": false, "limiting": false }` | Stereo input meters with indicators |
| gain | `{ "type": "gain", "value": 1.5 }` | Echo current gain value |

## Event Details

### Status Event
```json
{
  "type": "status",
  "streaming": true,
  "streaming_requested": true,
  "phase": "live",
  "duration": 3661,
  "error": null,
  "uplink_ok": true,
  "uplink_reason": "ok"
}
```
- `streaming`: boolean - whether audio is actually flowing to the server
- `streaming_requested`: boolean - whether the operator asked to stream (stays
  true while connecting/retrying)
- `phase`: string - lifecycle: `stopped` | `connecting` | `live` | `stalled` |
  `error`. Source of truth for the status display; omitted by legacy servers
  (consumers should fall back to `streaming`/`error`).
- `duration`: integer - stream duration in seconds (0 when stopped)
- `error`: string or null - error message if any
- `uplink_ok`: boolean or null - source server reachable (null if not yet checked)
- `uplink_reason`: string - connectivity-doctor result: `ok` | `no_internet` |
  `dns_failed` | `server_unreachable` | `not_configured`

### Levels Event
```json
{
  "type": "levels",
  "left_rms": 0.2,
  "right_rms": 0.18,
  "left_peak": 0.7,
  "right_peak": 0.65,
  "clipping": false,
  "limiting": false
}
```
- `left_rms`, `right_rms`: float 0.0-1.0 - RMS level per channel
- `left_peak`, `right_peak`: float 0.0-1.0 - Peak level per channel
- `clipping`: boolean - true if input is clipping
- `limiting`: boolean - true if limiter is active

### Gain Event
```json
{
  "type": "gain",
  "value": 3.0
}
```
- `value`: float - current gain in dB

## Timing
- Levels events should be sent at ~30 Hz for smooth VU meter display
- Status events should be sent when state changes and periodically (~1 Hz)
- Ping commands are sent every 5 seconds as heartbeat
