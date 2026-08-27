"""Vaimennus **päätöksinä**, ei näytteinä.

``duck_envelopes`` palauttaa ``{puhuja: [(aika, dB), …]}``. autoraffkat
kirjoittaa ne Final Cutin ``<adjust-volume>``-keyframeiksi, jolloin leikkaaja
voi yhä muuttaa niitä; isäntä jolla ei ole mitään mihin automaatio
kirjoitetaan polttaa saman käyrän näytteisiin. Sama laskenta, eri emissio.

    Tasopäätökset jotka tulevat ketjun **jälkeen** voivat olla automaatiota.
    Tasopäätökset jotka tulevat sitä **ennen** on poltettava sisään.

``closed_ranges`` ja ``speech_blocks`` muuntavat ruudukon aikajanalta
tiedostoaikaan. Ne tarvitsevat esiintymät — mikä tahansa olio jolla on
``placements`` ja ``asset_start`` kelpaa — koska muunnos on esiintymän sisällä
lineaarinen, ja se on ainoa aikajanatieto jota ketju tarvitsee.

Siirretty autoraffkatin ``audio/mix.py``:stä, ei kopioitu.
"""

import numpy as np

from .masks import HOP, duck_masks, runs


def duck_envelopes(grid, settings: object,
                   program_start: float) -> dict[str, list]:
    """Vaimennus käyränä, aikajanan aikaa: ``puhuja -> [(t, dB), …]``.

    Vaimennus ei kuulu tiedostoihin. Se on tasopäätös siinä missä
    panorointikin, ja poltettuna se on ainoa asia koko ketjussa jota
    leikkaaja ei voi enää muuttaa katsomatta: liian syvä vaimennus vaatii
    minuuttien ajon, kun se käyränä on yhden liu'un veto. Sama peruste kuin
    reaktiokuvien omalla lanella.

    Muoto vastaa ``chain.apply_duck``ia piste pisteeltä, koska tulos ei saa
    muuttua sen mukaan kummalla tavalla se tehdään: liu'ut ovat **jakson
    sisällä** — lasku alkaa jakson alusta, nousu päättyy sen loppuun — ja
    epäsymmetriset, koska lasku osuu toisen puhujan aloitukseen ja jää sen
    alle, kun taas nousu osuu hiljaisuuteen jossa mikään ei peitä sitä.
    Liuku on desibeleissä, ja niin on Final Cutin keyframe-parametrikin.

    Pelkkää laskentaa ruudukon päällä: ei tiedostoja, joten tämä saa olla
    myös esikatselussa.
    """
    depth = float(settings.duck_db)
    if not settings.duck or depth >= 0:
        return {}
    fade = float(settings.duck_fade)
    release = float(settings.duck_release or settings.duck_fade)
    out: dict[str, list] = {}
    for name, mask in duck_masks(grid, settings).items():
        points: list[tuple[float, float]] = []
        for start, end, value in runs(np.asarray(mask).astype(np.int8)):
            if not value:
                continue
            t0 = program_start + start * HOP
            t1 = program_start + end * HOP
            span = t1 - t0
            head = min(fade, span / 2.0)
            tail = min(release, span - head)
            points.append((t0, 0.0))
            points.append((t0 + head, depth))
            points.append((t1 - tail, depth))
            points.append((t1, 0.0))
        if points:
            out[name] = points
    return out

def envelope_at(points: list, when: float) -> float:
    """Käyrän arvo hetkellä ``when``, desibeleinä. Väleissä lineaarinen.

    Käyrän ulkopuolella nolla: vaimennus on paikallinen tapahtuma, ei tila.
    """
    if not points:
        return 0.0
    if when <= points[0][0] or when >= points[-1][0]:
        return 0.0
    times = [t for t, _ in points]
    index = np.searchsorted(times, when)
    if index <= 0:
        return float(points[0][1])
    t0, v0 = points[index - 1]
    t1, v1 = points[min(index, len(points) - 1)]
    if t1 <= t0:
        return float(v1)
    return float(v0 + (v1 - v0) * (when - t0) / (t1 - t0))

def closed_ranges(
    item, closed, program_start: float, rate: int
) -> list[tuple[int, int]]:
    """Missä tiedoston kohdissa mikki on kiinni, näyteväleinä.

    Ruudukko on aikajanan aikaa, tiedosto omaansa. Muunnos tehdään
    esiintymittäin, koska kunkin palan sisällä kuvaus on lineaarinen.
    Ruudukon ulkopuolelle jäävää osaa ei vaimenneta: siitä ei ole tietoa, eikä
    vienti käytä sitä.
    """
    out: list[tuple[int, int]] = []
    for start, end, value in runs(closed.astype(np.int8)):
        if not value:
            continue
        low = program_start + start * HOP
        high = program_start + end * HOP
        for placement in item.placements:
            first = max(low, float(placement.offset))
            last = min(high, float(placement.end))
            if last <= first:
                continue
            # tiedostoaika = klipin start - assetin start + (aikajana - offset)
            base = float(placement.start - item.asset_start - placement.offset)
            out.append(
                (int(round((base + first) * rate)), int(round((base + last) * rate)))
            )
    return out

def speech_blocks(item, mask, program_start: float, rate: int,
                  block: int, count: int) -> np.ndarray:
    """Puhujan oma puhe lohkoittain tässä tiedostossa.

    Ruudukko on aikajanan aikaa, tiedosto omaansa; muunnos on
    esiintymittäin lineaarinen, sama kaava kuin ``closed_ranges``issa.
    Tasonkuljettaja tarvitsee juuri tämän eikä signaalista pääteltyä
    puhetta — ks. ``chain.rider_gain``.
    """
    out = np.zeros(count, dtype=bool)
    mask = np.asarray(mask, dtype=bool)
    for placement in item.placements:
        base = float(placement.start - item.asset_start - placement.offset)
        # Lohkon keskikohta tiedostoajassa -> aikajana -> ruudukon solu.
        times = (np.arange(count) + 0.5) * block / rate
        timeline = times - base
        inside = ((timeline >= float(placement.offset))
                  & (timeline < float(placement.end)))
        cells = ((timeline - program_start) / HOP).astype(int)
        ok = inside & (cells >= 0) & (cells < mask.shape[0])
        out[ok] |= mask[cells[ok]]
    return out

