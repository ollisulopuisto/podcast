"""Seeded percentile checks against the established NumPy reference."""

import os
import random

import numpy as np
import pytest

from silencelearn import percentile

SEED = int(os.environ.get("FUZZ_SEED", "20261106"))


@pytest.mark.parametrize("seed", [SEED, SEED + 1, SEED + 2])
def test_percentile_reference_order_and_translation(seed):
    rng = random.Random(seed)
    for case in range(120):
        values = [rng.randrange(-1200, 1) / 10 for _ in range(rng.randrange(1, 80))]
        before = list(values)
        q = rng.choice([0, 10, 25, 50, 75, 90, 95, 100, rng.uniform(0, 100)])
        context = f"seed={seed} case={case} q={q} values={values!r}"
        found = percentile(values, q)
        assert found == pytest.approx(float(np.percentile(values, q))), context
        assert min(values) <= found <= max(values), context
        assert values == before, context
        rng.shuffle(values)
        assert percentile(values, q) == pytest.approx(found), context
        assert percentile([v + 10 for v in values], q) == pytest.approx(found + 10), context


def test_retained_fractional_rank_fixture():
    assert percentile([-100.0, -40.0, -20.0], 25) == -70.0
