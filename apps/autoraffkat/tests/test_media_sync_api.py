"""Mediasynkan API pitää pitkän mittauksen taustatyönä ja näyttää tilan."""

from fastapi.testclient import TestClient

from autoraffkat import media_import
from autoraffkat.server import app as server_app
from autoraffkat.server.app import AppState, create_app


def _media(tmp_path, monkeypatch):
    camera = tmp_path / "camera.mp4"
    microphone = tmp_path / "Peter.wav"
    camera.touch()
    microphone.touch()
    metadata = {
        str(camera): {
            "duration": 18.0,
            "video": {"width": 1920, "height": 1080, "fps": 25.0},
            "audio": {"channels": 2, "rate": 48000},
        },
        str(microphone): {
            "duration": 17.0,
            "audio": {"channels": 1, "rate": 48000},
        },
    }
    monkeypatch.setattr(media_import.probe, "info", metadata.__getitem__)
    return camera, microphone


def test_media_inspect_returns_sync_reference_candidates(tmp_path, monkeypatch):
    camera, microphone = _media(tmp_path, monkeypatch)
    client = TestClient(create_app(AppState(xml_path="")))

    response = client.post("/api/media/inspect", json={"paths": [str(camera), str(microphone)]})

    assert response.status_code == 200
    assert response.json()["references"] == [str(camera)]
    assert [item["name"] for item in response.json()["sources"]] == ["camera", "Peter"]


def test_media_estimate_status_reports_completed_review(tmp_path, monkeypatch):
    camera, microphone = _media(tmp_path, monkeypatch)

    def estimate(paths, *, reference_path, progress, window="auto"):
        progress("camera", 0.5)
        progress("Peter", 1.0)
        return {
            "reference": reference_path,
            "tracks": [{
                "path": paths[1], "name": "Peter", "shift_seconds": 0.24,
                "correlation": 0.91, "error": "",
            }],
        }

    monkeypatch.setattr(server_app.media_import, "estimate_sync", estimate)

    class ImmediateThread:
        def __init__(self, *, target, daemon, name):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(server_app.threading, "Thread", ImmediateThread)
    client = TestClient(create_app(AppState(xml_path="")))
    response = client.post(
        "/api/media/estimate",
        json={"paths": [str(camera), str(microphone)], "reference": str(camera)},
    )

    assert response.status_code == 202
    status = client.get("/api/state").json()["media_sync"]
    assert status["ready"] is True
    assert status["fraction"] == 1.0
    assert status["result"]["tracks"][0]["shift_seconds"] == 0.24


def test_media_import_requires_reviewed_shifts_and_returns_source_xml(tmp_path, monkeypatch):
    camera, microphone = _media(tmp_path, monkeypatch)
    client = TestClient(create_app(AppState(xml_path="")))

    response = client.post(
        "/api/media/import",
        json={"paths": [str(camera), str(microphone)], "shifts": {str(microphone): 0.5}},
    )

    assert response.status_code == 200
    path = response.json()["path"]
    assert path.endswith("autoraffkat-source.fcpxml")
    assert "<fcpxml" in __import__("pathlib").Path(path).read_text(encoding="utf-8")


def test_media_picker_returns_multiple_paths(tmp_path, monkeypatch):
    selected = [str(tmp_path / "camera.mp4"), str(tmp_path / "mic.wav")]
    monkeypatch.setattr(server_app.pick, "has_native_picker", lambda: True)
    monkeypatch.setattr(server_app.pick, "native_many", lambda *_args, **_kwargs: selected)
    client = TestClient(create_app(AppState(xml_path="")))

    response = client.post("/api/pick-media")

    assert response.json() == {"paths": selected}


