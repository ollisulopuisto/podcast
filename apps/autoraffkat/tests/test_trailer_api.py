"""Trailer-sivun rajapinta: pilkonta, ruutu ja vienti."""

import pathlib
from xml.etree import ElementTree as ET

import pytest
from conftest import needs_ffmpeg
from fastapi.testclient import TestClient
from test_trailer import _synthetic

from autoraffkat.server.app import AppState, create_app


@pytest.fixture
def client(scratch_xml):
    return TestClient(create_app(AppState(xml_path=str(scratch_xml()))))


def test_the_page_is_served_with_versioned_assets(client):
    res = client.get("/trailer")
    assert res.status_code == 200
    assert "trailer.js?v=" in res.text
    assert "/static/style.css?v=" in res.text


def test_plan_rejects_a_missing_or_odd_path(client):
    for bad in ("", "/no/such/file.mp4", "../x.mp4", "a\0b"):
        res = client.post("/api/trailer/plan", json={"path": bad})
        assert res.status_code in (400, 404), bad
        assert res.json().get("detail") != "Not Found", bad
    assert client.post("/api/trailer/plan", json={}).status_code in (400, 404)


@needs_ffmpeg
def test_plan_frame_and_export_round_trip(client, tmp_path):
    video = _synthetic(tmp_path / "Trailer One.mp4")
    plan = client.post("/api/trailer/plan", json={"path": video}).json()
    assert plan["ok"]
    assert (plan["width"], plan["height"]) == (320, 180)
    assert len(plan["pieces"]) == 3
    assert plan["pieces"][0]["x"] < 0.4 < 0.6 < plan["pieces"][2]["x"]

    fixed = client.post("/api/trailer/plan", json={"path": video, "every": 3.0}).json()
    assert fixed["pieces"][0]["end"] == 3.0

    frame = client.get("/api/trailer/frame", params={"path": video, "t": 1.0})
    assert frame.status_code == 200
    assert frame.headers["content-type"] == "image/jpeg"
    assert frame.content[:2] == b"\xff\xd8"

    # käyttäjän korjaama paikka menee vientiin sellaisenaan
    pieces = plan["pieces"]
    pieces[1]["x"] = 0.9
    out = client.post("/api/trailer/export", json={
        "path": video, "pieces": pieces, "lane": "bottom", "dialect": "resolve"})
    data = out.json()
    assert out.status_code == 200 and data["ok"]
    written = pathlib.Path(data["path"])
    assert written.parent == tmp_path and written.exists()
    root = ET.fromstring(written.read_text(encoding="utf-8"))
    assert root.get("version") == "1.9"
    spine = list(root.find(".//spine"))
    assert len(spine) == 3
    top, bottom = [k for k in spine[0] if k.tag == "asset-clip"]
    assert top.get("enabled") == "0" and bottom.get("enabled") in (None, "1")

    # toinen vienti ei korvaa ensimmäistä
    again = client.post("/api/trailer/export", json={
        "path": video, "pieces": pieces}).json()
    assert again["path"] != data["path"] and written.exists()

    # kirjattu vienti voidaan näyttää Finderissa
    assert client.post("/api/reveal", json={"path": data["path"]}).status_code == 200


@needs_ffmpeg
def test_export_validates_its_input(client, tmp_path):
    video = _synthetic(tmp_path / "t.mp4")
    ok = [{"start": 0.0, "end": 2.0, "x": 0.5}]
    cases = [
        {"pieces": []},
        {"pieces": [{"start": 2.0, "end": 1.0, "x": 0.5}]},
        {"pieces": [{"start": 0.0, "end": "inf", "x": 0.5}]},
        {"pieces": [{"start": 0.0, "end": 1.0}]},
        {"pieces": ok, "lane": "left"},
        {"pieces": ok, "dialect": "avid"},
        {"pieces": ok * 6000},
    ]
    for body in cases:
        res = client.post("/api/trailer/export", json={"path": video, **body})
        assert res.status_code == 400, body
    # x ulkona 0–1:stä rajataan, ei hylätä
    res = client.post("/api/trailer/export", json={
        "path": video, "pieces": [{"start": 0.0, "end": 2.0, "x": 7}]})
    assert res.status_code == 200


@needs_ffmpeg
def test_frame_only_serves_a_video_the_user_has_planned(client, tmp_path):
    video = _synthetic(tmp_path / "t.mp4")
    other = _synthetic(tmp_path / "other.mp4")
    assert client.get("/api/trailer/frame", params={"path": video, "t": 1}).status_code == 404
    client.post("/api/trailer/plan", json={"path": video})
    assert client.get("/api/trailer/frame", params={"path": video, "t": 1}).status_code == 200
    assert client.get("/api/trailer/frame", params={"path": other, "t": 1}).status_code == 404


@needs_ffmpeg
def test_export_rejects_pieces_with_a_gap_or_an_overlap(client, tmp_path):
    video = _synthetic(tmp_path / "t.mp4")
    gap = [{"start": 0.0, "end": 2.0, "x": 0.5}, {"start": 3.0, "end": 6.0, "x": 0.5}]
    overlap = [{"start": 0.0, "end": 3.0, "x": 0.5}, {"start": 2.0, "end": 6.0, "x": 0.5}]
    late = [{"start": 1.0, "end": 6.0, "x": 0.5}]
    past_end = [{"start": 0.0, "end": 9.0, "x": 0.5}]   # trailer on 6 s
    for pieces in (gap, overlap, late, past_end):
        res = client.post("/api/trailer/export", json={"path": video, "pieces": pieces})
        assert res.status_code == 400, pieces
    assert not list(tmp_path.glob("* trailer*.fcpxml"))


@needs_ffmpeg
def test_repeated_exports_get_distinct_project_names(client, tmp_path):
    video = _synthetic(tmp_path / "t.mp4")
    pieces = [{"start": 0.0, "end": 6.0, "x": 0.5}]
    names = []
    for _ in range(2):
        out = client.post("/api/trailer/export", json={"path": video, "pieces": pieces}).json()
        root = ET.fromstring(pathlib.Path(out["path"]).read_text(encoding="utf-8"))
        names.append(root.find(".//project").get("name"))
    assert names[0] != names[1]


def test_plan_failures_are_translated_not_raw(client, tmp_path, monkeypatch):
    from autoraffkat import i18n, trailer
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    def boom(*a, **k):
        raise OSError("RAW-ERRNO-TEXT")
    monkeypatch.setattr(trailer, "plan", boom)
    i18n.set_language("en")
    try:
        res = client.post("/api/trailer/plan", json={"path": str(video)})
    finally:
        i18n.set_language("fi")
    assert res.status_code == 400
    assert "RAW-ERRNO-TEXT" not in res.json()["detail"]
    assert not res.json()["detail"].startswith("trailer.")
