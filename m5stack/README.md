# M5Stack Serial Protocol (draft)

## Transport
- USB serial, 115200 baud, 8N1
- UTF-8 JSON messages, one per line

## Messages from device -> OndePi
```json
{"action": "start"}
{"action": "stop"}
{"action": "gain", "value": 3.5}
{"action": "ping"}
```

## Messages from OndePi -> device
```json
{"type": "status", "streaming": true, "error": null}
{"type": "levels", "rms": 0.12, "peak": 0.62}
{"type": "gain", "value": 2.5}
```

## Next
A basic M5Stack sketch will be added in this folder.
