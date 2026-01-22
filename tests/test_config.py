from ondepi.config import ensure_config, load_config
from ondepi.state import StreamState


def test_load_config(tmp_path):
    config_text = """
[general]
log_level = "info"
reconnect = true
buffer_seconds = 5

[input]
alsa_device = "hw:3,0"
sample_rate = 44100
bits_per_sample = 16
channels = 2
limiter_enabled = true
limiter_drive = 1.5

[stream]
format = "mp3"
bitrate_kbps = 128
bitrate_mode = "cbr"
server = "example.com"
port = 8000
mount = "input"
username = "source"
password = "secret"
icy = true

[metadata]
name = "OndePi Live"
description = "Test"
genre = "Live"
public = false
artist = "OndePi"
track = "Live"

[web]
bind = "0.0.0.0"
port = 8090

[serial]
port = ""
baudrate = 115200

[azuracast]
enabled = false
api_url = ""
station_id = 0
access_token = ""
"""
    path = tmp_path / "config.toml"
    path.write_text(config_text.strip())

    config = load_config(path)
    assert config.stream.server == "example.com"
    assert config.input.channels == 2


def test_state_as_dict():
    state = StreamState()
    payload = state.as_dict()
    assert payload["levels"]["rms"] == 0.0
    assert payload["streaming"] is False


def test_validate_config_invalid_format(tmp_path):
    config_text = """
[general]
log_level = "info"
reconnect = true
buffer_seconds = 5

[input]
alsa_device = "hw:3,0"
sample_rate = 44100
bits_per_sample = 16
channels = 2
limiter_enabled = true
limiter_drive = 1.5

[stream]
format = "flac"
bitrate_kbps = 128
bitrate_mode = "cbr"
server = "example.com"
port = 8000
mount = "input"
username = "source"
password = "secret"
icy = true

[metadata]
name = "OndePi Live"
description = "Test"
genre = "Live"
public = false
artist = "OndePi"
track = "Live"

[web]
bind = "0.0.0.0"
port = 8090

[serial]
port = ""
baudrate = 115200

[azuracast]
enabled = false
api_url = ""
station_id = 0
access_token = ""
"""
    path = tmp_path / "config.toml"
    path.write_text(config_text.strip())
    try:
        load_config(path)
    except ValueError as exc:
        assert "stream.format" in str(exc)


def test_ensure_config(tmp_path):
    example = tmp_path / "example.toml"
    example.write_text("[general]\nlog_level = 'info'\n")
    target = tmp_path / "config.toml"
    created = ensure_config(target, example)
    assert created is True
    assert target.exists()
