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


def test_transcribe_info_says_whether_the_aligner_can_run(client, monkeypatch):
    """Käyttöliittymä näyttää puuttuvan kohdistimen ennen ajoa, ei vasta tunnin litteroinnin jälkeen."""
    from podcastmagic.transcribe import align

    monkeypatch.setattr(
        align,
        "availability",
        lambda: {"available": False, "reason": "puuttuu: torch", "install": "uv sync --extra align"},
    )
    info = client.get("/api/transcribe/info").json()
    assert info["aligner"] == {
        "available": False,
        "reason": "puuttuu: torch",
        "install": "uv sync --extra align",
    }
    assert info["options"]["align"] is False


def _run_job(written: str):
    """Ajaa työn joka kirjoitti ``written``in, ja odottaa sen loppuun."""
    import time

    from podcastmagic.jobs import RUNNER

    job = RUNNER.start("t", "nimi", lambda progress: {"written": written})
    deadline = time.time() + 5
    while job.running and time.time() < deadline:
        time.sleep(0.01)
    assert job.snapshot()["ok"]


def test_reveal_shows_only_what_a_job_wrote(client, tmp_path, monkeypatch):
    """Näyttäminen ei ole yleinen tiedostonavain: vain työn kirjoittama polku kelpaa.

    Käyttöliittymä näyttää aina ``job.result.written``in. Mikä tahansa muu
    olemassa oleva polku on pyyntö jota sovellus ei ole itse tehnyt.
    """
    import subprocess

    calls = []
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    stranger = tmp_path / "vieras.txt"
    stranger.write_text("x", encoding="utf-8")
    refused = client.post("/api/reveal", json={"path": str(stranger)})
    assert refused.status_code == 403
    assert refused.json()["detail"]
    assert calls == []

    mine = tmp_path / "jakso v2.nhsx"
    mine.write_text("x", encoding="utf-8")
    _run_job(str(mine))
    assert client.post("/api/reveal", json={"path": str(mine)}).json() == {"ok": True}
    assert len(calls) == 1


def test_reveal_of_a_written_file_that_is_gone_is_not_found(client, tmp_path):
    gone = tmp_path / "poissa.nhsx"
    _run_job(str(gone))
    assert client.post("/api/reveal", json={"path": str(gone)}).status_code == 404


def test_reveal_and_exists_take_a_nul_path_as_nothing(client):
    """NUL ei ole polku. Se ei saa kaataa palvelinta eikä päästä mitään läpi."""
    assert client.post("/api/reveal", json={"path": "a\0b"}).status_code == 404
    assert client.post("/api/reveal", json={"path": ""}).status_code == 404
    found = client.get("/api/exists", params={"path": "a\0b"}).json()
    assert found["file"] is False and found["dir"] is False


def test_browse_does_not_pass_the_oserror_text_to_the_page(client, tmp_path, monkeypatch):
    """Käyttöliittymä näyttää virheen sellaisenaan, joten teksti on sovelluksen oma."""
    from pathlib import Path

    def deny(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "iterdir", deny)
    listing = client.get("/api/browse", params={"dir": str(tmp_path)}).json()
    assert listing["error"]
    assert "Permission denied" not in listing["error"]
    assert str(tmp_path) not in listing["error"]


def test_browse_takes_a_nul_path_as_unreadable(client):
    listing = client.get("/api/browse", params={"dir": "a\0b"}).json()
    assert listing["dirs"] == [] and listing["files"] == []


def test_a_job_path_is_matched_exactly_not_normalised(tmp_path):
    """Pyynnön polkua ei kosketa tiedostojärjestelmään; vastaus on kirjattu merkkijono."""
    from podcastmagic.jobs import Runner

    real = tmp_path / "oikea"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    given = str(real / "jakso v2.nhsx")

    runner = Runner()
    runner._remember(given)
    runner._remember("a\0b")
    runner._remember("")
    assert runner.written_path(given) == given
    assert runner.written_path(str(alias / "jakso v2.nhsx")) == ""
    assert runner.written_path(str(real / "toinen.nhsx")) == ""
    assert runner.written_path("") == ""
    assert runner.written_path("a\0b") == ""
    assert runner._written == {given}
