"""Learning from clips: muted and unmuted stretches of a file as examples, no words.

kuulas has clips (a stretch of a media file, muted by the user or not) and level
windows, and no transcript. ``calibrate_clips`` learns a threshold from them.
"""

from __future__ import annotations

import pytest

import silencelearn as sl
from silencelearn import Calibration, Clip, calibrate_clips


class Levels:
    """Piecewise constant levels: ``{ref: [(start, end, dBFS), ...]}``.

    Only ``level`` and ``missing``: no ``words``, which is the point."""

    def __init__(self, table, missing=False):
        self.table = table
        self._missing = missing

    def level(self, ref, start, end):
        mid = (start + end) / 2
        for a, b, level in self.table.get(ref, []):
            if a <= mid < b:
                return level
        return None

    def missing(self):
        return self._missing


NOISE, SPEECH = -50.0, -20.0


def example():
    """10 s of noise to mute, then 10 s of speech to keep, in one file."""
    levels = Levels({"a": [(0.0, 10.0, NOISE), (10.0, 20.0, SPEECH)]})
    clips = [Clip("a", 0.0, 10.0, muted=True), Clip("a", 10.0, 20.0, muted=False)]
    return clips, levels


def test_the_threshold_is_just_above_what_was_muted():
    clips, levels = example()
    found = calibrate_clips(clips, levels)
    assert found.reason == ""
    assert found.threshold == pytest.approx(NOISE + sl.MARGIN_DB)
    assert found.muted_seconds == pytest.approx(10.0)
    assert found.speech_level == pytest.approx(SPEECH)


def test_it_needs_no_words_from_the_source():
    clips, levels = example()
    assert not hasattr(levels, "words")
    assert calibrate_clips(clips, levels).threshold is not None


def test_spikes_among_the_muted_windows_are_ignored_like_in_the_word_based_learning():
    """90th percentile: a cough in about 1 % of the muted time does not set the level."""
    levels = Levels({"a": [(0.0, 30.0, NOISE), (30.0, 30.6, -20.0), (30.6, 60.0, NOISE),
                           (60.0, 70.0, SPEECH)]})
    found = calibrate_clips(
        [Clip("a", 0.0, 60.0, muted=True), Clip("a", 60.0, 70.0)], levels
    )
    assert found.threshold == pytest.approx(NOISE + sl.MARGIN_DB)


