"""Pitkien ohjelmahiljaisuuksien vientikäyrät ja esikatselujaksot."""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np

from speechmix.envelopes import envelope_at
from speechmix.masks import HOP, runs


def dead_air_spans(grid, minimum: float = 2.0) -> list[tuple[float, float]]:
    """Sisäiset jaksot, joissa yksikään puhuja ei ole äänessä.

    Ohjelman alku ja loppu jätetään pois: niiden häivytyksistä vastaa
    ``program_fades``. Palautetut ajat ovat aikajanan sekunteja.
    """
    speakers = getattr(grid, "speakers", ())
    n = int(getattr(grid, "n", 0))
    if n <= 0 or not speakers:
        return []

    talking = np.zeros(n, dtype=bool)
    for speaker in speakers:
        lane = np.asarray(speaker.on, dtype=bool)
        talking[:min(n, lane.size)] |= lane[:n]

    min_hops = max(1, math.ceil(max(0.0, float(minimum)) / HOP))
    start = float(grid.program_start)
    return [
        (start + lo * HOP, start + hi * HOP)
        for lo, hi, is_talking in runs((~talking).astype(np.int8))
        if is_talking and lo > 0 and hi < n and hi - lo >= min_hops
    ]


def silence_envelopes(grid, settings) -> dict[str, list[tuple[float, float]]]:
    """Puhujamikeille kirjoitettavat dB-käyrät jaetuissa hiljaisuuksissa."""
    depth = float(settings.silence_db)
    if not settings.silence_pass or depth >= 0:
        return {}

    fade = max(0.0, float(settings.silence_fade))
    spans = dead_air_spans(grid, settings.silence_min_gap)
    if not spans:
        return {}

    points: list[tuple[float, float]] = []
    for start, end in spans:
        ramp = min(fade, (end - start) / 2.0)
        candidates = [
            (start, 0.0),
            (start + ramp, depth),
            (end - ramp, depth),
            (end, 0.0),
        ]
        # Rajatapauksessa puoli- ja loppupiste osuvat samaan aikaan.
        for point in candidates:
            if points and point[0] == points[-1][0]:
                points[-1] = (point[0], min(points[-1][1], point[1]))
            else:
                points.append(point)

    return {speaker.name: list(points) for speaker in grid.speakers}


def merge_envelopes(*layers) -> dict[str, list[tuple[float, float]]]:
    """Combine dB attenuation layers without stacking their depth."""
    names = {name for layer in layers for name in layer}
    merged = {}
    for name in names:
        curves = [layer[name] for layer in layers if layer.get(name)]
        times = sorted({float(t) for curve in curves for t, _ in curve})
        crossings = set()
        # Between adjacent source keyframes every curve is linear. Preserve
        # intersections so interpolation of the merged lower envelope stays
        # exact when the stronger attenuation changes from one layer to another.
        for left, right in pairwise(times):
            values = [
                (float(envelope_at(curve, left)), float(envelope_at(curve, right)))
                for curve in curves
            ]
            for index, (start_a, end_a) in enumerate(values):
                for start_b, end_b in values[index + 1:]:
                    delta_start, delta_end = start_a - start_b, end_a - end_b
                    if delta_start * delta_end < 0:
                        fraction = delta_start / (delta_start - delta_end)
                        crossings.add(left + (right - left) * fraction)
        times = sorted((*times, *crossings))
        merged[name] = [
            (at, min(float(envelope_at(curve, at)) for curve in curves))
            for at in times
        ]
    return merged
