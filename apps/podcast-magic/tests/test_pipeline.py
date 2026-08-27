"""Sauma puheenkäsittelyketjulle.

Ketjua ei ole vielä täällä. Tämä kiinnittää sen sanaston, jolla istunto
sille annetaan, jotta ketjun tuominen tänne on ketjun tuomista eikä lukijan
uudelleenkirjoittamista.
"""

from __future__ import annotations

from podcastmagic import nhsx
from podcastmagic.nhsx import pipeline


def test_a_track_becomes_a_speaker_with_spans(session_file):
    (session_file.parent / "olli.wav").write_bytes(b"")
    (session_file.parent / "panu.wav").write_bytes(b"")
    session = nhsx.read(session_file)
    tracks = pipeline.tracks(session, with_probe=False)
    assert [t.speaker for t in tracks] == ["Olli", "Panu"]
    assert all(t.mono for t in tracks)
    assert tracks[0].spans[0].programme_start == 0.0


def test_programme_time_converts_to_file_time(session_file):
    """Yksi kaava on kaikki mitä ketju tarvitsee aikajanasta tietää."""
    (session_file.parent / "olli.wav").write_bytes(b"")
    session = nhsx.read(session_file)
    session.tracks[0].regions[0].elem.set("Start", "100.0")
    session.tracks[0].regions[0].start = 100.0
    session.tracks[0].regions[0].offset = 5.0
    track = pipeline.tracks(session, with_probe=False)[0]
    assert track.spans[0].file_time(110.0) == 15.0


def test_a_track_with_no_audio_on_disk_is_left_out(session_file):
    """Ketju käsittelee tiedostoja. Tiedosto jota ei ole ei ole raita."""
    session = nhsx.read(session_file)
    assert pipeline.tracks(session, with_probe=False) == []
