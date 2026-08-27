"""Vaimennus **päätöksinä**, ei näytteinä.

``duck_envelopes`` palauttaa ``{puhuja: [(aika, dB), …]}``. autoraffkat
kirjoittaa ne Final Cutin ``<adjust-volume>``-keyframeiksi, jolloin leikkaaja
voi yhä muuttaa niitä; isäntä jolla ei ole mitään mihin automaatio
kirjoitetaan polttaa saman käyrän näytteisiin. Sama laskenta, eri emissio.

    Tasopäätökset jotka tulevat ketjun **jälkeen** voivat olla automaatiota.
    Tasopäätökset jotka tulevat sitä **ennen** on poltettava sisään.

``closed_ranges``, ``speech_blocks``, ``duck_gain`` ja ``geometry``
muuntavat ruudukon aikajanalta tiedostoaikaan. Ne ottavat ``Track``in eivätkä
isännän mediaoliota: muunnos on paikan sisällä lineaarinen, ja ``Track`` on
juuri se yksi asia jonka kirjasto aikajanasta tarvitsee tietää. Aiemmin ne
lukivat ``item.placements`` ja ``item.asset_start`` suoraan, mikä siirsi
koodin saumasta yli mutta jätti sauman leikkaamatta — ja jätti ``Track``in
sellaiseksi jota mikään ei tuonut sisään.

Muunnos on hiljainen kun se menee väärin. Käännetty etumerkki, pudonnut
paikka tai unohtunut ``asset_start`` tuottavat kelvollisen, oikean mittaisen
tiedoston väärässä kohdassa: mikään ei kaadu, mitään ei tulostu, ja vika
kuuluu vasta valmiissa ohjelmassa. Mitattuna kaksi noista kolmesta meni
läpi koko sarjasta, molemmista, ennen kuin ne kytkettiin tänne.

Siirretty autoraffkatin ``audio/mix.py``:stä, ei kopioitu.
"""

import numpy as np

from .masks import HOP, duck_masks, runs
from .timeline import Track


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

def geometry(track: Track, frames: int) -> tuple:
    """Raidan sijainti ohjelmassa, vertailukelpoisena avaimena.

    Summa lasketaan tiedostoista näyte näytteeltä, mikä on oikein vain jos
    stemit ovat samassa kohdassa aikajanaa ja yhtä pitkiä. Tämä tekee siitä
    tarkistettavan asian eikä oletuksen.
    """
    return (
        frames,
        tuple(
            (
                round(span.programme_start, 4),
                round(span.programme_end, 4),
                round(span.file_offset, 4),
            )
            for span in track.spans
        ),
    )


def closed_ranges(
    track: Track, closed, program_start: float, rate: int
) -> list[tuple[int, int]]:
    """Missä tiedoston kohdissa mikki on kiinni, näyteväleinä.

    Ruudukko on aikajanan aikaa, tiedosto omaansa. Muunnos tehdään
    paikoittain, koska kunkin paikan sisällä kuvaus on lineaarinen.
    Ruudukon ulkopuolelle jäävää osaa ei vaimenneta: siitä ei ole tietoa, eikä
    vienti käytä sitä.
    """
    out: list[tuple[int, int]] = []
    for start, end, value in runs(np.asarray(closed).astype(np.int8)):
        if not value:
            continue
        low = program_start + start * HOP
        high = program_start + end * HOP
        for span in track.spans:
            first = max(low, span.programme_start)
            last = min(high, span.programme_end)
            if last <= first:
                continue
            out.append(
                (
                    int(round(span.to_file_time(first) * rate)),
                    int(round(span.to_file_time(last) * rate)),
                )
            )
    return out


def speech_blocks(track: Track, mask, program_start: float, rate: int,
                  block: int, count: int) -> np.ndarray:
    """Puhujan oma puhe lohkoittain tässä tiedostossa.

    Ruudukko on aikajanan aikaa, tiedosto omaansa. Tasonkuljettaja tarvitsee
    juuri tämän eikä signaalista pääteltyä puhetta — kahden mikin
    nauhoituksessa puolet siitä mikä on raidalla kovaa on toinen puhuja.
    Ks. ``chain.rider_gain``.
    """
    out = np.zeros(count, dtype=bool)
    mask = np.asarray(mask, dtype=bool)
    for span in track.spans:
        base = span.file_offset - span.programme_start
        # Lohkon keskikohta tiedostoajassa -> aikajana -> ruudukon solu.
        times = (np.arange(count) + 0.5) * block / rate
        timeline = times - base
        inside = (timeline >= span.programme_start) & (timeline < span.programme_end)
        cells = ((timeline - program_start) / HOP).astype(int)
        ok = inside & (cells >= 0) & (cells < mask.shape[0])
        out[ok] |= mask[cells[ok]]
    return out


def duck_gain(track: Track, points: list, low: int, high: int,
              rate: int) -> np.ndarray:
    """Vaimennuksen kerroin tiedoston näyteväliltä ``[low, high)``.

    Käyrä on aikajanan aikaa, tiedosto omaansa. Ykkösiä silloin kun käyrää
    ei ole: silloin summaan menee tiedosto sellaisenaan.

    Tämä on ``duck_envelopes``in toinen emissio. Sama käyrä menee joko Final
    Cutin keyframeiksi tai — täällä — näytteisiin, ja kummankin on annettava
    sama tulos, koska muuten vienti ja ohjelmakatto eivät kuule samaa asiaa.
    """
    if not points:
        return np.ones(1, dtype=np.float32)
    gain = np.ones(high - low, dtype=np.float32)
    times_db = [t for t, _ in points]
    values_db = [v for _, v in points]
    for span in track.spans:
        base = span.file_offset - span.programme_start
        first = max(low / rate, span.file_offset)
        last = min(high / rate, span.to_file_time(span.programme_end))
        if last <= first:
            continue
        i0 = max(0, int(round(first * rate)) - low)
        i1 = min(len(gain), int(round(last * rate)) - low)
        if i1 <= i0:
            continue
        timeline = (np.arange(i0, i1, dtype=np.float64) + low) / rate - base
        curve = np.interp(timeline, times_db, values_db, left=0.0, right=0.0)
        gain[i0:i1] = (10.0 ** (curve / 20.0)).astype(np.float32)
    return gain
