"""Programme measurements keep meter scratch space bounded without changing LUFS."""

import numpy as np
import pytest

from speechmix import chain, programme
from speechmix.meter import IntegratedMeter


@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_programme_loudness_matches_a_single_real_meter_add(channels, dtype):
    rate = 48000
    count = 2 * chain._MEASURE_CHUNK + 123
    rng = np.random.default_rng(20261028)
    audio = rng.normal(0, 0.025, (channels, count)).astype(dtype)
    # A transient on each side of a boundary exercises filter continuity.
    audio[:, chain._MEASURE_CHUNK - 1:chain._MEASURE_CHUNK + 1] = 0.95
    meter = IntegratedMeter(rate)
    meter.add(audio)
    assert programme._lufs(audio, rate) == meter.value()


def test_programme_loudness_never_hands_the_meter_a_full_long_programme(monkeypatch):
    sizes = []
    original = IntegratedMeter.add

    def record(self, block, speech=None):
        sizes.append(block.shape[-1])
        return original(self, block, speech)

    monkeypatch.setattr(IntegratedMeter, "add", record)
    count = 2 * chain._MEASURE_CHUNK + 123
    audio = np.ones((2, count), dtype=np.float32) * 0.02
    assert programme._lufs(audio, 48000) is not None
    assert sizes == [chain._MEASURE_CHUNK, chain._MEASURE_CHUNK, 123]


@pytest.mark.parametrize("samples", [0, 47999, 48000, 48001])
def test_silent_and_short_programmes_still_have_no_measurable_loudness(samples):
    assert programme._lufs(np.zeros((2, samples), dtype=np.float32), 48000) is None
