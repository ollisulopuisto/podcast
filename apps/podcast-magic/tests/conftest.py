"""Testien yhteiset kiinnikkeet."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def session_file(tmp_path: Path) -> Path:
    """Pieni istunto, jossa on kaksi raitaa ja yksi valmis litterointi.

    Fikstuuri on käsin kirjoitettu eikä Hindenburgin viemä: testit koskevat
    juuri niitä attribuutteja jotka tässä ovat, ja oikeasta istunnosta
    leikattu näyte toisi mukanaan sata riviä joilla ei ole tekemistä
    minkään tässä testatun kanssa.
    """
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="testi">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription>
        <p>
          <w s="1.000" l="0.400" sp="UU">Terve</w>
          <w s="1.500" l="0.300" sp="UU">vaan</w>
          <w s="8.000" l="0.500" sp="UU">jatketaan</w>
        </p>
      </Transcription>
    </File>
    <File Id="2" Name="panu.wav" Path="panu.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Olli">
      <Region Ref="1" Start="0.000" Length="12.000" Offset="0.000"/>
    </Track>
    <Track Name="Panu">
      <Region Ref="2" Start="0.000" Length="12.000" Offset="0.000"/>
    </Track>
  </Tracks>
</Session>
"""
    path = tmp_path / "jakso.nhsx"
    path.write_text(xml, encoding="utf-8")
    return path
