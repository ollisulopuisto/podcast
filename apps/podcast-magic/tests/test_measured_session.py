"""Mitattu istunnosta, ei arvattu formaatista.

Kaikki tämän tiedoston luvut on luettu yhdestä istunnosta ja siitä
Hindenburgin itsensä renderöimästä tiedostosta: `pans and stuff`,
Hindenburg PRO 2.05.2718, kaksi panoroitua raitaa, alueen taso, `ClipGain`
ja kolme häivytystä. Se on ensimmäinen istunto kummassakaan repositoriossa,
jossa faderia on liikutettu — tätä ennen taso, panorointi ja häivytykset
olivat valintoja, eivät mittauksia, ja `KNOWN_REGION_ATTRS` oli olemassa
juuri siksi että ne kerran mitattaisiin.

Mittaustapa: renderöity raita puretaan stereoksi, ja panorointi poistetaan
laskemalla `L + R` yhteen — mikä on tarkkaa vain siksi että laki on
vakiosummainen, ja se on itsessään yksi mitatuista asioista (kaksi eri
tavoin panoroitua raitaa eroavat summattuna 0,24 dB).
"""

import math

import pytest

from podcastmagic.nhsx.mix import db_to_linear, pan_gains, plan
from podcastmagic.nhsx.read import read as read_session

# Pienimmän neliösumman sovitus renderöidystä raidasta: R = k·L.
# Ennuste (1-p)/(1+p) antaa 0,23077 ja 3,44444.
MEASURED = {0.625: 0.23027, -0.55: 3.44347}


class TestPanIsLinearAndPositiveIsLeft:
    def test_positive_pan_is_left(self):
        left, right = pan_gains(1.0)
        assert left > right, "Hindenburgissa positiivinen panorointi on vasen"
        assert (left, right) == (1.0, 0.0)

    def test_negative_pan_is_right(self):
        assert pan_gains(-1.0) == (0.0, 1.0)

    @pytest.mark.parametrize("pan,ratio", MEASURED.items())
    def test_ratio_matches_the_render(self, pan, ratio):
        left, right = pan_gains(pan)
        assert right / left == pytest.approx(ratio, rel=0.01)

    @pytest.mark.parametrize("pan", [-1.0, -0.55, 0.0, 0.3, 0.625, 1.0])
    def test_the_law_is_constant_sum(self, pan):
        """Kaksi eri tavoin panoroitua raitaa ovat summattuna samalla tasolla.

        Mitattu: raita 1 (`Pan="0.625"`) ja raita 2 (`Pan="-0.55"`) eroavat
        summattuna 0,24 dB. Vakiotehoinen laki antaisi eron 1,5 dB.
        """
        left, right = pan_gains(pan)
        assert left + right == pytest.approx(1.0)

    def test_centre_is_not_equal_power(self):
        """Vakiotehoinen laki antaisi keskellä 0,7071; tämä ei ole se."""
        assert pan_gains(0.0) == (0.5, 0.5)
        assert pan_gains(0.0)[0] != pytest.approx(math.sqrt(0.5))


SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session Samplerate="48000">
 <AudioPool Path="."><File Id="1" Name="a.wav"/></AudioPool>
 <Tracks>
  <Track Name="Raita 1" Pan="0.625">
   <Region Ref="1" Start="35.600" Length="28.400" Offset="35.600">
    <Fade Length="02.500" Gain="-11.2"/>
    <Fade Start="25.900" Length="02.500"/>
   </Region>
   <Region Ref="1" Start="01:04.000" Length="01:00.473" Offset="01:04.000"
           Gain="-11.2" ClipGain="-22.2"><Fade/></Region>
  </Track>
 </Tracks>
</Session>
"""


def _clips(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"")
    (tmp_path / "s.nhsx").write_text(SESSION, encoding="utf-8")
    return plan(read_session(tmp_path / "s.nhsx"))


class TestClipGain:
    def test_clip_gain_is_the_level_and_does_not_stack_with_gain(self, tmp_path):
        """Mitattu -22,50 dB. `Gain` + `ClipGain` olisi -33,4 dB."""
        third = _clips(tmp_path).clips[1]
        assert third.gain == pytest.approx(db_to_linear(-22.2), rel=1e-6)
        assert third.gain != pytest.approx(db_to_linear(-33.4), rel=1e-3)

    def test_clip_gain_is_not_reported_as_unknown(self, tmp_path):
        assert "ClipGain" not in _clips(tmp_path).unknown


class TestFadesAreEnvelopeRamps:
    def test_the_fade_is_read_at_all(self, tmp_path):
        """`Start`/`Length`, ei `In`/`Out`. Keksityt nimet luettiin nollana."""
        assert _clips(tmp_path).clips[0].ramps, "häivytykset katosivat kokonaan"

    def test_a_fade_ramps_to_its_gain_and_holds(self, tmp_path):
        """Mitattu: alueen runko on 12,02 dB vaimeampi, `Gain` on -11,2."""
        first = _clips(tmp_path).clips[0]
        assert first.level_at(0.0) == pytest.approx(1.0)
        assert first.level_at(2.5) == pytest.approx(db_to_linear(-11.2))
        assert first.level_at(10.0) == pytest.approx(db_to_linear(-11.2))

    def test_a_fade_without_gain_returns_to_unity(self, tmp_path):
        """Toinen häivytys päättyy alueen loppuun eikä sillä ole `Gain`ia."""
        first = _clips(tmp_path).clips[0]
        assert first.level_at(25.9) == pytest.approx(db_to_linear(-11.2))
        assert first.level_at(28.4) == pytest.approx(1.0)

    def test_unknown_fade_attributes_are_reported(self, tmp_path):
        """Häivytyksen tuntematon attribuutti jäi ennen kertomatta.

        `--plan` vaikeni `Fade`ista kokonaan, koska vain tuntematon
        *elementti* kirjattiin, ei tuntematonta attribuuttia sen sisällä.
        Juuri se aukko piilotti sen, ettei häivytyksiä luettu lainkaan.
        """
        (tmp_path / "a.wav").write_bytes(b"")
        (tmp_path / "s.nhsx").write_text(
            SESSION.replace('<Fade Start="25.900" Length="02.500"/>',
                            '<Fade Start="25.900" Length="02.500" Curve="log"/>'),
            encoding="utf-8")
        assert "Fade/Curve" in plan(read_session(tmp_path / "s.nhsx")).unknown
