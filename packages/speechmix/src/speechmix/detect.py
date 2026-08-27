"""Kuka on äänessä: verhokäyrästä ruudukoksi.

Ruudukko on aikajanan aikaa ``HOP`` sekunnin askelin, ja se on koko
päätöskerroksen syöte: ``masks``, ``envelopes`` ja ``debleed`` lukevat vain
sitä. Se on myös se kerros joka automixerilta puuttui — kolme valmista
ominaisuutta jäi käyttämättä siksi, ettei ruudukkoa ollut mistä rakentaa.

**Kaksi kerrosta, älä sekoita niitä.** Verhokäyrän laskenta on hidas ja
tapahtuu kerran tiedostoa kohden; ruudukon rakentaminen on nopea ja tapahtuu
joka säädöllä. ``rms_db`` on hitaan kerroksen laskenta ilman tiedostojen
lukua: isäntä hankkii näytteet miten haluaa — autoraffkat purkaa ffmpegillä
ja välimuistittaa levylle, automixerilla wav on jo muistissa — ja saa saman
käyrän. ``align`` ja ``lane`` ovat nopeaa kerrosta: pelkkää numpyta, ei
silmukkaa yksittäisten näytteiden yli.

Siirretty autoraffkatin ``analysis.py``:stä ja ``audio/envelope.py``:stä, ei
kopioitu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np

from .masks import HOP
from .session import Track

#: Hiljaisuuden lukema. Nollasta otettu logaritmi on -inf, ja se leviää
#: jokaiseen laskuun johon se päätyy — pohjakohinan mediaaniin, kynnykseen,
#: esikatselupalkkiin.
FLOOR_DB = -120.0

#: Liukuvan keskiarvon pituus. Tasoittaa tavuvälit, joita ei haluta
#: leikkauksiksi eikä vaimennuksen aukoiksi.
SMOOTH_SECONDS = 0.10

#: Mistä kohtaa jakaumaa pohjakohina luetaan. Viidennes on tarpeeksi alhaalta
#: ollakseen taukoa myös vilkkaassa puheessa, ja tarpeeksi ylhäältä ettei se
#: osu yksittäiseen digitaaliseen nollaan.
NOISE_PERCENTILE = 20.0


def rms_db(samples, rate: int, hop: float = HOP) -> np.ndarray:
    """RMS-desibelit ``hop`` sekunnin välein tiedoston alusta.

    Verhokäyrä indeksoidaan **tiedoston** alusta eikä aikajanasta, jotta sama
    välimuisti kelpaa vaikka klippi siirtyisi aikajanalla.

    Näytetaajuus saa olla mikä tahansa: ikkuna on sekunneissa ja tulos
    desibeleissä, joten kahdeksan kilohertsin purku ja 48 kilohertsin wav
    antavat saman käyrän. autoraffkat purkaa kahdeksaan, koska se riittää
    puheen energialle ja on neljäsosa purkuajasta.
    """
    win = max(1, int(round(rate * hop)))
    flat = np.asarray(samples, dtype=np.float32).reshape(-1)
    usable = (flat.size // win) * win
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = flat[:usable].reshape(-1, win)
    mean_sq = np.mean(np.square(frames, dtype=np.float64), axis=1)
    db = 10.0 * np.log10(np.maximum(mean_sq, 1e-12))
    return np.maximum(db, FLOOR_DB).astype(np.float32)


def smooth(db: np.ndarray, seconds: float = SMOOTH_SECONDS) -> np.ndarray:
    """Liukuva keskiarvo. Tasoittaa tavuvälit, joita ei haluta leikkauksiksi."""
    k = max(1, int(round(seconds / HOP)))
    if k <= 1 or db.size < k:
        return db
    kernel = np.ones(k, dtype=np.float32) / k
    return np.convolve(db, kernel, mode="same").astype(np.float32)


def noise_floor(db: np.ndarray, valid: np.ndarray) -> float:
    """Pohjakohina: aineiston hiljaisin viidennes siellä missä on mediaa.

    Riippuu vain verhokäyrästä, ei säätimistä, joten se lasketaan kerran ja
    säilyy säädöstä toiseen. Ilman yhtäkään kelvollista solua vastaus on
    lattia — kysymys on kelvollinen, aineistoa ei vain ole.
    """
    valid = np.asarray(valid, dtype=bool)
    if not valid.any():
        return FLOOR_DB
    return float(np.percentile(np.asarray(db)[valid], NOISE_PERCENTILE))


def align(track: Track, envelope: np.ndarray, program_start,
          n: int) -> tuple[np.ndarray, np.ndarray]:
    """Verhokäyrä aikajanan ruudukolle. Palauttaa ``(dB, onko mediaa)``.

    Muunnos on jakson sisällä lineaarinen, sama kaava kuin
    ``session.file_ranges``issa. Ruudukon kohta johon tämä tiedosto ei yllä
    jää lattiaan ja merkitään mediattomaksi: se on eri asia kuin hiljaisuus,
    ja pohjakohina laskettaisiin väärin jos ne menisivät sekaisin.
    """
    out = np.full(n, FLOOR_DB, dtype=np.float32)
    valid = np.zeros(n, dtype=bool)
    if n <= 0 or np.asarray(envelope).size == 0:
        return out, valid
    envelope = np.asarray(envelope)
    start_f = float(program_start)
    # Ruudukon loppu isännän omassa lukutyypissä: Fractionilla tarkasti,
    # koska liukuluvun viimeinen bitti riittää pudottamaan reunan solun.
    step = Fraction(1, 50) if isinstance(program_start, Fraction) else HOP
    program_end = program_start + n * step

    for span in track.spans:
        lo = max(span.start, program_start)
        hi = min(span.end, program_end)
        if hi <= lo:
            continue
        i0 = max(0, int(np.ceil((float(lo) - start_f) / HOP)))
        i1 = min(n, int(np.floor((float(hi) - start_f) / HOP)))
        if i1 <= i0:
            continue
        idx = np.arange(i0, i1)
        base = float(span.base)
        file_t = base + start_f + idx * HOP
        cells = np.rint(file_t / HOP).astype(np.int64)
        ok = (cells >= 0) & (cells < envelope.size)
        out[idx[ok]] = envelope[cells[ok]]
        valid[idx[ok]] = True
    return out, valid


@dataclass
class Lane:
    """Yhden puhujan aineisto ruudukolla.

    ``level`` on desibeliä vahvistuskorjaus mukaan luettuna, ``on`` kynnyksen
    ylitys. Nämä kaksi ovat kaikki mitä ``masks`` lukee: ``on`` kertoo kuka
    on äänessä ja ``level`` ratkaisee päällekkäispuheen «kovin voittaa».
    """

    name: str
    level: np.ndarray
    on: np.ndarray


@dataclass
class Grid:
    """Päätöskerroksen syöte: kaikki ruudukolle kohdistettuna."""

    n: int  # ruudukon pituus (HOP-askelta)
    program_start: float  # aikajanan sekunneissa
    speakers: list[Lane] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.n * HOP


def curve(track: Track, envelope: np.ndarray, program_start,
          n: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Yhden tiedoston osuus ruudukosta: ``(dB, onko mediaa, pohjakohina)``.

    Erillään ``lane``sta, koska tämä riippuu vain verhokäyrästä ja isäntä saa
    siksi välimuistittaa sen. autoraffkatilla se on pakko: ruudukko
    rakennetaan uudestaan joka kerta kun liukusäädintä liikautetaan, ja
    kohdistus koko ohjelman yli jokaisella säädöllä olisi juuri se hidastus
    jota vastaan kerrosjako on. Säätimet luetaan vasta ``lane``ssa, joten
    tämän tulos kelpaa niiden muuttuessakin.
    """
    db, valid = align(track, envelope, program_start, n)
    db = smooth(db)
    return db, valid, noise_floor(db, valid)


