"""Formaatin kartoitus: mitä oikeassa istunnossa todella on."""

from __future__ import annotations

from podcastmagic.nhsx import prospect


def survey_of(xml: str, tmp_path):
    path = tmp_path / "jakso.nhsx"
    path.write_text(xml, encoding="utf-8")
    return prospect.survey(str(path))


SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="testi">
  <AudioPool Path=""><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>
  <Tracks>
    <Track Name="Olli" Volume="0.5" Pan="-0.3">
      <Region Ref="1" Start="0" Length="4" Gain="-3" Kummallinen="7"/>
      <Region Ref="1" Start="4" Length="4" Kummallinen="9"><Fade In="0.2"/></Region>
    </Track>
  </Tracks>
</Session>
"""


def test_it_counts_every_element_it_meets(tmp_path):
    s = survey_of(SESSION, tmp_path)
    assert s.elements["Region"] == 2
    assert s.elements["Track"] == 1
    assert s.elements["Fade"] == 1


def test_it_counts_attributes_per_element(tmp_path):
    s = survey_of(SESSION, tmp_path)
    assert s.attributes["Region"]["Kummallinen"] == 2
    assert s.attributes["Region"]["Gain"] == 1
    assert s.attributes["Track"]["Volume"] == 1


def test_it_keeps_example_values_because_the_name_is_only_half_the_answer(tmp_path):
    """«Gain» ei kerro onko se desibeliä vai kerroin. Arvo kertoo."""
    s = survey_of(SESSION, tmp_path)
    assert "-3" in s.values["Region"]["Gain"]
    assert "0.5" in s.values["Track"]["Volume"]


def test_it_separates_what_we_read_from_what_we_do_not(tmp_path):
    s = survey_of(SESSION, tmp_path)
    assert "Kummallinen" in s.unknown["Region"]
    assert "Gain" not in s.unknown["Region"]
    # Raidan `Volume` on juuri se tapaus jonka takia tämä työkalu on: se voi
    # olla se nimi jolla faderi oikeasti kirjoitetaan.
    assert "Volume" in s.unknown["Track"]


def test_the_report_names_the_unknown_ones(tmp_path):
    s = survey_of(SESSION, tmp_path)
    text = prospect.text(s)
    assert "Kummallinen" in text
    assert "Volume" in text
    assert "Region" in text


def test_a_session_with_nothing_unknown_says_so(tmp_path):
    xml = """<?xml version="1.0"?><Session><AudioPool Path=""/>
    <Tracks><Track Name="Olli"><Region Ref="1" Start="0" Length="4" Muted="True"/></Track></Tracks>
    </Session>"""
    text = prospect.text(survey_of(xml, tmp_path))
    assert "Region" in text
    assert prospect.survey_is_fully_understood(survey_of(xml, tmp_path))


def test_the_session_wrapper_is_not_flagged_as_a_mystery(tmp_path):
    """`?` tarkoittaa «tämä voi olla se faderi». Istunnon nimi ei ole.

    Raportti jossa joka rivillä on kysymysmerkki ei osoita mihinkään, ja
    tämän työkalun koko arvo on siinä mihin se osoittaa.
    """
    s = survey_of(SESSION, tmp_path)
    assert "Session" not in s.unknown


def test_a_namespaced_session_surveys_the_same(tmp_path):
    xml = SESSION.replace("<Session ", '<Session xmlns="urn:hindenburg" ')
    s = survey_of(xml, tmp_path)
    assert s.elements["Region"] == 2
    assert "Kummallinen" in s.unknown["Region"]


def test_the_transcription_is_not_surveyed_word_by_word(tmp_path):
    """Tunnin litteroinnissa on kymmeniätuhansia ``<w>``-elementtejä.

    Ne ovat jo tunnettuja ja dokumentoituja, ja kartoitettuna ne hukuttaisivat
    raportin siihen mitä ollaan etsimässä.
    """
    xml = SESSION.replace(
        '<File Id="1" Name="a.wav" Path="a.wav"/>',
        '<File Id="1" Name="a.wav"><Transcription><p>'
        + "".join(f'<w s="{i}" l="0.1">x</w>' for i in range(50))
        + "</p></Transcription></File>",
    )
    s = survey_of(xml, tmp_path)
    assert "w" not in s.elements
    assert s.elements["Transcription"] == 1
