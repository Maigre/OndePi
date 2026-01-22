# AzuraCast metadata update

Issue observed: when live source starts, the web player may continue showing the previous playlist metadata.

## Plan
- Push metadata on stream start and periodically while live.
- Retry a few times if AzuraCast doesn't update immediately.

## Configuration
Add the following section to `config.toml`:

```toml
[azuracast]
enabled = true
api_url = "https://your-azuracast.example/api"
station_id = 0
access_token = "<your-token>"

[metadata]
push_enabled = true
push_interval_seconds = 30
retry_attempts = 2
retry_delay_seconds = 5
```

## Next step
We use the endpoint:
`POST /station/{station_id}/streamer-metadata` with JSON `{ "song": "Artist - Title" }`.
