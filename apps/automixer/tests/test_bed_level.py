"""Musiikkipohjan taso puheeseen nähden on valittavissa: ``--bed-under-speech-db``.

Kuulas pyysi lippua (``docs/PODCAST-MAGIC.md``, «Music bed level»): oletus
``BED_UNDER_SPEECH_DB`` on +1,0, eli pohjan kovin hetki on puheen **yläpuolella**
(käyttäjän oma valinta 2026-10-09), ja se kuulosti jaksossa liian kovalta. Lippu
ei muuta oletusta: ilman sitä tulos on sama kuin ennen.
"""

from __future__ import annotations

import inspect
import math

import pytest

from automixer import cli_mix, stems_mix


def test_the_change_is_speech_plus_the_offset_minus_the_bed():
    """Puhe -20 LUFS, pohjan kovin hetki -10: oletus nostaa pohjan puheen +1:een."""
    assert stems_mix.bed_change(-20.0, -10.0, 1.0) == -9.0
    assert stems_mix.bed_change(-20.0, -10.0, -9.0) == -19.0
    assert stems_mix.bed_change(-20.0, -10.0, 0.0) == -10.0


def test_the_change_is_rounded_to_two_decimals_as_before():
    assert stems_mix.bed_change(-20.123, -10.0, 1.0) == round(-20.123 + 1.0 + 10.0, 2)


def test_without_the_option_the_default_is_still_plus_one():
    assert stems_mix.BED_UNDER_SPEECH_DB == 1.0
    default = inspect.signature(stems_mix.mix).parameters["bed_under_speech_db"].default
    assert default is None  # None = BED_UNDER_SPEECH_DB; sääntö on yhdessä paikassa


@pytest.mark.parametrize("value", [-30.0, -9, 0, 1.0, 6.0])
def test_offsets_inside_the_range_are_accepted_as_floats(value):
    got = stems_mix.check_bed_offset(value)
    assert got == float(value) and isinstance(got, float)


@pytest.mark.parametrize(
    "value", [-30.01, 6.01, 100.0, -100.0, math.nan, math.inf, -math.inf]
)
def test_offsets_outside_the_range_or_not_finite_are_refused(value):
    with pytest.raises(ValueError, match="-30"):
        stems_mix.check_bed_offset(value)


def _cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["automixer", *argv])
    cli_mix.main()


def test_the_flag_is_parsed_and_defaults_to_none(monkeypatch):
    seen = []
    monkeypatch.setattr(cli_mix, "_mix_session", lambda args, path: seen.append(args))
    _cli(monkeypatch, "jakso.nhsx")
    _cli(monkeypatch, "jakso.nhsx", "--bed-under-speech-db", "-9")
    assert seen[0].bed_under_speech_db is None
    assert seen[1].bed_under_speech_db == -9.0


@pytest.mark.parametrize("value", ["7", "-31", "nan", "inf", "kova"])
def test_a_bad_flag_value_is_refused_before_any_work(monkeypatch, capsys, value):
    monkeypatch.setattr(cli_mix, "_mix_session", lambda *a: pytest.fail("ran"))
    with pytest.raises(SystemExit) as stop:
        _cli(monkeypatch, "jakso.nhsx", "--bed-under-speech-db", value)
    assert stop.value.code == 2
    assert "bed-under-speech-db" in capsys.readouterr().err


def test_the_flag_appears_in_help_because_kuulas_looks_for_it_there(monkeypatch, capsys):
    with pytest.raises(SystemExit) as stop:
        _cli(monkeypatch, "--help")
    assert stop.value.code == 0
    assert "--bed-under-speech-db" in capsys.readouterr().out


def test_the_value_reaches_the_mix(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli_mix, "_exit_on_sigterm", lambda: None)
    monkeypatch.setattr(
        stems_mix, "mix", lambda path, output, **kwargs: seen.update(kwargs)
    )
    _cli(monkeypatch, str(tmp_path / "jakso.nhsx"), "--bed-under-speech-db", "-9")
    assert seen["bed_under_speech_db"] == -9.0
    seen.clear()
    _cli(monkeypatch, str(tmp_path / "jakso.nhsx"))
    assert seen["bed_under_speech_db"] is None
