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


def test_sharpness_degenerate_dimensions() -> None:
    # 0x0, 1x1, 1x10, 10x1 images have no (height-1)*(width-1) pairs to compare
    assert sharpness(b"", 0, 0, 0) == 0.0
    assert sharpness(b"\x00", 1, 1, 1) == 0.0
    assert sharpness(bytes(10), 1, 10, 1) == 0.0
    assert sharpness(bytes(10), 10, 1, 10) == 0.0


def test_sharpness_non_square_and_exact_variance() -> None:
    # 3x2 image (width=3, height=2, stride=4 with 1 byte padding per row)
    # y=0: [10, 20, 30, padding]
    # y=1: [40, 50, 60, padding]
    # pairs for (x, y):
    # (0, 0): val=10, right=20, below=40 -> abs(10-20) + abs(10-40) = 10 + 30 = 40
    # (1, 0): val=20, right=30, below=50 -> abs(20-30) + abs(20-50) = 10 + 30 = 40
    # Both edges are 40 -> mean = 40, variance = 0.0
    data = bytes([10, 20, 30, 0, 40, 50, 60, 0])
    assert sharpness(data, 3, 2, 4) == 0.0

    # Modify (1,0) to have variance:
    # y=0: [10, 20, 30, 0]
    # y=1: [40, 70, 60, 0]
    # (0,0): abs(10-20) + abs(10-40) = 40
    # (1,0): abs(20-30) + abs(20-70) = 10 + 50 = 60
    # edges = [40, 60], mean = 50, variance = ((40-50)^2 + (60-50)^2)/2 = (100 + 100)/2 = 100.0
    data2 = bytes([10, 20, 30, 0, 40, 70, 60, 0])
    assert sharpness(data2, 3, 2, 4) == pytest.approx(100.0)


def test_sharpness_single_pass_no_list_allocation() -> None:
    """Verify that sharpness does not allocate intermediate lists for edge values."""
    import gc
    import tracemalloc

    data, size = _checkerboard(128)
    gc.collect()
    tracemalloc.start()
    sharpness(data, size, size, size)
    _curr, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # In the old code, a list of ~16,000 edge ints was allocated (peak ~167 KB).
    # In single-pass accumulation, peak memory is < 10 KB.
    assert peak < 30_000, f"Expected peak < 30KB, got {peak} bytes"
