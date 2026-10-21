"""``--keep-music-level``: the music keeps the level the owner gave it.

Without it the beds are fitted to the processed speech (``--bed-under-speech-db``).
With it each music stem gets the same gain change as the speech did:
``delta = processed speech level - raw speech level``, so a music-to-speech balance
made by ear survives. Spec: kuulas ``docs/PODCAST-MAGIC.md``, "Owner confirmed requests".
"""

from __future__ import annotations

import contextlib
import io

import numpy as np
import pytest
import soundfile as sf
from test_events import _events
from test_stems_folder import _folder

from automixer import cli_mix, stems_mix


def test_the_change_is_what_the_speech_was_moved_by():
    assert stems_mix.keep_change(-23.0, -35.5) == 12.5
    assert stems_mix.keep_change(-23.0, -20.0) == -3.0


def test_the_change_is_rounded_to_hundredths_like_the_other_bed_rule():
    assert stems_mix.keep_change(-23.0, -30.123) == 7.12


def _run(tmp_path, speech_gain=1.0, **options):
    folder = _folder(tmp_path)
    if speech_gain != 1.0:
        for path in folder.glob("*P?.wav"):
            audio, rate = sf.read(path, dtype="float32")
            sf.write(path, (audio * speech_gain).astype(np.float32), rate, subtype="PCM_24")
    text = io.StringIO()
    with contextlib.redirect_stdout(text):
        stems_mix.mix_folder(
            str(folder), str(tmp_path / "out.wav"), target_lufs=-16.0, events=True, **options
        )
    return text.getvalue()


def _bed(out):
    (event,) = [e for e in _events(out) if e["event"] == "bed"]
    return event


@pytest.fixture(scope="module")
def kept(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("kept"), keep_music_level=True)


@pytest.fixture(scope="module")
def kept_from_quieter_speech(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("quiet"), speech_gain=0.5, keep_music_level=True)


def test_the_beds_move_by_what_the_speech_moved_by(kept):
    event = _bed(kept)
    assert event["mode"] == "keep"
    assert event["change_db"] == round(event["speech_lufs"] - event["speech_raw_lufs"], 2)


def test_the_raw_level_is_measured_on_the_stems_as_they_came(kept, kept_from_quieter_speech):
    """Speech stems at half the amplitude are 6.02 dB lower before processing."""
    loud = _bed(kept)["speech_raw_lufs"]
    quiet = _bed(kept_from_quieter_speech)["speech_raw_lufs"]
    assert loud - quiet == pytest.approx(6.02, abs=0.3)


def test_quieter_speech_is_lifted_more_and_the_music_with_it(kept, kept_from_quieter_speech):
    assert _bed(kept_from_quieter_speech)["change_db"] - _bed(kept)["change_db"] == pytest.approx(
        6.02, abs=0.3
    )


def test_the_beds_line_says_what_was_done_and_keeps_its_prefix(kept):
    line = next(x for x in kept.splitlines() if x.startswith("[automixer] beds:"))
    assert "kept your levels" in line
    event = _bed(kept)
    assert f"{event['change_db']:+.1f} dB" in line


def test_without_the_flag_the_fitting_rule_runs_as_before(tmp_path):
    event = _bed(_run(tmp_path))
    assert event.get("mode", "fit") == "fit"
    assert "speech_raw_lufs" not in event and event["offset_db"] == 1.0


def test_the_two_ways_of_setting_the_music_level_exclude_each_other(tmp_path):
    with pytest.raises(ValueError, match="bed-under-speech-db"):
        stems_mix.mix_folder(
            str(_folder(tmp_path)),
            str(tmp_path / "o.wav"),
            keep_music_level=True,
            bed_under_speech_db=-9.0,
        )


def _cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["automixer", *argv])
    cli_mix.main()


def test_the_flag_is_in_help_because_kuulas_looks_for_it_there(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        _cli(monkeypatch, "--help")
    assert "--keep-music-level" in capsys.readouterr().out


def test_the_flag_reaches_the_mix_and_defaults_to_off(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(cli_mix, "_exit_on_sigterm", lambda: None)
    monkeypatch.setattr(stems_mix, "mix", lambda path, output, **kw: seen.append(kw))
    _cli(monkeypatch, str(tmp_path / "jakso.nhsx"))
    _cli(monkeypatch, str(tmp_path / "jakso.nhsx"), "--keep-music-level")
    assert [kw["keep_music_level"] for kw in seen] == [False, True]


def test_both_flags_together_are_refused_before_any_work(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli_mix, "_mix_session", lambda *a: pytest.fail("ran"))
    with pytest.raises(SystemExit):
        _cli(
            monkeypatch,
            str(tmp_path / "jakso.nhsx"),
            "--keep-music-level",
            "--bed-under-speech-db",
            "-9",
        )
    assert "--keep-music-level" in capsys.readouterr().err
