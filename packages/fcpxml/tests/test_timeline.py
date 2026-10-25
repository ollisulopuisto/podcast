"""FCPXML times are rational: `1001/30000s`, `5s`, `0s`.

Floats do not do. The rounding error adds up over thousands of frames and
leaves gaps on the timeline, so every time that is read from or written to XML
is a `Fraction`.
"""

from fractions import Fraction

import pytest
from fcpxml import timeline as t


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1001/30000s", Fraction(1001, 30000)),
        ("5s", Fraction(5)),
        ("0s", Fraction(0)),
        ("-1001/30000s", Fraction(-1001, 30000)),
        ("", Fraction(0)),
        (None, Fraction(0)),
    ],
)
def test_parse_time(text, expected):
    assert t.parse_time(text) == expected


def test_format_round_trip():
    for value in ("1001/30000s", "5s", "0s", "3603601/30000s"):
        assert t.format_time(t.parse_time(value)) == value


def test_quantize_is_exact_over_many_frames():
    """With floats this would add up to an error; with a Fraction it does not."""
    fd = Fraction(1001, 30000)
    for frames in (1, 7, 1234, 216_000):
        assert t.to_frames(fd * frames, fd) == frames


def test_half_rounds_up():
    fd = Fraction(1, 25)
    assert t.to_frames(Fraction(1, 50), fd) == 1


def test_format_name():
    assert t.format_name(1920, 1080, Fraction(1, 25)) == "FFVideoFormat1080p25"
    assert t.format_name(1920, 1080, Fraction(1001, 30000)) == "FFVideoFormat1080p2997"


@pytest.mark.parametrize("duration", ["1/5644800s", "100/2500s", "1001/30000s"])
def test_the_rates_of_real_exports_survive_a_round_trip(duration):
    """`vertical2.fcpxmld` has times in 1001/30000, 100/2500 and /5644800."""
    assert t.format_time(t.parse_time(duration)) == duration.replace("100/2500s", "1/25s")
