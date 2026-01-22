# OndePi Serial Protocol

This protocol is shared between the Raspberry Pi and M5Stack/dial device.

## Framing
- JSON line-delimited
- Each message is a single line terminated by `\n`

## Commands
| Action | Payload | Description |
| --- | --- | --- |
| start | `{ "action": "start" }` | start streaming |
| stop | `{ "action": "stop" }` | stop streaming |
| gain | `{ "action": "gain", "value": 2.0 }` | set gain in dB |
| ping | `{ "action": "ping" }` | keep-alive |

## Events
| Type | Payload | Description |
| --- | --- | --- |
| status | `{ "type": "status", "streaming": true, "error": null }` | overall status |
| levels | `{ "type": "levels", "rms": 0.2, "peak": 0.7 }` | input meter |
| gain | `{ "type": "gain", "value": 1.5 }` | echo current gain |
