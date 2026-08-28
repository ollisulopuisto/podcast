"""automixerin puheketju on jaettu ketju, ei toinen toteutus siitä.

`SPEECHMIX-INVENTORY.md` mittasi mitä automixerin oma ketju tekee ja mitä
`packages/speechmix` tekee samoissa kohdissa. Neljä eroa oli mitattavia
vikoja eikä makuasioita, ja jokainen niistä on tässä väitteenä:

* naksunpoisto ei poista mitään (0 näytettä muuttuu millään herkkyydellä)
* masterin katto on `-1.0 dBFS` näytehuipuista laskettuna, ja todellinen
  huippu jää **0,59 dB sen yli** — juuri se ylitys joka leikkaa lossy-
  koodauksessa
* monikaistatila liikuttaa kaistojen tasapainoa **13,56 dB**, ohjelman
  mukana
* kompressorivaiheilla ei ole vaimennuskattoa

Jokainen alla oleva testi kaatui vanhalla ketjulla. Viimeinen on
rakenteellinen: se väittää että automixer kutsuu kirjaston **oliota**, ei
omaa kopiotaan siitä — `is`, ei yhtäsuuruus, kuten
`apps/autoraffkat/tests/test_shared_pipeline.py`. Uudelleen kopioitu funktio
joka sattuu olemaan identtinen kaatuu silti, ja se on tarkoitus: kopio ei
kaadu koskaan, se alkaa vain hiljaa erota.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import signal as sp_signal

from automixer.domain import shared
from speechmix import chain

RATE = 44100


def speech(seconds: float = 3.0, rate: int = RATE) -> np.ndarray:
    """Epätasaisia puhepurskeita. Sama aineiston muoto kuin inventaariossa."""
    rng = np.random.default_rng(20260827)
    t = np.arange(int(seconds * rate)) / rate
    voice = (
        0.6 * np.sin(2 * np.pi * 120 * t)
        + 0.3 * np.sin(2 * np.pi * 340 * t)
        + 0.1 * np.sin(2 * np.pi * 2600 * t)
    )
    # Purskeet: puhetta ja taukoja, eri tasoilla.
    envelope = np.zeros_like(t)
    for start, length, level in ((0.2, 0.6, 1.0), (1.1, 0.5, 0.35), (2.0, 0.7, 0.8)):
        lo, hi = int(start * rate), int((start + length) * rate)
        envelope[lo:hi] = level
    envelope = sp_signal.savgol_filter(envelope, 1025, 2)
    return (voice * envelope + 0.002 * rng.normal(size=t.size)).astype(np.float32)


def with_clicks(audio: np.ndarray, rate: int = RATE, count: int = 5) -> np.ndarray:
    """Istuttaa huulinaksut taukoihin, kuten inventaarion mittauksessa."""
    out = audio.copy()
    for i in range(count):
        at = int((0.85 + i * 0.02) * rate) + i * 137
        click = np.sin(2 * np.pi * 7000 * np.arange(60) / rate) * 0.25
        out[at : at + 60] += click.astype(np.float32) * np.hanning(60).astype(np.float32)
    return out


def band_energies(audio: np.ndarray, rate: int = RATE) -> tuple[float, float, float]:
    """Energia kolmessa kaistassa desibeleinä — sama jako kuin ketjulla."""
    low = sp_signal.sosfilt(
        sp_signal.butter(4, 250 / (rate / 2), output="sos"), audio, axis=-1
    )
    rest = audio - low
    mid = sp_signal.sosfilt(
        sp_signal.butter(4, 4000 / (rate / 2), output="sos"), rest, axis=-1
    )
    high = rest - mid

    def db(part: np.ndarray) -> float:
        return 10.0 * np.log10(float(np.mean(part**2)) + 1e-20)

    return db(low), db(mid), db(high)


def true_peak_db(audio: np.ndarray) -> float:
    """Huippu 4× ylinäytteistettynä. Näytteiden väliin jäävä huippu on se,
    joka leikkaa D/A-muuntimessa eikä näy näytteitä katsomalla."""
    dense = sp_signal.resample_poly(np.asarray(audio, dtype=np.float64), 4, 1, axis=-1)
    return 20.0 * np.log10(float(np.abs(dense).max()) + 1e-12)


# --------------------------------------------------------------------------
# Rakenne: sama olio, ei kopio
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["declick", "deess", "compress", "multiband", "limiter", "peak_guard"],
)
def test_the_stage_is_the_librarys_own_object(name: str):
    """`is`, ei yhtäsuuruus: identtinen kopio kaatuu silti.

    Tämä on koko muutoksen tarkoitus. Kolme kopiota tästä ketjusta ajautui
    kerran erilleen, ja automixer oli neljä mitattua korjausta jäljessä kun
    se sulautettiin. Kopio ei kaadu koskaan — se alkaa vain erota.
    """
    assert getattr(shared, name) is getattr(chain, name)


def test_the_constants_come_from_the_library_too():
    """Vakio kopioituna on sama vika hitaammin: se ei kaadu, se jää jälkeen."""
    assert shared.CEILING_DB is chain.CEILING_DB
    assert shared.MAX_GR_DB is chain.MAX_GR_DB


@pytest.mark.parametrize(
    "method,module,name",
    [
        ("duck_envelopes", "envelopes", "duck_envelopes"),
        ("duck_gain", "envelopes", "duck_gain"),
        ("solo_masks", "masks", "solo_masks"),
        ("speech_masks", "masks", "speech_masks"),
        ("debleed", "debleed", "remove"),
    ],
)
def test_the_decision_layer_is_the_librarys_too(method, module, name, monkeypatch):
    """`room.py` on sauma, ei toteutus.

    Ketjun vaiheet olivat jaettuja jo ennen tätä; päätöskerros ei ollut,
    koska sen tie aikajanalle kulki FCPXML:n ``item.placements``in kautta.
    Nyt se on jaettu, ja tämä on se väite jota ei saa purkaa: jokainen
    `Room`in metodi kutsuu kirjaston omaa funktiota, joten autoraffkatin
    puolella mitattu korjaus tulee tänne samassa commitissa.

    Kirjaston funktio korvataan ja katsotaan kutsuttiinko sitä. Lähdekoodin
    lukeminen kelpaisi kanssa, mutta se menisi rikki muotoilusta; tämä menee
    rikki vain siitä mistä pitääkin, eli jos laskenta siirtyy tänne.
    """
    import importlib

    from automixer.domain import room

    called = []
    library = importlib.import_module(f"speechmix.{module}")
    original = getattr(library, name)

    def spy(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(library, name, spy)

    heard = room.listen(
        [
            room.Mic("A", speech()),
            room.Mic("B", (speech() * 0.25).astype(np.float32)),
        ],
        RATE,
    )
    {
        "duck_envelopes": lambda: heard.duck_envelopes(room.DuckSettings()),
        "duck_gain": lambda: heard.duck_gain("A", [(0.0, 0.0), (1.0, -9.0)], RATE),
        "solo_masks": heard.solo_masks,
        "speech_masks": heard.speech_masks,
        "debleed": lambda: heard.debleed(
            "A", heard.samples_of("A"), {"B": heard.samples_of("B")}
        ),
    }[method]()

    assert called, f"Room.{method} ei kutsunut speechmix.{module}.{name}"


def test_the_duck_defaults_are_the_measured_ones():
    """Mitattu luku kopioituna on kaksi vastausta samaan kysymykseen.

    Vaimennuksen ajat ja syvyys mitattiin oikealla aineistolla ja olivat
    autoraffkatin ``AudioSettings``issa. Jos automixer kirjoittaisi omansa,
    ne eivät kaataisi mitään — ne alkaisivat vain erota, ja kaksi eri
    vaimennusta yhden nimen alla on tarkalleen se vika jota vastaan tämä
    työtila on.

    autoraffkatin puolella on tämän peilikuva. Kumpikin sovellus
    tarkistetaan **kirjastoa** vastaan eikä toista sovellusta vastaan:
    kirjasto on se yksi paikka jossa muutos tehdään, eikä kummankaan testin
    tarvitse tuoda toista sovellusta sisään.
    """
    from automixer.domain.room import DuckSettings
    from speechmix import masks

    made = DuckSettings()
    assert made.duck_db == masks.DUCK_DB
    assert made.duck_fade == masks.DUCK_FADE
    assert made.duck_release == masks.DUCK_RELEASE
    assert made.duck_hold == masks.DUCK_HOLD
    assert made.duck_lookahead == masks.DUCK_LOOKAHEAD
    assert made.duck_min_open == masks.DUCK_MIN_OPEN
    assert made.duck_min_closed == masks.DUCK_MIN_CLOSED
    assert made.duck_dominance_db == masks.DUCK_DOMINANCE_DB


# --------------------------------------------------------------------------
# 1. Naksunpoisto tekee jotain
# --------------------------------------------------------------------------


def test_the_declicker_removes_a_planted_click():
    """Vanha `DeSmackProcessor` muutti 0 näytettä millään herkkyydellä.

    Se vertasi jokaista näytettä oman ympäristönsä liukuvaan **maksimiin**
    kerrottuna 2–5:llä, mitä mikään ei voi ylittää. Mitattuna viidellä
    istutetulla naksulla: 0 muutettua näytettä herkkyyksillä 0,0, 0,5 ja 1,0.
    """
    dirty = with_clicks(speech())
    cleaned = shared.declick(dirty[None, :], RATE, sensitivity=0.5)[0]

    changed = int(np.count_nonzero(~np.isclose(cleaned, dirty, atol=1e-7)))
    assert changed > 0, "naksunpoisto ei koskenut yhteenkään näytteeseen"

    # Ja se osui naksuihin eikä puheeseen: yläkaistan huippu laskee.
    def hf_peak(x: np.ndarray) -> float:
        sos = sp_signal.butter(4, 4000, "hp", fs=RATE, output="sos")
        return float(np.abs(sp_signal.sosfiltfilt(sos, x)).max())

    assert hf_peak(cleaned) < hf_peak(dirty)


# --------------------------------------------------------------------------
# 2. Katto pitää siellä missä se sanoo pitävänsä
# --------------------------------------------------------------------------


def test_the_ceiling_holds_at_the_true_peak():
    """Vanha rajoitin laski näytehuipuista, ja jätti 0,59 dB katon yli.

    Mitattuna −14 LUFSiin normalisoidulla puheella: sisään +2,12 dBFS /
    +2,33 dBTP, ulos −1,00 dBFS / **−0,41 dBTP**. Näytteiden väliin jäävä
    huippu on se joka leikkaa, ja lossy-koodaus nostaa sitä vielä.
    """
    loud = (speech() * 4.0).astype(np.float32)[None, :]
    limited, _ = shared.limiter(loud, RATE)

    assert true_peak_db(limited) <= shared.CEILING_DB + 0.1


def test_the_ceiling_does_not_step_the_gain():
    """Vanhan vahvistuskäyrän suurin näytteestä toiseen -askel oli 120 dB.

    Pehmentämätön käyrä on itsessään särölähde: se moduloi signaalia
    askeleen taajuudella.
    """
    loud = (speech() * 4.0).astype(np.float32)[None, :]
    gain = shared.limiter_gain(loud, RATE)

    step_db = np.abs(np.diff(20.0 * np.log10(np.maximum(gain, 1e-9))))
    assert float(step_db.max()) < 6.0


# --------------------------------------------------------------------------
# 3. Monikaista ei liikuta sävyä
# --------------------------------------------------------------------------


def test_multiband_keeps_the_band_balance():
    """Vanha tila vahvisti jokaisen kaistan erikseen −23 LUFSiin.

    Mitattuna: matalat −11,02 dB, keskitaajuudet −9,09 ja ylätaajuudet
    +2,54 — eli kaistojen tasapaino liikkui **13,56 dB**, ja se liikkui eri
    tavalla sen mukaan mitä puhuttiin. Jaettu `multiband` käyttää samaa
    suhdetta ja samaa vaimennuskattoa joka kaistalle juuri tästä syystä.
    """
    quiet = speech()[None, :]
    before = band_energies(quiet[0])
    after = band_energies(
        shared.multiband(quiet, RATE, threshold_db=-12.0, ratio=3.0)[0]
    )

    moves = [a - b for b, a in zip(before, after, strict=True)]
    assert max(moves) - min(moves) < 3.0, dict(zip("lmh", moves, strict=True))


# --------------------------------------------------------------------------
# 4. Jokaisella vaiheella on vaimennuskatto
# --------------------------------------------------------------------------


def test_a_compressor_stage_cannot_pull_more_than_its_cap():
    """Kaksi kattamatonta vaihetta reagoi yhteen napsahdukseen koko lauseen
    voimalla, ja juuri se kuullaan pumppauksena."""
    loud = (speech() * 3.0).astype(np.float32)[None, :]
    out = shared.compress(
        loud,
        RATE,
        threshold_db=-30.0,
        ratio=8.0,
        max_gr_db=shared.MAX_GR_DB,
        attack_ms=15.0,
        release_ms=80.0,
    )

    moving = np.abs(out[0]) > 1e-6
    ratio_db = 20.0 * np.log10(
        np.abs(out[0][moving]) / np.maximum(np.abs(loud[0][moving]), 1e-12)
    )
    assert float(-ratio_db.max(initial=0.0)) <= 0.01
    assert float(-ratio_db.min()) <= shared.MAX_GR_DB + 0.5


# --------------------------------------------------------------------------
# 5. Sihinä hoidetaan ennen kompressoreita
# --------------------------------------------------------------------------


def test_sibilance_is_tamed_and_the_body_is_not():
    """automixerillä ei ollut sihinänpoistoa lainkaan.

    Ongelma ei ole s-äänteen kovuus vaan se, että s ohjaa kompressoria:
    ilman tätä yksi sihahdus vetää koko lauseen alas.
    """
    body = speech()
    hiss = np.zeros_like(body)
    at = int(0.4 * RATE)
    rng = np.random.default_rng(4)
    hiss[at : at + int(0.15 * RATE)] = 0.5 * rng.normal(size=int(0.15 * RATE))
    sos = sp_signal.butter(4, 6000, "hp", fs=RATE, output="sos")
    hiss = sp_signal.sosfilt(sos, hiss).astype(np.float32)

    noisy = (body + hiss)[None, :]
    tamed = shared.deess(noisy, RATE)

    def energy(x: np.ndarray, lo: float, hi: float) -> float:
        sos = sp_signal.butter(4, [lo, hi], "bp", fs=RATE, output="sos")
        return float(np.mean(sp_signal.sosfilt(sos, x) ** 2))

    assert energy(tamed[0], 6000, 15000) < energy(noisy[0], 6000, 15000) * 0.9
    # Runko ei liiku mukana: jako on vähennyslasku, joten se summautuu takaisin.
    assert energy(tamed[0], 80, 1000) == pytest.approx(
        energy(noisy[0], 80, 1000), rel=0.05
    )
