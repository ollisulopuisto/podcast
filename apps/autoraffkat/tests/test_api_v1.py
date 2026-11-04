"""Versioned v1 REST API tests for autoraffkat."""

import time

from fastapi.testclient import TestClient

from autoraffkat.server.app import AppState, create_app


def _wait_ready(state: AppState, timeout_s: float = 10.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if state.progress.get("ready"):
            return
        time.sleep(0.05)


def test_api_v1_status_unloaded():
    state = AppState(xml_path="")
    client = TestClient(create_app(state))
    res = client.get("/api/v1/status")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] == "autoraffkat"
    assert data["version"] == "1.0"
    assert data["loaded"] is False


def test_api_v1_project_inspect_unloaded():
    state = AppState(xml_path="")
    client = TestClient(create_app(state))
    res = client.get("/api/v1/project/inspect")
    assert res.status_code == 409
    err = res.json()
    assert err["error"]["code"] == "PROJECT_NOT_LOADED"


def test_api_v1_workflow_loaded(scratch_xml):
    xml_path = scratch_xml("multicam.fcpxml")
    state = AppState(xml_path=str(xml_path))
    state.load()
    _wait_ready(state)

    client = TestClient(create_app(state))

    # 1. Status
    res_status = client.get("/api/v1/status")
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert data_status["loaded"] is True
    assert data_status["analysis_ready"] is True
    assert str(xml_path) in data_status["xml_path"]

    # 2. Inspect
    res_inspect = client.get("/api/v1/project/inspect")
    assert res_inspect.status_code == 200
    data_inspect = res_inspect.json()
    assert data_inspect["name"] in ("multicam", "Monikamera")
    assert len(data_inspect["tracks"]) > 0
    assert "settings" in data_inspect

    # 3. Settings update
    mic_tracks = [t for t in data_inspect["tracks"] if t["has_audio"] and not t["has_video"]]
    cam_tracks = [t for t in data_inspect["tracks"] if t["has_video"]]
    assert len(mic_tracks) >= 2
    assert len(cam_tracks) >= 2

    settings_payload = {
        "tracks": {
            mic_tracks[0]["key"]: {"role": "mic", "speaker": "Host"},
            mic_tracks[1]["key"]: {"role": "mic", "speaker": "Guest"},
            cam_tracks[0]["key"]: {"role": "shot", "covers": ["Host"], "context": False},
            cam_tracks[1]["key"]: {"role": "shot", "covers": ["Guest"], "context": True},
        },
        "globals": {
            "rhythm": "mellow",
            "min_shot": 4.5,
        },
        "audio": {
            "enabled": False,
        },
    }

    res_settings = client.post("/api/v1/project/settings", json=settings_payload)
    assert res_settings.status_code == 200
    data_settings = res_settings.json()
    assert data_settings["ok"] is True
    assert data_settings["cuts_count"] > 0
    assert data_settings["output_path"].endswith(".fcpxml")

    # 4. Cut computation
    res_cut = client.post("/api/v1/project/cut")
    assert res_cut.status_code == 200
    data_cut = res_cut.json()
    assert data_cut["ok"] is True
    assert len(data_cut["segments"]) > 0
    assert data_cut["segments"][0]["duration"] > 0

    # 5. Export
    res_export = client.post("/api/v1/project/export", json={"render": False})
    assert res_export.status_code == 200
    data_export = res_export.json()
    assert data_export["ok"] is True
    assert data_export["cuts"] > 0
    assert data_export["path"].endswith(".fcpxml")
