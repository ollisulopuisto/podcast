"""Kynnys opitaan käsin vaimennetuista alueista.

Käyttäjä avaa istunnon Hindenburgissa, muokkaa alun minuutin tai pari ja
vaimentaa kohdat joissa kukaan ei puhu. Se on ainoa tieto siitä missä *tämän
mikin* raja puheen ja ei-puheen välillä on, ja sen antaa ihminen: oma korva
päättää, mikä on vuotoa, hengitystä tai huoneen hälyä. Ohjelma mittaa
vaimennettujen alueiden tason ja käyttää sitä kynnyksenä muualle istuntoon,
joten kynnystä ei tarvitse arvata.

**Tämä tiedosto on yksi tiedosto ja vain standardikirjastoa, tahallaan.** Se
ladataan sellaisenaan Colabiin colab-transcriben skriptin viereen, ja siellä ei
ole työtilaa. Kirjasto ei tiedä ``.nhsx``-tiedostoista eikä äänestä: se saa
raidat (``Track``) ja ``Source``n, joka vastaa kahteen kysymykseen — mitkä
sanat tiedostossa ovat, ja mikä taso on tietyllä välillä. Lukeminen ja purku
ovat kutsujan asia. ``test_the_library_imports_nothing_but_the_standard_
library`` vartioi tätä.

**Taso ei ole yksi luku.** Vaimennetussa alueessa on taustakohinaa, toisen
puhujan vuotoa — ja yskäisyjä, naurua, tuolin kolahduksia. Maksimi tai
keskiarvo antaisi yskäisyn tason, ja sen yli jäisi vain huutaminen. Siksi
kynnys on tason **korkea persentiili** (``PERCENTILE``): alueen tavallinen
yläpää, vuoto mukaan lukien, mutta harvinaiset piikit eivät. Persentiili
sietää piikkejä sen verran kuin niitä on alle 100 − ``PERCENTILE`` prosenttia
alueesta.

**Sama asteikko kuin sanalla.** Kynnystä verrataan sanan kohdalta mitattuun
tasoon, joten vaimennettu alue mitataan sanan mittaisilla ikkunoilla
(``WINDOW``), ei kaistaleilla joiden taso tarkoittaisi eri asiaa.

**Opittu kynnys tarkistetaan puhetta vasten.** Jos käyttäjä on vaimentanut
vahingossa puhetta, kynnys on puheen tasolla ja vaientaisi kaiken: liikaa
vaimennettu jakso on pahempi virhe kuin liian vähän vaimennettu. Kynnys, joka
ei jää selvästi vaimentamattomien sanojen tason alle
(``GUARD_DB``), hylätään ja sanotaan miksi, ja raita ajetaan tavallisella
säännöllä.

**Sidechain: kanavien välinen tieto.** Kaksi todistetta käyttäjän omista
merkinnöistä, kumpikin muokatulta ajalta (``horizon``: viimeisen vaimennetun
alueen loppu; sen jälkeen kaikki on vaimentamatta vain koska kukaan ei ole
vielä katsonut):

* Kun raita B on vaimennettu ja raita A puhuu samalla hetkellä, B:n taso on
  A:n vuotoa. Se on vahva merkki, ja sillä on kaksi käyttöä: B:n kynnys ei saa
  jäädä sen alle (harvinainen vuoto ei häviä persentiilissä, kun vuoto
  mitataan erikseen), ja A:n ja B:n välinen **ero** on vuodon ero.
* Kun B on vaimentamatta ja A puhuu samalla hetkellä, B:n sana on oikeaa
  puhetta — usea kanava voi puhua yhtä aikaa — ja sen ero A:han on se, mikä
  pitää päästää läpi. Sama koskee tasoa: vaimentamattoman sanan taso on
  päästettävä, joten kynnys ei saa olla sen yläpuolella.

Ero-raja asetetaan vuodon eron ja puheen eron väliin. Jos ne menevät
päällekkäin, raja menee puheen yläpuolelle ja syy kirjoitetaan: liikaa
vaimennettu on pahempi virhe kuin liian vähän vaimennettu.

**Ilman sanoja: klipit esimerkkeinä.** ``calibrate`` tarvitsee litteroinnin
(``Source.words``). Editori, jolla on vain klipit (väli tiedostossa, jonka
käyttäjä on vaimentanut tai jättänyt) ja tasoikkunat, käyttää
``calibrate_clips``ia: vaimennetut klipit antavat kynnyksen kuten ennenkin,
vaimentamattomat klipit puheen tason ja vartijan. Vaimentamaton klippi on
puhetta **taukoineen**, joten sen puheen taso on ikkunoiden yläneljännes
(``SPEECH_PERCENTILE_TRANSCRIPT``), ei alaneljännes: se olisi tauko. Kutsuja
antaa vain ``level`` ja ``missing``; sanoja ei kysytä.

Mikään tässä tiedostossa olevista luvuista ei ole mitattu. Ne ovat makuarvoja
ja ensimmäisen oikean istunnon tarkistamatta: aja oppiminen istunnolla ja
katso lokista mitä raita sai.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import floor
from typing import Protocol

# Digitaalinen hiljaisuus on -inf, ja persentiili -inf:istä päästäisi minkä
# tahansa marginaalin kanssa kaiken läpi. Sama luku kuin speechmix.dsp.FLOOR_DB;
# tämä kirjasto ei tuo sitä, koska se ei saa tuoda mitään.
FLOOR_DB = -120.0

# Sanan mittainen ikkuna ja sen askel. Makuarvo: suomalainen sana on tyypillisesti
# kolmesta viiteen kymmenesosaan sekuntia, eikä sen pituutta ole mitattu.
WINDOW = 0.3
HOP = 0.15

# Kynnys on näin suuri osa vaimennettujen alueiden ikkunoista alle. 90 sietää
# piikkejä (yskäisy, nauru) jos ne ovat alle 10 % vaimennetusta ajasta.
# Makuarvo.
PERCENTILE = 90.0

# Varmuusvara persentiilin päälle, desibeleinä. Makuarvo.
MARGIN_DB = 1.0

# Alle tämän vaimennettua ääntä raidalta ei opita mitään: muutama sekunti on
# yksi yskäisy tai yksi hengitys, ei raidan tyypillinen taso. Makuarvo.
MIN_SECONDS = 3.0

# Kuinka monta vaimentamatonta sanaa mitataan puheen tasoksi, ja kuinka paljon
# kynnyksen pitää jäädä puheen tason alle. Makuarvot.
SPEECH_WORDS = 400
GUARD_DB = 3.0

# Puheen taso on muokatulla ajalla vaimentamatta jätettyjen sanojen hiljaisin
# neljännes (käyttäjä on kuullut ne ja jättänyt puheeksi). Jos niitä ei ole,
# taso mitataan litteroidusta alusta, jossa on kohinasanoja: 07 uutiset,
# Perttu, sanat 60–180 s mediaani −49 dBFS (kohina, puhe −25…−31) ja Olli
# 180–300 s −54 dBFS. Silloin hiljaisin neljännes on kohinaa ja kynnys
# (Perttu −38,7, Olli −43,9 dBFS) näytti olevan 'puheen tasolla'; yläneljännes
# on puhetta. Luvut ovat PR 57:n mittauksia, ei tässä uudelleen mitattu.
SPEECH_PERCENTILE_VETTED = 25.0
SPEECH_PERCENTILE_TRANSCRIPT = 75.0

# Peräkkäiset vaimennetut palat ovat yksi lohko: yksi puheenvuoro on voitu
# pätkiä moneen alueeseen. Rako alle tämän (s) ei erota lohkoja. Makuarvo.
BLOCK_GAP = 0.01

# Vuotokehyksiä (vaimennettu, toinen puhuu) pitää olla näin monta, jotta niistä
# lasketaan mitään. Makuarvo.
MIN_BLEED_FRAMES = 4

# Vaimentamattomia sanoja muokatulla ajalla pitää olla näin monta, jotta
# niistä lasketaan päästettävä taso ja puheen ero. Makuarvo.
MIN_SPEECH_WORDS = 3

# Persentiilit: vuodon ero (kovin vuoto = pienin ero, alin kymmenys) ja
# puheen ero (suurin ero = ylin kahdeskymmenesosa). Makuarvot.
BLEED_GAP_PERCENTILE = 10.0
SPEECH_GAP_PERCENTILE = 95.0

# Kuinka paljon alle vuodon eron raja asetetaan, kun puheen eroa ei ole
# mitattu, ja kuinka paljon yli puheen eron kun erot menevät päällekkäin.
# Makuarvot, desibeleinä.
GAP_MARGIN_DB = 2.0

# Kynnys jää tämän verran alle hiljaisimman päästettävän sanan. Makuarvo.
KEEP_MARGIN_DB = 0.5

# Klipeistä oppiessa vaimentamattomia ikkunoita pitää olla näin monta, jotta
# puheen taso lasketaan ja vartija toimii: kuusi ikkunaa on noin sekunti
# (WINDOW + 5 × HOP = 1,05 s). Makuarvo, ei mitattu.
MIN_SPEECH_WINDOWS = 6

__all__ = [
    "BLEED_GAP_PERCENTILE", "BLOCK_GAP", "FLOOR_DB", "GAP_MARGIN_DB", "GUARD_DB", "HOP",
    "KEEP_MARGIN_DB", "MARGIN_DB", "MIN_BLEED_FRAMES", "MIN_SECONDS",
    "MIN_SPEECH_WINDOWS", "MIN_SPEECH_WORDS", "PERCENTILE", "SPEECH_GAP_PERCENTILE",
    "SPEECH_PERCENTILE_TRANSCRIPT", "SPEECH_PERCENTILE_VETTED", "SPEECH_WORDS",
    "WINDOW", "Calibration", "Clip", "Levels", "Region", "Source", "Track",
    "calibrate", "calibrate_clips", "horizon", "percentile",
]


@dataclass(frozen=True)
class Region:
    """Alue raidalla. ``start`` ja ``length`` ovat aikajanaa, ``offset`` tiedoston aikaa."""

    ref: str
    start: float
    length: float
    offset: float
    muted: bool = False

    @property
    def end(self) -> float:
        return self.start + self.length


@dataclass
class Track:
    name: str
    regions: list[Region]


@dataclass(frozen=True)
class Clip:
    """Esimerkki ilman aikajanaa: väli tiedostossa ``ref`` (tiedoston aikaa, s)."""

    ref: str
    start: float
    end: float
    muted: bool = False


class Levels(Protocol):
    """Klipeistä oppimiseen riittää tämä: taso välillä, ei sanoja."""

    def level(self, ref: str, start: float, end: float) -> float | None:
        """Taso desibeleinä tiedoston ajassa, tai ``None`` kun ääntä ei ole."""

    def missing(self) -> bool:
        """Puuttuiko jokin äänitiedosto (selittää tyhjän tuloksen)."""


class Source(Protocol):
    """Kutsujan puoli: sanat ja tasot, jotka kirjasto ottaa annettuna."""

    def words(self, ref: str) -> list[tuple[float, float]]:
        """Tiedoston ``ref`` sanat: ``(alku, pituus)`` tiedoston aikaa."""

    def level(self, ref: str, start: float, end: float) -> float | None:
        """Taso desibeleinä tiedoston ajassa, tai ``None`` kun ääntä ei ole."""

    def missing(self) -> bool:
        """Puuttuiko jokin äänitiedosto (selittää tyhjän tuloksen)."""


@dataclass
class Calibration:
    """Yhden raidan opittu kynnys ja ero-raja, tai syy miksi niitä ei ole."""

    threshold: float | None = None   # dBFS sanan ikkunassa; ``None`` = ei opittu
    muted_seconds: float = 0.0
    frames: int = 0
    speech_level: float | None = None
    reason: str = ""
    # Sidechain: kuinka monta desibeliä kovimman toisen raidan alle sana saa
    # jäädä ja olla silti puhetta. ``None`` = ei opittu, käytetään oletusta.
    dominance: float | None = None
    bleed_gap: float | None = None     # vuodon ero, alin kymmenys
    speech_gap: float | None = None    # yhtäaikaisen puheen ero, ylin 5 %
    bleed_frames: int = 0
    gap_note: str = ""
    # Selitys sille, että kynnys laskettiin pienemmäksi kuin vaimennetusta
    # ajasta: päästettävä sana oli sen alla.
    clamp_note: str = ""
    # Vain ``calibrate_clips``: vaimentamattomien ikkunoiden määrä ja se osuus
    # niistä, joka on kynnyksen yläpuolella (``None`` = ei vaimentamattomia).
    unmuted_frames: int = 0
    kept_share: float | None = None


def percentile(values: list[float], q: float) -> float:
    """Lineaarisesti interpoloitu persentiili, sama luku kuin ``numpy.percentile``.

    Kirjoitettu itse, koska kirjasto ei saa tuoda numpya (ks. moduulin
    dokumentti); ``test_the_percentile_is_numpys`` vertaa sitä numpyyn.
    """
    ordered = sorted(values)
    k = (len(ordered) - 1) * q / 100.0
    lower = floor(k)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (k - lower)


def horizon(tracks: list[Track]) -> float:
    """Muokattu aika: viimeisen vaimennetun alueen loppu ohjelma-aikajanalla."""
    return max((r.end for t in tracks for r in t.regions if r.muted), default=0.0)


def _region_at(regions: list[Region], programme_time: float) -> Region | None:
    """Alue joka on tällä raidalla kyseisellä hetkellä, tai ``None``."""
    for region in regions:
        if region.start <= programme_time < region.end:
            return region
    return None


def _muted_blocks(regions: list[Region]) -> list[tuple[float, float]]:
    """Vaimennetut alueet lohkoina ``(alku, pituus)``: vierekkäiset yhdistetty."""
    spans = sorted((r.start, r.end) for r in regions if r.muted)
    blocks: list[list[float]] = []
    for start, end in spans:
        if blocks and start <= blocks[-1][1] + BLOCK_GAP:
            blocks[-1][1] = max(blocks[-1][1], end)
        else:
            blocks.append([start, end])
    return [(a, b - a) for a, b in blocks]


def _windows(start: float, length: float):
    if length < 0.1:
        return
    if length <= WINDOW:
        yield start, start + length
        return
    t = start
    while t + WINDOW <= start + length + 1e-9:
        yield t, t + WINDOW
        t += HOP


class _Words:
    """Tiedoston sanat kerran: sama tiedosto on aikajanalla usein monta kertaa."""

    def __init__(self, source: Source):
        self.source = source
        self._by_ref: dict[str, list[tuple[float, float]]] = {}

    def of(self, ref: str) -> list[tuple[float, float]]:
        if ref not in self._by_ref:
            self._by_ref[ref] = list(self.source.words(ref))
        return self._by_ref[ref]

    def in_region(self, region: Region):
        """Alueeseen osuvat sanat: ``(tiedostoaika, pituus, alku, loppu)`` aikajanalla.

        Sanan loppu leikataan alueen loppuun. Alueen ulkopuolelle jäävä osa ei
        ole olemassa aikajanalla.
        """
        for ws, wl in self.of(region.ref):
            if ws < region.offset or ws >= region.offset + region.length:
                continue
            start = region.start + (ws - region.offset)
            end = min(region.end, start + wl)
            if end <= start:
                continue
            yield ws, wl, start, end


def calibrate(tracks: list[Track], source: Source) -> dict[str, Calibration]:
    """Raita -> opittu kynnys ja ero-raja. Raidalla jolla ei ole opittavaa on syy.

    Kutsujan on pidettävä kaikki äänet saatavilla koko laskennan ajan: jokaisen
    ikkunan kohdalla verrataan myös muita raitoja, ja jos ``source`` purkaa
    äänen uudestaan joka haulla (kahden tiedoston välimuisti, kolme raitaa),
    jokainen haku maksaa tunnin äänen purun.
    """
    words = _Words(source)
    regions = {t.name: sorted(t.regions, key=lambda r: r.start) for t in tracks}
    edited = horizon(tracks)

    unmuted: dict[str, list[tuple[float, float]]] = {}
    starts: dict[str, list[float]] = {}
    for track in tracks:
        found = []
        for region in regions[track.name]:
            if region.muted:
                continue
            for _ws, _wl, start, end in words.in_region(region):
                if start < edited:
                    found.append((start, end))
        unmuted[track.name] = sorted(found)
        starts[track.name] = [w[0] for w in unmuted[track.name]]

    def level_at(name: str, begin: float, end: float) -> float | None:
        region = _region_at(regions[name], begin)
        if region is None:
            return None
        file_start = region.offset + (begin - region.start)
        level = source.level(region.ref, file_start, file_start + (end - begin))
        return None if level is None else max(level, FLOOR_DB)

    def active(name: str, begin: float, end: float) -> bool:
        """Osuuko jokin sana ikkunaan ``[begin, end)``."""
        low = bisect_left(starts[name], begin - 1.0)       # sanat ovat alle sekunnin
        high = bisect_right(starts[name], end)
        return any(a < end and b > begin for a, b in unmuted[name][low:high])

    def loudest_other(own: str, begin: float, end: float) -> float | None:
        found = None
        for other in tracks:
            if other.name == own or not active(other.name, begin, end):
                continue
            level = level_at(other.name, begin, end)
            if level is not None and (found is None or level > found):
                found = level
        return found

    def speech_levels(name: str) -> list[float]:
        """Vaimentamattomien alueiden ensimmäisten sanojen tasot."""
        levels: list[float] = []
        for region in regions[name]:
            if region.muted:
                continue
            for ws, wl, _start, _end in words.in_region(region):
                level = source.level(region.ref, ws, ws + wl)
                if level is None:
                    continue
                levels.append(max(level, FLOOR_DB))
                if len(levels) >= SPEECH_WORDS:
                    return levels
        return levels

    out: dict[str, Calibration] = {}
    for track in tracks:
        name = track.name
        found = Calibration()
        muted_levels: list[float] = []
        bleed_levels: list[float] = []
        bleed_gaps: list[float] = []
        for block_start, block_length in _muted_blocks(regions[name]):
            found.muted_seconds += block_length
            for begin, end in _windows(block_start, block_length):
                mine = level_at(name, begin, end)
                if mine is None:
                    continue
                muted_levels.append(mine)
                other = loudest_other(name, begin, end)
                if other is not None:
                    bleed_levels.append(mine)
                    bleed_gaps.append(other - mine)
        found.frames = len(muted_levels)
        found.bleed_frames = len(bleed_gaps)

        if not muted_levels:
            found.reason = ("ääntä ei löytynyt" if source.missing()
                            else "ei käsin vaimennettuja alueita")
            out[name] = found
            continue
        if found.muted_seconds < MIN_SECONDS:
            found.reason = (f"vaimennettua ääntä vain {found.muted_seconds:.1f} s — "
                            f"liian vähän, vähintään {MIN_SECONDS:.0f} s")
            out[name] = found
            continue

        # Päästettävä tieto kerätään ennen kynnystä, koska ero-raja ei saa
        # riippua siitä onnistuiko kynnys: kaksi eri todistetta.
        passable: list[float] = []
        speech_gaps: list[float] = []
        for begin, end in unmuted[name]:
            mine = level_at(name, begin, end)
            if mine is None:
                continue
            passable.append(mine)
            other = loudest_other(name, begin, end)
            if other is not None:
                speech_gaps.append(other - mine)

        if len(bleed_gaps) >= MIN_BLEED_FRAMES:
            found.bleed_gap = percentile(bleed_gaps, BLEED_GAP_PERCENTILE)
            if len(speech_gaps) >= MIN_SPEECH_WORDS:
                found.speech_gap = percentile(speech_gaps, SPEECH_GAP_PERCENTILE)
                if found.speech_gap < found.bleed_gap:
                    found.dominance = (found.speech_gap + found.bleed_gap) / 2
                else:
                    found.dominance = found.speech_gap + GAP_MARGIN_DB / 2
                    found.gap_note = (
                        f"vuodon ({found.bleed_gap:.1f} dB) ja puheen "
                        f"({found.speech_gap:.1f} dB) erot eivät erotu — raja "
                        "puheen yläpuolella")
            else:
                found.dominance = found.bleed_gap - GAP_MARGIN_DB

        threshold = percentile(muted_levels, PERCENTILE) + MARGIN_DB
        if len(bleed_levels) >= MIN_BLEED_FRAMES:
            # Vuoto mitataan erikseen: harvinainen vuoto ei näy koko vaimennetun
            # ajan persentiilissä, mutta se on juuri se mitä kynnyksen pitää
            # estää.
            threshold = max(threshold, percentile(bleed_levels, PERCENTILE) + MARGIN_DB)

        if len(passable) >= MIN_SPEECH_WORDS:
            found.speech_level = percentile(passable, SPEECH_PERCENTILE_VETTED)
        else:
            speech = speech_levels(name)
            if speech:
                found.speech_level = percentile(speech, SPEECH_PERCENTILE_TRANSCRIPT)
        if found.speech_level is not None and threshold >= found.speech_level - GUARD_DB:
            found.reason = (
                f"vaimennettujen alueiden taso ({threshold:.1f} dBFS) on puheen "
                f"tasolla ({found.speech_level:.1f} dBFS) — vaimennettiinko puhetta?")
            out[name] = found
            continue

        # Päästettävä on päästettävä: muokatulla ajalla vaimentamatta jätetty
        # sana on käyttäjän oma päätös, eikä kynnys saa jäädä sen yläpuolelle.
        if len(passable) >= MIN_SPEECH_WORDS:
            ceiling = min(passable) - KEEP_MARGIN_DB
            if threshold > ceiling:
                found.clamp_note = (
                    f"kynnys {threshold:.1f} → {ceiling:.1f} dBFS: vaimentamatta "
                    "jätetty sana on sen alla")
                threshold = ceiling
        found.threshold = threshold
        out[name] = found
    return out


def _clip_level(levels: Levels, ref: str, begin: float, end: float) -> float | None:
    level = levels.level(ref, begin, end)
    return None if level is None else max(level, FLOOR_DB)


def calibrate_clips(clips: list[Clip], levels: Levels) -> Calibration:
    """Kynnys vaimennetuista klipeistä, puheen taso ja vartija vaimentamattomista.

    Sama sääntö kuin ``calibrate``: kynnys on vaimennettujen ikkunoiden
    ``PERCENTILE`` plus ``MARGIN_DB``; liian vähän vaimennettua ääntä ei opeta
    mitään; kynnys joka ei jää ``GUARD_DB`` vaimentamattomien klippien tason
    alle hylätään (vaimennettiinko puhetta?). Erona ei kysytä sanoja, ja
    vartija toimii vasta kun vaimentamattomia ikkunoita on
    ``MIN_SPEECH_WINDOWS``. Ei ero-rajaa eikä katto-leikkausta: ne tarvitsevat
    sanoja ja toisia raitoja.
    """
    found = Calibration()
    by_ref: dict[str, list[Region]] = {}
    for clip in clips:
        if clip.muted and clip.end > clip.start:
            by_ref.setdefault(clip.ref, []).append(
                Region(clip.ref, clip.start, clip.end - clip.start, clip.start, muted=True)
            )
    muted_levels: list[float] = []
    for ref, regions in by_ref.items():
        for block_start, block_length in _muted_blocks(regions):
            found.muted_seconds += block_length
            for begin, end in _windows(block_start, block_length):
                mine = _clip_level(levels, ref, begin, end)
                if mine is not None:
                    muted_levels.append(mine)
    found.frames = len(muted_levels)

    if not muted_levels:
        found.reason = ("ääntä ei löytynyt" if levels.missing()
                        else "ei käsin vaimennettuja alueita")
        return found
    if found.muted_seconds < MIN_SECONDS:
        found.reason = (f"vaimennettua ääntä vain {found.muted_seconds:.1f} s — "
                        f"liian vähän, vähintään {MIN_SECONDS:.0f} s")
        return found

    kept: list[float] = []
    for clip in clips:
        if clip.muted or clip.end <= clip.start:
            continue
        for begin, end in _windows(clip.start, clip.end - clip.start):
            level = _clip_level(levels, clip.ref, begin, end)
            if level is not None:
                kept.append(level)
    found.unmuted_frames = len(kept)

    threshold = percentile(muted_levels, PERCENTILE) + MARGIN_DB
    if len(kept) >= MIN_SPEECH_WINDOWS:
        found.speech_level = percentile(kept, SPEECH_PERCENTILE_TRANSCRIPT)
        found.kept_share = sum(1 for level in kept if level >= threshold) / len(kept)
        if threshold >= found.speech_level - GUARD_DB:
            found.reason = (
                f"vaimennettujen alueiden taso ({threshold:.1f} dBFS) on puheen "
                f"tasolla ({found.speech_level:.1f} dBFS) — vaimennettiinko puhetta?")
            return found
    found.threshold = threshold
    return found
