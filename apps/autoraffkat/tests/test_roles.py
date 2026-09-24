"""Roolitus: raitojen roolit puhujiksi ja kuviksi."""

from fractions import Fraction

from autoraffkat import project
from autoraffkat.analysis import resolve_roles
from autoraffkat.fcpxml.read import Timeline, Track
from autoraffkat.model import (
    ROLE_CLOSE,
    ROLE_GROUP,
    ROLE_MIC,
    ROLE_WIDE,
    TrackConfig,
)


def _timeline(*keys):
    return Timeline(
        media=[], frame_duration=Fraction(1, 25), kind="project", name="t",
        tracks=[Track(key=k, name=k, has_video=k.startswith("CAM"),
                      has_audio=k.startswith("MIC")) for k in keys],
    )


def _studio(covers):
    """Kolme kameraa ja kolme mikkiä: A laaja, B kahden kuva, C lähikuva."""
    return {
        "CAM A": TrackConfig(role=ROLE_WIDE),
        "CAM B": TrackConfig(role=ROLE_GROUP, covers=covers),
        "CAM C": TrackConfig(role=ROLE_CLOSE, speaker="3"),
        "MIC 1": TrackConfig(role=ROLE_MIC, speaker="1"),
        "MIC 2": TrackConfig(role=ROLE_MIC, speaker="2"),
        "MIC 3": TrackConfig(role=ROLE_MIC, speaker="3"),
    }


TIMELINE = _timeline("CAM A", "CAM B", "CAM C", "MIC 1", "MIC 2", "MIC 3")


def test_a_group_shot_covers_the_named_speakers():
    roles = resolve_roles(TIMELINE, _studio(["1", "2"]))
    assert roles.problems == []
    assert roles.groups == {"CAM B": ["1", "2"]}
    assert roles.closes == {"3": "CAM C"}


def test_a_group_shot_of_nobody_is_a_problem():
    roles = resolve_roles(TIMELINE, _studio([]))
    assert any("CAM B" in p for p in roles.problems), roles.problems


def test_a_group_shot_of_an_unknown_speaker_is_a_problem():
    """Nimi joka ei ole kenenkään mikki on kirjoitusvirhe tai vanha nimi.

    Hiljaa ohitettuna kuva jäisi käyttämättä eikä mikään kertoisi miksi.
    """
    roles = resolve_roles(TIMELINE, _studio(["1", "Kakkonen"]))
    assert any("Kakkonen" in p for p in roles.problems), roles.problems


def test_group_shots_alone_are_enough_pictures():
    tracks = _studio(["1", "2", "3"])
    tracks["CAM C"] = TrackConfig()
    roles = resolve_roles(TIMELINE, tracks)
    assert roles.problems == []


def test_covers_survive_a_save(tmp_path):
    xml = tmp_path / "jakso.fcpxml"
    xml.write_text("<fcpxml/>")
    project.save(str(xml), project.ProjectSettings(tracks=_studio(["1", "2"])))
    again = project.load(str(xml))
    assert again.tracks["CAM B"].role == ROLE_GROUP
    assert again.tracks["CAM B"].covers == ["1", "2"]
