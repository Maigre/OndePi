# OndePi M5Stack Interface

Hardware control interface for OndePi streaming server using M5Stack Core Basic.

## Features

- **VU Meters**: Stereo level meters with peak hold, smooth animation
- **Status Display**: Streaming state, duration, connection status
- **Indicators**: INPUT CLIP and LIMITING warnings
- **Gain Control**: Adjust input gain with buttons
- **Start/Stop**: Control streaming with long press

## Hardware

- **M5Stack Core Basic** (ESP32, 320x240 LCD, 3 buttons)
- USB connection to Raspberry Pi running OndePi server

## Button Controls

| Button | Action |
|--------|--------|
| **A** (left) | Decrease gain (-0.5 dB per press, auto-repeat) |
| **B** (center) | Long press to Start/Stop streaming |
| **C** (right) | Increase gain (+0.5 dB per press, auto-repeat) |

## Display Layout

```
┌─────────────────────────────────────────┐
│  OndePi                                 │  Header
├─────────────────────────────────────────┤
│  ● STREAMING              01:23:45      │  Status + Duration
│                                         │
│            [ INPUT CLIP ]               │  Clip indicator
│  L ████████████░░░░░░░░░░░░░░  -6       │  VU Meter L
│  R ██████████░░░░░░░░░░░░░░░░  -8       │  VU Meter R
│             [ LIMITING ]                │  Limiter indicator
│                                         │
│      -      Gain: +3.0 dB      +        │  Gain display
│                                         │
├─────────────────────────────────────────┤
│  GAIN -      HOLD:START      GAIN +     │  Button hints
└─────────────────────────────────────────┘
```

## Building

### Prerequisites

- [PlatformIO](https://platformio.org/) (CLI or VS Code extension)

### Build & Upload

```bash
cd m5stack

# Build
pio run

# Upload to M5Stack
pio run --target upload

# Monitor serial output
pio device monitor
```

### VS Code

1. Open the `m5stack` folder in VS Code
2. Install PlatformIO extension
3. Click "Build" or "Upload" in the bottom toolbar

## Project Structure

```
m5stack/
├── platformio.ini          # PlatformIO configuration
├── include/
│   ├── config.h            # Constants and settings
│   ├── state.h             # Application state management
│   ├── protocol.h          # JSON serial protocol handler
│   └── ui.h                # Display drawing functions
├── src/
│   └── main.cpp            # Main application
└── ondepi_serial_protocol.md  # Protocol specification
```

## Serial Protocol

See [ondepi_serial_protocol.md](ondepi_serial_protocol.md) for the complete protocol specification.

The M5Stack communicates with the OndePi server via USB serial (115200 baud) using JSON-line messages.

## Configuration

Edit `include/config.h` to adjust:

- **Display layout**: Positions, sizes, colors
- **Meter behavior**: Attack/release times, peak hold duration
- **Gain range**: Min/max dB values, step size
- **Button timing**: Long press threshold, auto-repeat rate

## Dependencies

Managed automatically by PlatformIO:

- [M5Stack](https://github.com/m5stack/M5Stack) - Official M5Stack library
- [ArduinoJson](https://arduinojson.org/) - JSON parsing/serialization
