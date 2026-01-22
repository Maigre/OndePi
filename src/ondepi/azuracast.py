from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .config import AzuraCastConfig, MetadataConfig


@dataclass
class AzuraCastClient:
    config: AzuraCastConfig

    def update_streamer_metadata(self, metadata: MetadataConfig) -> None:
        if not self.config.enabled:
            return
        if not self.config.api_url or not self.config.station_id or not self.config.access_token:
            raise ValueError("AzuraCast config missing api_url, station_id, or access_token")

        song = format_song(metadata.artist, metadata.track)
        url = f"{self.config.api_url.rstrip('/')}/station/{self.config.station_id}/streamer-metadata"
        payload = json.dumps({"song": song}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.access_token}",
            },
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # nosec - controlled URL
            response.read()

    def update_streamer_metadata_safe(self, metadata: MetadataConfig) -> Optional[str]:
        try:
            self.update_streamer_metadata(metadata)
        except Exception as exc:  # pragma: no cover - runtime only
            return str(exc)
        return None


def format_song(artist: str, track: str) -> str:
    artist_value = (artist or "").strip()
    track_value = (track or "").strip()
    if artist_value and track_value:
        return f"{artist_value} - {track_value}"
    return artist_value or track_value or "Live"
