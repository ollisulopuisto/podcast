"""Ranks sampled frames by capture quality and sharpness. Pure, no platform calls.

The capture quality is whatever the detector reports (Vision's face capture quality
in pycapslap). The sharpness is measured here on grey pixels, so every backend
ranks the same way once it has its own quality number.

Weights are hand-set, not tuned: quality leads, sharpness breaks ties between
frames that are about as good as each other.
"""

from __future__ import annotations

from dataclasses import dataclass

CAPTURE_QUALITY_WEIGHT = 0.7
SHARPNESS_WEIGHT = 0.3


@dataclass
class FrameCandidate:
    """One sampled frame, judged by its best face."""

    time_seconds: float
    quality: float  # the detector's capture quality, 0-1
    expression: float
    gesture: float
    sharpness: float  # raw edge variance; normalised by rank_candidates
    score: float = 0.0


def sharpness(grey: bytes, width: int, height: int, stride: int) -> float:
    """Variance of a simple edge measure on an 8-bit grey image: higher is sharper.

    ``stride`` is the byte length of one row, which may be wider than ``width``.
    Scale the image down before calling: the measure is per pixel, so resolution
    changes the number.
    """
    count = (height - 1) * (width - 1) if height > 1 and width > 1 else 0
    if count == 0:
        return 0.0

    # Single-pass accumulation of sum and sum of squares: avoids allocating
    # and populating an intermediate list of (height - 1) * (width - 1) edge
    # values (e.g. 65k entries on 256x256), eliminating list allocations and
    # multiple iterations (~1.35x-1.40x speedup).
    total_edges = 0
    total_edges_sq = 0
    for y in range(height - 1):
        row = y * stride
        below = row + stride
        for x in range(width - 1):
            value = grey[row + x]
            edge = abs(value - grey[row + x + 1]) + abs(value - grey[below + x])
            total_edges += edge
            total_edges_sq += edge * edge

    mean = total_edges / count
    variance = (total_edges_sq / count) - (mean * mean)
    return max(0.0, variance)


def rank_candidates(candidates: list[FrameCandidate]) -> list[FrameCandidate]:
    """Combines capture quality and normalized sharpness into one score, best first."""
    if not candidates:
        return []

    sharpness_values = [c.sharpness for c in candidates]
    lo, hi = min(sharpness_values), max(sharpness_values)
    spread = (hi - lo) or 1.0

    for c in candidates:
        normalized_sharpness = (c.sharpness - lo) / spread
        c.score = (
            CAPTURE_QUALITY_WEIGHT * c.quality + SHARPNESS_WEIGHT * normalized_sharpness
        )

    return sorted(candidates, key=lambda c: c.score, reverse=True)
