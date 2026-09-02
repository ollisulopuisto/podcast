"""Pipeline skriptin yksikkötestit — testataan erillisinä funktioina.

Huom: pipeline.py on Colabissa ajettava resurssi, mutta sen funktiot
ovat testattavissa erillään ilman Colabia.
"""

from __future__ import annotations

import pytest

from colabtranscribe.colab.pipeline import (
    merge_intervals_with_gap,
    seconds_to_time,
    time_to_seconds,
)


def test_time_to_seconds_valid_formats():
    assert time_to_seconds("0") == 0.0
    assert time_to_seconds("1.5") == 1.5
    assert time_to_seconds("1:30") == 90.0
    assert time_to_seconds("0:01:30") == 90.0
    assert time_to_seconds("1:23:45") == 5025.0
    assert time_to_seconds("0:00:00.5") == 0.5


def test_time_to_seconds_invalid_raises():
    # Virheelliset muodot eivät saa palauttaa 0.0 hiljaa — se piilottaa bugeja.
    # time_to_seconds palauttaa 0.0 virheessä, mikä on vaarallista (ks. CLAUDE.md).
    # Testi vaatii, että virheellisestä syötteestä nousee poikkeus.
    with pytest.raises(ValueError):
        time_to_seconds("invalid")
    with pytest.raises(ValueError):
        time_to_seconds("1:2:3:4")  # liian monta osaa
    with pytest.raises(ValueError):
        time_to_seconds("")  # tyhjä


def test_time_to_seconds_omitted_start_is_zero():
    """Hindenburg jättää ``Start``in pois kun alue alkaa nollasta.

    ``region.get("Start")`` on silloin None, ei tyhjä merkkijono. Tyhjä
    merkkijono on virhe; puuttuva attribuutti on mitattu nolla.
    """
    assert time_to_seconds(None) == 0.0


def test_auto_silence_reads_a_region_with_no_start(tmp_path):
    """Ensimmäinen alue h-test A:ssa on ``Length`` ilman ``Start``ia."""
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session>
      <AudioPool Path="">
        <File Id="1" Name="a.wav" Path="a.wav">
          <Transcription><p><w s="0.5" l="0.2" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1" Length="5.000" Offset="0.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = tree.find(".//Track")
    intervals = get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35)
    assert intervals == [(0.5, 0.7)]


def test_seconds_to_time():
    assert seconds_to_time(0) == "0.000"
    assert seconds_to_time(1.5) == "1.500"
    assert seconds_to_time(90) == "90.000"


def test_merge_intervals_with_gap():
    intervals = [(1.0, 2.0), (3.0, 4.0)]
    # gap 0 -> ei yhdistä
    assert merge_intervals_with_gap(intervals, 0.0) == [(1.0, 2.0), (3.0, 4.0)]
    # gap 1.5 -> yhdistää (1.0, 2.0) ja (3.0, 4.0) kun gap 1.5 >= 1.0
    assert merge_intervals_with_gap(intervals, 1.5) == [(1.0, 4.0)]
    # tyhjä lista
    assert merge_intervals_with_gap([], 1.0) == []


def test_merge_intervals_does_not_modify_input():
    intervals = [(3.0, 4.0), (1.0, 2.0)]
    original = list(intervals)
    merge_intervals_with_gap(intervals, 0.0)
    assert intervals == original  # ei muokkaa alkuperäistä


