"""Komentorivi: täysin skriptattava ajo ilman käyttöliittymää.

`--dry-run` tulostaa ajettavat komennot eikä aja mitään — se on sekä
dokumentaatio että testikiinnitys sille mitä oikea ajo tekisi.
"""

from __future__ import annotations

import pytest

from colabtranscribe import __main__ as cli


def test_version_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip()


def test_missing_input_dir_is_a_clean_error(capsys):
    assert cli.main(["--input", "/eiole/olemassa", "--output", "x"]) == 1
    err = capsys.readouterr().err
    assert "/eiole/olemassa" in err


def test_dry_run_prints_commands_and_runs_nothing(tmp_path, capsys):
    (tmp_path / "puhe.wav").write_bytes(b"")
    code = cli.main(
        [
            "--input", str(tmp_path),
            "--output", str(tmp_path / "out"),
            "--preset", "intra-mic",
            "--dry-run",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "colab new" in out
    assert "colab upload" in out and "puhe.wav" in out
    assert "python3 /content/pipeline.py" in out
    assert "--preset intra-mic" in out
    assert "colab stop" in out


def test_real_run_streams_output_and_reports_results(tmp_path, capsys, monkeypatch):
    (tmp_path / "puhe.wav").write_bytes(b"")
    calls = []

    def fake_run(commands, log, timeout=None):
        calls.append(commands)
        log("Litteroitu .nhsx luotu: /content/output/j litteroitu.nhsx")
        return 0

    monkeypatch.setattr(cli.driver, "run", fake_run)
    code = cli.main(["--input", str(tmp_path), "--output", str(tmp_path / "out")])
    assert code == 0
    assert len(calls) == 1
    assert "litteroitu.nhsx" in capsys.readouterr().out


def test_failing_remote_run_returns_its_code(tmp_path, monkeypatch):
    (tmp_path / "puhe.wav").write_bytes(b"")

    def fake_run(commands, log, timeout=None):
        return 3

    monkeypatch.setattr(cli.driver, "run", fake_run)
    assert cli.main(["--input", str(tmp_path), "--output", str(tmp_path / "out")]) == 3
