"""``stems_mix.stereo_layout``: how the stems sound in the output, for the meter.

It runs once per 60 s piece in every mastering pass (3-4 passes) and for the
bed level, so it is a hot path. These tests hold its result fixed, bit for
bit, against the straightforward version it replaced.
"""

from __future__ import annotations

import numpy as np
import pytest

from automixer import stems_mix
from speechmix import stems


def _reference(members, blocks):
    """The first version: every mono stem is stacked into a pair."""
    n = np.atleast_2d(blocks[0]).shape[-1]
    out = np.zeros((2, n), dtype=np.float64)
    for job, block in zip(members, blocks, strict=True):
        block = np.atleast_2d(block)
        if job.get("stereo") and block.shape[0] == 2:
            pair = block
        else:
            mono = block.mean(axis=0)
            pair = np.stack([mono, mono])
        left, right = stems.pan_gains(job.get("pan", 0.0), job.get("pan_law", "balance"))
        out[0] += pair[0] * left
        out[1] += pair[1] * right
    return out


def _pieces(dtype=np.float32, n=48000 * 3 + 17):
    rng = np.random.default_rng(11)
    jobs = [
        {"pan": 0.0, "pan_law": "power"},
        {"pan": -35.0},
        {"pan": 60.0, "pan_law": "power"},
        {"stereo": True, "pan": 0.0},
        {"pan": 10.0},  # two channels but not marked stereo: folded to mono
    ]
    blocks = [
        rng.normal(0, 0.1, n).astype(dtype),
        rng.normal(0, 0.1, (1, n)).astype(dtype),
        rng.normal(0, 0.1, n).astype(dtype),
        rng.normal(0, 0.1, (2, n)).astype(dtype),
        rng.normal(0, 0.1, (2, n)).astype(dtype),
    ]
    return jobs, blocks


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("take", [[0], [1, 2], [3], [4], [0, 1, 2, 3, 4]])
def test_the_layout_is_the_reference_bit_for_bit(dtype, take):
    jobs, blocks = _pieces(dtype)
    jobs, blocks = [jobs[i] for i in take], [blocks[i] for i in take]
    got = stems_mix.stereo_layout(jobs, blocks)
    want = _reference(jobs, blocks)
    assert got.dtype == want.dtype and got.shape == want.shape
    assert np.array_equal(got, want)


def test_a_mono_stem_is_not_copied_into_a_pair(monkeypatch):
    """The pair was two more full-length arrays per stem per piece for nothing:
    each channel is the mono stem times its own gain."""

    def stacked(*args, **kwargs):
        raise AssertionError("np.stack: the mono stem was copied into a pair")

    monkeypatch.setattr(np, "stack", stacked)
    jobs, blocks = _pieces()
    stems_mix.stereo_layout(jobs[:3], blocks[:3])
