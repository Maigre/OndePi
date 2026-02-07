from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .config import AzuraCastConfig, MetadataConfig, StreamConfig

logger = logging.getLogger(__name__)


@dataclass
class AzuraCastClient:
    config: AzuraCastConfig
    stream_config: Optional[StreamConfig] = None

    def update_config(self, config: AzuraCastConfig, stream_config: Optional[StreamConfig] = None) -> None:
        """Update the AzuraCast configuration."""
        self.config = config
        if stream_config is not None:
            self.stream_config = stream_config

    def _get_api_url(self) -> str:
        """Derive the AzuraCast API URL from the Icecast server host."""
        # Use explicit api_url if set (backward compat), otherwise derive from stream server
        if self.config.api_url:
            return self.config.api_url.rstrip("/")
        if self.stream_config and self.stream_config.server:
            return f"https://{self.stream_config.server}/api"
        return ""

    def update_nowplaying(self) -> None:
        """Force AzuraCast to re-read Now Playing metadata from Icecast."""
        if not self.config.station_id or not self.config.access_token:
            return

        api_url = self._get_api_url()
        if not api_url:
            logger.warning("AzuraCast: cannot derive API URL – no stream server configured")
            return

        url = f"{api_url}/station/{self.config.station_id}/nowplaying/update"
        request = urllib.request.Request(
            url,
            data=b"",
            method="POST",
            headers={
                "X-API-Key": self.config.access_token,
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec - controlled URL
            response.read()
        logger.info("AzuraCast now-playing refresh triggered")

    def update_nowplaying_safe(self) -> Optional[str]:
        try:
            self.update_nowplaying()
        except Exception as exc:
            logger.warning("AzuraCast nowplaying update failed: %s", exc)
            return str(exc)
        return None

    # Legacy aliases kept for backward compatibility
    def update_streamer_metadata(self, metadata: MetadataConfig) -> None:
        self.update_nowplaying()

    def update_streamer_metadata_safe(self, metadata: MetadataConfig) -> Optional[str]:
        return self.update_nowplaying_safe()


def format_song(artist: str, track: str) -> str:
    artist_value = (artist or "").strip()
    track_value = (track or "").strip()
    if artist_value and track_value:
        return f"{artist_value} - {track_value}"
    return artist_value or track_value or "Live"
