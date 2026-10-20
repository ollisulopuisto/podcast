"""Puhujien keskinäinen tasaus on rajattu: ``--balance-speakers-max-db``.

Ketju nostaa jokaisen puhekaistan samaan viitetasoon (``SPEECH_REFERENCE_LUFS``)
ennen dynamiikkaa, eli puhujat tasataan täysin. Kuulas pyysi rajan
(``docs/PODCAST-MAGIC.md`` kuulaksen repossa, «Speaker balance»): käsin säädetty
taso on likimääräinen, joten automaatio saa liikuttaa puhujaa enintään N dB
(0 = käyttäjän tasot jäävät, suuri = täysi tasaus). Ilman lippua tulos on ennallaan.
"""

from __future__ import annotations

import math
import pathlib

import numpy as np
import pyloudnorm as pyln
import pytest
import soundfile as sf
from test_stems_folder import RATE, _folder

from automixer import cli_mix, stems_mix

# --- Laskenta: kuka liikkuu kuinka paljon -----------------------------------


def test_the_group_reference_is_the_median_and_corrections_move_towards_it():
    levels = {"A": -20.0, "B": -36.0}  # mediaani −28
    applied, after = stems_mix.balance_corrections(levels, max_db=100.0)
    assert applied == {"A": pytest.approx(-8.0), "B": pytest.approx(8.0)}
    # Täysi tasaus: ketjun jälkeen puhujat ovat jo samalla tasolla, ei jälkivahvistusta.
    assert after == {"A": pytest.approx(0.0), "B": pytest.approx(0.0)}


def test_a_limit_of_zero_leaves_the_users_relative_levels():
    applied, after = stems_mix.balance_corrections({"A": -20.0, "B": -36.0}, max_db=0.0)
    assert applied == {"A": 0.0, "B": 0.0}
    # Ketju tasasi molemmat; jälkivahvistus palauttaa 16 dB:n eron mediaanin ympärille.
    assert after == {"A": pytest.approx(8.0), "B": pytest.approx(-8.0)}


def test_a_limit_in_between_moves_each_speaker_at_most_that_far():
    applied, after = stems_mix.balance_corrections({"A": -20.0, "B": -36.0}, max_db=3.0)
    assert applied == {"A": pytest.approx(-3.0), "B": pytest.approx(3.0)}
    assert after == {"A": pytest.approx(5.0), "B": pytest.approx(-5.0)}
    # Ero 16 → 10 dB: kuusi desibeliä tasattu, loput jätetty.
    assert (-20.0 + applied["A"]) - (-36.0 + applied["B"]) == pytest.approx(10.0)


def test_a_speaker_within_the_limit_is_balanced_fully_the_other_is_capped():
    levels = {"A": -28.0, "B": -29.0, "C": -40.0}  # mediaani −29
    applied, _ = stems_mix.balance_corrections(levels, max_db=4.0)
    assert applied["A"] == pytest.approx(-1.0)
    assert applied["B"] == pytest.approx(0.0)
    assert applied["C"] == pytest.approx(4.0)  # tarvittaisiin 11


def test_speakers_already_within_the_tolerance_are_left_as_they_are():
    levels = {"A": -20.0, "B": -22.5}
    applied, after = stems_mix.balance_corrections(levels, max_db=100.0, tolerance_db=3.0)
    assert applied == {"A": 0.0, "B": 0.0}
    assert after["A"] == pytest.approx(1.25) and after["B"] == pytest.approx(-1.25)


def test_a_spread_just_above_the_tolerance_is_balanced_normally():
    levels = {"A": -20.0, "B": -23.5}
    applied, _ = stems_mix.balance_corrections(levels, max_db=100.0, tolerance_db=3.0)
    assert applied["A"] != 0.0 and applied["B"] != 0.0


def test_one_speaker_has_nothing_to_balance_against():
    applied, after = stems_mix.balance_corrections({"A": -30.0}, max_db=3.0)
    assert applied == {"A": 0.0} and after == {"A": 0.0}


