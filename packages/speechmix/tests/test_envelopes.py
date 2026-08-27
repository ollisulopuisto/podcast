"""Ducking as gain *decisions*, not gain changes.

One host writes them into an FCPXML as `<adjust-volume>` keyframes so the
editor can still change them; another bakes the same curve into samples. Same
computation, different emission.
"""

import numpy as np
import pytest
from speechmix import envelopes, grid
from speechmix.errors import EmptyResult

RATE = 48000


def _grid(seconds=20.0):
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    rng = np.random.default_rng(11)

    def voice(f0):
        return sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 9)) * 0.1

    half = n // 2
    gate_a = np.zeros(n, dtype=bool)
    gate_b = np.zeros(n, dtype=bool)
    gate_a[:half] = True
    gate_b[half:] = True
    a = (voice(118.0) + rng.normal(0, 3e-3, n)) * gate_a
    b = (voice(197.0) + rng.normal(0, 3e-3, n)) * gate_b
    mic_a = a + 0.12 * np.roll(b, 144)
    return grid.speech_grid({"a": mic_a, "b": b + 0.10 * np.roll(a, 150)}, RATE), mic_a


def test_the_result_is_breakpoints_not_audio():
    speech, _ = _grid()
    result = envelopes.duck_envelopes(speech)

    assert set(result) == {"a", "b"}
    for points in result.values():
        assert all(len(p) == 2 for p in points)
        times = [t for t, _ in points]
        assert times == sorted(times)
    assert min(db for _, db in result["a"]) == pytest.approx(envelopes.DEFAULT_DEPTH_DB, abs=0.1)


def test_the_same_decision_can_be_baked_instead():
    """The host decides emission; the computation does not change."""
    speech, mic_a = _grid()
    points = envelopes.duck_envelopes(speech)["a"]
    baked = envelopes.apply_envelope(mic_a, RATE, points)

    assert baked.size == mic_a.size
    half = mic_a.size // 2
    quiet = 20 * np.log10(
        np.sqrt(np.mean(baked[half + RATE :] ** 2))
        / np.sqrt(np.mean(mic_a[half + RATE :] ** 2))
    )
    assert quiet < -6.0, "the microphone was not ducked while the other person had the floor"


def test_depth_of_zero_means_no_ducking():
    speech, _ = _grid()
    result = envelopes.duck_envelopes(speech, envelopes.DuckSettings(depth_db=0.0))
    assert all(points == [] for points in result.values())


def test_a_setting_that_produced_nothing_is_an_error():
    """Pressing the button before the analysis finished left the masks empty
    with nothing said: the setting read -9 dB and the output had none.
    """
    n = RATE * 20
    t = np.arange(n) / RATE
    # One speaker with ordinary pauses: the grid itself is fine, there is
    # simply nobody to duck against.  A microphone is not ducked in a silence
    # -- that would only pump the room tone.
    speaking = (np.sin(2 * np.pi * 0.2 * t) > 0.0).astype(float)
    tone = np.sin(2 * np.pi * 150 * t) * 0.1 * speaking
    speech = grid.speech_grid({"a": tone}, RATE)
    assert speech.coverage("a") > 0.2, "the grid must be valid for this to test envelopes"
    with pytest.raises(EmptyResult) as excinfo:
        envelopes.duck_envelopes(speech)
    assert "not a silence" in str(excinfo.value)
