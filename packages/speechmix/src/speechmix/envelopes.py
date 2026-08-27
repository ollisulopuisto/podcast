"""Vaimennus **päätöksinä**, ei näytteinä.

``duck_envelopes`` palauttaa ``{puhuja: [(aika, dB), …]}``. autoraffkat
kirjoittaa ne Final Cutin ``<adjust-volume>``-keyframeiksi, jolloin leikkaaja
voi yhä muuttaa niitä; isäntä jolla ei ole mitään mihin automaatio
kirjoitetaan polttaa saman käyrän näytteisiin. Sama laskenta, eri emissio.

    Tasopäätökset jotka tulevat ketjun **jälkeen** voivat olla automaatiota.
    Tasopäätökset jotka tulevat sitä **ennen** on poltettava sisään.

Ruudukon muunnos aikajanalta tiedostoaikaan on ``session.py``:ssä, ja
``envelope_gain`` on sen ainoa käyttäjä täällä: käyrä on aikajanan aikaa,
tiedosto omaansa, ja väli niiden välillä on yksi ``Span``.

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

def envelope_gain(track, points, low: int, high: int, rate: int) -> np.ndarray:
    """Vaimennuksen kerroin tiedoston näyteväliltä ``[low, high)``.

    Tämä on se puoli saumaa jolla vaimennus **poltetaan sisään**: isäntä
    jolla on automaatio kirjoittaa ``duck_envelopes``in pisteet sellaisenaan,
    isäntä joka vie valmiin miksauksen kertoo tällä. Sama käyrä, eri emissio.

    Käyrä on aikajanan aikaa, tiedosto omaansa. Muunnos on jakson sisällä
    lineaarinen, sama kaava kuin ``session.file_ranges``issa. Ykkösiä silloin
    kun puhujalle ei ole käyrää: silloin summaan menee tiedosto sellaisenaan.
    """
    if not points or track is None:
        return np.ones(1, dtype=np.float32)
    gain = np.ones(high - low, dtype=np.float32)
    for span in track.spans:
        base = float(span.base)
        # Tiedostoaika = base + aikajana, joten aikajana = tiedostoaika - base.
        first = max(low / rate, float(span.start) + base)
        last = min(high / rate, float(span.end) + base)
        if last <= first:
            continue
        i0, i1 = int(round(first * rate)) - low, int(round(last * rate)) - low
        i0, i1 = max(0, i0), min(len(gain), i1)
        if i1 <= i0:
            continue
        times = (np.arange(i0, i1, dtype=np.float64) + low) / rate - base
        curve = np.interp(
            times,
            [t for t, _ in points],
            [v for _, v in points],
            left=0.0,
            right=0.0,
        )
        gain[i0:i1] = (10.0 ** (curve / 20.0)).astype(np.float32)
    return gain
