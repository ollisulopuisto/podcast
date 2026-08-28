"""Istunnon miksaus: geometria, taso, häivytys ja panorointi.

Nämä testit koskevat **pelkkää laskentaa**. Yhtään tiedostoa ei avata, koska
miksauksen viat eivät ole tiedosto-operaatioissa: ne ovat siinä, mihin
kohtaan aikajanaa alue osuu ja millä kertoimella. Purku ja kirjoitus ovat
``test_render.py``:ssä.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from lxml import etree

from podcastmagic import nhsx
from podcastmagic.nhsx import mix


def session_with(regions_xml: str, files_xml: str = "", tmp_path=None):
    """Istunto annetuilla alueilla. Poolissa on yksi tiedosto, ellei toisin sanota."""
    pool = files_xml or '<File Id="1" Name="a.wav" Path="a.wav"/>'
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Name="testi">
  <AudioPool Path="">{pool}</AudioPool>
  <Tracks><Track Name="Olli">{regions_xml}</Track></Tracks>
</Session>
"""
    path = tmp_path / "jakso.nhsx"
    path.write_text(xml, encoding="utf-8")
    (tmp_path / "a.wav").write_bytes(b"")
    return nhsx.read(str(path))


# --- Geometria ----------------------------------------------------------


def test_an_area_becomes_a_clip_where_the_timeline_says(tmp_path):
    """``Start`` on ohjelma-aikaa ja ``Offset`` tiedoston aikaa, eri asia."""
    s = session_with('<Region Ref="1" Start="10.0" Length="5.0" Offset="3.0"/>', tmp_path=tmp_path)
    plan = mix.plan(s)
    assert len(plan.clips) == 1
    clip = plan.clips[0]
    assert clip.start == 10.0
    assert clip.length == 5.0
    assert clip.end == 15.0
    # Kolme sekuntia sisään tiedostoon, ei kolme sekuntia aikajanalla.
    assert clip.file_offset == 3.0
    assert clip.file_time(12.0) == 5.0


def test_the_programme_is_as_long_as_its_last_area_ends(tmp_path):
    s = session_with(
        '<Region Ref="1" Start="0" Length="4"/><Region Ref="1" Start="30" Length="2.5"/>',
        tmp_path=tmp_path,
    )
    assert mix.plan(s).duration == pytest.approx(32.5)


def test_the_same_file_twice_on_the_timeline_is_two_clips(tmp_path):
    """Sama tiedosto voi esiintyä aikajanalla monta kertaa eri kohdasta."""
    s = session_with(
        '<Region Ref="1" Start="0" Length="4" Offset="0"/>'
        '<Region Ref="1" Start="10" Length="4" Offset="60"/>',
        tmp_path=tmp_path,
    )
    clips = mix.plan(s).clips
    assert [c.file_offset for c in clips] == [0.0, 60.0]


def test_a_muted_area_is_not_in_the_mix_and_says_so(tmp_path):
    """Vaimennusmoduulin tulos on täynnä näitä; ne eivät kuulu."""
    s = session_with(
        '<Region Ref="1" Start="0" Length="4"/>'
        '<Region Ref="1" Start="4" Length="4" Muted="True"/>',
        tmp_path=tmp_path,
    )
    plan = mix.plan(s)
    assert len(plan.clips) == 1
    assert plan.muted == 1
    # Vaimennettu alue ei silti lyhennä ohjelmaa: aikajana on yhtä pitkä.
    assert plan.duration == pytest.approx(8.0)


def test_an_area_whose_file_is_not_on_disk_is_reported_not_dropped_quietly(tmp_path):
    s = session_with(
        '<Region Ref="9" Start="0" Length="4"/>',
        files_xml='<File Id="9" Name="poissa.wav" Path="poissa.wav"/>',
        tmp_path=tmp_path,
    )
    plan = mix.plan(s)
    assert plan.clips == []
    assert plan.missing == ["poissa.wav"]


# --- Panorointi ---------------------------------------------------------


def test_the_law_is_linear_and_constant_sum(tmp_path):
    """Oli vakiotehoinen, on lineaarinen. Vaihdettu mittauksen perusteella.

    Vanha väite oli, että keskellä on -3,01 dB kummallakin puolella ja että
    teho säilyy. Perustelu oli hyvä — lineaarisella lailla keskellä oleva
    raita on summassa 3 dB kovempaa — mutta se on perustelu sille, miten
    asian *pitäisi* olla. Hindenburg tekee toisin, ja renderöity istunto
    sanoo sen suoraan; ks. `test_measured_session.py`.
    """
    del tmp_path
    left, right = mix.pan_gains(0.0)
    assert left == pytest.approx(right)
    assert 20 * math.log10(left) == pytest.approx(-6.02, abs=0.01)
    for pan in (-1.0, -0.5, 0.0, 0.5, 1.0):
        left, right = mix.pan_gains(pan)
        assert left + right == pytest.approx(1.0)


