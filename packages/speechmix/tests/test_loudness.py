"""The loudness target is the programme's, not one stem's.

Two microphones each normalised to -14 LUFS sum above it -- measured -12.2,
because the speakers overlap and the microphones hear each other. The
difference has to come off every file, and it has to go into the **target**,
never into the gain: the chain normalises to the target as its last act, so a
trim added to the gain is removed again exactly. Measured with the trim in the
wrong place, stems landed on -14.1 instead of -15.8 and the reading looked
correct.
"""

import numpy as np
import pytest

from speechmix import loudness

RATE = 48000


def _mic(seed, seconds=30.0):
    """One microphone: bursts at uneven levels, with pauses."""
    rng = np.random.default_rng(seed)
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    body = sum(np.sin(2 * np.pi * (105 + 55 * seed) * k * t) / k for k in range(1, 10))
    # The two speakers overlap for part of the time: that overlap is why the
    # sum reads louder than either stem.
    gate = (np.sin(2 * np.pi * 0.09 * t + seed * 1.6) > -0.35).astype(float)
    audio = body * gate * (0.5 + 0.5 * np.sin(2 * np.pi * 0.31 * t))
    return audio * 0.1 + rng.normal(0, 1e-4, n)


def test_stems_each_at_the_target_sum_above_it():
    """The premise, and the reason a programme trim exists at all."""
    target = -14.0
    stems = {}
    for name, seed in (("a", 1), ("b", 2)):
        raw = _mic(seed)
        stems[name] = raw * 10 ** ((target - loudness.integrated_lufs(raw, RATE)) / 20)

    for stem in stems.values():
        # One raw scaling does not land exactly: loudness is gated, so scaling
        # changes which blocks are counted.  See `normalise`, which settles.
        assert loudness.integrated_lufs(stem, RATE) == pytest.approx(target, abs=0.5)

    summed = stems["a"] + stems["b"]
    assert loudness.integrated_lufs(summed, RATE) > target + 0.5


def test_the_stem_target_makes_the_sum_land_on_the_target():
    target = -14.0
    raw = {"a": _mic(1), "b": _mic(2)}
    programme = loudness.programme_target(raw, RATE, target)

    assert programme.trim_db < 0.0, "the sum reads louder than the target, so the trim is down"
    assert programme.stem_target_lufs == pytest.approx(target + programme.trim_db)

    normalised = [
        stem * 10 ** ((programme.stem_target_lufs - loudness.integrated_lufs(stem, RATE)) / 20)
        for stem in raw.values()
    ]
    landed = loudness.integrated_lufs(normalised[0] + normalised[1], RATE)
    assert landed == pytest.approx(target, abs=0.5)


def test_a_trim_put_into_the_gain_is_removed_again_exactly():
    """The measurement that made this a rule rather than a preference.

    ``normalise`` is the chain's last act, so anything added ahead of it is
    undone -- and the reading afterwards looks perfectly correct.
    """
    target = -16.0
    stem = _mic(3)

    honest, _ = loudness.normalise(stem, RATE, target)
    with_trim_in_gain, _ = loudness.normalise(stem * 10 ** (-1.8 / 20), RATE, target)

    np.testing.assert_allclose(with_trim_in_gain, honest, rtol=1e-9)
    assert loudness.integrated_lufs(with_trim_in_gain, RATE) == pytest.approx(target, abs=0.1)


def test_normalise_reports_the_total_it_moved():
    """The reported gain is the whole move, settling included.

    A caller that logs it, or writes it into a stamp, needs the number that was
    actually applied -- not the first estimate, which is the one that misses.
    """
    stem = _mic(4)
    out, gain_db = loudness.normalise(stem, RATE, -16.0)

    assert loudness.integrated_lufs(out, RATE) == pytest.approx(-16.0, abs=0.1)
    np.testing.assert_allclose(out, stem * 10 ** (gain_db / 20), rtol=1e-9)
    first_estimate = -16.0 - loudness.integrated_lufs(stem, RATE)
    assert gain_db != pytest.approx(first_estimate, abs=1e-6)


def test_normalising_settles_rather_than_assuming_one_pass_lands():
    """Loudness is gated, so scaling changes which blocks count.

    A single scaling by `target - measured` lands short.  That is not a
    rounding error to be ignored: on a real episode, through a chain that also
    has a limiter eating loudness, the first round was 1-2 dB short.
    """
    stem = _mic(5)
    measured = loudness.integrated_lufs(stem, RATE)

    one_pass = stem * 10 ** ((-14.0 - measured) / 20)
    settled, _ = loudness.normalise(stem, RATE, -14.0)

    naive_error = abs(loudness.integrated_lufs(one_pass, RATE) + 14.0)
    settled_error = abs(loudness.integrated_lufs(settled, RATE) + 14.0)
    assert naive_error > 0.1, "the fixture must actually show the gating effect"
    assert settled_error <= 0.1
    assert settled_error < naive_error


def test_material_too_short_to_meter_says_so_rather_than_guessing():
    assert np.isnan(loudness.integrated_lufs(np.zeros(100), RATE))
    out, gain = loudness.normalise(np.zeros(100), RATE, -16.0)
    assert gain == 0.0
    assert out.size == 100
