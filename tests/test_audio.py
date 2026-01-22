import numpy as np

from ondepi.audio import AudioMeter, GainController, SoftClipper


def test_audio_meter_levels():
    meter = AudioMeter()
    data = np.array([0, 16384, -16384], dtype=np.int16)
    levels = meter.compute_levels(data)
    assert 0 < levels.rms <= 1
    assert 0 < levels.peak <= 1


def test_gain_controller():
    gain = GainController(gain_db=6.0)
    data = np.array([0.5, -0.5], dtype=np.float32)
    out = gain.apply(data)
    assert out.max() > 0.5
    assert out.min() < -0.5


def test_soft_clipper():
    clipper = SoftClipper(enabled=True, drive=2.0)
    data = np.array([2.0, -2.0, 0.0], dtype=np.float32)
    out = clipper.apply(data)
    assert out.max() <= 1.0
    assert out.min() >= -1.0
