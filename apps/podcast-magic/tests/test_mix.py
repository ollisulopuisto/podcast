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


def test_the_centre_is_three_decibels_down_on_each_side(tmp_path):
    """Vakiotehoinen panorointi, ei lineaarinen.

    Lineaarisella lailla keskellä oleva raita on summassa 3 dB kovempaa kuin
    laidoilla oleva, ja koko miksaus kallistuu keskelle sitä mukaa kun
    raitoja lisätään.
    """
    del tmp_path
    left, right = mix.pan_gains(0.0)
    assert left == pytest.approx(right)
    assert 20 * math.log10(left) == pytest.approx(-3.01, abs=0.01)
    # Teho säilyy laidasta laitaan.
    for pan in (-1.0, -0.5, 0.0, 0.5, 1.0):
        left, right = mix.pan_gains(pan)
        assert left**2 + right**2 == pytest.approx(1.0)


def test_hard_left_is_silent_on_the_right(tmp_path):
    del tmp_path
    left, right = mix.pan_gains(-1.0)
    assert left == pytest.approx(1.0)
    assert right == pytest.approx(0.0, abs=1e-12)


def test_a_pan_outside_the_scale_is_clamped_not_wrapped(tmp_path):
    """Tuntemattomasta attribuutista voi tulla mitä tahansa; ei negatiivista vahvistusta."""
    del tmp_path
    assert mix.pan_gains(-4.0) == mix.pan_gains(-1.0)
    assert mix.pan_gains(4.0) == mix.pan_gains(1.0)


# --- Häivytykset --------------------------------------------------------


def test_a_fade_in_starts_at_silence_and_arrives_at_full(tmp_path):
    del tmp_path
    env = mix.envelope(length=2.0, sample_rate=100, fade_in=0.5, fade_out=0.0)
    assert len(env) == 200
    assert env[0] == pytest.approx(0.0)
    assert env[49] == pytest.approx(1.0, abs=0.03)
    assert env[-1] == pytest.approx(1.0)


def test_a_fade_out_ends_at_silence(tmp_path):
    del tmp_path
    env = mix.envelope(length=2.0, sample_rate=100, fade_in=0.0, fade_out=0.5)
    assert env[0] == pytest.approx(1.0)
    assert env[-1] == pytest.approx(0.0, abs=0.02)


def test_fades_longer_than_the_clip_are_scaled_not_allowed_to_cross(tmp_path):
    """Kaksi sekunnin häivytystä sekunnin leikkeessä ei saa mennä nollan alle.

    Pilkkominen jättää lyhyitä paloja, ja jos häivytykset periytyisivät
    sellaisenaan, ne olisivat leikettä pidempiä.
    """
    del tmp_path
    env = mix.envelope(length=1.0, sample_rate=100, fade_in=2.0, fade_out=2.0)
    assert len(env) == 100
    assert env.min() >= 0.0
    assert env.max() <= 1.0
    # Molemmat häivytykset mahtuvat, eli molemmat on kutistettu puoleen
    # sekuntiin — eivät kumpikaan pudonneet pois. Se erottaa suhteellisen
    # kutistamisen siitä, että jälkimmäinen jäisi rakenteellisesti nollaan:
    # sisääntulo saavuttaa täyden tason keskellä ja ulostulo päätyy nollaan.
    assert env[0] == pytest.approx(0.0)
    assert env[49] == pytest.approx(1.0)
    assert env[-1] == pytest.approx(0.0)


def test_a_clip_without_fades_is_flat(tmp_path):
    del tmp_path
    env = mix.envelope(length=1.0, sample_rate=48000, fade_in=0.0, fade_out=0.0)
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


def test_a_fade_child_element_is_read_as_a_fade(tmp_path):
    """Alueen lapsielementti on häivytys — sitä ``apply.py`` varoo pudottavansa."""
    s = session_with(
        '<Region Ref="1" Start="0" Length="4">'
        '<Fade In="0.5" Out="1.0"/>'
        "</Region>",
        tmp_path=tmp_path,
    )
    clip = mix.plan(s).clips[0]
    assert clip.fade_in == pytest.approx(0.5)
    assert clip.fade_out == pytest.approx(1.0)


def test_the_fades_in_the_plan_already_fit_the_clip(tmp_path):
    """Kutistus kuuluu suunnitelmaan, ei vasta renderöintiin.

    Sääntö oli ennen vain `envelope`ssa, eli renderöinnin sisällä. Silloin
    suunnitelma kertoi kahden sekunnin häivytykset sekunnin mittaisesta
    leikkeestä, ja jokaisen lukijan piti tietää kutistaa ne itse — myös
    QuickLook-esikatselun, joka on toista kieltä eikä jaa riviäkään koodia.
    Sääntö, joka on kerrottava jokaiselle lukijalle erikseen, on sääntö jota
    joku lukija ei noudata.

    Nyt `Clip` pitää lupauksen `fade_in + fade_out <= length`, ja
    `envelope` saa valmiiksi mahtuvat luvut.
    """
    s = session_with(
        '<Region Ref="1" Start="0" Length="1.0"><Fade In="2.0" Out="2.0"/></Region>',
        tmp_path=tmp_path,
    )
    clip = mix.plan(s).clips[0]
    assert clip.fade_in == pytest.approx(0.5)
    assert clip.fade_out == pytest.approx(0.5)
    assert clip.fade_in + clip.fade_out <= clip.length


def test_fades_that_already_fit_are_left_alone(tmp_path):
    s = session_with(
        '<Region Ref="1" Start="0" Length="10.0"><Fade In="1.5" Out="3.0"/></Region>',
        tmp_path=tmp_path,
    )
    clip = mix.plan(s).clips[0]
    assert clip.fade_in == pytest.approx(1.5)
    assert clip.fade_out == pytest.approx(3.0)


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
        {"Ref", "Start", "Length", "Offset", "Muted", "Name", "Gain", "Pan"}
    )


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