def test_inject_replaces_only_the_audio_suffix(tmp_path):
    """Pääte vaihdetaan kirjainkoosta riippumatta, eikä keskeltä nimeä.

    ``replace(".wav", ".json")`` jättää ``A.WAV`` ennalleen ja tekee
    ``take.wav.wav``:sta ``take.json.json``.
    """
    from xml.etree import ElementTree

    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    (outbox / "transcripts" / "take.wav.json").write_text(
        '{"segments":[{"words":[{"start":0.1,"end":0.3,"word":"hei"}]}]}',
        encoding="utf-8",
    )
    (inbox / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
      <AudioPool><File Id="1" Name="take.wav.WAV" Path="take.wav.WAV"/></AudioPool>
    </Session>""",
        encoding="utf-8",
    )
    inject_transcriptions_to_nhsx(str(inbox), str(outbox))
    written = next(outbox.glob("*litteroitu*"))
    tree = ElementTree.parse(written)
    words = [w.text for w in tree.findall(".//w")]
    assert words == ["hei"]


def test_inject_does_not_read_a_name_outside_transcripts(tmp_path):
    """File/@Name on käyttäjän XML:ä, ei polku transcripts-kansioon."""
    from xml.etree import ElementTree

    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    secret = tmp_path / "secret.json"
    secret.write_text(
        '{"segments":[{"words":[{"start":0,"end":1,"word":"LEAK"}]}]}',
        encoding="utf-8",
    )
    (inbox / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
      <AudioPool><File Id="1" Name="../../secret.wav" Path="a.wav"/></AudioPool>
    </Session>""",
        encoding="utf-8",
    )
    inject_transcriptions_to_nhsx(str(inbox), str(outbox))
    written = next(outbox.glob("*litteroitu*"))
    text = ElementTree.parse(written).find(".//w")
    assert text is None or (text.text or "") != "LEAK"


def test_inject_writes_utf8(tmp_path):
    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    (outbox / "transcripts" / "a.json").write_text(
        '{"segments":[{"words":[{"start":0.1,"end":0.3,"word":"ää"}]}]}',
        encoding="utf-8",
    )
    (inbox / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
      <AudioPool><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>
    </Session>""",
        encoding="utf-8",
    )
    inject_transcriptions_to_nhsx(str(inbox), str(outbox))
    raw = next(outbox.glob("*litteroitu*")).read_bytes()
    assert "ää".encode() in raw
    assert raw.startswith(b"<?xml")


def test_quoted_region_ref_does_not_crash_auto_silence(tmp_path):
    """Ref menee XPath-predikaattiin lainausmerkeissä: `'` kaataa lxml:n."""
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session>
      <AudioPool>
        <File Id="1" Name="a.wav">
          <Transcription><p><w s="0.5" l="0.2" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1'" Length="5.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = tree.find(".//Track")
    assert get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35) == []


def test_auto_silence_reads_namespaced_sessions(tmp_path):
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session xmlns="urn:hindenburg">
      <AudioPool>
        <File Id="1" Name="a.wav">
          <Transcription><p><w s="0.5" l="0.2" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1" Length="5.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = next(e for e in tree.iter() if e.tag.endswith("Track"))
    assert get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35) == [
        (0.5, 0.7)
    ]


def test_auto_silence_handles_colon_word_times(tmp_path):
    """Sanan ``s`` voi olla muodossa ``MM:SS`` vanhemmissa istunnoissa.

    ``float("01:30")`` kaataisi koko Auto-Silencen. Jäsennin käyttää
    ``time_to_seconds``ia kuten muutkin toteutukset — sama aika, sama
    muoto, sama tulos.
    """
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session>
      <AudioPool Path="">
        <File Id="1" Name="a.wav" Path="a.wav">
          <Transcription><p><w s="01:30" l="0.5" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1" Start="0.000" Length="120.000" Offset="0.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = tree.find(".//Track")
    intervals = get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35)
    assert intervals == [(90.0, 90.5)]


def test_inject_rejects_a_doctype(tmp_path):
    """Istunto ei saa julistaa DTD:tä.

    ``<!DOCTYPE>`` avaisi ovi entiteettejä: tiedostojen luku (XXE) ja
    laajennus. Kelvollinen ``.nhsx`` ei koskaan julista DTD:tä, joten
    julistava tiedosto hylätään eikä käsitellä.
    """
    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    (inbox / "evil.nhsx").write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE Session [<!ENTITY name "a.wav">]>\n'
        '<Session><AudioPool><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>'
        '<Tracks><Track Name="t"><Region Ref="1" Start="0" Length="1"/></Track></Tracks></Session>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        inject_transcriptions_to_nhsx(str(inbox), str(outbox))
