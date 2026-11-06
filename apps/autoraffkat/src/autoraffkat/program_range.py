"""Tallenna ohjelma-alueen ajat tarkasti ja sovita ne kuvakehyksiin."""

from __future__ import annotations

import math
from fractions import Fraction


def encode_time(value: float | int | str | Fraction | None) -> str | None:
    """Muuntaa kelvollisen sekuntiluvun vakaaksi murtolukumerkkijonoksi."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("A program mark must be a time in seconds.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("A program mark must be finite.")
    fraction = Fraction(str(value)).limit_denominator(1_000_000)
    if fraction < 0:
        raise ValueError("A program mark cannot be negative.")
    return f"{fraction.numerator}/{fraction.denominator}"


def resolve_range(
    start: str | None,
    end: str | None,
    lower: Fraction,
    upper: Fraction,
    frame_duration: Fraction,
) -> tuple[Fraction, Fraction]:
    """Palauttaa ohjelma-alueen rajat, rajattuina ja lähimpään kehykseen pyöristettyinä."""
    if upper <= lower or frame_duration <= 0:
        return lower, upper
    total_frames = max(1, int(round((upper - lower) / frame_duration)))
    try:
        requested_start = Fraction(start) if start else lower
        requested_end = Fraction(end) if end else upper
    except (ValueError, ZeroDivisionError):
        return lower, upper
    if requested_end <= requested_start:
        return lower, upper
    first = int((requested_start - lower) / frame_duration + Fraction(1, 2))
    last = int((requested_end - lower) / frame_duration + Fraction(1, 2))
    first = max(0, min(total_frames - 1, first))
    last = max(first + 1, min(total_frames, last))
    if last <= first:
        return lower, upper
    return (
        lower + first * frame_duration,
        lower + last * frame_duration,
    )
