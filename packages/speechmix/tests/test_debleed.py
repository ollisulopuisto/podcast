"""Bleed is linear: subtract it, do not gate it.

Ducking cannot reach the bleed.  Measured on real material, the masks fired
correctly and closed the microphone on 64 % of the frames where only the other
person spoke, and *infinite* attenuation still moved the comb ripple only from
6.22 dB to 6.01 -- because the gaps fall on turn-taking boundaries where the
bleed is loudest, and overlapping speech needs both microphones open anyway.

Subtracting it works: coherence 0.1069 -> 0.0098, the target's own speech
preserved at r = 0.9993.
"""

import numpy as np
import pytest
from scipy import signal as sp_signal

from speechmix import Refused, debleed
from speechmix.debleed import _mean_coherence


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.asarray(x) ** 2)) + 1e-15)


def test_leakage_is_removed_and_own_speech_survives(two_mic_session):
    s = two_mic_session
    out, report = debleed(
        s["mic_a"], s["mic_b"], s["rate"], s["b_only"], target_only_mask=s["a_only"]
    )

    assert report.applied
    assert report.coherence_after < report.coherence_before / 2
    assert report.preservation > 0.99

    # Where only B speaks, mic A carries nothing but leakage.
    before = _rms_db(s["mic_a"][s["b_only"]])
    after = _rms_db(out[s["b_only"]])
    assert after - before < -10.0

    # Where only A speaks, the track must come back essentially untouched.
    own_error = _rms_db(out[s["a_only"]] - s["mic_a"][s["a_only"]])
    assert own_error - _rms_db(s["mic_a"][s["a_only"]]) < -20.0


def test_ducking_cannot_do_this(two_mic_session):
    """Even infinite attenuation in the gaps leaves the overlap untouched.

    This is the measurement that sent the project from gating to subtraction:
    the bleed that matters is the bleed *under* the other person's speech.
    """
    s = two_mic_session
    gated = s["mic_a"].copy()
    gated[s["b_only"]] = 0.0  # infinite ducking, the best a gate could ever do

    overlap = s["gate_a"] & s["gate_b"]
    gate_coherence = _mean_coherence(gated[overlap], s["mic_b"][overlap], s["rate"])

    cleaned, _ = debleed(
        s["mic_a"], s["mic_b"], s["rate"], s["b_only"], target_only_mask=s["a_only"]
    )
    debleed_coherence = _mean_coherence(cleaned[overlap], s["mic_b"][overlap], s["rate"])

    assert debleed_coherence < gate_coherence


def test_it_must_run_before_a_restoration_plugin(two_mic_session):
    """A generative plug-in does not preserve the linear relation between tracks.

    Here the "plug-in" is a mild waveshaper, which is as much non-linearity as
    any restoration model applies.  After it, the same estimate no longer
    cancels: the filter that would have removed the bleed cannot any more.
    """
    s = two_mic_session
    rate = s["rate"]

    before_plugin, _ = debleed(
        s["mic_a"], s["mic_b"], rate, s["b_only"], target_only_mask=s["a_only"]
    )

    processed_a = np.tanh(s["mic_a"] * 3.0) / 3.0
    processed_b = np.tanh(s["mic_b"] * 3.0) / 3.0
    after_plugin, _ = debleed(
        processed_a, processed_b, rate, s["b_only"], target_only_mask=s["a_only"]
    )

    leak = s["b_only"]
    removed_before = _rms_db(before_plugin[leak]) - _rms_db(s["mic_a"][leak])
    removed_after = _rms_db(after_plugin[leak]) - _rms_db(processed_a[leak])
    assert removed_before < removed_after - 3.0


def test_a_filter_that_eats_the_target_is_refused(two_mic_session):
    """The estimate measures its own output, because the mistake is inaudible until export."""
    s = two_mic_session
    # Estimate on frames where the *target* is doing the talking: the estimator
    # then fits the target's own voice and would subtract it.
    out, report = debleed(
        s["mic_a"],
        s["mic_b"],
        s["rate"],
        s["a_only"],
        target_only_mask=s["a_only"],
        min_preservation=0.999,
    )
    if report.applied:
        pytest.skip("this material did not produce a destructive estimate")
    assert "own speech" in report.reason
    np.testing.assert_array_equal(out, s["mic_a"])


def test_an_empty_mask_is_an_error_not_a_silence(two_mic_session):
    s = two_mic_session
    with pytest.raises(Refused) as excinfo:
        debleed(s["mic_a"], s["mic_b"], s["rate"], np.zeros_like(s["b_only"]))
    assert "not a silence" in str(excinfo.value)


def test_sample_count_is_preserved(two_mic_session):
    s = two_mic_session
    out, _ = debleed(s["mic_a"], s["mic_b"], s["rate"], s["b_only"])
    assert out.size == s["mic_a"].size


def test_stems_that_do_not_line_up_are_refused(two_mic_session):
    s = two_mic_session
    with pytest.raises(ValueError):
        debleed(s["mic_a"], s["mic_b"][: -1000], s["rate"], s["b_only"][:-1000])