@pytest.mark.parametrize("bad", [-0.1, 60.1, math.nan, math.inf, -math.inf])
def test_the_limit_must_be_between_zero_and_sixty(bad):
    with pytest.raises(ValueError, match="balance-speakers-max-db"):
        stems_mix.check_balance_max(bad)


@pytest.mark.parametrize("bad", [-0.1, 30.1, math.nan, math.inf])
def test_the_tolerance_must_be_between_zero_and_thirty(bad):
    with pytest.raises(ValueError, match="balance-speakers-tolerance-db"):
        stems_mix.check_balance_tolerance(bad)


@pytest.mark.parametrize("ok", [0, 0.0, 12.5, 55.0, 60.0])
def test_the_limit_accepts_zero_up_to_sixty_inclusive(ok):
    assert stems_mix.check_balance_max(ok) == float(ok)


@pytest.mark.parametrize("ok", [0, 0.0, 1.5, 25.0, 30.0])
def test_the_tolerance_accepts_zero_up_to_thirty_inclusive(ok):
    assert stems_mix.check_balance_tolerance(ok) == float(ok)


def test_a_spread_exactly_at_the_tolerance_is_left_alone():
    applied, _ = stems_mix.balance_corrections(
        {"A": -20.0, "B": -23.0}, max_db=100.0, tolerance_db=3.0
    )
    assert applied == {"A": 0.0, "B": 0.0}


# --- Tiedoston skaalaus -----------------------------------------------------


def test_a_file_is_scaled_in_place_in_32_bit_float_without_leftovers(tmp_path):
    path = tmp_path / "puhuja.wav"
    x = (0.1 * np.sin(np.arange(RATE) / 20.0)).astype(np.float32)
    sf.write(path, x, RATE, subtype="PCM_24")
    stems_mix.scale_file(str(path), 6.0)
    y, rate = sf.read(path, dtype="float32")
    assert rate == RATE and len(y) == len(x)
    assert sf.info(path).subtype == "FLOAT"
    ratio = float(np.max(np.abs(y)) / np.max(np.abs(x)))
    assert 20 * math.log10(ratio) == pytest.approx(6.0, abs=0.01)
    assert [p.name for p in tmp_path.iterdir()] == ["puhuja.wav"]


def test_a_file_scaled_by_zero_db_is_not_rewritten(tmp_path):
    path = tmp_path / "puhuja.wav"
    sf.write(path, np.zeros(1000, dtype=np.float32), RATE, subtype="PCM_24")
    before = path.stat().st_mtime_ns
    stems_mix.scale_file(str(path), 0.0)
    assert path.stat().st_mtime_ns == before and sf.info(path).subtype == "PCM_24"


# --- Komentorivi ----------------------------------------------------------------


def _cli(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["automixer", *argv])
    cli_mix.main()


def test_the_flags_are_parsed_and_default_to_none_and_zero(monkeypatch):
    seen = []
    monkeypatch.setattr(cli_mix, "_mix_session", lambda args, path: seen.append(args))
    _cli(monkeypatch, "jakso.nhsx")
    _cli(
        monkeypatch,
        "jakso.nhsx",
        "--balance-speakers-max-db",
        "3",
        "--balance-speakers-tolerance-db",
        "1.5",
    )
    assert seen[0].balance_speakers_max_db is None
    assert seen[0].balance_speakers_tolerance_db == 0.0
    assert seen[1].balance_speakers_max_db == 3.0
    assert seen[1].balance_speakers_tolerance_db == 1.5


@pytest.mark.parametrize(
    "flag, value",
    [
        ("--balance-speakers-max-db", "-1"),
        ("--balance-speakers-max-db", "nan"),
        ("--balance-speakers-max-db", "61"),
        ("--balance-speakers-tolerance-db", "-1"),
        ("--balance-speakers-tolerance-db", "31"),
    ],
)
def test_a_bad_flag_value_is_refused_before_any_work(monkeypatch, capsys, flag, value):
    monkeypatch.setattr(cli_mix, "_mix_session", lambda *a: pytest.fail("ran"))
    with pytest.raises(SystemExit) as stop:
        _cli(monkeypatch, "jakso.nhsx", flag, value)
    assert stop.value.code == 2
    assert flag in capsys.readouterr().err