def test_hard_left_is_silent_on_the_right(tmp_path):
    """Vasen on **positiivinen**. Tämä oli väärin päin.

    Väärin päin oleva panorointi on kelvollinen tiedosto, jossa puhujat
    ovat vaihtaneet puolta: mikään ei kaadu eikä sitä huomaa muuten kuin
    kuuntelemalla — tai mittaamalla, kuten lopulta tehtiin.
    """
    del tmp_path
    left, right = mix.pan_gains(1.0)
    assert left == pytest.approx(1.0)
    assert right == pytest.approx(0.0, abs=1e-12)


def test_a_pan_outside_the_scale_is_clamped_not_wrapped(tmp_path):
    """Tuntemattomasta attribuutista voi tulla mitä tahansa; ei negatiivista vahvistusta."""
    del tmp_path
    assert mix.pan_gains(-4.0) == mix.pan_gains(-1.0)
    assert mix.pan_gains(4.0) == mix.pan_gains(1.0)


# --- Häivytykset --------------------------------------------------------


def test_a_ramp_to_silence_starts_at_full_and_arrives_at_zero(tmp_path):
    """Luiska nollaan on se, mitä ennen kutsuttiin ulosajoksi."""
    del tmp_path
    env = mix.envelope(2.0, 100, (mix.Ramp(start=1.5, length=0.5, gain=0.0),))
    assert len(env) == 200
    assert env[0] == pytest.approx(1.0)
    assert env[149] == pytest.approx(1.0)
    assert env[-1] == pytest.approx(0.0, abs=0.02)


def test_a_ramp_holds_its_level_afterwards(tmp_path):
    """Tämä on se, mitä `fade_in`/`fade_out` ei osannut esittää lainkaan.

    Mitattu alue laskee 2,5 sekunnissa arvoon -11,2 dB ja **jää sinne**
    26 sekunniksi. Hiljaisuudesta täyteen ja täydestä hiljaisuuteen ei
    kuvaa sitä millään lukuparilla.
    """
    del tmp_path
    env = mix.envelope(4.0, 100, (mix.Ramp(start=0.0, length=1.0, gain=0.25),))
    assert env[0] == pytest.approx(1.0, abs=0.02)
    assert env[99] == pytest.approx(0.25, abs=0.02)
    assert env[-1] == pytest.approx(0.25)
    assert np.all(env[100:] == pytest.approx(0.25))


def test_a_ramp_that_runs_past_the_clip_is_cut_not_scaled(tmp_path):
    """Pilkottu pala on lyhyempi kuin alue, ei hitaampi.

    Vanha sääntö kutisti leikettä pidemmät häivytykset suhteessa, koska
    kaksi *summattua* käyrää olisi mennyt nollan ali. Luiskat eivät summaudu
    vaan seuraavat toisiaan, joten kesken jäävä luiska yksinkertaisesti
    katkeaa — ja katkeaa oikeaan arvoon, ei nollaan.
    """
    del tmp_path
    env = mix.envelope(1.0, 100, (mix.Ramp(start=0.0, length=2.0, gain=0.0),))
    assert len(env) == 100
    assert env.min() >= 0.0
    assert env.max() <= 1.0
    assert env[0] == pytest.approx(1.0, abs=0.02)
    assert env[-1] == pytest.approx(0.5, abs=0.02)


def test_a_clip_without_ramps_is_flat(tmp_path):
    del tmp_path
    env = mix.envelope(1.0, 48000)
    assert np.all(env == 1.0)


# --- Taso ---------------------------------------------------------------


def test_decibels_become_a_linear_factor(tmp_path):
    del tmp_path
    assert mix.db_to_linear(0.0) == pytest.approx(1.0)
    assert mix.db_to_linear(-6.02) == pytest.approx(0.5, abs=0.001)
    assert mix.db_to_linear(6.02) == pytest.approx(2.0, abs=0.005)


def test_minus_infinity_is_silence_not_an_error(tmp_path):
    del tmp_path
    assert mix.db_to_linear(float("-inf")) == 0.0


# --- Se mitä emme osaa lukea -------------------------------------------


