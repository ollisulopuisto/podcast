"""Aluesijoittelu: mitä istunnosta kuuluu ja millä käyrällä."""

from __future__ import annotations

import numpy as np

from nhsx import read
from nhsx.mix import envelope, plan

RATE = 1000


def _session(tmp_path, region_attrs: str):
    (tmp_path / "a.wav").write_bytes(b"")
    path = tmp_path / "s.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session>
  <AudioPool Path="" Location="{tmp_path}">
    <File Id="1" Name="a.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="olli">
      <Region Ref="1" Start="10.000" Length="04.000" Offset="00.000" {region_attrs}/>
    </Track>
  </Tracks>
</Session>""", encoding="utf-8")
    return plan(read(path))


def test_fade_in_and_out_are_read_not_reported_as_unknown(tmp_path):
    """Hindenburg kirjoittaa alueen häivytykset attribuutteina `FadeIn` ja
    `FadeOut` (pikis 2026-09-11: 2 + 6 aluetta). Ne ohitettiin ja
    kirjattiin tuntemattomiksi, eli jokainen editoitu häivytys soi
    täydellä tasolla."""
    mix = _session(tmp_path, 'FadeIn="01.000" FadeOut="00.500"')
    assert "FadeIn" not in mix.unknown and "FadeOut" not in mix.unknown
    clip = mix.clips[0]
    assert (clip.fade_in, clip.fade_out) == (1.0, 0.5)


def test_fades_go_to_silence_on_the_measured_curve():
    env = envelope(4.0, RATE, (), fade_in=1.0, fade_out=0.5)
    assert env[0] < 0.01 and env[-1] < 0.01
    assert abs(env[500] - 0.5) < 0.01          # raised-cosine puolivälissä
    assert np.all(env[1000:3500] == 1.0)
