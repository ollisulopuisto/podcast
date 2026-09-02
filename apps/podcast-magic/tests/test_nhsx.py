"""Istuntotiedoston luku ja kirjoitus."""

from __future__ import annotations

import pytest

from podcastmagic import nhsx
from podcastmagic.nhsx.read import NhsxError, locate, time_to_seconds
from podcastmagic.nhsx.read import read as read_session
from podcastmagic.nhsx.write import next_free_path, set_transcription


def test_reads_pool_and_tracks(session_file):
    session = nhsx.read(session_file)
    assert [f.name for f in session.files] == ["olli.wav", "panu.wav"]
    assert [t.name for t in session.tracks] == ["Olli", "Panu"]
    assert session.tracks[0].regions[0].ref == "1"


def test_words_carry_start_and_length(session_file):
    session = nhsx.read(session_file)
    words = session.file_by_id("1").words()
    assert [w.text for w in words] == ["Terve", "vaan", "jatketaan"]
    assert words[0].start == 1.0
    assert words[0].end == 1.4


def test_untranscribed_file_is_visible_as_such(session_file):
    session = nhsx.read(session_file)
    assert session.file_by_id("1").transcribed
    assert not session.file_by_id("2").transcribed


def test_time_accepts_both_notations():
    assert time_to_seconds("12.5") == 12.5
    assert time_to_seconds("01:02:03") == 3723.0
    assert time_to_seconds("02:03") == 123.0
    # Rikkinäinen arvo nostaa poikkeuksen (ei hiljaista nollaa); puuttuva
    # arvo (None) on nolla. Sama sovitu kuin jaetussa nhsx-paketissa.
    with pytest.raises(ValueError):
        time_to_seconds("kaksitoista")
    assert time_to_seconds(None) == 0.0


def test_time_rejects_more_than_three_parts():
    """``HH:MM:SS`` on enimmäkseen: neljästä osasta koostuva arvo on rikkinäinen.

    Ilman vartijaa ``1:2:3:4`` laskettaisiin päiviksi (223 384 s) ja alue
    sijoittuisi kymmenen päivän päähän hiljaisesti. Kaikki jäsennit — tämä,
    jaettu nhsx-paketti ja Colabin snapshot — hylkäävät sen poikkeuksella.
    """
    with pytest.raises(ValueError):
        time_to_seconds("1:2:3:4")


def test_read_raises_nhsxerror_on_malformed_region_time(tmp_path):
    """Rikkinäinen alueen aika on NhsxError, ei hiljainen nolla.

    Sama sovitu kuin jaetussa ``nhsx``-paketissa: luku pinottaa NhsxErrorin,
    eikä sijoita aluetta kymmenen päivän päähän.
    """
    (tmp_path / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
          <Tracks><Track Name="t"><Region Ref="1" Start="1:2:3:4" Length="1"/></Track></Tracks>
        </Session>""",
        encoding="utf-8",
    )
    with pytest.raises(NhsxError):
        read_session(tmp_path / "s.nhsx")


def test_locate_does_not_treat_the_filename_as_a_glob(tmp_path):
    """rglob(Name) tulkitsi ``*``:n kuvioksi ja osui ensimmäiseen tiedostoon."""
    (tmp_path / "real.wav").write_bytes(b"")
    (tmp_path / "other.wav").write_bytes(b"")
    (tmp_path / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
      <AudioPool Path="">
        <File Id="1" Name="*" Path="*"/>
      </AudioPool>
      <Tracks><Track Name="t"><Region Ref="1" Start="0" Length="1"/></Track></Tracks>
    </Session>""",
        encoding="utf-8",
    )
    session = read_session(tmp_path / "s.nhsx")
    assert locate(session, session.files[0]) == ""


def test_read_does_not_resolve_external_entities(tmp_path):
    """Istunto on käyttäjän tiedosto. Entiteetti ei saa lukea levyä."""
    secret = tmp_path / "secret.txt"
    secret.write_text("LEAKME", encoding="utf-8")
    path = tmp_path / "evil.nhsx"
    path.write_text(
        f"""<?xml version="1.0"?>
<!DOCTYPE Session [
  <!ENTITY xxe SYSTEM "{secret.as_uri()}">
]>
<Session>
  <AudioPool Path="">
    <File Id="1" Name="a.wav" Path="a.wav">&xxe;</File>
  </AudioPool>
  <Tracks>
    <Track Name="t"><Region Ref="1" Start="0" Length="1"/></Track>
  </Tracks>
</Session>
""",
        encoding="utf-8",
    )
    try:
        session = nhsx.read(path)
    except nhsx.NhsxError:
        return
    leaked = "LEAKME" in "".join(
        [(f.name or "") + (f.path or "") + ((f.elem.text or "") if f.elem is not None else "")
         for f in session.files]
    )
    assert not leaked


def test_second_transcription_replaces_the_first(session_file):
    """Uudelleenlitterointi ei saa jättää kahta <Transcription>ia."""
    session = nhsx.read(session_file)
    file_info = session.file_by_id("1")
    set_transcription(file_info.elem, [nhsx.Word("uusi", 2.0, 0.5)])
    from podcastmagic.nhsx.read import children

    assert len(children(file_info.elem, "Transcription")) == 1
    assert [w.text for w in file_info.words()] == ["uusi"]


def test_empty_words_are_dropped(session_file):
    session = nhsx.read(session_file)
    file_info = session.file_by_id("2")
    report = set_transcription(file_info.elem, [
        nhsx.Word("  ", 1.0, 0.2), nhsx.Word("sana", 2.0, 0.2),
    ])
    assert report["words"] == 1


def test_existing_output_is_never_overwritten(tmp_path):
    first = tmp_path / "jakso litteroitu.nhsx"
    assert next_free_path(first) == first
    first.write_text("x")
    second = next_free_path(first)
    assert second.name == "jakso litteroitu v2.nhsx"
    second.write_text("x")
    assert next_free_path(first).name == "jakso litteroitu v3.nhsx"
