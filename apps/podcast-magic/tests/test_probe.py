"""Mittasignaali on mittalaite, joten se mitataan.

Koko koeasetelma lepää sen varassa, että signaalin taso on **tarkalleen**
se joka väitetään: Hindenburgin renderöinnistä luetaan tasoja, ja jokainen
päätelmä on lähdetason ja renderöidyn tason erotus. Väärä lähdetaso ei
näy mitenkään — se siirtää jokaisen tuloksen saman verran ja näyttää
johdonmukaiselta.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from podcastmagic.nhsx.probe import MARK_LENGTH, MARK_SPACING, probe

RATE = 48_000


def test_the_level_is_exactly_what_it_claims():
    # -20 dBFS on huippuamplitudi 0,1 tasan. Toleranssi on yksi 24-bittinen
    # LSB (2**-23 ≈ 1,19e-7), ei "suunnilleen".
    x = probe(2.0, rate=RATE, level_db=-20.0)
    assert np.max(np.abs(x)) == pytest.approx(0.1, abs=2.0**-23)


def test_another_level_is_also_exact():
    x = probe(2.0, rate=RATE, level_db=-6.0)
    assert np.max(np.abs(x)) == pytest.approx(10.0 ** (-6.0 / 20.0), abs=2.0**-23)


def test_the_frequency_is_the_one_asked_for():
    # Nollan ylitykset ylöspäin: yksi jaksoa kohden.
    x = probe(2.0, rate=RATE, freq=1000.0, mark_spacing=0.0)
    ups = np.sum((x[:-1] <= 0) & (x[1:] > 0))
    assert ups == pytest.approx(2000, abs=1)


def test_one_cycle_is_a_whole_number_of_samples():
    # 1000 Hz / 48 kHz = 48 näytettä jaksossa tasan. Se on syy taajuuden
    # valintaan: aluerajalle ei jää katkaistua jaksoa, joten leikkauskohta
    # ei tuota napsahdusta jota voisi luulla häivytykseksi.
    assert RATE % 1000 == 0


def test_marks_are_silent_and_the_rest_is_not():
    x = probe(25.0, rate=RATE, level_db=-20.0)
    for k in range(1, 3):  # merkit 10 s ja 20 s kohdalla
        i = int(k * MARK_SPACING * RATE)
        j = i + int(MARK_LENGTH * RATE)
        assert np.max(np.abs(x[i:j])) == 0.0, f"merkki {k} ei ole vaiti"
        # Heti merkin jälkeen signaalin on jatkuttava täydellä tasolla.
        after = x[j : j + RATE // 10]
        assert np.max(np.abs(after)) == pytest.approx(0.1, abs=1e-6)


def test_there_is_no_mark_at_zero():
    # Merkki nollassa söisi alun häivytyksen ensimmäiset millisekunnit.
    x = probe(25.0, rate=RATE)
    assert np.max(np.abs(x[: int(0.2 * RATE)])) == pytest.approx(0.1, abs=1e-6)


def test_the_tone_keeps_its_phase_across_a_mark():
    # Merkki on vaimennus, ei katkos: sinin vaihe jatkuu kuin merkkiä ei
    # olisi. Muuten merkin jälkeinen vaihe olisi mielivaltainen, ja
    # verhokäyrän sovitus merkin yli tuottaisi roskaa.
    rate, freq = RATE, 1000.0
    x = probe(25.0, rate=rate, freq=freq)
    i = int((MARK_SPACING + MARK_LENGTH + 0.001) * rate)
    t = np.arange(i, i + 480) / rate
    expected = 0.1 * np.sin(2 * math.pi * freq * t)
    assert np.allclose(x[i : i + 480], expected, atol=1e-9)


def test_marks_can_be_turned_off():
    x = probe(25.0, rate=RATE, mark_spacing=0.0)
    assert np.min(np.abs(x[: int(24 * RATE)]).max()) > 0.0
    i = int(MARK_SPACING * RATE)
    assert np.max(np.abs(x[i : i + int(MARK_LENGTH * RATE)])) > 0.0


def test_the_length_is_the_length_asked_for():
    assert len(probe(3.5, rate=RATE)) == int(3.5 * RATE)


def test_the_landmarks_are_where_the_instructions_say():
    # Nämä kaksi lukua ovat rajapintaa eivätkä toteutusta: ohje, jonka
    # mukaan istunto rakennetaan, sanoo «10 sekunnin välein, 50 ms». Muut
    # testit lukevat vakiot moduulista, joten ne seuraisivat muutosta
    # mukana ja hyväksyisivät minkä tahansa arvon.
    assert (MARK_SPACING, MARK_LENGTH) == (10.0, 0.050)


def test_the_landmark_really_lands_on_the_whole_ten_seconds():
    # Sama syy: kirjoitettu auki, ei johdettu vakiosta.
    x = probe(25.0, rate=RATE)
    assert np.max(np.abs(x[10 * RATE : 10 * RATE + 2400])) == 0.0
    assert np.max(np.abs(x[20 * RATE : 20 * RATE + 2400])) == 0.0
    # ja 5 s kohdalla ei ole merkkiä
    assert np.max(np.abs(x[5 * RATE : 5 * RATE + 2400])) > 0.09
