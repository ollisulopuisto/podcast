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

from .masks import HOP, drop_short, duck_masks, runs
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

#: Ohjelman päiden häivytys. Pituudet ovat leikkauskonventio eivätkä mittaus:
#: sisääntulo lyhyt, jotta ohjelma alkaa heti, ulostulo pidempi, koska loppuun
#: kuuluu jäädä aikaa. Vartti on turvaväli puheeseen — häivytys saa koskea vain
#: hiljaisuutta ja tilaääntä, ja puheentunnistuksen raja on ruudukon askeleen
#: (20 ms) tarkkuudella, joten se ei kelpaa sellaisenaan reunaksi.
FADE_IN_SEC = 1.0
FADE_OUT_SEC = 2.0
FADE_GUARD_SEC = 0.25
#: Final Cutin äänenvoimakkuusliu'un pohja.
FADE_FLOOR_DB = -96.0
#: Tätä lyhyempää häivytystä ei kirjoiteta: se on naksahdus, ei häivytys.
FADE_MIN_SEC = 0.1
#: Tätä lyhyempi puhejakso ei ole ohjelman alku eikä loppu. Ruudukon
#: ensimmäinen ja viimeinen solu ovat vajaita ikkunoita, ja tunnistus antaa
#: niissä yhden tai kahden solun tosia — mitattuna molemmissa päissä, sekä
#: fixtuurilla että jaksolla. Ilman tätä rajaa se yksi 20 ms:n solu on
#: «ensimmäinen sana», ja häivytys jää kokonaan kirjoittamatta.
FADE_SPEECH_MIN_SEC = 0.2


def program_fades(grid, program_start: float, program_end: float,
                  ducks: dict | None = None,
                  fade_in: float = FADE_IN_SEC,
                  fade_out: float = FADE_OUT_SEC,
                  guard: float = FADE_GUARD_SEC,
                  floor_db: float = FADE_FLOOR_DB) -> dict[str, list]:
    """Häivytys ohjelman päistä, vaimennuskäyriin sulautettuna.

    Häivytys on tasopäätös ketjun **jälkeen**, joten se on automaatiota siinä
    missä vaimennuskin: sama ``{puhuja: [(aika, dB), …]}`` ja sama emissio
    Final Cutin keyframeiksi. Erillistä rakennetta ei siis tarvita, ja
    leikkaaja voi vetää liu'un toiseen kohtaan avaamatta tätä työkalua.

    Rajat luetaan puheentunnistuksesta eikä kellosta: häivytys saa koskea vain
    hiljaisuutta ja tilaääntä. Puheen päälle ajettuna se on juuri sen
    lajin vika jota tässä projektissa ei kuule ennen kuin vienti on
    Final Cutissa — tiedosto on kelvollinen, oikean mittainen, ja ensimmäinen
    sana on vaimea. Siksi häivytys **lyhenee** mahtuakseen ja jää kokonaan
    kirjoittamatta jos tilaa ei ole.

    Häivytys kuuluu jokaiselle mikille, myös niille joilla ei ole
    vaimennuskäyrää: ohjelma häipyy kokonaan tai ei ollenkaan.
    """
    speakers = [lane.name for lane in getattr(grid, "speakers", [])]
    if not speakers or program_end <= program_start:
        return dict(ducks or {})

    talking = np.zeros_like(np.asarray(grid.speakers[0].on, dtype=bool))
    for lane in grid.speakers:
        talking |= np.asarray(lane.on, dtype=bool)
    said = np.flatnonzero(drop_short(talking, FADE_SPEECH_MIN_SEC))
    first = program_start + int(said[0]) * HOP if said.size else program_end
    last = program_start + int(said[-1] + 1) * HOP if said.size else program_start

    head_end = min(program_start + fade_in, first - guard)
    tail_start = max(program_end - fade_out, last + guard)
    head = ([(program_start, floor_db), (head_end, 0.0)]
            if head_end - program_start >= FADE_MIN_SEC else [])
    tail = ([(tail_start, 0.0), (program_end, floor_db)]
            if program_end - tail_start >= FADE_MIN_SEC else [])
    if not head and not tail:
        return dict(ducks or {})

    out: dict[str, list] = {}
    for name in speakers:
        # Vaimennus on aina päiden puheen sisällä, joten pisteet eivät voi
        # osua päällekkäin — mutta järjestys on silti varmistettava, koska
        # sekä ``envelope_at`` että ``duck_gain`` olettavat käyrän nousevan.
        merged = [*head, *(ducks or {}).get(name, []), *tail]
        out[name] = sorted(merged, key=lambda point: point[0])
    return out


def envelope_at(points: list, when: float) -> float:
    """Käyrän arvo hetkellä ``when``, desibeleinä. Väleissä lineaarinen.

    Käyrän ulkopuolella **reunan arvo**, ei nolla. Vaimennukselle nämä ovat
    sama asia — se alkaa ja päättyy nollaan, koska se on paikallinen tapahtuma
    eikä tila — mutta häivytykselle eivät: sen viimeinen piste on ohjelman
    lopussa ja alimmillaan, ja nollana luettuna vienti kirjoittaisi kuvan
    reunaan 0 dB:n keyframen ja nostaisi äänen takaisin juuri siinä kohdassa
    jossa sen pitäisi olla poissa.
    """
    if not points:
        return 0.0
    if when <= points[0][0]:
        return float(points[0][1])
    if when >= points[-1][0]:
        return float(points[-1][1])
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


def mask_samples(track: Track, mask, program_start: float, rate: int,
                 frames: int) -> np.ndarray:
    """Ruudukon maski tämän tiedoston näytteiksi. Sama muunnos, maalattuna.

    Vuodon estimointi lukee tätä: se tarvitsee näytekohtaiset «vain tämä
    puhuja» -jaksot, ja ``closed_ranges`` antaa saman asian väleinä.
    """
    out = np.zeros(frames, dtype=bool)
    for first, last in closed_ranges(track, mask, program_start, rate):
        low, high = max(0, first), min(frames, last)
        if high > low:
            out[low:high] = True
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
        # Reunat kuten ``envelope_at``issa: käyrän ulkopuolella sen oma
        # reuna-arvo. Nollalla nämä kaksi emissiota antaisivat häivytetylle
        # ohjelmalle eri tuloksen, ja katto laskettaisiin ohjelmasta jota
        # Final Cut ei soita.
        curve = np.interp(timeline, times_db, values_db,
                          left=values_db[0], right=values_db[-1])
        gain[i0:i1] = (10.0 ** (curve / 20.0)).astype(np.float32)
    return gain