def lane(name: str, parts, n: int) -> Lane:
    """Yksi kaista: puhuja, ja kaikki tiedostot joissa hänen mikkinsä on.

    ``parts`` on ``(db, valid, floor, sensitivity_db, gain_db)`` -viisikoita,
    yksi kutakin tiedostoa kohden — niitä on useampi kun sama mikki on oma
    tiedostonsa joka osassa. Sama säädin, sama puhuja, eri kohta aikajanaa.

    **Herkkyys on kynnys pohjakohinan yli, vahvistus ei liikuta sitä.**
    Vahvistus siirtää sekä signaalin että pohjan, joten kynnys pysyy; se
    vaikuttaa vain mikkien keskinäiseen vertailuun päällekkäispuheessa, ja
    siksi se on ``level``issä eikä ``on``issa. Sekoita nämä ja säätimet
    alkavat häiritä toisiaan.
    """
    level = np.full(n, FLOOR_DB, dtype=np.float32)
    on = np.zeros(n, dtype=bool)
    for db, valid, floor, sensitivity_db, gain_db in parts:
        if not np.asarray(valid).any():
            continue
        on |= valid & (db > floor + sensitivity_db)
        level = np.maximum(level, db + gain_db)
    return Lane(name=name, level=level, on=on)


def grid_for(sources_by_speaker: dict, program_start, n: int) -> Grid:
    """Ruudukko puhujittain: ``{nimi: [(track, envelope, herkkyys, gain)]}``.

    Tämä on koko sauma päätöskerrokseen ilman välimuistia: isäntä jolla ei ole
    säätösilmukkaa saa ruudukon yhdellä kutsulla. Isäntä jolla on, kutsuu
    ``curve``a ja ``lane``a erikseen ja välimuistittaa väliin.

    Isännän vastuulle jää tietää kenen mikki mikäkin tiedosto on ja mistä
    näytteet tulevat; sen jälkeen vaimennus, ristivuodon estimointi ja
    tasonkuljettajan maski ovat samaa koodia riippumatta siitä luettiinko
    istunto FCPXML:stä, ``.nhsx``:stä vai wav-tiedostojen listasta.
    """
    return Grid(
        n=n,
        program_start=float(program_start),
        speakers=[
            lane(
                name,
                [
                    (*curve(track, envelope, program_start, n), sensitivity_db, gain_db)
                    for track, envelope, sensitivity_db, gain_db in sources
                ],
                n,
            )
            for name, sources in sources_by_speaker.items()
        ],
    )
