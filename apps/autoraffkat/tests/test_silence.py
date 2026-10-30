from types import SimpleNamespace

import numpy as np
import pytest

from autoraffkat.audio import silence
from autoraffkat.decide import SpeakerLanes
from autoraffkat.model import HOP, AudioSettings
from autoraffkat.preview import build as build_preview


def _grid(active_ranges, n=200, program_start=12.5):
    speakers = []
    for name, ranges in active_ranges.items():
        on = np.zeros(n, dtype=bool)
        for start, end in ranges:
            on[start:end] = True
        speakers.append(
            SpeakerLanes(name, np.zeros(n), on, close_key=None)
        )
    return SimpleNamespace(n=n, duration=n * HOP, program_start=program_start,
                           speakers=speakers)


def test_dead_air_only_includes_interior_gaps_meeting_minimum_duration():
    grid = _grid({"Aino": [(0, 50)], "Pekka": [(150, 200)]})

    spans = silence.dead_air_spans(grid, minimum=2.0)

    assert spans == pytest.approx([(12.5 + 50 * HOP, 12.5 + 150 * HOP)])


def test_dead_air_ignores_short_gaps_and_gaps_at_program_edges():
    grid = _grid({"Aino": [(30, 70)], "Pekka": [(120, 160)]})

    spans = silence.dead_air_spans(grid, minimum=1.1)

    assert spans == []


def test_enabled_silence_pass_builds_faded_envelopes_for_each_dialogue_speaker():
    grid = _grid({"Aino": [(0, 50)], "Pekka": [(150, 200)]})
    settings = AudioSettings(
        silence_pass=True,
        silence_min_gap=2.0,
        silence_db=-48.0,
        silence_fade=0.4,
    )

    envelopes = silence.silence_envelopes(grid, settings)

    expected = [
        (12.5 + 50 * HOP, 0.0),
        (12.5 + 50 * HOP + 0.4, -48.0),
        (12.5 + 150 * HOP - 0.4, -48.0),
        (12.5 + 150 * HOP, 0.0),
    ]
    assert set(envelopes) == {"Aino", "Pekka"}
    assert envelopes["Aino"] == pytest.approx(expected)
    assert envelopes["Pekka"] == pytest.approx(expected)


def test_silence_settings_are_default_off_and_round_trip():
    defaults = AudioSettings().to_json()
    configured = AudioSettings(
        silence_pass=True, silence_min_gap=3.5, silence_db=-42.0,
        silence_fade=0.25,
    )

    assert defaults["silence_pass"] is False
    assert defaults["silence_min_gap"] == 2.0
    assert AudioSettings.from_json(configured.to_json()) == configured

def test_disabled_silence_pass_emits_no_envelopes():
    grid = _grid({"Aino": [(0, 50)], "Pekka": [(150, 200)]})

    assert silence.silence_envelopes(grid, AudioSettings()) == {}


def test_preview_carries_visible_gaps_and_fade_for_timeline_lane():
    grid = _grid({"Aino": [(0, 50)], "Pekka": [(150, 200)]})
    decision = SimpleNamespace(chosen=np.zeros(grid.n, dtype=np.int32))
    start = 12.5 + 50 * HOP
    end = 12.5 + 150 * HOP

    preview = build_preview(
        grid, decision, columns=20, window=(start + 0.2, end - 0.2),
        silence_spans=[(start, end)], silence_fade=0.4,
    )

    assert preview["silence"] == [{"start": start, "end": end, "fade": 0.4}]


def test_merging_duck_and_silence_uses_stronger_layer_without_adding_depth():
    merged = silence.merge_envelopes(
        {"Aino": [(0.0, 0.0), (1.0, -12.0), (2.0, 0.0)]},
        {"Aino": [(0.5, 0.0), (1.5, -48.0), (2.5, 0.0)]},
    )

    assert merged["Aino"] == pytest.approx([
        (0.0, 0.0), (0.5, -6.0), (2 / 3, -8.0), (1.0, -24.0),
        (1.5, -48.0), (2.0, -24.0), (2.5, 0.0),
    ])


def test_merging_preserves_the_crossing_of_two_fades():
    merged = silence.merge_envelopes(
        {"Aino": [(0.0, -20.0), (2.0, 0.0)]},
        {"Aino": [(0.0, 0.0), (2.0, -20.0)]},
    )

    assert merged["Aino"] == pytest.approx([
        (0.0, -20.0), (1.0, -10.0), (2.0, -20.0),
    ])
