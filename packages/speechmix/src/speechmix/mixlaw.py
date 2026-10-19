"""dxReviven Mix-laki: liukusäädin yhdestä märästä renderistä.

``chain.apply_plugin`` ajaa liitännäisen koko ikkunaan, ja jokainen ajo maksaa
(neljä 10 sekunnin ikkunaa ~5 s, ``SHARED-AUDIO.md`` §3.11). Jos Mix-säätimen
jokaista asentoa varten pitäisi renderöidä uudelleen, liukusäädin ei liiku.
Mix ei kuitenkaan ole tavallinen ``(1-m)·kuiva + m·märkä``: se on
**gain-preserving ristiinhäivytys jyrkällä kartiolla**. Kuivan polun paino on
``(1 - m)^MIX_EXPONENT`` ja märän ``1 - kuiva``, ja tässä kaavassa yksi
100 %:n render ja raakaääni riittävät mihin tahansa asentoon.

``MIX_EXPONENT`` on sovitettu Studio 2:n seitsemään tasoon (10, 25, 40, 50, 60, 75
ja 90 %): keskivirhe 0,005, suurin 0,0095 (40 %), eli painojen oma
pyöristystarkkuus. Sama laki mitattiin toisessa ikkunassa ja Studio-mallilla
kahdessa pisteessä. Se on yhden puhujan ja kahden ikkunan tulos, ei kalibrointi.

**Satunnaisuus.** dxReviven ulostulo ei toistu: kaksi samanlaista ajoa eroavat
−38 dB (Studio 2) tai −25 dB (Studio). Yhdestä renderistä tehty liukusäädin on
siksi tasaisempi kuin erilliset ajot: kaikki asennot jakavat yhden kohinan
realisaation.

**Ajoitus.** Märkä render voi olla muutaman näytteen verran eri paikassa kuin
raaka (mitatut viiveet 0…−3 näytettä, ``SHARED-AUDIO.md`` §3.11). Epäselvää on,
onko se todellinen vai viivearvion artefakti, ja 25–50 %:n sekoituksessa
virheellinen ajoitus tekisi kampasuotimen. ``wet_lag`` siirtää märän ajon
paikalleen ennen sekoitusta; arvio on kutsujan (``chain.lag_samples``).
"""

from __future__ import annotations

import math

import numpy as np

#: Kuivan painon eksponentti. Sovitus seitsemään mitattuun tasoon, ks. moduulin
#: docstring ja ``SHARED-AUDIO.md`` §3.11.
MIX_EXPONENT = 2.37


def _check_mix(mix: float) -> float:
    mix = float(mix)
    if not math.isfinite(mix) or not 0.0 <= mix <= 1.0:
        raise ValueError(f"mix must be a number from 0 to 1, got {mix!r}")
    return mix


def dry_weight(mix: float) -> float:
    """Kuivan polun paino Mixillä ``mix`` (0–1, eli liitännäisen prosentti / 100).

    Märän polun paino on ``1 - dry_weight(mix)``.
    """
    return (1.0 - _check_mix(mix)) ** MIX_EXPONENT


def _shift_back(audio: np.ndarray, lag: int) -> np.ndarray:
    """Siirtää ``audio``:ta ``lag`` näytettä aikaisemmaksi, pituus säilyy.

    ``lag`` on kuten ``chain.lag_samples``: positiivinen = ``audio`` on myöhässä.
    """
    if lag == 0:
        return audio
    out = np.zeros_like(audio)
    if lag > 0:
        out[..., : audio.shape[-1] - lag] = audio[..., lag:]
    else:
        out[..., -lag:] = audio[..., : audio.shape[-1] + lag]
    return out


def mix_blend(
    raw: np.ndarray, wet: np.ndarray, mix: float, wet_lag: int = 0
) -> np.ndarray:
    """Liitännäisen Mix asennossa ``mix`` raakasta ja 100 %:n renderistä.

    ``raw`` ja ``wet`` ovat samanmuotoisia ``(kanavat, näytteet)`` -taulukoita.
    ``wet`` on liitännäisen ulostulo Mixillä 100 %. ``wet_lag`` on märän ajon
    viive raakaan nähden näytteinä (positiivinen = myöhässä, kuten
    ``chain.lag_samples``), ja se siirretään pois ennen sekoitusta.

    Palauttaa uuden ``float32``-taulukon: kumpaakaan sisääntuloa ei muuteta.
    Mix 0 palauttaa raa'an ja Mix 1 märän täsmälleen (märkä siirrettynä
    ``wet_lag``:n verran).
    """
    weight = dry_weight(mix)
    if raw.shape != wet.shape:
        raise ValueError(
            f"raw and wet must have the same shape, got {raw.shape} and {wet.shape}"
        )
    aligned = _shift_back(wet, int(wet_lag))
    out = weight * raw.astype(np.float64) + (1.0 - weight) * aligned.astype(np.float64)
    return out.astype(np.float32)
