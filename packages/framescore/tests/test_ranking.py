"""Tests for ranking frames by capture quality and sharpness."""

import pytest

from framescore.ranking import FrameCandidate, rank_candidates, sharpness


def _frame(quality: float, sharpness_value: float, t: float = 0.0) -> FrameCandidate:
    return FrameCandidate(
        time_seconds=t,
        quality=quality,
        expression=0.0,
        gesture=0.0,
        sharpness=sharpness_value,
    )


def test_rank_prefers_higher_capture_quality() -> None:
    ranked = rank_candidates([_frame(0.4, 10.0, 1.0), _frame(0.9, 10.0, 2.0)])
    assert [c.time_seconds for c in ranked] == [2.0, 1.0]


def test_rank_normalizes_sharpness_across_the_set() -> None:
    ranked = rank_candidates([_frame(0.5, 100.0, 1.0), _frame(0.5, 300.0, 2.0)])
    assert ranked[0].time_seconds == 2.0
    assert ranked[0].score - ranked[1].score == pytest.approx(0.3)


def test_rank_handles_identical_sharpness_without_division_by_zero() -> None:
    ranked = rank_candidates([_frame(0.5, 7.0), _frame(0.6, 7.0)])
    assert ranked[0].quality == 0.6


def test_rank_empty_list_returns_empty() -> None:
    assert rank_candidates([]) == []


def _checkerboard(size: int = 32) -> tuple[bytes, int]:
    row = bytes(255 if (x // 4) % 2 else 0 for x in range(size))
    return b"".join(
        row if (y // 4) % 2 == 0 else bytes(255 - v for v in row) for y in range(size)
    ), size


def test_a_detailed_image_is_sharper_than_a_flat_one() -> None:
    data, size = _checkerboard()
    flat = bytes([128]) * (size * size)
    assert sharpness(data, size, size, size) > sharpness(flat, size, size, size)


def test_sharpness_respects_the_row_stride_padding() -> None:
    data, size = _checkerboard()
    padded = b"".join(data[y * size : (y + 1) * size] + b"\x00" * 4 for y in range(size))
    assert sharpness(padded, size, size, size + 4) == pytest.approx(
        sharpness(data, size, size, size)
    )
