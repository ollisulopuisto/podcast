"""Virtaava äänekkyysmittari: sama lukema kuin kerralla mitattuna.

Koko ohjelma ei mahdu muistiin — 77 minuuttia on 890 megatavua float32:na —
mutta äänekkyys on lohkoittainen suure, joten se voidaan kerätä virrasta.
Tämän testin koko tehtävä on että virrasta kerätty lukema on **sama** kuin
vertailutoteutuksen kerralla laskema.
"""

import numpy as np
import pytest

from speechmix.meter import IntegratedMeter

RATE = 48000


def _speechlike(seconds=30.0, rate=RATE, seed=4):
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    out = (rng.standard_normal(n) * 0.001).astype(np.float32)
    for start in np.arange(0.5, seconds - 1.0, 1.7):
        i0, i1 = int(start * rate), int((start + 0.9) * rate)
        t = np.arange(i1 - i0) / rate
        out[i0:i1] += (0.15 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    return out


@pytest.mark.parametrize("chunk", [4096, 48000, 100_000])
def test_the_streamed_reading_matches_a_single_pass(chunk):
    """Palakoko ei saa näkyä lukemassa.

    Suotimet ovat IIR-muotoisia, joten palan raja jättää jälkensä jos tilaa
    ei kanneta yli. Se on hiljainen vika: lukema on uskottava, vain väärä.
    """
    pyln = pytest.importorskip("pyloudnorm")
    audio = _speechlike()
    reference = pyln.Meter(RATE).integrated_loudness(audio.astype(np.float64))

    meter = IntegratedMeter(RATE)
    for at in range(0, len(audio), chunk):
        meter.add(audio[at : at + chunk])
    assert meter.value() == pytest.approx(reference, abs=0.1)


def test_silence_has_no_reading():
    """Portin alle jäävästä ohjelmasta ei ole lukemaa, ei nollaa."""
    meter = IntegratedMeter(RATE)
    meter.add(np.zeros(RATE * 5, dtype=np.float32))
    assert meter.value() is None


def test_a_gain_moves_the_reading_by_the_same_amount():
    """Kuusi desibeliä lisää on kuusi desibeliä lukemassa."""
    audio = _speechlike(10.0)
    quiet, loud = IntegratedMeter(RATE), IntegratedMeter(RATE)
    quiet.add(audio)
    loud.add(audio * (10 ** (6 / 20)))
    assert loud.value() - quiet.value() == pytest.approx(6.0, abs=0.05)


def test_momentary_and_short_term_have_the_right_windows():
    """400 ms ja 3 s, standardin ikkunat.

    Lyhyt piikki hiljaisessa ohjelmassa nostaa hetkellistä paljon ja
    lyhytaikaista vähän: se on ikkunoiden ero, ja väärä ikkuna näkyisi vain
    siinä että raja laukeaa väärään aikaan.
    """
    rate = RATE
    audio = np.full(rate * 10, 0.001, dtype=np.float32)
    audio[rate * 5 : rate * 5 + rate // 2] = 0.3      # 0,5 s kovaa
    meter = IntegratedMeter(rate)
    meter.add(audio)
    assert meter.momentary_max() > meter.short_term_max() + 4.0


def test_the_range_is_the_spread_of_the_short_term_values():
    """LRA: 10. ja 95. prosenttipisteen väli, EBU Tech 3342.

    Ohjelma jossa on kaksi tasoa 10 dB:n päässä toisistaan antaa noin
    kymmenen; tasainen ohjelma antaa lähes nollan.
    """
    rate = RATE
    rng = np.random.default_rng(9)
    flat = (rng.standard_normal(rate * 40) * 0.05).astype(np.float32)
    steady = IntegratedMeter(rate)
    steady.add(flat)
    assert steady.range() < 1.5, steady.range()

    varied = flat.copy()
    varied[: rate * 20] *= 10 ** (-10 / 20)
    swung = IntegratedMeter(rate)
    swung.add(varied)
    assert 7.0 < swung.range() < 13.0, swung.range()


def test_dialogue_gating_ignores_what_is_not_speech():
    """Puheportti: vain puhe lasketaan mukaan.

    RX arvioi puheen sijainnin itse 500 ms viipaleina. Meillä se on tiedossa
    — leikkaus on rakennettu sen päälle — joten portti on tarkempi kuin
    arvaus ja ilmainen.

    Hiljainen jakso ohjelman keskellä painaa integroitua alaspäin, ja
    alaspäin painettu lukema pyytää enemmän nostoa kuin ohjelma tarvitsee.
    Portin kanssa lukema on puheen lukema.
    """
    rate = RATE
    speech = _speechlike(20.0)
    # Ei hiljaisuutta vaan **muuta ääntä**: standardin oma suhteellinen
    # portti hylkää jo sen mikä on 10 LU puheen alla, joten hiljaisuudella
    # testattuna portti näyttäisi toimivan vaikka se ei tekisi mitään.
    # Ero syntyy vasta sisällöstä joka on tarpeeksi kovaa jäädäkseen
    # mukaan mutta ei ole puhetta.
    other = (np.random.default_rng(2).standard_normal(rate * 20) * 0.012)
    audio = np.concatenate([speech, other.astype(np.float32)])

    meter = IntegratedMeter(rate)
    meter.add(audio)
    ungated = meter.value()

    # Puhetta on ensimmäiset 20 s.
    times = meter.times()
    gated = meter.value(keep=times < 20.0)
    assert gated > ungated + 0.3, (ungated, gated)

    # Ja sama kuin pelkästä puheesta mitattuna.
    alone = IntegratedMeter(rate)
    alone.add(speech)
    assert gated == pytest.approx(alone.value(), abs=0.35)


def test_times_line_up_with_the_blocks():
    """Aikaleima on lohkon keskikohta, jotta maskin voi kohdistaa siihen."""
    meter = IntegratedMeter(RATE)
    meter.add(np.zeros(RATE * 5, dtype=np.float32))
    times = meter.times()
    assert len(times) == len(meter.momentary())
    assert times[0] == pytest.approx(0.2, abs=0.05)
    assert np.all(np.diff(times) > 0)


def test_the_speech_flag_travels_with_the_audio():
    """Maski kulkee palan mukana, ei erillisenä aikatauluna.

    Mittari saa palansa siinä järjestyksessä kuin isäntä ne lukee — eri
    osista, eri tiedostoista — ja maskin kohdistaminen jälkikäteen olisi
    arvaus siitä järjestyksestä. Väärin kohdistettuna portti hylkäisi puhetta
    ja päästäisi muun läpi, eikä lukemasta näkisi mitään.
    """
    rate = RATE
    speech = _speechlike(10.0)
    other = (np.random.default_rng(7).standard_normal(rate * 10) * 0.012)
    meter = IntegratedMeter(rate)
    meter.add(speech, speech=np.ones(speech.size, dtype=bool))
    meter.add(other.astype(np.float32), speech=np.zeros(other.size, dtype=bool))

    marks = meter.speech()
    assert marks[:80].mean() > 0.9, "puhe merkittiin muuksi"
    assert marks[-80:].mean() < 0.1, "muu merkittiin puheeksi"
    assert meter.value(keep=marks > 0.5) > meter.value() + 0.3