def test_an_unknown_area_attribute_is_counted_and_named(tmp_path):
    """Ominaisuus, joka ei tuottanut mitään, sanoo sen.

    Tason, panoroinnin ja häivytysten attribuuttinimiä ei ole mitattu (ks.
    ``mix.py``). Väärä arvaus on hiljainen: tiedosto aukeaa, leikkeet ovat
    oikean mittaisia, ja miksaus on väärällä tasolla. Siksi tuntematon
    attribuutti kerrotaan sen sijaan että se ohitettaisiin.
    """
    s = session_with(
        '<Region Ref="1" Start="0" Length="4" Tuntematon="7" Muuta="x"/>',
        tmp_path=tmp_path,
    )
    plan = mix.plan(s)
    assert set(plan.unknown) == {"Tuntematon", "Muuta"}
    assert plan.unknown["Tuntematon"] == 1


def test_the_attributes_we_do_read_are_not_reported_as_unknown(tmp_path):
    s = session_with(
        '<Region Ref="1" Start="0" Length="4" Offset="0" Muted="False" Name="pala"/>',
        tmp_path=tmp_path,
    )
    assert mix.plan(s).unknown == {}


def test_a_fade_child_element_is_read_as_a_ramp(tmp_path):
    """`Start` ja `Length`, ei `In` ja `Out`.

    Nämä kaksi nimeä olivat keksittyjä, eikä yksikään istunto ollut
    kiistänyt niitä ennen kuin sellainen vihdoin nähtiin. Niin kauan
    jokaisen istunnon jokainen häivytys luettiin nollana.
    """
    s = session_with(
        '<Region Ref="1" Start="0" Length="4">'
        '<Fade Start="0.5" Length="1.0" Gain="-6.02"/>'
        "</Region>",
        tmp_path=tmp_path,
    )
    clip = mix.plan(s).clips[0]
    assert clip.ramps == (mix.Ramp(start=0.5, length=1.0, gain=pytest.approx(0.5, abs=1e-3)),)
    assert clip.level_at(0.0) == pytest.approx(1.0)
    assert clip.level_at(1.5) == pytest.approx(0.5, abs=1e-3)
    assert clip.level_at(4.0) == pytest.approx(0.5, abs=1e-3)


def test_the_ramps_in_the_plan_already_fit_the_clip(tmp_path):
    """Leikkaus kuuluu suunnitelmaan, ei vasta renderöintiin.

    Sääntö oli ennen vain `envelope`ssa eli renderöinnin sisällä, ja
    jokaisen lukijan piti tietää se itse — myös katselimen Swift-puolen,
    joka ei jaa tämän kanssa riviäkään koodia. Sääntö, joka on kerrottava
    jokaiselle lukijalle erikseen, on sääntö jota joku lukija ei noudata.

    Nyt jokainen `Ramp` mahtuu leikkeeseen sellaisenaan.
    """
    s = session_with(
        '<Region Ref="1" Start="0" Length="1.0">'
        '<Fade Start="0" Length="2.0" Gain="-inf"/></Region>',
        tmp_path=tmp_path,
    )
    clip = mix.plan(s).clips[0]
    assert clip.ramps[0].end <= clip.length


def test_a_ramp_starting_past_the_clip_is_dropped(tmp_path):
    s = session_with(
        '<Region Ref="1" Start="0" Length="1.0">'
        '<Fade Start="5.0" Length="1.0"/></Region>',
        tmp_path=tmp_path,
    )
    assert mix.plan(s).clips[0].ramps == ()


def test_a_gain_attribute_is_read_as_decibels(tmp_path):
    s = session_with('<Region Ref="1" Start="0" Length="4" Gain="-6.02"/>', tmp_path=tmp_path)
    assert mix.plan(s).clips[0].gain == pytest.approx(0.5, abs=0.001)


def test_the_track_gain_multiplies_the_area_gain(tmp_path):
    """Raidan faderi ja leikkeen taso ovat eri säätimiä ja molemmat kuuluvat."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session><AudioPool Path=""><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>
<Tracks><Track Name="Olli" Gain="-6.02">
  <Region Ref="1" Start="0" Length="4" Gain="-6.02"/>
</Track></Tracks></Session>
"""
    path = tmp_path / "jakso.nhsx"
    path.write_text(xml, encoding="utf-8")
    (tmp_path / "a.wav").write_bytes(b"")
    clip = mix.plan(nhsx.read(str(path))).clips[0]
    assert clip.gain == pytest.approx(0.25, abs=0.002)


