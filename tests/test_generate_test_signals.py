"""Testisignaalityökalun testit: lähteet ovat pelkkää ääntä, lait ovat UI:ssä.

Jos joku alkaa taas paalata panin, häivytyksen, automaation tai efekin
WAV:ihin, testisignaali mittaisi generointiohjelmaa eikä Hindenburgia —
ja PARSER-NEEDS.md:n kaikki luvut olisivat mitättämiä.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

_gen_path = Path(__file__).parent.parent / "scripts" / "generate_test_signals.py"
_spec = importlib.util.spec_from_file_location("generate_test_signals", _gen_path)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def per_second_rms(x: np.ndarray) -> np.ndarray:
    """Sekunnittainen RMS: tasaisen lähteen kurve on vakio."""
    seg = gen.SAMPLE_RATE
    return np.array(
        [np.sqrt(np.mean(x[i * seg : (i + 1) * seg] ** 2)) for i in range(len(x) // seg)]
    )


def test_file_a_sources_carry_no_laws(tmp_path):
    """File A: pan ja häivytykset ovat UI-asetuksia, ei lähteen sisältöä."""
    gen.generate_file_a_laws(tmp_path)

    for name in ("A4_pan_0.625.wav", "A5_pan_m0.55.wav"):
        x, _ = sf.read(tmp_path / name)
        assert x.ndim == 1, f"{name} pitää olla mono — pan kuuluu UI:lle"

    for name in ("A7_fade_plateau.wav", "A8_fade_short.wav"):
        x, _ = sf.read(tmp_path / name)
        rms = per_second_rms(x)
        cv = rms.std() / rms.mean()
        assert cv < 0.05, f"{name} ei ole tasainen (cv={cv:.3f}) — häivytys kuuluu UI:lle"


def test_file_c_sources_carry_no_structure(tmp_path):
    """File C: automaatio ja efektit ovat UI-asetuksia, ei lähteen sisältöä."""
    gen.generate_file_c_structure(tmp_path)

    x, _ = sf.read(tmp_path / "C5_pan_sweep.wav")
    assert x.ndim == 1, "C5 pitää olla mono — pan-automaatio kuuluu UI:lle"

    for name in ("C3_reverb.wav", "C4_master_fade.wav"):
        x, _ = sf.read(tmp_path / name)
        rms = per_second_rms(x)
        cv = rms.std() / rms.mean()
        assert cv < 0.05, f"{name} ei ole tasainen (cv={cv:.3f})"


def test_file_d_tones_are_pure_and_bin_centred(tmp_path):
    """File D: sinusit ovat puhtaita ja analyysi-ikkunan keskellä.

    Liukuvan Goertzelin erottaa 400 ja 1000 Hz:n päällekkäin asetettujen
    alueiden kuoret vain jos taajuudet ovat tarkkoja: 400 Hz on 120
    näytteen jakso (48 kHz), 1000 Hz on 48 — molemmat tasan, joten
    ikkunavuoto ei valehde kuoren pituudesta.
    """
    gen.generate_file_d_joints(tmp_path)
    sr = gen.SAMPLE_RATE

    for name, freq in (("D1_tone_400.wav", 400.0), ("D2_tone_1000.wav", 1000.0)):
        x, _ = sf.read(tmp_path / name)
        spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        freqs = np.fft.rfftfreq(len(x), 1 / sr)
        assert freqs[np.argmax(spec)] == pytest.approx(freq, abs=1.0), name
        # toiseksi suurin vaihe > 40 dB piikin alla: ei säröä, ei kohinaa
        spec_rest = spec.copy()
        spec_rest[np.argmax(spec)] = 0
        spec_rest[max(0, np.argmax(spec) - 40): np.argmax(spec) + 40] = 0
        assert 20 * np.log10(spec_rest.max() / spec.max()) < -40.0, name


def test_file_d_noise_is_continuous(tmp_path):
    """D3 on yhtenäinen kohina ilman sisäänrakennettua saumaa."""
    gen.generate_file_d_joints(tmp_path)
    x, _ = sf.read(tmp_path / "D3_long_noise.wav")
    rms = per_second_rms(x)
    cv = rms.std() / rms.mean()
    assert cv < 0.05, f"D3 ei ole tasainen (cv={cv:.3f})"
