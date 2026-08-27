"""The programme ceiling: one curve from the sum, multiplied into every stem.

Each stem limited to -1.5 dBTP is not enough, because what plays is the sum.
Two stems whose peaks are both pressed to the ceiling exceed full scale
whenever those peaks coincide -- measured on a real episode +4.51 dBFS, 49 971
samples over full scale in 4072 bursts, 200 a minute.

The fix is not harder per-stem limiting -- then every stem pays six decibels of
crest for what some other file happens to do. These tests hold the two
properties that make the shared curve the right answer: the sum obeys the
ceiling, and the balance between speakers cannot move.
"""

import numpy as np
import pytest
from speechmix import ceiling
from speechmix.errors import Misaligned

RATE = 48000


def _stem(seed, seconds=8.0, peak_db=-1.5):
    """Speech-ish bursts at uneven levels, pressed up to the ceiling."""
    rng = np.random.default_rng(seed)
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    body = sum(np.sin(2 * np.pi * (110 + 40 * seed) * k * t) / k for k in range(1, 10))
    gate = (np.sin(2 * np.pi * 0.7 * t + seed) > -0.2).astype(float)
    audio = body * gate * (0.6 + 0.4 * np.sin(2 * np.pi * 0.23 * t))
    audio += rng.normal(0, 1e-3, n)
    return audio / np.max(np.abs(audio)) * 10 ** (peak_db / 20)


def test_two_stems_at_the_ceiling_sum_over_full_scale():
    """The premise. Without this the rest of the module has nothing to fix."""
    a, b = _stem(1), _stem(2)
    assert np.max(np.abs(a)) <= 10 ** (-1.5 / 20) + 1e-9
    assert np.max(np.abs(b)) <= 10 ** (-1.5 / 20) + 1e-9
    assert np.max(np.abs(a + b)) > 1.0, "the fixture must actually clip when summed"


def test_the_sum_obeys_the_ceiling():
    a, b = _stem(1), _stem(2)
    shaped, report = ceiling.programme_ceiling([a, b], RATE)
    summed = shaped[0] + shaped[1]

    assert report.peak_before_dbfs > 0.0
    assert report.peak_after_dbfs <= ceiling.DEFAULT_CEILING_DBFS + 0.01
    assert np.max(np.abs(summed)) <= 10 ** (ceiling.DEFAULT_CEILING_DBFS / 20) + 1e-6
    assert report.samples_over_full_scale > 0
    assert report.bursts_over_full_scale > 0


def test_the_balance_between_speakers_cannot_move():
    """Every stem gets the same number, so their ratio is identical sample by sample."""
    a, b = _stem(1), _stem(2)
    shaped, _ = ceiling.programme_ceiling([a, b], RATE)

    loud = np.abs(a) > 1e-4
    before = a[loud] / b[loud] if np.all(np.abs(b[loud]) > 0) else None
    after = shaped[0][loud] / shaped[1][loud]
    if before is not None:
        np.testing.assert_allclose(after, before, rtol=1e-9)


def test_the_pass_is_idempotent():
    """min(1, ceiling/peak) gives 1 everywhere on a sum already at the ceiling.

    That is what makes it safe to run on every processing round.
    """
    a, b = _stem(1), _stem(2)
    once, _ = ceiling.programme_ceiling([a, b], RATE)
    twice, report = ceiling.programme_ceiling(once, RATE)

    np.testing.assert_allclose(twice[0], once[0], atol=1e-12)
    np.testing.assert_allclose(twice[1], once[1], atol=1e-12)
    assert report.max_reduction_db == pytest.approx(0.0, abs=1e-9)


def test_a_static_attenuation_would_cost_far_more():
    """Measured on real material, a static cut turned -14.00 LUFS into -25.74.

    It scales the whole file by what its single loudest sample demands, which
    also makes the balance between speakers depend on whose loudest transient
    was loudest -- that is to say random.
    """
    a, b = _stem(1), _stem(2)
    summed = a + b

    shaped, _ = ceiling.programme_ceiling([a, b], RATE)
    limited = shaped[0] + shaped[1]

    static = summed * (10 ** (ceiling.DEFAULT_CEILING_DBFS / 20) / np.max(np.abs(summed)))

    def rms_db(x):
        return 20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12)

    assert rms_db(limited) - rms_db(static) > 2.0


def test_stems_that_do_not_line_up_are_left_alone():
    """Summing sample-by-sample is only correct when the stems line up.

    That is a checked fact, not an assumption.
    """
    a, b = _stem(1), _stem(2)
    with pytest.raises(Misaligned):
        ceiling.programme_ceiling([a, b[:-1000]], RATE)
    with pytest.raises(Misaligned):
        ceiling.programme_ceiling([], RATE)


def test_the_sample_count_never_changes():
    a, b = _stem(1), _stem(2)
    shaped, _ = ceiling.programme_ceiling([a, b], RATE)
    assert shaped[0].size == a.size
    assert shaped[1].size == b.size
