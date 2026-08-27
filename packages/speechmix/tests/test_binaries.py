"""ffmpegin ja ffprobin paikannus.

Kaksi sovellusta kolmesta niputtaa ffmpegin, ja molemmat etsivät sen
samasta kolmesta paikasta — samassa järjestyksessä, samalla koodilla.
Haku on siis kirjaston kokonaan, ei sovelluksen osittain.
"""

import os
import sys

import pytest
from speechmix import binaries


def _fake_tool(directory, name="ffmpeg"):
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / (f"{name}.exe" if os.name == "nt" else name)
    tool.touch()
    tool.chmod(0o755)
    return tool


def test_meipass_wins(monkeypatch, tmp_path):
    """Purkuhakemiston binääri menee järjestelmän edelle."""
    meipass = tmp_path / "meipass"
    tool = _fake_tool(meipass / "bin")
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert binaries.get_binary_path("ffmpeg") == str(tool)


def test_next_to_the_executable(monkeypatch, tmp_path):
    """Ilman _MEIPASSia katsotaan suoritettavan viereen ja sen bin-hakemistoon."""
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "autoraffkat").touch()
    tool = _fake_tool(app_dir)

    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "autoraffkat"))

    assert binaries.get_binary_path("ffmpeg") == str(tool)


def test_falls_back_to_path(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(binaries.shutil, "which", lambda _name: "/usr/local/bin/ffmpeg")

    assert binaries.get_binary_path("ffmpeg") == "/usr/local/bin/ffmpeg"


def test_missing_is_a_file_not_found(monkeypatch):
    """``MissingBinary`` on ``FileNotFoundError``.

    Sovellusten ottokohdat kirjoitettiin ennen tätä pakettia ja nappaavat
    ``FileNotFoundError``in. Perintä pitää ne toimivina; ilman sitä
    puuttuva ffmpeg lentäisi läpi käsittelijän, joka on kirjoitettu juuri
    sitä varten.
    """
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(binaries.shutil, "which", lambda _name: None)

    assert issubclass(binaries.MissingBinary, FileNotFoundError)
    with pytest.raises(FileNotFoundError, match="ffmpeg"):
        binaries.get_binary_path("ffmpeg")


def test_require_ffmpeg_checks_both(monkeypatch):
    """Molemmat, koska ne tulevat eri niputuksista.

    Purku tarvitsee ffmpegin ja keston lukeminen ffprobin. Puuttuva
    jälkimmäinen huomattaisiin muuten vasta kesken ajon.
    """
    asked = []

    def which(name):
        asked.append(name)
        return f"/usr/local/bin/{name}"

    monkeypatch.setattr(binaries.shutil, "which", which)
    binaries.require_ffmpeg()
    assert asked == ["ffmpeg", "ffprobe"]