def test_the_threshold_is_the_percentile_of_the_muted_windows_plus_the_margin():
    # Half the muted time at -50, half at -40: the 90th percentile is -40.
    levels = Levels({"a": [(0.0, 5.0, -50.0), (5.0, 10.0, -40.0), (10.0, 20.0, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)], levels)
    assert found.threshold == pytest.approx(-40.0 + sl.MARGIN_DB)


def test_too_little_muted_audio_teaches_nothing_and_says_how_much():
    levels = Levels({"a": [(0.0, 2.0, NOISE), (2.0, 12.0, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 2.0, True), Clip("a", 2.0, 12.0)], levels)
    assert found.threshold is None
    assert "liian vähän" in found.reason and "2.0 s" in found.reason


def test_exactly_the_minimum_seconds_is_enough():
    levels = Levels({"a": [(0.0, sl.MIN_SECONDS, NOISE), (5.0, 15.0, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, sl.MIN_SECONDS, True), Clip("a", 5.0, 15.0)], levels)
    assert found.threshold is not None, found.reason


def test_nothing_muted_says_so():
    levels = Levels({"a": [(0.0, 10.0, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0)], levels)
    assert found.threshold is None and found.reason == "ei käsin vaimennettuja alueita"


def test_a_missing_file_is_told_apart_from_nothing_muted():
    found = calibrate_clips([Clip("a", 0.0, 10.0, True)], Levels({}, missing=True))
    assert found.threshold is None and found.reason == "ääntä ei löytynyt"


def test_a_threshold_at_the_level_of_the_kept_speech_is_refused():
    """If what was muted is as loud as what was kept, speech was muted by mistake."""
    levels = Levels({"a": [(0.0, 10.0, -22.0), (10.0, 20.0, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)], levels)
    assert found.threshold is None
    assert "vaimennettiinko puhetta" in found.reason


def test_the_guard_refuses_at_exactly_the_guard_distance_and_not_beyond():
    # threshold = muted + margin; refused when threshold >= speech - guard.
    edge = SPEECH - sl.GUARD_DB - sl.MARGIN_DB
    refused = calibrate_clips(
        [Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)],
        Levels({"a": [(0.0, 10.0, edge), (10.0, 20.0, SPEECH)]}),
    )
    allowed = calibrate_clips(
        [Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)],
        Levels({"a": [(0.0, 10.0, edge - 0.01), (10.0, 20.0, SPEECH)]}),
    )
    assert refused.threshold is None
    assert allowed.threshold is not None


def test_without_unmuted_examples_the_threshold_is_learned_without_the_guard():
    levels = Levels({"a": [(0.0, 10.0, NOISE)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True)], levels)
    assert found.threshold == pytest.approx(NOISE + sl.MARGIN_DB)
    assert found.speech_level is None


def test_a_few_unmuted_windows_are_not_enough_for_the_guard():
    n = sl.MIN_SPEECH_WINDOWS - 1
    length = sl.WINDOW + (n - 1) * sl.HOP
    levels = Levels({"a": [(0.0, 10.0, -22.0), (10.0, 10.0 + length, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 10.0 + length)], levels)
    assert found.unmuted_frames == n
    assert found.speech_level is None
    assert found.threshold is not None  # no guard, so the too-loud mute passes


def test_enough_unmuted_windows_turn_the_guard_on():
    n = sl.MIN_SPEECH_WINDOWS
    length = sl.WINDOW + (n - 1) * sl.HOP
    levels = Levels({"a": [(0.0, 10.0, -22.0), (10.0, 10.0 + length, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 10.0 + length)], levels)
    assert found.unmuted_frames == n
    assert found.threshold is None


def test_the_speech_level_is_the_upper_quarter_because_kept_clips_hold_pauses():
    """Unmuted clips are speech with gaps: the lower quarter would be a gap, not speech."""
    # Kept for 10 s: 6 s of pause at -60, then 4 s of speech at -20.
    levels = Levels({"a": [(0.0, 10.0, NOISE), (10.0, 16.0, -60.0), (16.0, 20.0, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)], levels)
    assert found.speech_level == pytest.approx(SPEECH)


def test_adjacent_muted_clips_are_one_block_like_in_the_word_based_learning():
    levels = Levels({"a": [(0.0, 4.0, NOISE), (5.0, 15.0, SPEECH)]})
    two = [Clip("a", 0.0, 2.0, True), Clip("a", 2.0 + sl.BLOCK_GAP / 2, 4.0, True),
           Clip("a", 5.0, 15.0)]
    apart = [Clip("a", 0.0, 2.0, True), Clip("a", 2.5, 4.0, True), Clip("a", 5.0, 15.0)]
    merged = calibrate_clips(two, levels)
    separate = calibrate_clips(apart, levels)
    one_block = len(list(sl._windows(0.0, 4.0)))
    assert merged.frames == one_block
    assert separate.frames != one_block


def test_clips_of_different_files_are_never_merged():
    levels = Levels({"a": [(0.0, 2.0, NOISE)], "b": [(2.0, 4.0, NOISE)], "c": [(0.0, 10.0, SPEECH)]})
    clips = [Clip("a", 0.0, 2.0, True), Clip("b", 2.0, 4.0, True), Clip("c", 0.0, 10.0)]
    found = calibrate_clips(clips, levels)
    assert found.frames == 2 * len(list(sl._windows(0.0, 2.0)))


def test_windows_with_no_audio_are_skipped_not_counted():
    levels = Levels({"a": [(0.0, 5.0, NOISE), (10.0, 20.0, SPEECH)]})  # 5-10 s has no audio
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)], levels)
    # A window counts when its middle is on audio (the same rule as the word-based learning).
    assert found.frames == sum(1 for a, b in sl._windows(0.0, 10.0) if (a + b) / 2 < 5.0)


def test_digital_silence_is_clamped_to_the_floor_not_minus_infinity():
    levels = Levels({"a": [(0.0, 10.0, float("-inf")), (10.0, 20.0, SPEECH)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)], levels)
    assert found.threshold == pytest.approx(sl.FLOOR_DB + sl.MARGIN_DB)


def test_the_kept_share_says_how_much_of_what_was_left_would_stay():
    # Kept clip: half at speech level, half silent (a pause inside it).
    levels = Levels({"a": [(0.0, 10.0, NOISE), (10.0, 15.0, SPEECH), (15.0, 20.0, NOISE)]})
    found = calibrate_clips([Clip("a", 0.0, 10.0, True), Clip("a", 10.0, 20.0)], levels)
    assert found.kept_share == pytest.approx(0.5, abs=0.05)


def test_the_kept_share_is_none_without_unmuted_examples():
    levels = Levels({"a": [(0.0, 10.0, NOISE)]})
    assert calibrate_clips([Clip("a", 0.0, 10.0, True)], levels).kept_share is None


def test_the_existing_calibration_is_unchanged_by_the_new_fields():
    found = Calibration()
    assert found.unmuted_frames == 0 and found.kept_share is None


def test_the_names_are_exported():
    assert {"Clip", "calibrate_clips", "MIN_SPEECH_WINDOWS"} <= set(sl.__all__)
