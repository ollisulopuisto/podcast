"""Kansikuvien henkilökentän Enter kunnioittaa IME-yhdistelmäsyöttöä."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
def test_add_person_enter_respects_ime_composition():
    here = Path(__file__).parent
    app = here.parent / "src/autoraffkat/server/static/app.js"
    done = subprocess.run(
        ["node", str(here / "ui_ime_enter.js"), str(app)],
        capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    assert "IME" in done.stdout
