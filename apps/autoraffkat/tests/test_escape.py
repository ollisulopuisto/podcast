"""Leikkauslistan puhujanimet eivät saa rikkoa innerHTML-merkkausta."""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="node missing")
def test_cut_list_escapes_speaker_labels():
    here = Path(__file__).parent
    app = here.parent / "src/autoraffkat/server/static/app.js"
    done = subprocess.run(
        ["node", str(here / "ui_escape.js"), str(app)],
        capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    assert "inert text" in done.stdout
