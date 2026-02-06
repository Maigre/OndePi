from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .config import AzuraCastConfig, MetadataConfig

logger = logging.getLogger(__name__)


@dataclass
class AzuraCastClient:
    config: AzuraCastConfig

    def update_config(self, config: AzuraCastConfig) -> None:
        """Update the AzuraCast configuration."""
        self.config = config

    def update_nowplaying(self) -> None:
        """Force AzuraCast to re-read Now Playing metadata from Icecast."""
        if not self.config.enabled:
            return
        if not self.config.api_url or not self.config.station_id or not self.config.access_token:
            logger.warning("AzuraCast enabled but missing api_url, station_id, or access_token – skipping")
            return

        url = f"{self.config.api_url.rstrip('/')}/station/{self.config.station_id}/nowplaying/update"
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
