import time

import numpy as np

from ondepi.streamer import (
    OUTPUT_RW_TIMEOUT_US,
    STALL_TIMEOUT,
    Streamer,
    _AudioChunkBuffer,
    _retry_delay,
)


def test_retry_delay_caps():
    assert _retry_delay(1, 3, 30) == 3
    assert _retry_delay(2, 3, 30) == 6
    assert _retry_delay(5, 3, 10) == 10


def test_is_stalled_predicate():
    # Bypass __init__: _is_stalled only touches _audio_queue and _last_write_at.
    s = Streamer.__new__(Streamer)
    s._audio_queue = _AudioChunkBuffer(max_frames=100)

    # Empty buffer is never a stall, even with an ancient last-write.
    s._last_write_at = time.monotonic() - 1000
    assert s._is_stalled() is False

    # Buffer backed up past the fraction AND no drain for > STALL_TIMEOUT → stall.
    s._audio_queue.put_nowait(np.zeros((60, 2), dtype=np.float32))
    s._last_write_at = time.monotonic() - (STALL_TIMEOUT + 1)
    assert s._is_stalled() is True

    # Recent drain progress → not a stall, even with a full buffer.
    s._last_write_at = time.monotonic()
    assert s._is_stalled() is False


def test_ffmpeg_command_has_rw_timeout():
    from ondepi.config import AppConfig

    cfg = AppConfig.from_dict({"stream": {"server": "example.com", "mount": "live"}})
    s = Streamer(cfg, state=__import__("ondepi.state", fromlist=["StreamState"]).StreamState(), audio_engine=None)
    cmd = s.build_ffmpeg_command()
    assert "-rw_timeout" in cmd
    assert str(OUTPUT_RW_TIMEOUT_US) in cmd


def test_audio_chunk_buffer_counts_frames():
    buffer = _AudioChunkBuffer(max_frames=4)
    chunk = np.zeros((3, 2), dtype=np.float32)

    assert buffer.put_nowait(chunk)
    assert buffer.frame_count == 3

    out = buffer.get(timeout=0.01)
    assert out is chunk
    assert buffer.frame_count == 0


def test_audio_chunk_buffer_rejects_overflow():
    buffer = _AudioChunkBuffer(max_frames=4)
    assert buffer.put_nowait(np.zeros((3, 2), dtype=np.float32))
    assert not buffer.put_nowait(np.zeros((2, 2), dtype=np.float32))


def test_audio_chunk_buffer_close_wakes_reader():
    buffer = _AudioChunkBuffer(max_frames=4)
    buffer.close()

    assert buffer.get(timeout=0.01) is None
