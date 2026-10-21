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
    edges = []
    for y in range(height - 1):
        row, below = y * stride, (y + 1) * stride
        for x in range(width - 1):
            value = grey[row + x]
            edges.append(abs(value - grey[row + x + 1]) + abs(value - grey[below + x]))
    if not edges:
        return 0.0
    mean = sum(edges) / len(edges)
    return sum((e - mean) ** 2 for e in edges) / len(edges)


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
