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
