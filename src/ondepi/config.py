from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Dict

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - py310 fallback
    import tomli as tomllib  # type: ignore[import-not-found]

import tomli_w  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config.toml")
DEFAULT_EXAMPLE_PATH = Path("config.example.toml")


@dataclass
class GeneralConfig:
    log_level: str = "debug"
    reconnect: bool = True
    buffer_seconds: int = 5
    retry_initial_delay_seconds: int = 3
    retry_max_delay_seconds: int = 30
    retry_max_attempts: int = 0


@dataclass
class InputConfig:
    alsa_device: str | int | None = None
    sample_rate: int = 44100
    bits_per_sample: int = 16
    channels: int = 2
    limiter_enabled: bool = True
    limiter_drive: float = 1.5
    # PortAudio capture block size in frames. Leave 0 (auto). Measured on a
    # Pi 3B+: forcing an explicit blocksize (e.g. 2048) *causes* ~7 input
    # overflows/s; 0 lets PortAudio size the buffers for the latency target and
    # measured 0/s. Tune `latency`, not this.
    blocksize: int = 0
    # PortAudio capture latency: "low" | "high" | seconds (float). The buffer
    # that absorbs scheduling/GIL jitter; if it's too small the capture drops
    # samples (input overflow = clicks). "high" resolved to only ~34 ms on a
    # Pi 3B+ — too small under load — so we default to 0.3 s. Raise to 0.5 if
    # clicks persist under heavy concurrent load.
    latency: float | str = 0.3


@dataclass
class StreamConfig:
    format: str = "mp3"
    bitrate_kbps: int = 256
    bitrate_mode: str = "cbr"
    server: str = ""
    port: int = 8000
    mount: str = ""
    username: str = "source"
    password: str = ""
    icy: bool = True


@dataclass
class MetadataConfig:
    name: str = "OndePi Live Source"
    description: str = "OndePi live input"
    genre: str = "Live"
    public: bool = False


@dataclass
class WebConfig:
    bind: str = "0.0.0.0"
    port: int = 8090


@dataclass
class SerialConfig:
    port: str = ""
    baudrate: int = 115200


@dataclass
class WebradioConfig:
    url: str = ""


@dataclass
class AppConfig:
    general: GeneralConfig
    input: InputConfig
    stream: StreamConfig
    metadata: MetadataConfig
    web: WebConfig
    serial: SerialConfig
    webradio: WebradioConfig

    def to_dict(self) -> Dict[str, Any]:
        return {
            "general": self.general.__dict__,
            "input": self.input.__dict__,
            "stream": self.stream.__dict__,
            "metadata": self.metadata.__dict__,
            "web": self.web.__dict__,
            "serial": self.serial.__dict__,
            "webradio": self.webradio.__dict__,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AppConfig":
        return AppConfig(
            general=_build(GeneralConfig, data, "general"),
            input=_build(InputConfig, data, "input"),
            stream=_build(StreamConfig, data, "stream"),
            metadata=_build(MetadataConfig, data, "metadata"),
            web=_build(WebConfig, data, "web"),
            serial=_build(SerialConfig, data, "serial"),
            webradio=_build(WebradioConfig, data, "webradio"),
        )


def _section(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Expected section '{key}' to be a table")
    return value


def _build(cls, data: Dict[str, Any], key: str):
    """Build a config dataclass from a section, ignoring unknown keys.

    Tolerating unknown keys means a stale field in a deployed config.toml (e.g.
    a removed option like the old `tls`) never bricks startup on a field unit —
    it's dropped with a warning instead of raising TypeError.
    """
    section = _section(data, key)
    known = {f.name for f in fields(cls)}
    kwargs = {}
    for k, v in section.items():
        if k in known:
            kwargs[k] = v
        else:
            logger.warning("Ignoring unknown config key '%s.%s'", key, k)
    return cls(**kwargs)


def load_config(path: str | Path, validate: bool = True) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)
    config = AppConfig.from_dict(data)
    if validate:
        validate_config(config)
    return config


def save_config(config: AppConfig, path: str | Path) -> None:
    config_path = Path(path)
    data = config.to_dict()
    config_path.write_text(tomli_w.dumps(data))


def ensure_config(
    path: str | Path,
    example_path: str | Path = DEFAULT_EXAMPLE_PATH,
) -> bool:
    config_path = Path(path)
    if config_path.exists():
        return False
    example_file = Path(example_path)
    if not example_file.exists():
        raise FileNotFoundError(f"Example config not found: {example_file}")
    config_path.write_text(example_file.read_text())
    return True


def validation_issues(config: AppConfig) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if config.input.channels not in (1, 2):
        issues.append({"field": "input.channels", "message": "must be 1 or 2"})
    if config.input.sample_rate <= 0:
        issues.append({"field": "input.sample_rate", "message": "must be > 0"})
    if config.input.limiter_drive <= 0:
        issues.append({"field": "input.limiter_drive", "message": "must be > 0"})
    if config.stream.format not in {"mp3", "aac", "opus"}:
        issues.append({"field": "stream.format", "message": "must be mp3, aac, or opus"})
    if config.stream.bitrate_kbps <= 0:
        issues.append({"field": "stream.bitrate_kbps", "message": "must be > 0"})
    if not config.stream.server:
        issues.append({"field": "stream.server", "message": "is required"})
    if not config.stream.mount:
        issues.append({"field": "stream.mount", "message": "is required"})
    if not (1 <= config.stream.port <= 65535):
        issues.append({"field": "stream.port", "message": "must be 1-65535"})
    if config.general.retry_initial_delay_seconds < 0:
        issues.append({"field": "general.retry_initial_delay_seconds", "message": "must be >= 0"})
    if config.general.retry_max_delay_seconds < 0:
        issues.append({"field": "general.retry_max_delay_seconds", "message": "must be >= 0"})
    if config.general.retry_max_attempts < 0:
        issues.append({"field": "general.retry_max_attempts", "message": "must be >= 0"})
    return issues


def validation_errors(config: AppConfig) -> list[str]:
    return [f"{issue['field']} {issue['message']}" for issue in validation_issues(config) if issue.get("level") != "warning"]


def validate_config(config: AppConfig) -> None:
    errors = validation_errors(config)
    if errors:
        raise ValueError("; ".join(errors))


def interactive_setup(config: AppConfig, path: str | Path) -> AppConfig:
    print("\nOndePi initial setup. Press Enter to keep defaults.\n")

    def prompt(label: str, current: str) -> str:
        value = input(f"{label} [{current}]: ").strip()
        return value or current

    stream = config.stream
    stream.server = prompt("Icecast server", stream.server)
    stream.port = int(prompt("Icecast port", str(stream.port)))
    stream.mount = prompt("Mount point", stream.mount)
    stream.username = prompt("Username", stream.username)
    stream.password = prompt("Password", stream.password)
    stream.format = prompt("Format (mp3/aac/opus)", stream.format)
    stream.bitrate_kbps = int(prompt("Bitrate kbps", str(stream.bitrate_kbps)))

    save_config(config, path)
    validate_config(config)
    return config
