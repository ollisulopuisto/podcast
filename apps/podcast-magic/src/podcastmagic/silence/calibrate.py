"""Kynnys opitaan käsin vaimennetuista alueista.

Käyttäjä avaa litteroidun istunnon Hindenburgissa, muokkaa alun minuutin tai
pari ja vaimentaa kohdat joissa kukaan ei puhu. Se on ainoa tieto siitä missä
*tämän mikin* raja puheen ja ei-puheen välillä on, ja sen antaa ihminen: oma
korva päättää, mikä on vuotoa, hengitystä tai huoneen hälyä. Ohjelma mittaa
vaimennettujen alueiden tason ja käyttää sitä kynnyksenä muualle istuntoon,
joten kynnystä ei tarvitse arvata.

**Taso ei ole yksi luku.** Vaimennetussa alueessa on taustakohinaa, toisen
puhujan vuotoa — ja yskäisyjä, naurua, tuolin kolahduksia. Maksimi tai
keskiarvo antaisi yskäisyn tason, ja sen yli jäisi vain huutaminen. Siksi
kynnys on tason **korkea persentiili** (``PERCENTILE``): alueen tavallinen
yläpää, vuoto mukaan lukien, mutta harvinaiset piikit eivät. Persentiili
sietää piikkejä sen verran kuin niitä on alle 100 − ``PERCENTILE`` prosenttia
alueesta.

**Sama asteikko kuin sanalla.** Kynnystä verrataan sanan kohdalta mitattuun
tasoon (``audio.dbfs`` sanan ikkunassa), joten vaimennettu alue mitataan
sanan mittaisilla ikkunoilla (``WINDOW``), ei kaistaleilla joiden taso
tarkoittaisi eri asiaa.

**Opittu kynnys tarkistetaan puhetta vasten.** Jos käyttäjä on vaimentanut
vahingossa puhetta, kynnys on puheen tasolla ja vaientaisi kaiken: liikaa
vaimennettu jakso on pahempi virhe kuin liian vähän vaimennettu. Kynnys, joka
ei jää selvästi vaimentamattomien sanojen hiljaisimman neljänneksen alle
(``GUARD_DB``), hylätään ja sanotaan miksi, ja raita ajetaan tavallisella
säännöllä (pohja + herkkyys).

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

Mikään tässä tiedostossa olevista luvuista ei ole mitattu. Ne ovat makuarvoja
ja ensimmäisen oikean istunnon tarkistamatta: aja ``learn`` istunnolla ja
katso lokista mitä raita sai.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

import numpy as np

from speechmix.dsp import FLOOR_DB

from .. import audio as audio_io
from ..nhsx import Session, TrackInfo, locate
from .detect import AudioCache, _region_at, is_muted, region_words

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
# kynnyksen pitää jäädä sen hiljaisimman neljänneksen alle. Makuarvot.
SPEECH_WORDS = 400
GUARD_DB = 3.0


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


@dataclass
class Calibration:
    """Yhden raidan opittu kynnys ja ero-raja, tai syy miksi niitä ei ole."""

    threshold: float | None = None   # dBFS sanan ikkunassa; ``None`` = ei opittu
    muted_seconds: float = 0.0
    frames: int = 0
    speech_p25: float | None = None
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


def horizon(session: Session) -> float:
    """Muokattu aika: viimeisen vaimennetun alueen loppu ohjelma-aikajanalla."""
    return max((r.end for t in session.tracks for r in t.regions if is_muted(r)),
               default=0.0)


class _Levels:
    """Tasot ohjelma-ajan ikkunoista mille tahansa raidalle."""

    def __init__(self, session: Session, cache: AudioCache, extra_dir: str):
        self.session = session
        self.cache = cache
        self.extra_dir = extra_dir
        self.regions = {t.name: sorted(t.regions, key=lambda r: r.start)
                        for t in session.tracks}
        self.missing: set[str] = set()

    def at(self, track: TrackInfo, start: float, end: float) -> float | None:
        region = _region_at(self.regions[track.name], start)
        if region is None:
            return None
        info = self.session.file_by_id(region.ref)
        if info is None:
            return None
        path = locate(self.session, info, self.extra_dir)
        samples = self.cache.get(path) if path else None
        if samples is None:
            self.missing.add(info.name)
            return None
        file_start = region.offset + (start - region.start)
        return max(audio_io.dbfs(samples, file_start, file_start + (end - start)),
                   FLOOR_DB)


def _unmuted_words(session: Session, track: TrackInfo, limit: float):
    """Vaimentamattomien alueiden sanat (alku, loppu ohjelma-aikaa) ennen ``limit``."""
    out = []
    for region in track.regions:
        if is_muted(region):
            continue
        for _word, _info, start, end in region_words(session, region):
            if start < limit:
                out.append((start, end))
    return sorted(out)


def _active(words: list[tuple[float, float]], starts: list[float],
            begin: float, end: float) -> bool:
    """Osuuko jokin sana ikkunaan ``[begin, end)``. ``starts`` on sanojen alut."""
    low = bisect_left(starts, begin - 1.0)       # sanat ovat alle sekunnin
    high = bisect_right(starts, end)
    return any(w_start < end and w_end > begin for w_start, w_end in words[low:high])


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


def _speech_levels(session: Session, track: TrackInfo, cache: AudioCache,
                   extra_dir: str) -> list[float]:
    """Vaimentamattomien alueiden ensimmäisten sanojen tasot."""
    levels: list[float] = []
    for region in track.regions:
        if is_muted(region):
            continue
        for word, info, _start, _end in region_words(session, region):
            path = locate(session, info, extra_dir)
            samples = cache.get(path) if path else None
            if samples is None:
                continue
            levels.append(max(audio_io.dbfs(samples, word.start, word.end), FLOOR_DB))
            if len(levels) >= SPEECH_WORDS:
                return levels
    return levels


def calibrate(session: Session, cache: AudioCache | None = None,
              extra_dir: str = "") -> dict[str, Calibration]:
    """Raita -> opittu kynnys ja ero-raja. Raidalla jolla ei ole opittavaa on syy."""
    cache = cache or AudioCache()
    levels = _Levels(session, cache, extra_dir)
    edited = horizon(session)
    words = {t.name: _unmuted_words(session, t, edited) for t in session.tracks}
    starts = {name: [w[0] for w in ws] for name, ws in words.items()}

    def loudest_other(track: TrackInfo, begin: float, end: float) -> float | None:
        found = None
        for other in session.tracks:
            if other.name == track.name:
                continue
            if not _active(words[other.name], starts[other.name], begin, end):
                continue
            level = levels.at(other, begin, end)
            if level is not None and (found is None or level > found):
                found = level
        return found

    out: dict[str, Calibration] = {}
    for track in session.tracks:
        found = Calibration()
        muted_levels: list[float] = []
        bleed_levels: list[float] = []
        bleed_gaps: list[float] = []
        for region in track.regions:
            if not is_muted(region):
                continue
            found.muted_seconds += region.length
            for begin, end in _windows(region.start, region.length):
                mine = levels.at(track, begin, end)
                if mine is None:
                    continue
                muted_levels.append(mine)
                other = loudest_other(track, begin, end)
                if other is not None:
                    bleed_levels.append(mine)
                    bleed_gaps.append(other - mine)
        found.frames = len(muted_levels)
        found.bleed_frames = len(bleed_gaps)

        if not muted_levels:
            found.reason = ("ääntä ei löytynyt" if levels.missing
                            else "ei käsin vaimennettuja alueita")
            out[track.name] = found
            continue
        if found.muted_seconds < MIN_SECONDS:
            found.reason = (f"vaimennettua ääntä vain {found.muted_seconds:.1f} s — "
                            f"liian vähän, vähintään {MIN_SECONDS:.0f} s")
            out[track.name] = found
            continue

        # Päästettävä tieto kerätään ennen kynnystä, koska ero-raja ei saa
        # riippua siitä onnistuiko kynnys: kaksi eri todistetta.
        speech_levels: list[float] = []
        speech_gaps: list[float] = []
        for begin, end in words[track.name]:
            mine = levels.at(track, begin, end)
            if mine is None:
                continue
            speech_levels.append(mine)
            other = loudest_other(track, begin, end)
            if other is not None:
                speech_gaps.append(other - mine)

        if len(bleed_gaps) >= MIN_BLEED_FRAMES:
            found.bleed_gap = float(np.percentile(bleed_gaps, BLEED_GAP_PERCENTILE))
            if len(speech_gaps) >= MIN_SPEECH_WORDS:
                found.speech_gap = float(np.percentile(speech_gaps, SPEECH_GAP_PERCENTILE))
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

        threshold = float(np.percentile(muted_levels, PERCENTILE)) + MARGIN_DB
        if len(bleed_levels) >= MIN_BLEED_FRAMES:
            # Vuoto mitataan erikseen: harvinainen vuoto ei näy koko vaimennetun
            # ajan persentiilissä, mutta se on juuri se mitä kynnyksen pitää
            # estää.
            threshold = max(threshold,
                            float(np.percentile(bleed_levels, PERCENTILE)) + MARGIN_DB)

        speech = _speech_levels(session, track, cache, extra_dir)
        if speech:
            found.speech_p25 = float(np.percentile(speech, 25))
            if threshold >= found.speech_p25 - GUARD_DB:
                found.reason = (
                    f"vaimennettujen alueiden taso ({threshold:.1f} dBFS) on puheen "
                    f"tasolla ({found.speech_p25:.1f} dBFS) — vaimennettiinko puhetta?")
                out[track.name] = found
                continue

        # Päästettävä on päästettävä: muokatulla ajalla vaimentamatta jätetty
        # sana on käyttäjän oma päätös, eikä kynnys saa jäädä sen yläpuolelle.
        if len(speech_levels) >= MIN_SPEECH_WORDS:
            ceiling = min(speech_levels) - KEEP_MARGIN_DB
            if threshold > ceiling:
                found.clamp_note = (
                    f"kynnys {threshold:.1f} → {ceiling:.1f} dBFS: vaimentamatta "
                    "jätetty sana on sen alla")
                threshold = ceiling
        found.threshold = threshold
        out[track.name] = found
    return out