def test_a_muted_track_is_silent_even_where_its_areas_are_not(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session><AudioPool Path=""><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>
<Tracks><Track Name="Musiikki" Muted="True">
  <Region Ref="1" Start="0" Length="4"/>
</Track></Tracks></Session>
"""
    path = tmp_path / "jakso.nhsx"
    path.write_text(xml, encoding="utf-8")
    (tmp_path / "a.wav").write_bytes(b"")
    plan = mix.plan(nhsx.read(str(path)))
    assert plan.clips == []
    assert plan.muted == 1


def test_reading_a_session_never_raises_on_a_strange_value(tmp_path):
    """Yksi sekaisin mennyt attribuutti ei saa kaataa koko esikatselua."""
    s = session_with(
        '<Region Ref="1" Start="0" Length="4" Gain="kissa" Pan="???"/>',
        tmp_path=tmp_path,
    )
    clip = mix.plan(s).clips[0]
    assert clip.gain == 1.0
    assert clip.pan == 0.0


def test_the_speaker_comes_from_the_track_name(tmp_path):
    s = session_with('<Region Ref="1" Start="0" Length="4"/>', tmp_path=tmp_path)
    assert mix.plan(s).clips[0].speaker == "Olli"


def test_the_element_namespace_does_not_matter(tmp_path):
    """Hindenburgin viemät tiedostot ovat joskus nimiavaruudessa, joskus eivät."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<Session xmlns="urn:hindenburg">
  <AudioPool Path=""><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>
  <Tracks><Track Name="Olli"><Region Ref="1" Start="0" Length="4"/></Track></Tracks>
</Session>
"""
    path = tmp_path / "jakso.nhsx"
    path.write_text(xml, encoding="utf-8")
    (tmp_path / "a.wav").write_bytes(b"")
    assert len(mix.plan(nhsx.read(str(path))).clips) == 1


def test_an_empty_session_is_a_mix_of_nothing_not_a_crash(tmp_path):
    xml = '<?xml version="1.0"?><Session><AudioPool Path=""/><Tracks/></Session>'
    path = tmp_path / "tyhja.nhsx"
    path.write_text(xml, encoding="utf-8")
    plan = mix.plan(nhsx.read(str(path)))
    assert plan.clips == []
    assert plan.duration == 0.0


def test_the_known_attributes_are_written_out_by_hand(tmp_path):
    """Sama vartija kuin litteroinnin tunnisteella.

    Jos uusi attribuutti luetaan, se kuuluu tähän listaan — muuten se
    katoaisi «tunnettujen» joukkoon ilman että kukaan päätti niin.
    """
    del tmp_path
    assert mix.KNOWN_REGION_ATTRS == frozenset(
        {
            "Ref", "Start", "Length", "Offset", "Muted", "Name", "Gain", "Pan",
            "ClipGain", "IsMusic", "UseTranscription",
        }
    )
    assert mix.KNOWN_FADE_ATTRS == frozenset({"Start", "Length", "Gain"})


def test_a_region_child_that_is_not_a_fade_is_reported(tmp_path):
    s = session_with(
        '<Region Ref="1" Start="0" Length="4"><Jokumuu/></Region>',
        tmp_path=tmp_path,
    )
    assert "Jokumuu" in mix.plan(s).unknown


def test_clips_come_out_in_timeline_order(tmp_path):
    """Esikatselu piirtää ja soittaa järjestyksessä; XML ei lupaa sitä."""
    s = session_with(
        '<Region Ref="1" Start="20" Length="1"/>'
        '<Region Ref="1" Start="5" Length="1"/>'
        '<Region Ref="1" Start="12" Length="1"/>',
        tmp_path=tmp_path,
    )
    starts = [c.start for c in mix.plan(s).clips]
    assert starts == sorted(starts)


def test_an_area_of_zero_length_is_not_a_clip(tmp_path):
    """Nollan mittainen alue on aikajanan jäänne, ei ääntä."""
    s = session_with(
        '<Region Ref="1" Start="0" Length="0"/><Region Ref="1" Start="1" Length="2"/>',
        tmp_path=tmp_path,
    )
    assert len(mix.plan(s).clips) == 1


def test_lxml_comments_between_regions_do_not_become_clips(tmp_path):
    s = session_with(
        '<!-- kommentti --><Region Ref="1" Start="0" Length="2"/>',
        tmp_path=tmp_path,
    )
    assert len(mix.plan(s).clips) == 1
    assert etree is not None
