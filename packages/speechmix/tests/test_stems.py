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