def test_media_estimate_passes_window_through(tmp_path, monkeypatch):
    camera, microphone = _media(tmp_path, monkeypatch)
    seen = {}

    def estimate(paths, *, reference_path, progress, window="auto"):
        seen["window"] = window
        return {"reference": reference_path, "tracks": []}

    monkeypatch.setattr(server_app.media_import, "estimate_sync", estimate)

    class ImmediateThread:
        def __init__(self, *, target, daemon, name):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(server_app.threading, "Thread", ImmediateThread)
    client = TestClient(create_app(AppState(xml_path="")))

    response = client.post(
        "/api/media/estimate",
        json={"paths": [str(camera), str(microphone)],
              "reference": str(camera), "window": "1800"},
    )

    assert response.status_code == 202
    assert seen["window"] == 1800.0


def test_media_estimate_rejects_invalid_window(tmp_path, monkeypatch):
    camera, microphone = _media(tmp_path, monkeypatch)
    client = TestClient(create_app(AppState(xml_path="")))

    response = client.post(
        "/api/media/estimate",
        json={"paths": [str(camera), str(microphone)],
              "reference": str(camera), "window": "sideways"},
    )

    assert response.status_code == 400


def _preview_harness(tmp_path, monkeypatch):
    """Valeverhot ja -renderöinti: API-testi ei koske ffmpeg:iin."""
    import numpy as np

    camera, microphone = _media(tmp_path, monkeypatch)
    envelopes = {
        str(camera): np.random.default_rng(3).normal(size=1000),
        str(microphone): np.random.default_rng(4).normal(size=1000),
    }
    monkeypatch.setattr(server_app, "envelope_for", lambda path, cache_dir=None: envelopes[path])
    monkeypatch.setattr(server_app, "cache_dir", lambda: str(tmp_path / "cache"))

    def fake_render(paths, reference_path, shifts, start, duration, output_path):
        with open(output_path, "wb") as handle:
            handle.write(b"fake mp4")
        return output_path

    monkeypatch.setattr(server_app.media_import, "render_preview_clip", fake_render)
    return camera, microphone


def test_media_preview_renders_and_serves_clip(tmp_path, monkeypatch):
    camera, microphone = _preview_harness(tmp_path, monkeypatch)
    client = TestClient(create_app(AppState(xml_path="")))

    response = client.post(
        "/api/media/preview",
        json={
            "paths": [str(camera), str(microphone)],
            "reference": str(camera),
            "shifts": {str(microphone): 1.25},
            "kind": "all",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("/api/media/preview/")
    assert body["duration"] == media_import.PREVIEW_ALL_SECONDS

    clip = client.get(body["url"])
    assert clip.status_code == 200
    assert clip.headers["content-type"] == "video/mp4"
    assert clip.content == b"fake mp4"


def test_media_preview_validates_request(tmp_path, monkeypatch):
    camera, microphone = _preview_harness(tmp_path, monkeypatch)
    client = TestClient(create_app(AppState(xml_path="")))
    base = {
        "paths": [str(camera), str(microphone)],
        "reference": str(camera),
        "shifts": {str(microphone): 0.0},
    }

    assert client.post("/api/media/preview", json={**base, "kind": "sideways"}).status_code == 400
    assert client.post("/api/media/preview", json={**base, "kind": "speaker"}).status_code == 400
    assert client.post(
        "/api/media/preview", json={"paths": [str(camera)], "reference": str(camera)}
    ).status_code == 400


def test_media_preview_speaker_uses_shorter_span(tmp_path, monkeypatch):
    camera, microphone = _preview_harness(tmp_path, monkeypatch)
    client = TestClient(create_app(AppState(xml_path="")))

    response = client.post(
        "/api/media/preview",
        json={
            "paths": [str(camera), str(microphone)],
            "reference": str(camera),
            "shifts": {str(microphone): 0.0},
            "kind": "speaker",
            "target": str(microphone),
        },
    )

    assert response.status_code == 200
    assert response.json()["duration"] == media_import.PREVIEW_SPEAKER_SECONDS


def test_media_preview_file_guards_name(tmp_path, monkeypatch):
    client = TestClient(create_app(AppState(xml_path="")))

    assert client.get("/api/media/preview/../etc/passwd").status_code in (400, 404)
    assert client.get("/api/media/preview/not-a-hash.mp4").status_code == 400
    assert client.get(
        "/api/media/preview/" + "0" * 40 + ".mp4"
    ).status_code == 404
