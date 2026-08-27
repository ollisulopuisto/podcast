"""Palvelin ja moduulien liittäminen."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from podcastmagic.modules import MODULES
from podcastmagic.server.app import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(start_dir=str(tmp_path)))


def test_state_lists_every_module(client):
    state = client.get("/api/state").json()
    assert [m["key"] for m in state["modules"]] == [m.key for m in MODULES]
    for module in state["modules"]:
        assert module["title"]["fi"] and module["title"]["en"]


def test_every_module_router_is_mounted(client):
    for module in MODULES:
        assert client.get(f"/api/{module.key}/info").status_code == 200


def test_every_module_script_exists():
    """Rekisterissä luvattu skripti pitää olla olemassa.

    Puuttuva tiedosto ei kaada mitään: välilehti ilmestyy ja paneeli jää
    tyhjäksi. Sitä ei huomaa ennen kuin sitä klikkaa.
    """
    from podcastmagic.paths import get_resource_path

    static = get_resource_path("server/static")
    for module in MODULES:
        assert (static / module.script).is_file(), module.script


def test_index_and_static_are_served(client):
    assert client.get("/").status_code == 200
    for name in ("app.js", "i18n.js", "style.css"):
        assert client.get(f"/static/{name}").status_code == 200


def test_browse_lists_only_sessions(client, session_file, tmp_path):
    (tmp_path / "ääni.wav").write_bytes(b"")
    listing = client.get("/api/browse", params={"dir": str(tmp_path)}).json()
    assert [f["name"] for f in listing["files"]] == ["jakso.nhsx"]


def test_running_without_a_session_is_a_stated_error(client):
    for module in MODULES:
        response = client.post(f"/api/{module.key}/run", json={})
        assert response.status_code == 400
        assert response.json()["detail"]


def test_silence_refuses_a_session_without_a_transcription(client, tmp_path):
    """«Asetus päällä ja tulos tyhjä» on virhe, ei hiljaisuus.

    Ilman litterointia vaimennus vaientaisi kaiken. Se on kelvollinen
    tiedosto ja täysin väärä tulos, ja sen huomaa vasta Hindenburgissa.
    """
    from podcastmagic.jobs import Job, Progress
    from podcastmagic.silence import run as runner
    from podcastmagic.silence.presets import Settings

    empty = tmp_path / "tyhja.nhsx"
    empty.write_text(
        '<?xml version="1.0"?><Session><AudioPool><File Id="1" Name="a.wav"/>'
        "</AudioPool><Tracks><Track Name=\"A\">"
        '<Region Ref="1" Start="0" Length="5" Offset="0"/></Track></Tracks></Session>',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="litterointi"):
        runner.run(str(empty), Settings(), Progress(Job(id=0, module="t", label="t")))


def test_a_bad_session_file_is_reported_not_raised(client, tmp_path):
    broken = tmp_path / "rikki.nhsx"
    broken.write_text("<Session>", encoding="utf-8")
    response = client.post("/api/silence/preview", json={"session": str(broken)})
    assert response.status_code == 400
    assert "XML" in response.json()["detail"]


def test_one_job_at_a_time(client, session_file, monkeypatch):
    import threading

    from podcastmagic.jobs import RUNNER

    gate = threading.Event()
    RUNNER.start("testi", "testi", lambda progress: gate.wait(5) and {})
    try:
        response = client.post(
            "/api/silence/run", json={"session": str(session_file), "settings": {}}
        )
        assert response.status_code == 409
    finally:
        gate.set()
