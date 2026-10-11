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

Mikään tässä tiedostossa olevista luvuista ei ole mitattu. Ne ovat makuarvoja
ja ensimmäisen oikean istunnon tarkistamatta: aja ``learn`` istunnolla ja
katso lokista mitä raita sai.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from speechmix.dsp import FLOOR_DB

from .. import audio as audio_io
from ..nhsx import Session, TrackInfo, locate
from .detect import AudioCache, is_muted, region_words

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


@dataclass
class Calibration:
    """Yhden raidan opittu kynnys, tai syy miksi sitä ei ole."""

    threshold: float | None = None   # dBFS sanan ikkunassa; ``None`` = ei opittu
    muted_seconds: float = 0.0
    frames: int = 0
    speech_p25: float | None = None
    reason: str = ""


def _frames(samples: np.ndarray, start: float, length: float) -> list[float]:
    """Alueen tasot sanan mittaisilla ikkunoilla, desibeleinä (lattia ``FLOOR_DB``)."""
    if length < 0.1:
        return []
    if length <= WINDOW:
        spans = [(start, start + length)]
    else:
        spans = []
        t = start
        while t + WINDOW <= start + length + 1e-9:
            spans.append((t, t + WINDOW))
            t += HOP
    return [max(audio_io.dbfs(samples, a, b), FLOOR_DB) for a, b in spans]


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


def calibrate_track(session: Session, track: TrackInfo, cache: AudioCache,
                    extra_dir: str = "") -> Calibration:
    frames: list[float] = []
    seconds = 0.0
    missing: set[str] = set()
    for region in track.regions:
        if not is_muted(region):
            continue
        info = session.file_by_id(region.ref)
        path = locate(session, info, extra_dir) if info is not None else ""
        samples = cache.get(path) if path else None
        if samples is None:
            if info is not None:
                missing.add(info.name)
            continue
        seconds += region.length
        frames += _frames(samples, region.offset, region.length)

    found = Calibration(muted_seconds=seconds, frames=len(frames))
    if not frames:
        found.reason = ("ääntä ei löytynyt" if missing
                        else "ei käsin vaimennettuja alueita")
        return found
    if seconds < MIN_SECONDS:
        found.reason = (f"vaimennettua ääntä vain {seconds:.1f} s — liian vähän, "
                        f"vähintään {MIN_SECONDS:.0f} s")
        return found

    threshold = float(np.percentile(frames, PERCENTILE)) + MARGIN_DB
    speech = _speech_levels(session, track, cache, extra_dir)
    if speech:
        found.speech_p25 = float(np.percentile(speech, 25))
        if threshold >= found.speech_p25 - GUARD_DB:
            found.reason = (
                f"vaimennettujen alueiden taso ({threshold:.1f} dBFS) on puheen "
                f"tasolla ({found.speech_p25:.1f} dBFS) — vaimennettiinko puhetta?")
            return found
    found.threshold = threshold
    return found


def calibrate(session: Session, cache: AudioCache | None = None,
              extra_dir: str = "") -> dict[str, Calibration]:
    """Raita -> opittu kynnys. Raidalla jolla ei ole mitään opittavaa on syy."""
    cache = cache or AudioCache()
    return {track.name: calibrate_track(session, track, cache, extra_dir)
            for track in session.tracks}
