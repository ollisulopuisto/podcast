"""Kohdista mikin ääniverho kameran vertailuääneen."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OffsetEstimate:
    """Mikin aikajanalle siirtoon ja huipun arviointiin."""

    shift_seconds: float
    correlation: float


def estimate_offset(
    reference: np.ndarray,
    source: np.ndarray,
    *,
    hop_seconds: float,
    max_shift_seconds: float,
    min_overlap_seconds: float,
) -> OffsetEstimate | None:
    """Arvioi siirron, joka lisätään lähderaidan aikajanaan.

    Verhot ovat tasavälisiä energiakäyriä, eivät ääniaaltoja. Positiivinen
    siirto siirtää lähdettä myöhemmäksi. `None` tarkoittaa, ettei etsinnän
    alueella ollut riittävästi vaihtelevaa yhteistä signaalia.
    """
    ref = np.asarray(reference, dtype=np.float64)
    src = np.asarray(source, dtype=np.float64)
    if ref.ndim != 1 or src.ndim != 1:
        raise ValueError("Ääniverhojen pitää olla yksiulotteisia")
    if not np.all(np.isfinite(ref)) or not np.all(np.isfinite(src)):
        raise ValueError("Ääniverhoissa ei saa olla äärettömiä arvoja")
    if not math.isfinite(hop_seconds) or hop_seconds <= 0:
        raise ValueError("hop_seconds pitää olla äärellinen ja positiivinen")
    if not math.isfinite(max_shift_seconds) or max_shift_seconds < 0:
        raise ValueError("max_shift_seconds ei saa olla negatiivinen")
    if not math.isfinite(min_overlap_seconds) or min_overlap_seconds <= 0:
        raise ValueError("min_overlap_seconds pitää olla positiivinen")

    max_lag = int(max_shift_seconds / hop_seconds)
    min_overlap = math.ceil(min_overlap_seconds / hop_seconds)
    corr_size = len(ref) + len(src) - 1
    if corr_size <= 0:
        return None
    fft_size = 1 << (corr_size - 1).bit_length()
    cross = np.fft.irfft(
        np.fft.rfft(ref, fft_size) * np.conjugate(np.fft.rfft(src, fft_size)),
        fft_size,
    )

    ref_sum = np.concatenate(([0.0], np.cumsum(ref)))
    ref_sq_sum = np.concatenate(([0.0], np.cumsum(ref * ref)))
    src_sum = np.concatenate(([0.0], np.cumsum(src)))
    src_sq_sum = np.concatenate(([0.0], np.cumsum(src * src)))
    best: tuple[float, int] | None = None

    for lag in range(-min(max_lag, len(src) - 1), min(max_lag, len(ref) - 1) + 1):
        src_start = max(0, -lag)
        ref_start = max(0, lag)
        count = min(len(src) - src_start, len(ref) - ref_start)
        if count < min_overlap:
            continue

        src_end = src_start + count
        ref_end = ref_start + count
        sx = src_sum[src_end] - src_sum[src_start]
        sy = ref_sum[ref_end] - ref_sum[ref_start]
        sxx = src_sq_sum[src_end] - src_sq_sum[src_start]
        syy = ref_sq_sum[ref_end] - ref_sq_sum[ref_start]
        dot = cross[lag if lag >= 0 else fft_size + lag]
        covariance = dot - sx * sy / count
        variance_src = sxx - sx * sx / count
        variance_ref = syy - sy * sy / count
        denominator = math.sqrt(max(variance_src, 0.0) * max(variance_ref, 0.0))
        if denominator <= 1e-12:
            continue
        correlation = float(np.clip(covariance / denominator, -1.0, 1.0))
        if best is None or correlation > best[0]:
            best = (correlation, lag)

    if best is None:
        return None
    correlation, lag = best
    return OffsetEstimate(lag * hop_seconds, correlation)
