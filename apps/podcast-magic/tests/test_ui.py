"""Käyttöliittymän savutesti.

`node --check` tarkistaa vain syntaksin. Viittaus kenttään jota ei ole
keskeyttää piirron hiljaa, ja ruudulle jää tyhjä paneeli — ei virhettä, ei
mitään. Tämä ajaa kuoren ja molemmat moduulit valeselaimessa oikealla
palvelimen tuottamalla tilalla, joten sellainen kaatuu tänne.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from podcastmagic.paths import get_resource_path
from podcastmagic.server.app import create_app

STATIC = get_resource_path("server/static")
SMOKE = Path(__file__).parent / "ui_smoke.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node puuttuu")


@needs_node
def test_interface_runs_without_errors(tmp_path, session_file):
    """Vastaukset tulevat oikealta palvelimelta, eivät käsin kirjoitettuina.

    Käsin kirjoitettu tila menee vanhaksi hiljaa: kenttä nimetään uudelleen
    palvelimella, testi jatkaa vanhalla nimellä ja käyttöliittymä on rikki
    testin ollessa vihreä.
    """
    client = TestClient(create_app(start_dir=str(session_file.parent)))
    answers = {
        "/api/state": client.get("/api/state").json(),
        "/api/job": {"running": False, "id": 0},
        "/api/job/cancel": {"cancelled": False},
        "/api/browse": client.get("/api/browse",
                                  params={"dir": str(session_file.parent)}).json(),
        "/api/exists": {"path": str(session_file), "file": True, "dir": False},
        "/api/reveal": {"ok": True},
        "/api/transcribe/info": client.get("/api/transcribe/info").json(),
        "/api/transcribe/plan": client.post(
            "/api/transcribe/plan", json={"session": str(session_file)}
        ).json(),
        "/api/transcribe/verify": client.post(
            "/api/transcribe/verify", json={"session": str(session_file)}
        ).json(),
        "/api/transcribe/run": {"id": 9, "module": "transcribe", "running": True,
                                "log": [], "result": {}, "elapsed": 0},
        "/api/silence/info": client.get("/api/silence/info").json(),
        "/api/silence/preview": client.post(
            "/api/silence/preview", json={"session": str(session_file)}
        ).json(),
        "/api/silence/run": {"id": 9, "module": "silence", "running": True,
                             "log": [], "result": {}, "elapsed": 0},
    }
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps(answers), encoding="utf-8")

    done = subprocess.run(
        ["node", str(SMOKE), str(STATIC), str(answers_file)],
        capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    assert "OK" in done.stdout


def test_every_translation_key_exists_in_both_languages():
    """Puuttuva käännös näkyy avaimena ruudulla, ei virheenä."""
    text = (STATIC / "i18n.js").read_text(encoding="utf-8")
    import re

    blocks = re.findall(r"\n  (fi|en): \{(.*?)\n  \},", text, re.S)
    keys = {name: set(re.findall(r"'([\w.]+)':", body)) for name, body in blocks}
    assert keys["fi"] == keys["en"], keys["fi"] ^ keys["en"]


def test_every_data_t_key_is_translated():
    """index.html:n `data-t` ilman käännöstä jättää ruudulle avaimen."""
    import re

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    strings = (STATIC / "i18n.js").read_text(encoding="utf-8")
    used = set(re.findall(r'data-t="([\w.]+)"', html))
    known = set(re.findall(r"'([\w.]+)':", strings))
    assert used <= known, used - known
