"""Pitkien ohjelmahiljaisuuksien vientikäyrät ja esikatselujaksot."""

from __future__ import annotations

import math

import numpy as np

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


def _curve_values(curve: list, when: np.ndarray) -> np.ndarray:
    """``envelope_at`` jokaiselle ``when``:n arvolle, samat laskutoimitukset.

    Alkiot lasketaan samassa IEEE-järjestyksessä kuin skalaariversiossa
    (vähennys, kerto, jako, plus), joten tulos on bittitarkasti sama —
    vain haku ja silmukka on vektorisoitu. Käyrän ulkopuolella reunan arvo.
    """
    t = np.fromiter((p[0] for p in curve), dtype=np.float64, count=len(curve))
    v = np.fromiter((p[1] for p in curve), dtype=np.float64, count=len(curve))
    out = np.empty(len(when))
    low, high = when <= t[0], when >= t[-1]
    mid = ~(low | high)
    out[low], out[high] = v[0], v[-1]
    if mid.any():
        w = when[mid]
        idx = np.maximum(np.searchsorted(t, w, side="left"), 1)
        t0, v0, t1, v1 = t[idx - 1], v[idx - 1], t[idx], v[idx]
        with np.errstate(divide="ignore", invalid="ignore"):
            vals = v0 + (v1 - v0) * (w - t0) / (t1 - t0)
        out[mid] = np.where(t1 <= t0, v1, vals)
    return out


def merge_envelopes(*layers) -> dict[str, list[tuple[float, float]]]:
    """Combine dB attenuation layers without stacking their depth."""
    names = {name for layer in layers for name in layer}
    merged = {}
    for name in names:
        curves = [layer[name] for layer in layers if layer.get(name)]
        if not curves:
            merged[name] = []
            continue
        times = np.array(
            sorted({float(t) for curve in curves for t, _ in curve}))
        values = np.stack([_curve_values(curve, times) for curve in curves])
        crossings: set = set()
        # Between adjacent source keyframes every curve is linear. Preserve
        # intersections so interpolation of the merged lower envelope stays
        # exact when the stronger attenuation changes from one layer to another.
        left, right = times[:-1], times[1:]
        for a in range(len(curves)):
            for b in range(a + 1, len(curves)):
                delta_start = values[a, :-1] - values[b, :-1]
                delta_end = values[a, 1:] - values[b, 1:]
                flip = delta_start * delta_end < 0
                if flip.any():
                    fraction = (
                        delta_start[flip] / (delta_start[flip] - delta_end[flip]))
                    crossings.update(
                        (left[flip] + (right[flip] - left[flip]) * fraction)
                        .tolist())
        at_all = np.sort(np.concatenate([times, np.fromiter(crossings, float)]))
        lows = np.stack([_curve_values(curve, at_all) for curve in curves]).min(0)
        merged[name] = list(zip(at_all.tolist(), lows.tolist(), strict=True))
    return merged
