import numpy as np

from ondepi.streamer import _AudioChunkBuffer, _retry_delay


def test_retry_delay_caps():
    assert _retry_delay(1, 3, 30) == 3
    assert _retry_delay(2, 3, 30) == 6
    assert _retry_delay(5, 3, 10) == 10


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
