"""Vaimennus: puhejaksot, kuuluvat alueet ja pilkkominen."""

from __future__ import annotations

from itertools import pairwise

from lxml import etree
from podcastmagic import nhsx
from podcastmagic.silence.apply import (
    audible_zones,
    has_region_children,
    merge,
    split_track,
)
from podcastmagic.silence.detect import speech_intervals
from podcastmagic.silence.presets import PRESETS, Settings


def test_merge_closes_only_short_gaps():
    assert merge([(0.0, 1.0), (1.2, 2.0)], 0.4) == [(0.0, 2.0)]
    assert merge([(0.0, 1.0), (1.6, 2.0)], 0.4) == [(0.0, 1.0), (1.6, 2.0)]


def test_region_children_are_noticed_before_they_are_dropped():
    """Pilkkominen pudottaa alueen lapset, ja siitä pitää voida kertoa.

    Sama häivytys sadassa palassa on eri asia kuin yksi häivytys alueen
    alussa, joten `run` varoittaa siitä lokissa. Muistikirja pudotti ne
    hiljaa, eikä sitä huomaa ennen kuin kuuntelee. Tämä on se tarkistus,
    jonka varassa varoitus on — ja se katsoo vain `Region`-elementtejä,
    ei mitä tahansa raidan lasta.
    """
    track = etree.fromstring(
        "<Track Name='Olli'>"
        "<Region Ref='1' Start='0.000' Length='12.000' Offset='0.000'/>"
        "</Track>"
    )
    assert has_region_children(track) is False

    # Raidan oma lapsi lapsineen ei ole alueen lapsi: pilkkominen ei koske
    # siihen, joten se ei saa laukaista varoitusta.
    etree.SubElement(etree.SubElement(track, "Automation"), "Point")
    assert has_region_children(track) is False

    etree.SubElement(track[0], "Fade")
    assert has_region_children(track) is True


def test_gap_stays_open_when_both_controls_allow_it():
    zones = audible_zones([(0.0, 1.0), (2.0, 3.0)], tail=0.1, gap=0.4)
    assert len(zones) == 2


def test_the_tail_closes_gaps_the_gap_control_would_not():
    """Kaksi säädintä sulkee taukoja, ja suurempi ratkaisee.

    Sanaväli on 1,0 s ja «lyhin tauko» 0,4 s, joten tauko ei sulkeudu siitä.
    Häntä 0,5 s molempiin päihin sulkee sen silti: hännät kohtaavat keskellä.
    Tämä on käyttäjälle yllättävää ja siksi kiinnitetty testiin — ei siksi
    että se olisi väärin, vaan jotta se ei muutu vahingossa.
    """
    zones = audible_zones([(0.0, 1.0), (2.0, 3.0)], tail=0.5, gap=0.4)
    assert zones == [(0.0, 3.5)]


def test_the_two_controls_do_not_add_up():
    """Sulkeutumisraja on suurempi säätimistä, ei niiden summa.

    Häntä lisätään vasta taukojen sulkemisen jälkeen. Toisin päin raja olisi
    ``gap + 2 × tail`` = 1,4 s ja 1,2 sekunnin tauko sulkeutuisi.
    """
    zones = audible_zones([(0.0, 1.0), (2.2, 3.0)], tail=0.4, gap=0.6)
    assert len(zones) == 2


def test_tail_does_not_run_past_zero():
    zones = audible_zones([(0.1, 0.5)], tail=1.0, gap=0.0)
    assert zones[0][0] == 0.0


def test_speech_intervals_are_timeline_time(session_file):
    """Sanan aika on tiedoston aikaa; jakson paikka on Start + (s - Offset)."""
    session = nhsx.read(session_file)
    track = session.tracks[0]
    track.regions[0].start = 100.0
    track.regions[0].offset = 0.5
    result = speech_intervals(session, track, Settings(rms=False))
    # Ensimmäinen sana alkaa tiedostossa 1,0 s ja alue on offsetissa 0,5 s.
    assert result.intervals[0][0] == 100.5
    assert result.words_seen == 3


def test_words_outside_the_region_are_not_counted(session_file):
    session = nhsx.read(session_file)
    track = session.tracks[0]
    track.regions[0].offset = 0.0
    track.regions[0].length = 2.0  # vain kaksi ensimmäistä sanaa mahtuu
    result = speech_intervals(session, track, Settings(rms=False))
    assert result.words_seen == 2


def test_split_mutes_the_gap_and_keeps_the_speech(session_file):
    session = nhsx.read(session_file)
    track = session.tracks[0]
    result = speech_intervals(session, track, Settings(rms=False))
    zones = audible_zones(result.intervals, tail=0.4, gap=0.4)
    heard, muted = split_track(track.elem, zones)
    assert heard >= 2 and muted >= 1

    pieces = [c for c in track.elem if c.tag == "Region"]
    assert len(pieces) == heard + muted
    # Palat peittävät alkuperäisen alueen ilman aukkoja ja päällekkäisyyksiä.
    edges = [(float(p.get("Start")), float(p.get("Length"))) for p in pieces]
    edges.sort()
    assert edges[0][0] == 0.0
    for (start, length), (next_start, _) in pairwise(edges):
        assert abs(start + length - next_start) < 1e-6
    assert abs(edges[-1][0] + edges[-1][1] - 12.0) < 1e-6


def test_offset_follows_the_split(session_file):
    """Palan Offset on alkuperäinen offset plus siirtymä alueen alusta.

    Tämä on se kohta jossa väärä laskenta ei näy XML:ssä millään tavalla:
    tiedosto avautuu, alueet ovat oikean mittaisia, ja ääni tulee väärästä
    kohtaa tiedostoa.
    """
    session = nhsx.read(session_file)
    track = session.tracks[0]
    track.regions[0].elem.set("Offset", "5.000")
    zones = [(2.0, 4.0)]
    split_track(track.elem, zones)
    pieces = sorted(
        [c for c in track.elem if c.tag == "Region"],
        key=lambda p: float(p.get("Start")),
    )
    for piece in pieces:
        start = float(piece.get("Start"))
        assert abs(float(piece.get("Offset")) - (5.0 + start)) < 1e-6


def test_a_track_with_no_transcription_is_left_alone(session_file):
    """Musiikki ja tunnukset eivät ole puhetta, eikä tiedon puute ole päätös.

    Ilman litterointia raidalla ei ole yhtään puhejaksoa, ja pilkkominen
    tyhjällä listalla vaimentaisi koko raidan. Tiedosto avautuisi
    normaalisti ja puuttuvan musiikin huomaisi vasta kuuntelemalla.
    """
    from podcastmagic.jobs import Job, Progress
    from podcastmagic.silence import run as runner

    result = runner.run(str(session_file), Settings(rms=False),
                        Progress(Job(id=0, module="t", label="t")))
    panu = next(row for row in result["tracks"] if row["name"] == "Panu")
    assert panu["skipped"] and panu["muted"] == 0

    written = nhsx.read(result["written"])
    regions = next(t for t in written.tracks if t.name == "Panu").regions
    assert len(regions) == 1
    assert regions[0].elem.get("Muted") is None


def test_presets_match_the_notebook():
    assert PRESETS["remote"].tail == 1.0 and PRESETS["remote"].rms is False
    assert PRESETS["bleed"].tail == 0.4 and PRESETS["bleed"].rms is True


def test_settings_are_clamped():
    settings = Settings.from_dict({"tail": 99, "gap": -3, "threshold": 40})
    assert settings.tail == 5.0 and settings.gap == 0.0 and settings.threshold == 0.0
