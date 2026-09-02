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
# Kaksi jälkimmäistä `h-test A` -testi-istunnosta: poikkeama 0,000 dB.
MEASURED = {0.625: 0.23027, -0.55: 3.44347, -0.25: 1.66667, 0.1: 0.81818}


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


class TestMissingStartIsZero:
    """Hindenburg jättää `Start`in kirjoittamatta kun alue alkaa nollasta.

    Mitattu `h-test A.nhsx` -testi-istunnosta (testisignaaleista rakennettu,
    Hindenburg PRO 2.05.2718): ensimmäinen alue on kirjoitettu
    `<Region Ref="1" Name="…" Length="05.000"/>` — ei `Start`ia lainkaan.
    Lukija joka vaatii attribuutin kuolee ensimmäiseen oikeaan istuntoon.
    """

    def test_region_without_start_starts_at_zero(self, tmp_path):
        session = SESSION.replace(
            '<Region Ref="1" Start="35.600" Length="28.400" Offset="35.600">',
            '<Region Ref="1" Length="28.400" Offset="35.600">')
        (tmp_path / "a.wav").write_bytes(b"")
        (tmp_path / "s.nhsx").write_text(session, encoding="utf-8")
        clips = plan(read_session(tmp_path / "s.nhsx")).clips
        assert clips[0].start == 0.0


class TestTrackVolume:
    """Raidan vaimennin on `Volume`, desibeleinä — ja se kuuluu summaan.

    Mitattu `h-test A` -testi-istunnosta ja sen renderöinnistä: raita
    `Volume="6"` → alueen rms −13,98 dBFS (lähde −20), raita `Volume="-6"`
    → −26,03. Alueen `Gain` ja raidan `Volume` laskevat yhteen: mitattu
    −8,06 dBFS, ennuste −20 + 6 + 6 = −8,00.

    Ennen mittoa `Volume` kirjattiin tuntemattomaksi ja ohitettiin —
    jokainen raidan fader asetti miksausbonuksen nollaksi, eli sama
    hiljaisen vian muoto kuin `ClipGain`-ohitus oli.
    """

    def test_track_volume_is_the_track_gain(self, tmp_path):
        session = SESSION.replace(
            '<Track Name="Raita 1" Pan="0.625">',
            '<Track Name="Raita 1" Pan="0.625" Volume="-6">')
        (tmp_path / "a.wav").write_bytes(b"")
        (tmp_path / "s.nhsx").write_text(session, encoding="utf-8")
        clips = plan(read_session(tmp_path / "s.nhsx")).clips
        assert clips[0].gain == pytest.approx(db_to_linear(-6.0))

    def test_volume_stacks_with_region_gain(self, tmp_path):
        """A10 mitattu −8,06 dBFS: `Gain` +6 alueella ja `Volume` +6 raidalla."""
        session = SESSION.replace(
            '<Track Name="Raita 1" Pan="0.625">',
            '<Track Name="Raita 1" Pan="0.625" Volume="6">')
        (tmp_path / "a.wav").write_bytes(b"")
        (tmp_path / "s.nhsx").write_text(session, encoding="utf-8")
        clips = plan(read_session(tmp_path / "s.nhsx")).clips
        # alueen ClipGain -22,2 + raidan Volume +6
        assert clips[1].gain == pytest.approx(db_to_linear(-22.2 + 6.0))

    def test_volume_is_not_reported_as_unknown(self, tmp_path):
        session = SESSION.replace(
            '<Track Name="Raita 1" Pan="0.625">',
            '<Track Name="Raita 1" Pan="0.625" Volume="6">')
        (tmp_path / "a.wav").write_bytes(b"")
        (tmp_path / "s.nhsx").write_text(session, encoding="utf-8")
        assert "Track/Volume" not in plan(read_session(tmp_path / "s.nhsx")).unknown


class TestFadeCurveIsRaisedCosine:
    """Luiskan muoto on mitattu: raised-cosine S-käyrä, ei jana.

    `h-test A` -testi-istunnon A7-alueelta (tasainen −20 dBFS kohina,
    luiska −10 dB:iin ja takaisin): 20 ms ikkunoiden RMS-sovitus antaa
    kosinille 0,29 dB RMS-virheen (mittauskohinan tuntumassa) ja janalle
    1,04 dB, pahimmillaan 2,06 dB pielessä. Sekä ylös- että alaskäyrä
    istuvat samaan muotoon.

    Aiempi valinta oli lineaarinen, ja peruste oli «se joka ei väitä
    mitään» — nyt muoto on mitattu, joten jana väittää väärin.
    """

    def test_quarter_ramp_is_above_the_chord(self, tmp_path):
        """Luiskan neljäsosakohdassa käyrä on janan yläpuolella.

        Jana antaisi 1 + (g−1)·0,25; kosini (1−cos(π/4))/2 osan, eli ~0,76 dB
        korkeammalla. Mittausero 2 dB on suurempi kuin tämä, joten kohta
        erottaa muodot varmasti.
        """
        first = _clips(tmp_path).clips[0]
        g = db_to_linear(-11.2)
        cosine = 1.0 + (g - 1.0) * (1 - math.cos(math.pi * 0.25)) / 2
        chord = 1.0 + (g - 1.0) * 0.25
        assert first.level_at(0.625) == pytest.approx(cosine, rel=1e-4)
        assert first.level_at(0.625) != pytest.approx(chord, rel=1e-3)

    def test_endpoints_and_plateau_are_unchanged(self, tmp_path):
        """Muoto muuttaa vain väliä: päätteet ja tasanne ovat samat."""
        first = _clips(tmp_path).clips[0]
        assert first.level_at(0.0) == pytest.approx(1.0)
        assert first.level_at(2.5) == pytest.approx(db_to_linear(-11.2))
        assert first.level_at(10.0) == pytest.approx(db_to_linear(-11.2))
