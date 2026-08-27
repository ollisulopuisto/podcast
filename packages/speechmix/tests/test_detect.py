"""Kuka on äänessä: verhokäyrästä ruudukoksi.

Tämä on se kerros joka automixerilta puuttui kokonaan, ja sen puuttuminen
jätti tekemättä kolme asiaa jotka kaikki lukevat sitä: vaimennuksen,
ristivuodon vähennyksen ja tasonkuljettajan. Ne olivat kirjastossa valmiina —
ruudukkoa vain ei ollut mistä rakentaa.

Laskenta on numpyta ruudukon päällä, ei tiedostojen lukua: ``rms_db`` saa
näytteet, ``align`` verhokäyrän. Kuka ne lukee ja millä, on isännän asia —
autoraffkat purkaa ffmpegillä ja välimuistittaa levylle, automixerilla wav on
jo muistissa.
"""

import numpy as np
import pytest

from speechmix import detect, session
from speechmix.masks import HOP

RATE = 48000


def _bursts(seconds=4.0, rate=RATE, level=0.3, quiet=1e-4, seed=7):
    """Puhetta ja taukoja: kovaa sekunneittain, hiljaista väleissä."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    out = rng.normal(size=n).astype(np.float32) * quiet
    for start in (0.5, 2.0, 3.0):
        lo, hi = int(start * rate), int(min(start + 0.5, seconds) * rate)
        if hi > lo:
            out[lo:hi] += rng.normal(size=hi - lo).astype(np.float32) * level
    return out


def test_rms_db_is_one_number_per_grid_step():
    """Ruudukon askel on ``HOP``, ja verhokäyrä on sen mittainen."""
    audio = _bursts(seconds=4.0)

    db = detect.rms_db(audio, RATE)

    assert db.shape == (int(4.0 / HOP),)
    assert db.dtype == np.float32
    # Puheen kohdalla kovempaa kuin tauossa, ja ero on desibeleissä iso.
    speech = db[int(0.6 / HOP)]
    pause = db[int(1.5 / HOP)]
    assert speech - pause > 40.0, (speech, pause)


def test_silence_lands_on_the_floor_not_on_minus_infinity():
    """Nollasta otettu logaritmi on -inf, ja se leviää joka laskuun."""
    db = detect.rms_db(np.zeros(RATE, dtype=np.float32), RATE)
    assert np.all(db == detect.FLOOR_DB)


def test_the_noise_floor_is_measured_not_assumed():
    """Pohja on aineiston hiljaisin viidennes, ei vakio.

    Herkkyys on kynnys **pohjan yli**, joten pohjan on tultava samasta
    aineistosta — muuten säädin tarkoittaisi eri asiaa eri mikillä.
    """
    db = detect.rms_db(_bursts(), RATE)
    valid = np.ones(db.shape, dtype=bool)

    floor = detect.noise_floor(db, valid)

    assert detect.FLOOR_DB < floor < float(db.max())
    assert floor == pytest.approx(
        float(np.percentile(db, detect.NOISE_PERCENTILE)), abs=1e-4
    )
    # Ilman yhtään kelvollista solua pohja on lattia, ei kaatuminen.
    assert detect.noise_floor(db, np.zeros(db.shape, dtype=bool)) == detect.FLOOR_DB


def test_align_puts_the_file_curve_on_the_programme_grid():
    """Verhokäyrä on tiedostoaikaa, ruudukko aikajanan aikaa."""
    # Tiedosto on aikajanalla 10–14 s ja alkaa omasta hetkestään 0.
    track = session.whole_file("", start=10.0, duration=4.0)
    envelope = np.full(int(4.0 / HOP), -30.0, dtype=np.float32)
    envelope[int(1.0 / HOP) : int(2.0 / HOP)] = -6.0  # tiedoston sekunti 1–2

    db, valid = detect.align(track, envelope, 0.0, int(20.0 / HOP))

    assert db.shape == (int(20.0 / HOP),)
    assert not valid[: int(10.0 / HOP)].any(), "ennen klippiä ei ole mediaa"
    assert valid[int(10.5 / HOP)]
    assert not valid[int(15.0 / HOP) :].any()
    # Tiedoston sekunti 1–2 on aikajanan 11–12.
    assert db[int(11.5 / HOP)] == pytest.approx(-6.0)
    assert db[int(13.0 / HOP)] == pytest.approx(-30.0)
    # Mediattomassa kohdassa lattia, ei edellinen arvo.
    assert db[int(2.0 / HOP)] == detect.FLOOR_DB


def test_sensitivity_is_a_threshold_over_the_floor_so_gain_does_not_move_it():
    """Vahvistus siirtää sekä signaalin että pohjan.

    Tämä on autoraffkatin sääntö, ja se on täällä koska se on nyt myös
    automixerin: säätimet lakkaavat tarkoittamasta mitään jos vahvistus
    liikuttaa kynnystä. Vahvistus vaikuttaa vain mikkien keskinäiseen
    vertailuun päällekkäispuheessa, ja se näkyy ``level``issä.
    """
    track = session.whole_file("", start=0.0, duration=4.0)
    envelope = detect.rms_db(_bursts(), RATE)
    n = int(4.0 / HOP)

    measured = detect.curve(track, envelope, 0.0, n)
    plain = detect.lane("A", [(*measured, 12.0, 0.0)], n)
    louder = detect.lane("A", [(*measured, 12.0, 6.0)], n)

    assert np.array_equal(plain.on, louder.on), "vahvistus ei saa liikuttaa kynnystä"
    heard = louder.level > detect.FLOOR_DB
    assert np.allclose(louder.level[heard], plain.level[heard] + 6.0)


def test_a_speaker_with_two_files_is_one_lane():
    """Monikamerassa sama mikki on oma tiedostonsa joka osassa.

    Sama puhuja, sama säädin, eri kohta aikajanaa — ja yksi kaista, koska
    päätöskerros kysyy puhujilta eikä tiedostoilta.
    """
    envelope = detect.rms_db(_bursts(seconds=2.0), RATE)
    n = int(4.0 / HOP)
    first = session.whole_file("a.wav", start=0.0, duration=2.0)
    second = session.whole_file("b.wav", start=2.0, duration=2.0)

    lane = detect.lane(
        "A",
        [
            (*detect.curve(first, envelope, 0.0, n), 12.0, 0.0),
            (*detect.curve(second, envelope, 0.0, n), 12.0, 0.0),
        ],
        n,
    )

    assert lane.on[: n // 2].any()
    assert lane.on[n // 2 :].any()


def test_the_grid_carries_the_lanes_in_order():
    """Ruudukko on päätöskerroksen syöte, ja kaistat ovat sen sisältö."""
    envelope = detect.rms_db(_bursts(), RATE)
    track = session.whole_file("", start=0.0, duration=4.0)
    n = int(4.0 / HOP)

    grid = detect.grid_for(
        {name: [(track, envelope, 12.0, 0.0)] for name in ("Olli", "Nyman")}, 0.0, n
    )

    assert grid.n == n
    assert grid.program_start == 0.0
    assert [lane.name for lane in grid.speakers] == ["Olli", "Nyman"]
    assert grid.duration == pytest.approx(4.0)


def test_the_grid_feeds_the_masks_the_library_already_had():
    """Koko pointti: ruudukko riittää, loput on jo kirjastossa.

    ``duck_masks``, ``solo_masks`` ja ``speech_masks`` lukevat vain
    ``grid.speakers``in ``name``, ``on`` ja ``level`` -kenttiä. Sillä
    hetkellä kun isäntä osaa rakentaa ruudukon, se saa vaimennuksen,
    ristivuodon estimoinnin ja tasonkuljettajan maskin ilman riviäkään omaa
    koodia.
    """
    from speechmix import masks

    n = 800
    a = np.zeros(n, dtype=bool)
    b = np.zeros(n, dtype=bool)
    a[: n // 2] = True
    b[n // 2 :] = True
    grid = detect.Grid(
        n=n,
        program_start=0.0,
        speakers=[
            detect.Lane("a", np.full(n, -20.0, dtype=np.float32), a),
            detect.Lane("b", np.full(n, -20.0, dtype=np.float32), b),
        ],
    )

    solos = masks.solo_masks(grid)
    assert set(solos) == {"a", "b"}
    assert solos["a"][: n // 2].all() and not solos["a"][n // 2 :].any()
    assert masks.speech_masks(grid)["b"][n // 2 :].all()
