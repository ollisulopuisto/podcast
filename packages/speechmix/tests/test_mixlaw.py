"""dxReviven Mix-laki: kuiva paino ja liukusäätimen sekoitus yhdestä renderistä.

Painot ovat mitattuja (``apps/autoraffkat/SHARED-AUDIO.md`` §3.11): Studio 2:lla
seitsemän tasoa ja kaksi ikkunaa. Taulukon testi on sidottu niihin lukuihin, ja
muut testit todistavat sekoituksen aritmetiikan ja virheet.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest

from speechmix import mixlaw

#: Mitatut kuivat painot (Mix murtolukuna -> kuiva paino), Studio 2, tasot 10-90 %.
MEASURED = {
    0.10: 0.77,
    0.25: 0.50,
    0.40: 0.30,
    0.50: 0.20,
    0.60: 0.12,
    0.75: 0.04,
    0.90: 0.01,
}


@pytest.mark.parametrize(("m", "dry"), MEASURED.items())
def test_the_law_reproduces_every_measured_weight(m, dry):
    # Suurin virhe sovituksessa oli 0,0095; painot on luettu kahdella desimaalilla.
    assert mixlaw.dry_weight(m) == pytest.approx(dry, abs=0.012)


def test_the_endpoints_are_exact():
    assert mixlaw.dry_weight(0.0) == 1.0
    assert mixlaw.dry_weight(1.0) == 0.0


def test_the_dry_weight_only_falls_as_mix_rises():
    weights = [mixlaw.dry_weight(m) for m in np.linspace(0.0, 1.0, 101)]
    assert all(a >= b for a, b in pairwise(weights))


def test_mix_zero_is_the_raw_and_mix_one_is_the_wet():
    rng = np.random.default_rng(1)
    raw = rng.standard_normal((1, 1000)).astype(np.float32)
    wet = rng.standard_normal((1, 1000)).astype(np.float32)
    assert np.array_equal(mixlaw.mix_blend(raw, wet, 0.0), raw)
    assert np.array_equal(mixlaw.mix_blend(raw, wet, 1.0), wet)


def test_the_blend_is_the_weighted_sum_and_the_weights_add_up_to_one():
    raw = np.ones((2, 100), np.float32)
    wet = np.zeros((2, 100), np.float32)
    out = mixlaw.mix_blend(raw, wet, 0.5)
    assert np.allclose(out, mixlaw.dry_weight(0.5), atol=1e-6)
    # Sama signaali kummassakin: gain-preserving, tulos ei muutu lainkaan.
    same = mixlaw.mix_blend(raw, raw, 0.37)
    assert np.allclose(same, raw, atol=1e-6)


def test_a_late_wet_render_is_aligned_before_it_is_blended():
    rng = np.random.default_rng(2)
    raw = rng.standard_normal((1, 4000)).astype(np.float32)
    late = np.zeros_like(raw)
    late[:, 3:] = raw[:, :-3]  # märkä ajo on 3 näytettä myöhässä
    aligned = mixlaw.mix_blend(raw, late, 0.5, wet_lag=3)
    assert np.allclose(aligned[:, :-3], raw[:, :-3], atol=1e-6)
    unaligned = mixlaw.mix_blend(raw, late, 0.5)
    assert not np.allclose(unaligned[:, :-3], raw[:, :-3], atol=1e-3)


def test_an_early_wet_render_is_aligned_with_a_negative_lag():
    rng = np.random.default_rng(3)
    raw = rng.standard_normal((1, 4000)).astype(np.float32)
    early = np.zeros_like(raw)
    early[:, :-2] = raw[:, 2:]  # märkä ajo on 2 näytettä etuajassa
    aligned = mixlaw.mix_blend(raw, early, 0.5, wet_lag=-2)
    assert np.allclose(aligned[:, 2:], raw[:, 2:], atol=1e-6)


def test_the_inputs_are_not_changed_and_float32_stays_float32():
    raw = np.full((1, 50), 0.25, np.float32)
    wet = np.full((1, 50), -0.5, np.float32)
    raw_before, wet_before = raw.copy(), wet.copy()
    out = mixlaw.mix_blend(raw, wet, 0.3, wet_lag=1)
    assert out.dtype == np.float32
    assert np.array_equal(raw, raw_before) and np.array_equal(wet, wet_before)


@pytest.mark.parametrize("m", [-0.01, 1.01, float("nan")])
def test_a_mix_outside_zero_to_one_is_an_error(m):
    with pytest.raises(ValueError, match="mix"):
        mixlaw.dry_weight(m)
    with pytest.raises(ValueError, match="mix"):
        mixlaw.mix_blend(np.zeros((1, 10), np.float32), np.zeros((1, 10), np.float32), m)


def test_different_shapes_are_an_error_not_a_silent_crop():
    with pytest.raises(ValueError, match="shape"):
        mixlaw.mix_blend(
            np.zeros((1, 10), np.float32), np.zeros((1, 11), np.float32), 0.5
        )
    with pytest.raises(ValueError, match="shape"):
        mixlaw.mix_blend(
            np.zeros((1, 10), np.float32), np.zeros((2, 10), np.float32), 0.5
        )
