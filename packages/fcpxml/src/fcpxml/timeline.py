"""FCPXML rational time.

Final Cut writes every time as a fraction of a second: ``"1001/30000s"``,
``"5s"``, ``"0s"``. Floats are not enough: the rounding error adds up over
thousands of frames and leaves gaps on the timeline. Everything read from XML
and written to XML goes through this module as a ``Fraction``; only an
analysis layer may use seconds as floats.
"""

from __future__ import annotations

from fractions import Fraction

ZERO = Fraction(0)

# Final Cut's named formats by frame rate.
FPS_LABELS = {
    Fraction(24000, 1001): "2398",
    Fraction(24, 1): "24",
    Fraction(25, 1): "25",
    Fraction(30000, 1001): "2997",
    Fraction(30, 1): "30",
    Fraction(50, 1): "50",
    Fraction(60000, 1001): "5994",
    Fraction(60, 1): "60",
    Fraction(120, 1): "120",
}


def parse_time(value: str | None, default: Fraction = ZERO) -> Fraction:
    """Reads an FCPXML time as a Fraction. ``None`` and empty give the default."""
    if value is None:
        return default
    text = value.strip()
    if not text:
        return default
    if text.endswith("s"):
        text = text[:-1]
    if not text:
        return default
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    if "/" in text:
        num, _, den = text.partition("/")
        result = Fraction(int(num), int(den))
    else:
        result = Fraction(int(text))
    return -result if negative else result


def format_time(value: Fraction) -> str:
    """Writes a Fraction as an FCPXML time."""
    value = Fraction(value)
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def to_frames(seconds: Fraction | float, frame_duration: Fraction) -> int:
    """Quantises a time to the nearest frame."""
    if not isinstance(seconds, Fraction):
        seconds = Fraction(seconds).limit_denominator(1_000_000)
    exact = seconds / frame_duration
    # Halves round up on the Fraction, so the result does not depend on the
    # banker's rounding of floats.
    floor = exact.numerator // exact.denominator
    remainder = exact - floor
    return floor + (1 if remainder >= Fraction(1, 2) else 0)


def frames_to_time(frames: int, frame_duration: Fraction) -> Fraction:
    """A number of frames as a time."""
    return frame_duration * frames


def frames_str(frames: int, frame_duration: Fraction) -> str:
    """A number of frames straight to an FCPXML time. Always frame-exact."""
    return format_time(frames_to_time(frames, frame_duration))


def fps_of(frame_duration: Fraction) -> Fraction:
    """The frame rate of a frame duration."""
    return 1 / frame_duration


def format_name(width: int, height: int, frame_duration: Fraction) -> str:  # noqa: ARG001
    """Final Cut's format name, e.g. ``FFVideoFormat1080p25``.

    ``width`` is a parameter for the callers' sake and because the name names
    the pair (width, height); Final Cut's own naming uses the height only.
    """
    label = FPS_LABELS.get(fps_of(frame_duration))
    if label is None:
        return "FFVideoFormatRateUndefined"
    return f"FFVideoFormat{height}p{label}"


def parse_fps(text: str) -> Fraction:
    """Reads a frame rate as a user or ffprobe states it."""
    text = str(text).strip()
    named = {
        "23.976": Fraction(24000, 1001),
        "29.97": Fraction(30000, 1001),
        "59.94": Fraction(60000, 1001),
        "119.88": Fraction(120000, 1001),
    }
    if text in named:
        return named[text]
    if "/" in text:
        num, _, den = text.partition("/")
        return Fraction(int(num), int(den))
    return Fraction(text).limit_denominator(1000)
