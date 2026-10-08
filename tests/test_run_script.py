"""``run.sh``: Homebrewin jälkeen yksi komento — riippuvuudet, kirjautuminen
ja sovellus. Testit ajavat skriptin oikealla ``sh``:lla, ``brew`` ja ``uvx``
korvattuina kirjaavilla tyngillä."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run.sh"


RECORDER = '#!/bin/sh\necho "$(basename "$0") $*" >> "$CALLS"\n'


def _recorder(bin_dir: Path, name: str) -> None:
    path = bin_dir / name
    path.write_text(RECORDER, encoding="utf-8")
    path.chmod(0o755)


def _run(tmp_path, *args, have=("brew",), token=False):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls.txt"
    calls.write_text("", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    if token:
        (home / ".config" / "colab-cli").mkdir(parents=True)
        (home / ".config" / "colab-cli" / "token.json").write_text("{}")
    for name in have:
        _recorder(bin_dir, name)
    if "brew" in have:
        # ``brew install x`` kirjataan ja luo x:n (uv tuo myös uvx:n).
        (bin_dir / "brew").write_text(
            RECORDER
            + 'shift\nfor p in "$@"; do\n'
            + f'  cp "{bin_dir}/.recorder" "{bin_dir}/$p"\n'
            + f'  [ "$p" = uv ] && cp "{bin_dir}/.recorder" "{bin_dir}/uvx"\n'
            + "done\nexit 0\n",
            encoding="utf-8",
        )
        _recorder(bin_dir, ".recorder")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(home),
        "CALLS": str(calls),
        "PODCAST_TTY": os.devnull,
    }
    done = subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True,
                          text=True, timeout=30)
    return done, calls.read_text(encoding="utf-8").splitlines()


def test_a_fresh_mac_gets_uv_ffmpeg_login_and_the_app(tmp_path):
    done, calls = _run(tmp_path)
    assert done.returncode == 0, done.stderr
    assert "brew install uv ffmpeg" in calls
    runs = [c for c in calls if c.startswith("uvx ")]
    assert len(runs) == 2
    assert runs[0].endswith("colab-transcribe --login")
    assert "#subdirectory=colab-transcribe" in runs[0]
    assert runs[1].endswith("colab-transcribe")


def test_a_signed_in_mac_goes_straight_to_the_app(tmp_path):
    done, calls = _run(tmp_path, have=("brew", "uv", "uvx", "ffmpeg"), token=True)
    assert done.returncode == 0, done.stderr
    assert not any(c.startswith("brew install") for c in calls)
    runs = [c for c in calls if c.startswith("uvx ")]
    assert len(runs) == 1 and runs[0].endswith("colab-transcribe")


def test_other_apps_and_their_arguments(tmp_path):
    done, calls = _run(tmp_path, "automixer", "jakso.nhsx", "--verbose",
                       have=("brew", "uv", "uvx", "ffmpeg"))
    assert done.returncode == 0, done.stderr
    (run,) = [c for c in calls if c.startswith("uvx ")]
    assert "#subdirectory=apps/automixer" in run
    assert run.endswith("automixer jakso.nhsx --verbose")


def test_podcast_magic_gets_its_whisper(tmp_path):
    done, calls = _run(tmp_path, "podcast-magic", have=("brew", "uv", "uvx", "ffmpeg"))
    assert done.returncode == 0, done.stderr
    (run,) = [c for c in calls if c.startswith("uvx ")]
    assert "podcast-magic[" in run and "#subdirectory=apps/podcast-magic" in run


def test_an_unknown_app_lists_the_known_ones(tmp_path):
    done, _ = _run(tmp_path, "nope", have=("brew", "uv", "uvx", "ffmpeg"))
    assert done.returncode != 0
    assert "colab-transcribe" in done.stderr and "autoraffkat" in done.stderr


def test_without_homebrew_it_says_where_to_get_it(tmp_path):
    done, calls = _run(tmp_path, have=())
    assert done.returncode != 0
    assert "brew.sh" in done.stderr
    assert calls == []


@pytest.mark.parametrize("shell", ["sh", "bash", "zsh"])
def test_the_script_parses_in_common_shells(shell):
    assert subprocess.run([shell, "-n", str(SCRIPT)], timeout=10).returncode == 0


def test_without_a_terminal_it_falls_back_to_stdin(tmp_path):
    """``/dev/tty`` voi olla luettava mutta avautumaton (ei ohjaavaa
    päätettä, esim. CI tai etäistunto): silloin syöte tulee stdinistä."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("brew", "uv", "uvx", "ffmpeg"):
        _recorder(bin_dir, name)
    calls = tmp_path / "calls.txt"
    calls.write_text("")
    home = tmp_path / "home"
    (home / ".config" / "colab-cli").mkdir(parents=True)
    (home / ".config" / "colab-cli" / "token.json").write_text("{}")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home), "CALLS": str(calls)}
    # Uusi istunto: ei ohjaavaa päätettä, joten oletus /dev/tty ei avaudu
    # vaikka ``[ -r /dev/tty ]`` on tosi.
    done = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True,
                          timeout=30, stdin=subprocess.DEVNULL, start_new_session=True)
    assert done.returncode == 0, done.stderr
    assert calls.read_text().strip().endswith("colab-transcribe")
