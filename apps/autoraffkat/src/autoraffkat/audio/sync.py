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
    if len(ref) == 0 or len(src) == 0:
        # Tyhjällä verholla ei ole yhteistä ääntä eikä arvioitavaa. Tämä
        # täytyy erottaa ennen FFT:tä: pituus-1 menee negatiiviseksi ja
        # viiverajat sekä ristikorrelaation indeksit lasketaan siitä.
        return None
    corr_size = len(ref) + len(src) - 1
    fft_size = 1 << (corr_size - 1).bit_length()
    cross = np.fft.irfft(
        np.fft.rfft(ref, fft_size) * np.conjugate(np.fft.rfft(src, fft_size)),
        fft_size,
    )

    ref_sum = np.concatenate(([0.0], np.cumsum(ref)))
    ref_sq_sum = np.concatenate(([0.0], np.cumsum(ref * ref)))
    src_sum = np.concatenate(([0.0], np.cumsum(src)))
    src_sq_sum = np.concatenate(([0.0], np.cumsum(src * src)))

    # Kaikkien etsintäalueen viiveiden pisteytys kerralla. Silmukka teki
    # saman laskennan yksi viive kerrallaan Pythonissa; vektoroitu versio on
    # numeerisesti identtinen mutta tekee koko aineiston (tunteja) haun
    # millisekunteja hitaamman ±5 min ikkunan sijaan sekunneissa.
    lo = -min(max_lag, len(src) - 1)
    hi = min(max_lag, len(ref) - 1)
    lags = np.arange(lo, hi + 1)
    if lags.size == 0:
        return None

    src_start = np.maximum(0, -lags)
    ref_start = np.maximum(0, lags)
    count = np.minimum(len(src) - src_start, len(ref) - ref_start)
    src_end = src_start + count
    ref_end = ref_start + count

    sx = src_sum[src_end] - src_sum[src_start]
    sy = ref_sum[ref_end] - ref_sum[ref_start]
    sxx = src_sq_sum[src_end] - src_sq_sum[src_start]
    syy = ref_sq_sum[ref_end] - ref_sq_sum[ref_start]
    dot = cross[np.where(lags >= 0, lags, fft_size + lags)]

    covariance = dot - sx * sy / count
    variance_src = sxx - sx * sx / count
    variance_ref = syy - sy * sy / count
    denominator = np.sqrt(np.maximum(variance_src, 0.0) * np.maximum(variance_ref, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = np.clip(covariance / denominator, -1.0, 1.0)

    # Kelvottomat viiveet (liian vähän päällekkäisyyttä tai vakiovariaanssi)
    # eivät osallistu maksimiin. Tasatilanteessa ensimmäinen voittaa, kuten
    # silmukassakin (silmukka piti ensimmäisen, argmax palauttaa sen).
    correlation[(count < min_overlap) | (denominator <= 1e-12)] = -np.inf
    best = int(np.argmax(correlation))
    if not math.isfinite(float(correlation[best])):
        return None
    return OffsetEstimate(int(lags[best]) * hop_seconds, float(correlation[best]))
