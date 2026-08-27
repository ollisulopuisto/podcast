"""Sauma: raitoja joilla on paikka ohjelman aikajanalla.

Isäntä antaa raitoja, ei istuntoformaatin olioita. Raidalla on **jaksoja**,
ja jakson sisällä kuvaus aikajanan ajasta tiedostoaikaan on lineaarinen:

    tiedostoaika = jakso.file_offset + (ohjelma-aika - jakso.start)

Se yksi kaava on kaikki mitä ketju tarvitsee aikajanasta. Kaikki mikä tässä
tiedostossa on, on sen soveltamista johonkin: maskiin, lohkoihin, näytteisiin,
toisen mikin ääneen.

**Miksi tämä on täällä eikä sovelluksessa.** Nämä funktiot lukivat ennen
``item.placements``ia ja ``item.asset_start``ia — FCPXML:n muotoa, jonka vain
autoraffkat osaa rakentaa. Ne olivat siis kirjastossa mutta vain yhden
sovelluksen käytettävissä, ja automixerin vaimennus, ristivuodon vähennys ja
tasonkuljettaja jäivät sen takia tekemättä: ne kaikki tarvitsevat juuri tämän
muunnoksen eivätkä mitään muuta aikajanasta. Jokainen sovellus rakentaa
``Track``:it omasta istuntoformaatistaan — se on se osa jota ei voi jakaa —
ja kaikki muu on tästä eteenpäin samaa koodia.

``Span``in ajat saavat olla mitä tahansa numeroita joilla laskeminen onnistuu.
autoraffkat antaa ``Fraction``eita, koska FCPXML:n ajat ovat rationaalisia
(1001/30000 s ruutu) ja ruudukon reunalla liukuluvun viimeinen bitti riittää
pudottamaan solun; automixer antaa liukulukuja, koska sen istunto on
sekunteja. Muunnos liukuluvuksi tehdään vasta näyteindeksiä laskettaessa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .masks import HOP, runs


@dataclass(frozen=True)
class Span:
    """Yksi pala raitaa aikajanalla.

    ``start`` ja ``end`` ovat ohjelman aikaa, ``file_offset`` on tiedostoaika
    hetkellä ``start``. Loppu on poissulkeva, kuten maskien jaksoissa.
    """

    start: float
    end: float
    file_offset: float = 0.0

    @property
    def base(self) -> float:
        """Vakio jolla ``tiedostoaika = base + ohjelma-aika``."""
        return self.file_offset - self.start

    @property
    def duration(self) -> float:
        return self.end - self.start

    def file_at(self, when: float) -> float:
        """Tiedostoaika ohjelman hetkellä ``when``."""
        return self.file_offset + (when - self.start)


@dataclass
class Track:
    """Yksi tiedosto ja sen paikat aikajanalla.

    ``speaker`` on se kenen mikki tämä on: vaimennus, ristivuoto ja
    tasonkuljettaja avaimetaan sillä, ja ruudukon kaistat kantavat samaa
    nimeä. Kaksi tiedostoa voi olla saman puhujan — monikamerassa sama mikki
    on oma tiedostonsa joka osassa.
    """

    path: str = ""
    speaker: str = ""
    spans: list[Span] = field(default_factory=list)
    #: Mikki on aina mono. Kaksikanavainen mikki rikkoo laskennan useassa
    #: kohtaa hiljaa: vuodon vähennys katsoo vain ensimmäistä kanavaa,
    #: ohjelmakatto summaa eri kanavamäärät levittämällä, ja panorointi on
    #: monolähteen käsite.
    mono: bool = True
    bit_depth: int = 24

    @property
    def timeline_start(self) -> float:
        return min((s.start for s in self.spans), default=0.0)

    @property
    def timeline_end(self) -> float:
        return max((s.end for s in self.spans), default=0.0)

    @property
    def span_total(self) -> float:
        """Yhteenlaskettu kesto aikajanalla, ilman jaksojen välejä."""
        return sum((s.duration for s in self.spans), start=0.0)


def whole_file(path: str, speaker: str = "", start: float = 0.0,
               duration: float = 0.0, file_offset: float = 0.0,
               **kwargs) -> Track:
    """Koko tiedosto yhtenä jaksona aikajanalla.

    Tämä on wav-isännän muoto: yksi tiedosto, yksi paikka, ei leikkauksia.
    automixerin istunnossa raidalla on alkuhetki ja pituus, eikä mitään
    muuta — ja se riittää, koska kaikki tästä eteenpäin lukee vain jaksoja.
    """
    return Track(
        path=path,
        speaker=speaker,
        spans=[Span(start=start, end=start + duration, file_offset=file_offset)],
        **kwargs,
    )


def overlaps(one: Track, other: Track) -> bool:
    """Ovatko kaksi raitaa yhtään hetkeä yhtä aikaa aikajanalla.

    Monikamerassa osat ovat peräkkäin, joten toisen osan mikki ei voi
    vuotaa tämän osan tiedostoon. Ilman tätä se tarjottiin silti
    vuotolähteeksi, ``aligned`` palautti pelkkää nollaa, ja lokiin tuli
    «vuotopolkua ei saatu ratkaistua» pariutumisesta joka ei ollut koskaan
    mahdollinen. Vienti ei mennyt siitä rikki — oikea kumppani käsiteltiin
    erikseen — mutta sama tiedosto näytti lokissa sekä onnistuvan että
    epäonnistuvan, ja se peitti alleen oikean vian pitkissä osissa.
    Virheilmoitus jota ei voi uskoa on huonompi kuin ei ilmoitusta.
    """
    for mine in one.spans:
        for theirs in other.spans:
            if float(mine.start) < float(theirs.end) and float(theirs.start) < float(
                mine.end
            ):
                return True
    return False


def file_ranges(track: Track, mask, program_start: float,
                rate: int) -> list[tuple[int, int]]:
    """Missä tiedoston kohdissa maski on tosi, näyteväleinä.

    Ruudukko on aikajanan aikaa, tiedosto omaansa. Muunnos tehdään
    jaksoittain, koska kunkin palan sisällä kuvaus on lineaarinen.
    Ruudukon ulkopuolelle jäävää osaa ei kosketa: siitä ei ole tietoa, eikä
    vienti käytä sitä.
    """
    out: list[tuple[int, int]] = []
    for start, end, value in runs(np.asarray(mask).astype(np.int8)):
        if not value:
            continue
        low = program_start + start * HOP
        high = program_start + end * HOP
        for span in track.spans:
            first = max(low, float(span.start))
            last = min(high, float(span.end))
            if last <= first:
                continue
            base = float(span.base)
            out.append(
                (int(round((base + first) * rate)), int(round((base + last) * rate)))
            )
    return out


def mask_samples(track: Track, mask, program_start: float, rate: int,
                 frames: int) -> np.ndarray:
    """Ruudukon maski tämän tiedoston näytteiksi. Sama muunnos, maalattuna."""
    out = np.zeros(frames, dtype=bool)
    for first, last in file_ranges(track, mask, program_start, rate):
        low, high = max(0, first), min(frames, last)
        if high > low:
            out[low:high] = True
    return out


def mask_blocks(track: Track, mask, program_start: float, rate: int,
                block: int, count: int) -> np.ndarray:
    """Maski lohkoittain tässä tiedostossa.

    Sama muunnos kuin ``file_ranges``issa, mutta vastaus on lohkoa kohden:
    tasonkuljettaja kysyy «puhuiko tämän raidan omistaja tässä lohkossa» ja
    tarvitsee juuri sen eikä signaalista pääteltyä puhetta — ks.
    ``chain.rider_gain``.
    """
    out = np.zeros(count, dtype=bool)
    mask = np.asarray(mask, dtype=bool)
    for span in track.spans:
        base = float(span.base)
        # Lohkon keskikohta tiedostoajassa -> aikajana -> ruudukon solu.
        times = (np.arange(count) + 0.5) * block / rate
        timeline = times - base
        inside = (timeline >= float(span.start)) & (timeline < float(span.end))
        cells = ((timeline - program_start) / HOP).astype(int)
        ok = inside & (cells >= 0) & (cells < mask.shape[0])
        out[ok] |= mask[cells[ok]]
    return out


def geometry(track: Track, frames: int) -> tuple:
    """Tiedoston sijainti aikajanalla, vertailukelpoisena avaimena.

    Summa lasketaan tiedostoista näyte näytteeltä, mikä on oikein vain jos
    stemit ovat samassa kohdassa aikajanaa ja yhtä pitkiä. Tämä tekee siitä
    tarkistettavan asian eikä oletuksen.
    """
    return (
        frames,
        tuple(
            (
                round(float(s.start), 4),
                round(float(s.end), 4),
                round(float(s.base), 4),
            )
            for s in track.spans
        ),
    )


def aligned(target: Track, source: Track, source_audio, rate: int,
            frames: int) -> np.ndarray:
    """Lähdemikin ääni kohdetiedoston näytepaikoille.

    Tiedostot ovat eri pituisia ja alkavat aikajanalla eri kohdista, joten
    vuotoa ei voi vähentää ennen kuin ne ovat samassa aikapohjassa. Kuvaus
    on jakson sisällä lineaarinen ja näytetaajuus sama, joten se on
    kokonaisluvun siirto — ei uudelleennäytteistystä, joka siirtäisi
    vaihetta ja pilaisi juuri sen mitä tässä yritetään mitata.
    """
    out = np.zeros(frames, dtype=np.float64)
    samples = np.asarray(source_audio, dtype=np.float64).reshape(-1)
    for mine in target.spans:
        base_t = float(mine.base)
        for theirs in source.spans:
            base_s = float(theirs.base)
            low = max(float(mine.start), float(theirs.start))
            high = min(float(mine.end), float(theirs.end))
            if high <= low:
                continue
            t0 = int(round((base_t + low) * rate))
            t1 = int(round((base_t + high) * rate))
            shift = int(round((base_s - base_t) * rate))
            t0, t1 = max(0, t0), min(frames, t1)
            s0, s1 = t0 + shift, t1 + shift
            if s1 <= 0 or s0 >= samples.size or t1 <= t0:
                continue
            cut = max(0, -s0)
            s0, t0 = s0 + cut, t0 + cut
            cut = max(0, s1 - samples.size)
            s1, t1 = s1 - cut, t1 - cut
            if t1 > t0:
                out[t0:t1] = samples[s0:s1]
    return out