def test_the_flags_appear_in_help_because_kuulas_looks_for_them_there(
    monkeypatch, capsys
):
    with pytest.raises(SystemExit):
        _cli(monkeypatch, "--help")
    out = capsys.readouterr().out
    assert "--balance-speakers-max-db" in out
    assert "--balance-speakers-tolerance-db" in out


def test_the_values_reach_the_mix(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(cli_mix, "_exit_on_sigterm", lambda: None)
    monkeypatch.setattr(stems_mix, "mix", lambda path, output, **kw: seen.update(kw))
    _cli(
        monkeypatch,
        str(tmp_path / "jakso.nhsx"),
        "--balance-speakers-max-db",
        "2",
        "--balance-speakers-tolerance-db",
        "1",
    )
    assert seen["balance_speakers_max_db"] == 2.0
    assert seen["balance_speakers_tolerance_db"] == 1.0
    seen.clear()
    _cli(monkeypatch, str(tmp_path / "jakso.nhsx"))
    assert seen["balance_speakers_max_db"] is None
    assert seen["balance_speakers_tolerance_db"] == 0.0


# --- Päästä päähän: oikea miksaus -------------------------------------------------


def _mix_two_speakers(tmp_path, monkeypatch, capsys, **options):
    """P1 on 16,2 dB hiljaisempi kuin P0. Palauttaa käsiteltyjen stemien erotuksen (dB)."""
    folder = _folder(tmp_path, bed=False)
    quiet = next(folder.glob("*P1.wav"))
    x, rate = sf.read(quiet, dtype="float32")
    sf.write(quiet, (x * 0.15).astype(np.float32), rate, subtype="PCM_24")

    kept = []
    real = stems_mix.shutil.rmtree
    monkeypatch.setattr(
        stems_mix.shutil,
        "rmtree",
        lambda p, *a, **k: kept.append(p) if "automixer-" in str(p) else real(p, *a, **k),
    )
    stems_mix.mix_folder(
        str(folder), str(tmp_path / "out.wav"), target_lufs=-16.0, **options
    )
    meter = pyln.Meter(RATE)

    def level(path):
        audio, _ = sf.read(path, always_2d=True)
        return meter.integrated_loudness(audio.mean(axis=1))

    files = sorted(
        p for p in pathlib.Path(kept[0]).iterdir() if p.name.endswith("[mix].wav")
    )
    loud, soft = (level(p) for p in files)
    return loud - soft, capsys.readouterr().out


def test_without_the_option_the_speakers_come_out_equally_loud(
    tmp_path, monkeypatch, capsys
):
    gap, printed = _mix_two_speakers(tmp_path, monkeypatch, capsys)
    assert abs(gap) < 1.0, gap
    assert "balance:" in printed


def test_a_limit_of_zero_keeps_the_gap_the_user_made(tmp_path, monkeypatch, capsys):
    gap, printed = _mix_two_speakers(
        tmp_path, monkeypatch, capsys, balance_speakers_max_db=0.0
    )
    assert gap == pytest.approx(16.2, abs=1.5), gap
    line = next(x for x in printed.splitlines() if "balance:" in x)
    assert "P0" in line and "P1" in line and "+0.0 dB" in line


def test_a_limit_of_four_removes_eight_of_the_sixteen_decibels(
    tmp_path, monkeypatch, capsys
):
    gap, printed = _mix_two_speakers(
        tmp_path, monkeypatch, capsys, balance_speakers_max_db=4.0
    )
    assert gap == pytest.approx(16.2 - 8.0, abs=1.5), gap
    line = next(x for x in printed.splitlines() if "balance:" in x)
    assert "-4.0 dB" in line and "+4.0 dB" in line


def test_a_bad_limit_stops_before_any_work(tmp_path):
    folder = _folder(tmp_path, bed=False)
    with pytest.raises(ValueError, match="balance-speakers-max-db"):
        stems_mix.mix_folder(
            str(folder), str(tmp_path / "out.wav"), balance_speakers_max_db=-3.0
        )
    assert not (tmp_path / "out.wav").exists()
