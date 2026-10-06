"""Stemit levyltä ohjelmaksi paloittain.

``sum_to_file`` on autoraffkatin videorenderin äänisumma, siirretty
kirjastoon jotta automixer voi kirjoittaa koko jakson ilman että se on
muistissa. Stereolähde (musiikki) säilyy stereona.
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from speechmix import stems

RATE = 48000


def test_sum_keeps_stereo_music_and_pans_mono_speech(tmp_path):
    n = RATE * 3
    left = np.full(n, 0.2, dtype=np.float32)
    right = np.full(n, -0.1, dtype=np.float32)
    sf.write(tmp_path / "music.wav", np.stack([left, right], axis=1), RATE)
    sf.write(tmp_path / "voice.wav", np.full(n, 0.3, dtype=np.float32), RATE)
    out = tmp_path / "mix.wav"
    stems.sum_to_file(
        [
            stems.Source(str(tmp_path / "music.wav"), [(0.0, 3.0, 0.0)], stereo=True),
            stems.Source(str(tmp_path / "voice.wav"), [(1.0, 2.0, 0.0)], pan=-100),
        ],
        0.0, 3.0, str(out), rate=RATE, block=0.7,
    )
    mix, rate = sf.read(out, always_2d=True)
    assert rate == RATE and mix.shape == (n, 2)
    # Musiikki: vasen ja oikea omina, ei keskiarvona.
    assert np.allclose(mix[int(0.5 * RATE)], [0.2, -0.1], atol=1e-4)
    # Puhe täysin vasemmalla: vasen +0,3, oikea ei mitään.
    assert np.allclose(mix[int(1.5 * RATE)], [0.5, -0.1], atol=1e-4)


def test_meter_reads_stereo_as_the_standard_does():
    """BS.1770: kanavien tehot summataan. Kaksoismono on 3 dB monoa
    kovempi, ja pyloudnorm lukee saman. Keskiarvo kanavista luki monon
    lukeman stereolle, ja automixerin miksaus jäi tavoitteen yli 3,7 dB."""
    import pyloudnorm as pyln

    from speechmix.meter import IntegratedMeter

    rng = np.random.default_rng(1)
    mono = rng.normal(0, 0.05, RATE * 10)
    stereo = np.stack([mono, rng.normal(0, 0.03, RATE * 10)])
    meter = IntegratedMeter(RATE)
    for i in range(0, stereo.shape[1], RATE):
        meter.add(stereo[:, i:i + RATE])
    want = pyln.Meter(RATE).integrated_loudness(stereo.T)
    assert abs(meter.value() - want) < 0.1
