"""Kuvavalikoima on riippumaton puhujien järjestyksestä."""

import numpy as np

from autoraffkat import preview
from autoraffkat.decide import Grid, ShotLanes, SpeakerLanes, _want_array, decide
from autoraffkat.model import Globals
from autoraffkat.project import ProjectSettings


def test_legacy_settings_migrate_without_losing_microphones():
    settings = ProjectSettings.from_json({'tracks': {
        'wide': {'role': 'wide'},
        'a': {'role': 'close', 'speaker': 'A'},
        'ab': {'role': 'group', 'covers': ['A', 'B']},
        'mic': {'role': 'mic', 'speaker': 'B', 'gain_db': 3},
    }})
    assert settings.tracks['wide'].role == 'shot'
    assert settings.tracks['wide'].covers == ['A', 'B']
    assert settings.tracks['wide'].context
    assert settings.tracks['a'].covers == ['A']
    assert settings.tracks['ab'].covers == ['A', 'B']
    assert settings.tracks['mic'].gain_db == 3
    assert ProjectSettings.from_json(settings.to_json()) == settings


def shot_grid():
    n = 1000
    return Grid(n, 0, speakers=[
        SpeakerLanes('A', np.full(n, -20), np.ones(n, bool), None),
        SpeakerLanes('B', np.full(n, -20), np.zeros(n, bool), None),
    ], shots=[
        ShotLanes('room', 'Room', (0, 1), context=True),
        ShotLanes('a1', 'A', (0,)),
        ShotLanes('a2', 'A alternate', (0,)),
    ])


def test_shot_indices_and_preview_inventory():
    grid = shot_grid()
    result = decide(grid, Globals(wide_every=0, min_shot=1))
    assert [s.angle for s in result.segments] == ['room', 'a1', 'room']
    assert result.chosen[500] == 1
    payload = preview.build(grid, result)
    assert [s['key'] for s in payload['shots']] == ['room', 'a1', 'a2']


def test_available_equal_coverage_holds_current_camera():
    grid = shot_grid()
    grid.shots[1].available = np.arange(grid.n) >= 200
    want, _ = _want_array(grid, Globals())
    assert np.all(want == 2)


def test_all_speaker_shot_infers_context_but_single_person_does_not():
    grid = shot_grid()
    grid.shots[0].context = False
    assert grid.context_key == 'room'
    grid.speakers.pop()
    grid.shots = grid.shots[1:]
    assert grid.context_key == ''


def test_roles_preserve_every_camera_in_track_order():
    from fractions import Fraction

    from autoraffkat.analysis import resolve_roles
    from autoraffkat.finalcut.read import Timeline, Track
    from autoraffkat.model import TrackConfig

    timeline = Timeline([], Fraction(1, 25), 'project', 't', tracks=[
        Track(key, key, has_video=True) for key in ['a1', 'room', 'a2', 'mic']
    ])
    roles = resolve_roles(timeline, {
        'a1': TrackConfig(role='shot', covers=['A']),
        'room': TrackConfig(role='shot', covers=['A', 'B']),
        'a2': TrackConfig(role='shot', covers=['A']),
        'mic': TrackConfig(role='mic', speaker='B'),
    })
    assert [shot.key for shot in roles.shots] == ['a1', 'room', 'a2']
    assert roles.closes == {'A': 'a1'}
    assert roles.speakers == ['A', 'B']
    assert roles.wide_key == 'room'
    assert roles.visual_speakers == ['A']
    assert roles.problems == []


def test_single_person_context_remains_a_closeup_for_visual_speech():
    from fractions import Fraction

    from autoraffkat.analysis import resolve_roles
    from autoraffkat.finalcut.read import Timeline, Track
    from autoraffkat.model import TrackConfig

    timeline = Timeline([], Fraction(1, 25), 'project', 't', tracks=[Track('a', 'A')])
    roles = resolve_roles(timeline, {
        'a': TrackConfig(role='shot', covers=['A'], context=True),
    })
    assert roles.closes == {'A': 'a'}
    assert roles.visual_speakers == ['A']


def test_short_confirmed_overlap_keeps_context_cut():
    grid = shot_grid()
    grid.speakers[1].on[500:530] = True
    result = decide(grid, Globals(min_shot=1, min_overlap=.3, confirm=.2,
                                  lead=0, hang=0, wide_every=0))
    assert any(s.angle == 'room' and s.start == 10 for s in result.segments)


def test_unused_tracks_do_not_expand_legacy_wide_coverage():
    settings = ProjectSettings.from_json({'tracks': {
        'room': {'role': 'wide'},
        'mic': {'role': 'mic', 'speaker': 'A'},
        'old': {'role': 'unused', 'covers': ['Former guest']},
    }})
    assert settings.tracks['room'].covers == ['A']


def test_ordinary_selection_prefers_group_over_equal_coverage_context():
    grid = shot_grid()
    grid.shots = [grid.shots[0], ShotLanes('pair', 'A & B', (0, 1))]
    grid.speakers[1].on[500:700] = True
    result = decide(grid, Globals(min_shot=1, lead=0, hang=0, wide_every=0))
    assert [s.angle for s in result.segments] == ['room', 'pair', 'room']
    assert result.chosen[600] == 1


def test_every_explicit_context_is_a_fallback():
    grid = shot_grid()
    grid.shots = [grid.shots[0], ShotLanes('other_room', 'Room 2', (0, 1), context=True),
                  ShotLanes('pair', 'A & B', (0, 1))]
    result = decide(grid, Globals(min_shot=1, wide_every=0))
    assert result.chosen[500] == 2
