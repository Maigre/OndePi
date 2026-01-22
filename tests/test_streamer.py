from ondepi.streamer import _retry_delay


def test_retry_delay_caps():
    assert _retry_delay(1, 3, 30) == 3
    assert _retry_delay(2, 3, 30) == 6
    assert _retry_delay(5, 3, 10) == 10
