"""Jaettu puheketju, ja sen sauma automixerin mlx-maailmaan.

Vaiheet **tuodaan** `speechmix.chain`ista, niitä ei kirjoiteta tänne.
`apps/automixer/tests/test_shared_chain.py` väittää `is`-vertailulla että
nämä nimet ovat kirjaston omia olioita: uudelleen kopioitu funktio, joka
sattuu olemaan identtinen, kaatuu silti. Kopio ei kaadu koskaan — se alkaa
vain hiljaa erota, ja juuri niin automixer oli neljä mitattua korjausta
jäljessä kun se sulautettiin tähän repositorioon.

## Miksi tässä on muunnos

Kirjasto ottaa ja palauttaa numpy-taulukoita muodossa ``(kanavat, näytteet)``
— se ei tunne mlx:ää eikä saa tuntea, koska autoraffkat ja podcast-magic
ajavat samat vaiheet ilman sitä. automixer taas pitää signaalin
`mx.array`ina muodossa ``(näytteet,)`` tai ``(näytteet, kanavat)``. Muunnos
on tässä tiedostossa, kerran, eikä jokaisessa vaiheessa erikseen.

## Mitä se maksaa

Kirjaston vaiheet ovat numpyä ja scipyä, eli suoritinta; automixerin omat
olivat mlx:ää, eli näytönohjainta. Mitattuna kahdella 20 s:n puheraidalla
tässä kontissa (suoritin, ei Apple Siliconia): **0,6 s ennen, 2,0 s jälkeen**
eli 3,3-kertainen. Apple Siliconilla vanha polku on vielä nopeampi, joten
siellä suhde on todennäköisesti tätä huonompi.

Vastineeksi: naksunpoisto joka laukeaa (ennen 0 muutettua näytettä),
katto joka pitää siellä missä sanoo (ennen −0,36 dBTP omaa −1,0:aa vastaan)
ja sävy joka ei liiku ohjelman mukana (ennen 10,72 dB). Luvut ja koko
vertailu ovat `SPEECHMIX-INVENTORY.md`:n kohdassa 6.
"""

from __future__ import annotations

import mlx.core as mx
import numpy as np

# Vaiheet sellaisenaan. Älä kääri, älä nimeä uudelleen: testi vertaa
# `is`-operaattorilla, ja kääre olisi jo eri olio.
from speechmix.chain import (
    CEILING_DB,
    DEESS_HZ,
    DEESS_RATIO,
    DEESS_THRESHOLD_DB,
    HIGH_PASS_HZ,
    LEVEL_ATTACK_MS,
    LEVEL_RATIO,
    LEVEL_RELEASE_MS,
    LEVELER_THRESHOLD_DB,
    MAX_GR_DB,
    PEAK_ATTACK_MS,
    PEAK_RATIO,
    PEAK_RELEASE_MS,
    PEAK_THRESHOLD_DB,
    THRESHOLD_REFERENCE_LUFS,
    compress,
    declick,
    deess,
    limiter,
    limiter_gain,
    multiband,
    peak_guard,
    process,
)

__all__ = [
    "CEILING_DB",
    "DEESS_HZ",
    "DEESS_RATIO",
    "DEESS_THRESHOLD_DB",
    "HIGH_PASS_HZ",
    "LEVELER_THRESHOLD_DB",
    "LEVEL_ATTACK_MS",
    "LEVEL_RATIO",
    "LEVEL_RELEASE_MS",
    "MAX_GR_DB",
    "PEAK_ATTACK_MS",
    "PEAK_RATIO",
    "PEAK_RELEASE_MS",
    "PEAK_THRESHOLD_DB",
    "THRESHOLD_REFERENCE_LUFS",
    "as_channels",
    "compress",
    "declick",
    "deess",
    "from_channels",
    "limiter",
    "limiter_gain",
    "multiband",
    "peak_guard",
    "process",
]


def as_channels(signal: mx.array) -> np.ndarray:
    """`mx.array` → numpy ``(kanavat, näytteet)``, mitä kirjasto odottaa.

    automixerin monoraita on ``(näytteet,)`` ja väylä ``(näytteet, 2)``.
    Kirjasto haluaa kanavat ensin, koska sen huippu- ja tasomittaukset
    kulkevat aikaa pitkin ja ``axis=-1`` on silloin oikea akseli kaikkialla.

    Muunnos ajetaan **kutsujan säikeellä** — `np.array(mx_array)` pakottaa
    mlx-taulukon arvon, ja mlx:n oletusvirta on säiekohtainen. Ks.
    `tests/test_mlx_threads.py`.
    """
    plain = np.asarray(np.array(signal), dtype=np.float64)
    if plain.ndim == 1:
        return plain[None, :]
    return plain.T


def from_channels(array: np.ndarray, like: mx.array) -> mx.array:
    """numpy ``(kanavat, näytteet)`` → `mx.array` samassa muodossa kuin ``like``.

    Muoto luetaan alkuperäisestä eikä pääteltäisi kanavamäärästä: yhden
    kanavan väylä on eri asia kuin monoraita, ja väärin päin palautettu
    taulukko ei kaadu vaan miksautuu väärin.
    """
    out = np.asarray(array, dtype=np.float32)
    if np.asarray(np.array(like)).ndim == 1:
        return mx.array(out[0])
    return mx.array(out.T)
