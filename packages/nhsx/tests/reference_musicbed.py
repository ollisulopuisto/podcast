"""Frozen scalar oracle from musicbed.py before PR #234 (a622577).

Keep the original branch and floating-point operation order for exact parity.
"""

from itertools import pairwise

from nhsx.musicbed import (
    COLD_OPEN_UNDER_DB,
    COLD_RISE,
    DROP,
    DROP_LEAD_S,
    END_MARGIN_S,
    FALL,
    MIN_FALL_S,
    ONSET_MARGIN_S,
    PLATEAU_AFTER_S,
    PLATEAU_MIN_S,
    RISE,
    SILENCE_DB,
    STEP_S,
    TAIL_S,
    TAIL_UNDER_DB,
    _gap,
)


def _interp(shape, t: float, scale: float = 1.0) -> float:
    """Muodon arvo hetkellä ``t``; ``scale`` venyttää aikaa."""
    pts = [(a * scale, b) for a, b in shape]
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, d0), (t1, d1) in pairwise(pts):
        if t <= t1:
            return d0 + (d1 - d0) * (t - t0) / (t1 - t0)
    return pts[-1][1]


def curve(start: float, end: float, speech, cold_open: bool = False):
    """Pohjan käyrä ``[(s alueen alusta, dB tasanteeseen nähden), ...]``.

    ``speech`` on aikajanan puhevälit (``activity.speech_intervals``).
    ``cold_open``: pohja soi puheen alla ennen nousuaan (intro). Muuten se
    nousee hiljaisuudesta.

    ``None``, jos pohjan alueella ei ole yhtään ``MIN_GAP_S``:n taukoa: sille
    ei ole mitattua sääntöä, eikä arvaus ole parempi kuin ei mitään.
    """
    gap = _gap(start, end, speech)
    if gap is None:
        return None
    last_word, next_word = gap
    plateau = last_word + PLATEAU_AFTER_S
    rise = COLD_RISE if cold_open else RISE
    rise_from = plateau - rise[-1][0]

    limit = end - END_MARGIN_S
    tail = (
        next_word is not None and limit - next_word >= DROP[-1][0] + TAIL_S + FALL[-1][0]
    )
    if tail:
        drop_from = next_word - DROP_LEAD_S
        fall_from = drop_from + DROP[-1][0] + TAIL_S
        fall_scale = 1.0
        floor = TAIL_UNDER_DB
    else:
        drop_from = None
        fall_end = limit if next_word is None else min(limit, next_word - ONSET_MARGIN_S)
        fall_from = max(fall_end - FALL[-1][0], plateau + PLATEAU_MIN_S)
        fall_from = min(fall_from, fall_end - MIN_FALL_S)
        fall_scale = (fall_end - fall_from) / FALL[-1][0]
        floor = 0.0

    def level(t: float) -> float:
        if t < plateau:
            if t >= rise_from:
                return _interp(rise, t - rise_from)
            return COLD_OPEN_UNDER_DB if cold_open else SILENCE_DB
        if drop_from is not None and t >= drop_from and t < fall_from:
            return _interp(DROP, t - drop_from)
        if t >= fall_from:
            fallen = floor + _interp(FALL, t - fall_from, fall_scale)
            past = t - fall_from > FALL[-1][0] * fall_scale
            return SILENCE_DB if past else fallen
        return 0.0

    count = int((end - start) / STEP_S) + 1
    return [(i * STEP_S, round(level(start + i * STEP_S), 2)) for i in range(count)]
