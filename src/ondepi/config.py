from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - py310 fallback
    import tomli as tomllib  # type: ignore[import-not-found]

import tomli_w  # type: ignore[import-not-found]

DEFAULT_CONFIG_PATH = Path("config.toml")
DEFAULT_EXAMPLE_PATH = Path("config.example.toml")


@dataclass
class GeneralConfig:
    log_level: str = "info"
    reconnect: bool = True
    buffer_seconds: int = 5
    retry_initial_delay_seconds: int = 3
    retry_max_delay_seconds: int = 30
    retry_max_attempts: int = 0


@dataclass
class InputConfig:
    alsa_device: str = "hw:0,0"
    sample_rate: int = 44100
    bits_per_sample: int = 16
    channels: int = 2
    limiter_enabled: bool = True
    limiter_drive: float = 1.5


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
    artist: str = "OndePi"
    track: str = "Live"
    push_enabled: bool = True
    push_interval_seconds: int = 30
    retry_attempts: int = 2
    retry_delay_seconds: int = 5


@dataclass
class WebConfig:
    bind: str = "0.0.0.0"
    port: int = 8090


@dataclass
class SerialConfig:
    port: str = ""
    baudrate: int = 115200


@dataclass
class AzuraCastConfig:
    enabled: bool = False
    api_url: str = ""
    station_id: int = 0
    access_token: str = ""


@dataclass
class AppConfig:
    general: GeneralConfig
    input: InputConfig
    stream: StreamConfig
    metadata: MetadataConfig
    web: WebConfig
    serial: SerialConfig
    azuracast: AzuraCastConfig

    def to_dict(self) -> Dict[str, Any]:
        return {
            "general": self.general.__dict__,
            "input": self.input.__dict__,
            "stream": self.stream.__dict__,
            "metadata": self.metadata.__dict__,
            "web": self.web.__dict__,
            "serial": self.serial.__dict__,
            "azuracast": self.azuracast.__dict__,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AppConfig":
        return AppConfig(
            general=GeneralConfig(**_section(data, "general")),
            input=InputConfig(**_section(data, "input")),
            stream=StreamConfig(**_section(data, "stream")),
            metadata=MetadataConfig(**_section(data, "metadata")),
            web=WebConfig(**_section(data, "web")),
            serial=SerialConfig(**_section(data, "serial")),
            azuracast=AzuraCastConfig(**_section(data, "azuracast")),
        )


def _section(data: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"Expected section '{key}' to be a table")
    return value


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
    if config.azuracast.enabled:
        if not config.azuracast.api_url:
            issues.append({"field": "azuracast.api_url", "message": "is required when enabled"})
        if config.azuracast.station_id <= 0:
            issues.append({"field": "azuracast.station_id", "message": "must be > 0"})
        if not config.azuracast.access_token:
            issues.append({"field": "azuracast.access_token", "message": "is required when enabled"})
    if config.metadata.push_interval_seconds <= 0:
        issues.append({"field": "metadata.push_interval_seconds", "message": "must be > 0"})
    if config.metadata.retry_attempts < 0:
        issues.append({"field": "metadata.retry_attempts", "message": "must be >= 0"})
    if config.metadata.retry_delay_seconds < 0:
        issues.append({"field": "metadata.retry_delay_seconds", "message": "must be >= 0"})
    if config.general.retry_initial_delay_seconds < 0:
        issues.append({"field": "general.retry_initial_delay_seconds", "message": "must be >= 0"})
    if config.general.retry_max_delay_seconds < 0:
        issues.append({"field": "general.retry_max_delay_seconds", "message": "must be >= 0"})
    if config.general.retry_max_attempts < 0:
        issues.append({"field": "general.retry_max_attempts", "message": "must be >= 0"})
    return issues


def validation_errors(config: AppConfig) -> list[str]:
    return [f"{issue['field']} {issue['message']}" for issue in validation_issues(config)]


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
