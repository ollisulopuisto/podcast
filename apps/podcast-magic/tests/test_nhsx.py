"""Istuntotiedoston luku ja kirjoitus."""

from __future__ import annotations

from podcastmagic import nhsx
from podcastmagic.nhsx.read import time_to_seconds
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
    # Rikkinäinen arvo on nolla, ei poikkeus: yksi attribuutti ei kaada lukua.
    assert time_to_seconds("kaksitoista") == 0.0
    assert time_to_seconds(None) == 0.0


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
