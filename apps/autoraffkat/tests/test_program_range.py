"""Ohjelma-alueen rajat pysyvät aikajanakehyksissä."""

from fractions import Fraction

from autoraffkat.program_range import encode_time, resolve_range


def test_encode_time_keeps_rational_frame_times():
    assert encode_time(0.12) == "3/25"


def test_resolve_range_clamps_and_rounds_to_frames():
    start, end = resolve_range("-1/3", "7/3", Fraction(0), Fraction(2), Fraction(1, 25))

    assert start == 0
    assert end == 2


def test_resolve_range_uses_program_bounds_when_marks_are_missing():
    start, end = resolve_range("1/2", None, Fraction(0), Fraction(3), Fraction(1, 25))

    assert start == Fraction(13, 25)
    assert end == 3


def test_resolve_range_rejects_empty_or_reversed_selection():
    start, end = resolve_range("2", "1", Fraction(0), Fraction(3), Fraction(1, 25))

    assert start == 0
    assert end == 3


def test_project_settings_round_trip_program_range():
    from autoraffkat.project import ProjectSettings

    settings = ProjectSettings(range_start="3/25", range_end="101/25")

    restored = ProjectSettings.from_json(settings.to_json())

    assert restored.range_start == "3/25"
    assert restored.range_end == "101/25"
