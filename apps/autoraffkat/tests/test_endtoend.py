"""Koko putki: XML sisään, päätös, XML ulos. Vaatii ffmpegin."""

import os
import pathlib
import threading
import time
from fractions import Fraction
from xml.etree import ElementTree as ET

import pytest
from conftest import needs_ffmpeg
from fastapi.testclient import TestClient
from make_fixture import SPEECH_A, SPEECH_B

from autoraffkat.analysis import analyze, build_grid, resolve_roles
from autoraffkat.decide import decide
from autoraffkat.fcpxml.read import read_fcpxml
from autoraffkat.model import ROLE_CLOSE, ROLE_MIC, ROLE_WIDE, Globals, TrackConfig
from autoraffkat.server.app import AppState, create_app


def _tracks():
    return {
        "WIDE.mp4": TrackConfig(role=ROLE_WIDE),
        "CLOSE_A.mp4": TrackConfig(role=ROLE_CLOSE, speaker="Host"),
        "CLOSE_B.mp4": TrackConfig(role=ROLE_CLOSE, speaker="Guest"),
        "MIC_A.wav": TrackConfig(role=ROLE_MIC, speaker="Host"),
        "MIC_B.wav": TrackConfig(role=ROLE_MIC, speaker="Guest"),
    }


def angle_at(segments, seconds):
    for seg in segments:
        if seg.start <= seconds < seg.end:
            return seg.label
    return None


def source_to_timeline(timeline, key="MIC_A.wav"):
    """Lähdeaika aikajanan ajaksi.

    Projektifixture alkaa lähteen sekunnista 1, synkkaklippi nollasta, joten
    puhejaksojen ajat on käännettävä ennen vertailua.
    """
    item = next(m for m in timeline.media if m.key == key)
    placement = item.placements[0]
    shift = float(placement.start - item.asset_start - placement.offset)
    return lambda t: t - shift


@needs_ffmpeg
@pytest.mark.parametrize("source", ["sync.fcpxml", "project.fcpxml"])
def test_speech_selects_the_right_camera(fixture_dir, source):
    timeline = read_fcpxml(str(fixture_dir / source))
    analysis = analyze(timeline)
    assert not analysis.errors
    tracks = _tracks()
    grid, start, end = build_grid(analysis, tracks, resolve_roles(timeline, tracks))
    decision = decide(
        grid, Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4)
    )
    to_timeline = source_to_timeline(timeline)

    # Yksinpuhelun keskellä pitää olla puhujan lähikuva.
    for spans, other, expected in (
        (SPEECH_A, SPEECH_B, "Host"),
        (SPEECH_B, SPEECH_A, "Guest"),
    ):
        for lo, hi in spans:
            mid = (lo + hi) / 2
            if any(o0 < mid < o1 for o0, o1 in other):
                continue  # päällekkäispuhe, oma sääntönsä
            at = to_timeline(mid)
            if not (float(start) + 1 < at < float(end) - 1):
                continue
            assert angle_at(decision.segments, at) == expected, f"kohta {mid}"


@needs_ffmpeg
def test_overlap_goes_wide(fixture_dir):
    """A puhuu 12–14 ja B 13,5–19: päällekkäisyys vie laajaan."""
    timeline = read_fcpxml(str(fixture_dir / "sync.fcpxml"))
    analysis = analyze(timeline)
    tracks = _tracks()
    grid, _, _ = build_grid(analysis, tracks, resolve_roles(timeline, tracks))
    decision = decide(
        grid,
        Globals(
            min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.3, overlap_rule="wide"
        ),
    )
    at = source_to_timeline(timeline)(13.8)
    assert angle_at(decision.segments, at) == "Laaja"


@needs_ffmpeg
def test_envelope_cache_makes_the_second_pass_free(fixture_dir, monkeypatch):
    """Toinen ajo ei pura ääntä lainkaan.

    Ennen tämä mittasi seinäkelloa ja vaati alle 0,4 sekuntia. Se on
    nopeuden mittaus, ei välimuistin: kone jonka toinen ydin tekee jotain
    muuta kaataa sen vaikka välimuisti toimisi täydellisesti — niin kävi
    kesken käsittelyajon. Nyt purku kielletään, jolloin ohitus näkyy
    virheenä eikä hitautena.
    """
    from speechmix import rms as envelope

    timeline = read_fcpxml(str(fixture_dir / "sync.fcpxml"))
    analyze(timeline)  # lämmitys levylle

    def refuse(*args, **kwargs):
        raise AssertionError("verhokäyrä laskettiin uudestaan: välimuisti ohitettiin")

    monkeypatch.setattr(envelope, "_decode_rms", refuse)
    analyze(timeline)


@needs_ffmpeg
def test_server_round_trip(scratch_xml):
    """Sama silmukka kuin käyttöliittymässä: säädä, katso, vie."""
    source = scratch_xml()
    state = AppState(xml_path=str(source))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    assert state.progress["ready"], "verhokäyrät eivät valmistuneet"

    client = TestClient(create_app(state))
    assert client.get("/").status_code == 200
    assert client.get("/api/state").json()["kind"] == "sync-clip"

    payload = {
        "tracks": {k: v.to_json() for k, v in _tracks().items()},
        "globals": Globals(
            min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4, project_name="Testi"
        ).to_json(),
    }
    result = client.post("/api/settings", json=payload).json()
    assert result["ok"], result.get("problems")
    assert len(result["segments"]) > 4
    assert result["preview"]["speakers"][0]["name"] == "Host"
    assert result["ms"] < 500

    exported = client.post("/api/export", json=payload).json()
    assert exported["ok"]
    written = ET.parse(exported["path"]).getroot()
    # Nimi kantaa myös sen mikä erottaa tämän viennin muista: Final Cut
    # näyttää projektin nimen eikä tiedostonimeä, joten ilman tätä peräkkäiset
    # tuonnit ovat selaimessa erottamattomia.
    shown = written.find(".//project").get("name")
    assert shown.startswith("Testi")
    assert shown != "Testi", "vientiä ei voi erottaa muista Final Cutissa"
    assert len(written.find(".//spine")) == exported["cuts"]

    # Asetukset jäivät XML:n viereen seuraavaa jaksoa varten.
    assert source.with_suffix(".autoraffkat.json").exists()


def test_defaults_are_guessed_but_speakers_are_asked(scratch_xml):
    """Ensiavaus arvaa roolit nimistä; puhujat on silti nimettävä itse."""
    state = AppState(xml_path=str(scratch_xml()))
    state.load()
    assert state.settings.tracks["WIDE.mp4"].role == "wide"
    assert state.settings.tracks["MIC_A.wav"].role == "mic"

    client = TestClient(create_app(state))
    result = client.post("/api/settings", json={"tracks": {}, "globals": {}}).json()
    assert not result["ok"]
    assert any("puhujaa" in p or "speaker" in p.lower() for p in result["problems"])


def test_new_tracks_are_guessed_even_when_the_episode_has_settings(scratch_xml):
    """Raita jota asetuksissa ei ole saa arvauksen, vaikka asetuksia on.

    Arvaus tehtiin vain jakson ensimmäisellä avauksella. Kun raita-avaimet
    muuttuivat — lukija oppi erottamaan tahdistetun kulman kameraksi ja
    mikiksi — tallennetut asetukset olivat vanhoilla avaimilla, ja jokainen
    uusi raita jäi käyttämättömäksi: mikit piti etsiä ja raahata käsin, eikä
    ryhmäkuvaan voinut valita ketään koska ketään ei ollut.
    """
    from autoraffkat import project
    from autoraffkat.project import ProjectSettings

    source = scratch_xml()
    project.save(str(source), ProjectSettings(
        tracks={"VANHA AVAIN": TrackConfig(role=ROLE_MIC, speaker="Vanha")}))
    state = AppState(xml_path=str(source))
    state.load()
    assert state.settings.tracks["MIC_A.wav"].role == ROLE_MIC
    assert state.settings.tracks["WIDE.mp4"].role == ROLE_WIDE
    # Tallennettu raita pysyy sellaisenaan.
    assert state.settings.tracks["VANHA AVAIN"].speaker == "Vanha"


def test_wide_can_be_excluded_and_exported(scratch_xml):
    """Laajan kuvan voi jättää käyttämättömäksi (unused), jolloin leikkaus käyttää vain lähikuvia."""
    state = AppState(xml_path=str(scratch_xml()))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    assert state.progress["ready"], "verhokäyrät eivät valmistuneet"

    client = TestClient(create_app(state))
    payload = {
        "tracks": {k: v.to_json() for k, v in _tracks().items()},
        "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4).to_json(),
    }
    payload["tracks"]["WIDE.mp4"]["role"] = "unused"
    result = client.post("/api/settings", json=payload).json()
    assert result["ok"], result.get("problems")
    assert result["segments"], "leikkauslista ei saa olla tyhjä"
    assert any(s["label"] == "Host" for s in result["segments"])
    assert any(s["label"] == "Guest" for s in result["segments"])
    assert all(s["label"] in ("Host", "Guest") for s in result["segments"])
    assert all(s["angle"] in ("CLOSE_A.mp4", "CLOSE_B.mp4") for s in result["segments"])

    # Viedään XML ja varmistetaan ettei laaja kuva päädy mukaan resursseihin tai spinelle
    exp = client.post("/api/export").json()
    assert exp["ok"], exp.get("problems")
    xml = pathlib.Path(exp["path"]).read_text(encoding="utf-8")
    root = ET.fromstring(xml)
    media_srcs = [rep.get("src", "") for rep in root.findall(".//media-rep")]
    assert any("CLOSE_A.mp4" in s for s in media_srcs)
    assert any("CLOSE_B.mp4" in s for s in media_srcs)
    assert not any("WIDE.mp4" in s for s in media_srcs)




@needs_ffmpeg
def test_a_group_shot_is_set_and_exported_through_the_interface(scratch_xml):
    """Kahden kuva roolitetaan rajapinnan kautta ja päätyy vientiin.

    Kummallakaan puhujalla ei ole omaa lähikuvaa, joten kaikki muu kuin
    laaja on kahden kuvaa — ei laajaa niin kuin ennen ryhmäkuvia.
    """
    state = AppState(xml_path=str(scratch_xml()))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    assert state.progress["ready"], "verhokäyrät eivät valmistuneet"

    client = TestClient(create_app(state))
    tracks = {k: v.to_json() for k, v in _tracks().items()}
    tracks["CLOSE_A.mp4"] = {"role": "group", "speaker": "",
                             "covers": ["Host", "Guest"]}
    tracks["CLOSE_B.mp4"] = {"role": "unused", "speaker": ""}
    result = client.post("/api/settings", json={
        "tracks": tracks,
        "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3,
                           min_overlap=0.4).to_json(),
    }).json()
    assert result["ok"], result.get("problems")
    shown = {(s["angle"], s["label"]) for s in result["segments"]}
    assert shown == {("WIDE.mp4", "Laaja"), ("CLOSE_A.mp4", "Host & Guest")}

    exp = client.post("/api/export").json()
    assert exp["ok"], exp.get("problems")
    root = ET.fromstring(pathlib.Path(exp["path"]).read_text(encoding="utf-8"))
    media_srcs = [rep.get("src", "") for rep in root.findall(".//media-rep")]
    assert any("CLOSE_A.mp4" in src for src in media_srcs)
    assert not any("CLOSE_B.mp4" in src for src in media_srcs)


@needs_ffmpeg
def test_vertical_export_evens_out_face_sizes(scratch_xml):
    """Pystyvienti zoomaa pienemmät kasvot suurimpien kokoisiksi.

    Käsin tehty pohja: Tomin kamera 1,22, jotta hänen kasvonsa olivat Mikon
    kokoiset. Taulukot annetaan suoraan, koska mittaus vaatii oikeat kasvot;
    tämä testaa että zoomi päätyy vientiin asti.
    """
    import numpy as np

    state = AppState(xml_path=str(scratch_xml()))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)

    def faces(h):
        n = 40
        return {"times": np.arange(n, dtype=np.float32), "found": np.ones(n, bool),
                "x": np.full(n, 0.45, np.float32), "w": np.full(n, 0.1, np.float32),
                "y": np.full(n, 0.4, np.float32), "h": np.full(n, h, np.float32)}

    state.video_tables = {"CLOSE_A.mp4": faces(0.246), "CLOSE_B.mp4": faces(0.30)}
    client = TestClient(create_app(state))
    result = client.post("/api/settings", json={
        "tracks": {k: v.to_json() for k, v in _tracks().items()},
        "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4,
                           vertical=True).to_json(),
    }).json()
    assert result["ok"], result.get("problems")
    exp = client.post("/api/export").json()
    assert exp["ok"], exp.get("problems")
    root = ET.fromstring(pathlib.Path(exp["path"]).read_text(encoding="utf-8"))
    scales = {}
    for clip in root.findall(".//spine/*"):
        transform = clip.find("adjust-transform")
        name = clip.get("name", "")
        if transform is not None:
            scales.setdefault(name.split()[0], set()).add(
                round(float(transform.get("scale").split()[0]), 3))
    from autoraffkat.reframe import MAX_ZOOM

    assert scales.get("Host") == {round(min(0.30 / 0.246, MAX_ZOOM), 3)}, scales
    assert scales.get("Guest") == {1.0}, scales


@needs_ffmpeg
@pytest.mark.parametrize("flip", [False, True], ids=["mitattu", "käsin"])
def test_vertical_follows_the_speaker_inside_a_two_shot(scratch_xml, flip):
    """Kahden kuva ilman lähikuvia: pystyrajaus seuraa puhujaa.

    Hostin ja Guestin kasvot mitataan kuvasta (tässä annettuina), kumpi on
    kumpi päätellään suun liikkeestä mikkien puheen aikana, ja vienti
    pilkkoo kahden kuvan puhujan mukaan ja rajaa kunkin palan hänen
    kasvoilleen. Host istuu vasemmalla: hänen palansa siirtyvät oikealle.
    """
    import numpy as np

    state = AppState(xml_path=str(scratch_xml()))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)

    def talking(spans, t):
        return any(a <= t < b for a, b in spans)

    rows = []
    for t in range(35):
        for x, spans in ((0.15, SPEECH_A), (0.65, SPEECH_B)):
            rows.append((t, x, 0.4 * talking(spans, t) * (t % 2)))
    n = len(rows)
    state.crowd_tables = {"CLOSE_A.mp4": {
        "times": np.arange(35, dtype=np.float32),
        "frame": np.array([r[0] for r in rows], np.int32),
        "x": np.array([r[1] for r in rows], np.float32),
        "w": np.full(n, 0.1, np.float32), "y": np.full(n, 0.4, np.float32),
        "h": np.full(n, 0.2, np.float32),
        "mouth": np.array([r[2] for r in rows], np.float32)}}

    tracks = {k: v.to_json() for k, v in _tracks().items()}
    tracks["CLOSE_A.mp4"] = {"role": "group", "speaker": "", "covers": ["Host", "Guest"]}
    tracks["CLOSE_B.mp4"] = {"role": "unused", "speaker": ""}
    client = TestClient(create_app(state))
    result = client.post("/api/settings", json={
        "tracks": tracks,
        "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4,
                           vertical=True).to_json(),
    }).json()
    assert result["ok"], result.get("problems")
    # Käyttöliittymä näkee mitä mitattiin, jotta väärän voi korjata.
    assert result["seats"]["CLOSE_A.mp4"] == [
        {"part": "CLOSE_A.mp4", "order": ["Host", "Guest"],
         "margin": result["seats"]["CLOSE_A.mp4"][0]["margin"], "manual": False}]
    assert result["seats"]["CLOSE_A.mp4"][0]["margin"] > 0
    if flip:
        tracks["CLOSE_A.mp4"]["seats"] = ["Guest", "Host"]
        result = client.post("/api/settings", json={
            "tracks": tracks,
            "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4,
                               vertical=True).to_json(),
        }).json()
        assert result["seats"]["CLOSE_A.mp4"][0]["order"] == ["Guest", "Host"]
        assert result["seats"]["CLOSE_A.mp4"][0]["manual"]
    exp = client.post("/api/export").json()
    assert exp["ok"], exp.get("problems")
    root = ET.fromstring(pathlib.Path(exp["path"]).read_text(encoding="utf-8"))
    moves = []
    for clip in root.find(".//sequence/spine"):
        transform = clip.find("adjust-transform")
        if transform is not None:
            start = float(Fraction(clip.get("offset").rstrip("s")))
            moves.append((start, float(transform.get("position").split()[0])))
    host = [x for t, x in moves if talking(SPEECH_A, t + 0.5) and not talking(SPEECH_B, t + 0.5)]
    guest = [x for t, x in moves if talking(SPEECH_B, t + 0.5) and not talking(SPEECH_A, t + 0.5)]
    assert host and guest, moves
    # Käsin käännetty järjestys voittaa mittauksen: Host rajataan oikealle.
    sign = -1 if flip else 1
    assert all(sign * x > 0 for x in host) and all(sign * x < 0 for x in guest), moves


@needs_ffmpeg
def test_shorts_style_punches_in_on_the_same_camera(scratch_xml, monkeypatch):
    """Shorts-tyyli rajapinnan kautta: vientiin tulee punch-inejä, eli
    saman kameran peräkkäisiä kuvia 112 %:ssa, ja nimeen «shorts».

    Fixturen «puhe» on yhtenäisiä siniääniä ilman lauseiden välisiä
    taukoja, joten painotuksia ei synny; niiden tunnistus on testattu
    ``test_movement``issa. Tässä pilkkoja lyö punchin ensimmäisen
    lähikuvan keskelle, ja testi katsoo että vienti kantaa sen perille.
    """
    from dataclasses import replace
    from itertools import pairwise

    from autoraffkat import movement

    def punch_middle(segments, grid, min_shot):
        out, done = [], False
        for seg in segments:
            if not done and seg.label != "Laaja" and seg.end - seg.start >= 3 * min_shot:
                third = (seg.end - seg.start) / 3
                out += [replace(seg, end=seg.start + third),
                        replace(seg, start=seg.start + third, end=seg.end - third, punch=True),
                        replace(seg, start=seg.end - third)]
                done = True
            else:
                out.append(seg)
        return out

    monkeypatch.setattr(movement, "punch_segments", punch_middle)
    state = AppState(xml_path=str(scratch_xml()))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    client = TestClient(create_app(state))
    result = client.post("/api/settings", json={
        "tracks": {k: v.to_json() for k, v in _tracks().items()},
        "globals": {**Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4,
                              movement=True).to_json(),
                    "movement_style": "shorts", "wide_every": 0},
    }).json()
    assert result["ok"], result.get("problems")
    assert state.settings.globals.movement_style == "shorts"
    exp = client.post("/api/export").json()
    assert exp["ok"], exp.get("problems")
    assert "shorts" in pathlib.Path(exp["path"]).name
    root = ET.fromstring(pathlib.Path(exp["path"]).read_text(encoding="utf-8"))
    clips = list(root.find(".//sequence/spine"))
    punched = []
    for before, clip in pairwise(clips):
        transform = clip.find("adjust-transform")
        if transform is None or transform.get("scale") is None:
            continue
        if abs(float(transform.get("scale").split()[0]) - movement.PUNCH) < 1e-6:
            punched.append((before.get("ref"), clip.get("ref")))
    assert punched, "ei yhtään punch-iniä"
    assert all(a == b for a, b in punched), punched   # sama kamera ennen punchia


# ------------------------------------------------------------------ multicam


def _multicam_tracks():
    """Roolit raita-avaimilla: kulma on yksi raita, vaikka osia on kaksi."""
    return {
        "WIDE": TrackConfig(role=ROLE_WIDE),
        "CLOSE_A": TrackConfig(role=ROLE_CLOSE, speaker="Host"),
        "CLOSE_B": TrackConfig(role=ROLE_CLOSE, speaker="Guest"),
        "host Track1": TrackConfig(role=ROLE_MIC, speaker="Host"),
        "guest Track2": TrackConfig(role=ROLE_MIC, speaker="Guest"),
    }


@needs_ffmpeg
def test_a_mic_missing_from_one_part_does_not_end_the_programme(fixture_dir, tmp_path):
    """Osa B ilman vieraan mikkiä on silti osa ohjelmaa.

    Ohjelma rajattiin aikaan jossa *jokainen* mikki on olemassa, joten
    yhdestä osasta puuttuva mikki katkaisi ohjelman ensimmäisen osan
    loppuun: osa B putosi viennistä kokonaan, eikä mikään kertonut siitä.
    """
    import make_fixture

    path = tmp_path / "uneven.fcpxml"
    make_fixture.write_multicam_xml(
        str(path), make_fixture.make_parts(str(fixture_dir), {}),
        missing_in_b=("mic_b",))
    timeline = read_fcpxml(str(path))
    guest = next(t.key for t in timeline.tracks if "Track2" in t.key)
    assert timeline.track_span(guest) == (0, 18), "fixture: mikki vain osassa A"

    tracks = _multicam_tracks()
    tracks[guest] = tracks.pop("guest Track2")
    roles = resolve_roles(timeline, tracks)
    assert roles.problems == []
    grid, start, end = build_grid(analyze(timeline), tracks, roles)
    assert (float(start), float(end)) == (0.0, 36.0)
    decision = decide(
        grid, Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4))
    assert decision.segments[-1].end == pytest.approx(36.0)
    # Osassa B vieraan mikki on hiljaa, ei puhuja: kuva ei mene hänelle.
    assert not any(s.label == "Guest" and s.start >= 18.0 for s in decision.segments)


CAMS = ("wide", "close_a", "close_b")


@needs_ffmpeg
def test_a_third_mic_only_in_the_middle_part(fixture_dir, tmp_path, monkeypatch):
    """Kolme osaa: 3+2, 3+3, 3+2 — kolmas mikki vain keskimmäisessä.

    Oikea jakso tällä rakenteella: vieras on mukana vain keskellä. Ohjelma
    on koko aikajana, jokainen osa viittaa viennissä vain omiin
    kulmiinsa, ja käsittely tekee jokaisen mikkitiedoston.
    """
    import shutil

    import make_fixture

    # Omat kopiot lähteistä: käsittely kirjoittaa [mix]-tiedostot lähteen
    # viereen, ja jaetun fixturen vieressä ne näkyisivät muille testeille.
    for name in ("WIDE.mp4", "CLOSE_A.mp4", "CLOSE_B.mp4", "MIC_A.wav", "MIC_B.wav"):
        shutil.copy(fixture_dir / name, tmp_path / name)
    source = tmp_path / "parts.fcpxml"
    make_fixture.write_parts_xml(str(source), str(tmp_path), [
        (*CAMS, "mic_a", "mic_b"),
        (*CAMS, "mic_a", "mic_b", "mic_c"),
        (*CAMS, "mic_a", "mic_b"),
    ])
    timeline = read_fcpxml(str(source))
    key = {name: next(t.key for t in timeline.tracks if name in t.key)
           for name in ("Track1", "Track2", "Track3")}
    assert [len(timeline.track_media(key[n])) for n in key] == [3, 3, 1]
    assert timeline.track_span(key["Track3"]) == (12, 24)

    state = AppState(xml_path=str(source))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    assert state.progress["ready"], "verhokäyrät eivät valmistuneet"
    tracks = {
        "WIDE": TrackConfig(role=ROLE_WIDE),
        "CLOSE_A": TrackConfig(role=ROLE_CLOSE, speaker="Host"),
        "CLOSE_B": TrackConfig(role=ROLE_CLOSE, speaker="Guest"),
        key["Track1"]: TrackConfig(role=ROLE_MIC, speaker="Host"),
        key["Track2"]: TrackConfig(role=ROLE_MIC, speaker="Guest"),
        key["Track3"]: TrackConfig(role=ROLE_MIC, speaker="Third"),
    }
    client = TestClient(create_app(state))
    result = client.post("/api/settings", json={
        "tracks": {k: v.to_json() for k, v in tracks.items()},
        "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3,
                           min_overlap=0.4).to_json(),
    }).json()
    assert result["ok"], result.get("problems")
    assert (result["program"]["start"], result["program"]["end"]) == (0.0, 36.0)
    assert result["segments"][-1]["end"] == pytest.approx(36.0)

    exp = client.post("/api/export").json()
    assert exp["ok"], exp.get("problems")
    root = ET.fromstring(pathlib.Path(exp["path"]).read_text(encoding="utf-8"))
    clips = root.findall(".//spine/mc-clip")
    assert {c.get("ref") for c in clips} == {"m1", "m2", "m3"}
    for clip in clips:
        part = clip.get("ref")[1:]
        ids = {el.get("angleID") for el in clip.iter() if el.get("angleID")}
        assert all(i.startswith(f"P{part}") for i in ids), (part, ids)
        assert any("mic_c" in i for i in ids) == (part == "2"), (part, ids)

    # Käsittely: jokainen mikkitiedosto, eikä virheitä.
    import io
    import json

    from autoraffkat.audio import mix as mix_module
    from autoraffkat.audio import worker
    from autoraffkat.model import AudioSettings
    from autoraffkat.project import ProjectSettings

    monkeypatch.setattr(mix_module.chain, "load_pool", lambda *a, **k: None)
    settings = ProjectSettings(tracks=tracks, audio=AudioSettings(
        enabled=True, plugin_path="", debleed=True, duck=True))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"xml_path": str(source), "settings": settings.to_json(), "force": True})))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    assert worker.main() == 0
    done = None
    for line in out.getvalue().splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("kind") == "done":
            done = message
    assert done is not None
    assert done["errors"] == {}
    assert len(done["replacements"]) == 7, sorted(done["replacements"])


@needs_ffmpeg
def test_a_synced_multicam_is_cut_processed_and_exported(fixture_dir, tmp_path, monkeypatch):
    """Kulmat synkkaklippeinä (kamera + mikki), vieras vain osassa 1.

    Rakenne on oikean projektin (hmh hannes): kamera ja mikki tahdistettu
    pareittain, pareista monikamera, kaksi osaa. Koko putki rajapinnan
    kautta: roolitus, leikkaus koko aikajanalle, käsittely ja vienti jossa
    jokainen mikki soi kerran.
    """
    import io
    import json
    import shutil

    import make_fixture

    from autoraffkat.audio import mix as mix_module
    from autoraffkat.audio import worker
    from autoraffkat.model import AudioSettings
    from autoraffkat.project import ProjectSettings

    for name in ("WIDE.mp4", "CLOSE_A.mp4", "CLOSE_B.mp4", "MIC_A.wav", "MIC_B.wav"):
        shutil.copy(fixture_dir / name, tmp_path / name)
    source = tmp_path / "synced.fcpxml"
    make_fixture.write_synced_multicam_xml(str(source), str(tmp_path))

    tracks = {
        "FOCUS CAM 1": TrackConfig(role=ROLE_CLOSE, speaker="Tomi"),
        "FOCUS CAM 2": TrackConfig(role=ROLE_WIDE),
        "FOCUS CAM 3": TrackConfig(role=ROLE_CLOSE, speaker="Mikko"),
        "Tomi": TrackConfig(role=ROLE_MIC, speaker="Tomi"),
        "Mikko": TrackConfig(role=ROLE_MIC, speaker="Mikko"),
        "Vieras": TrackConfig(role=ROLE_MIC, speaker="Vieras"),
    }
    monkeypatch.setattr(mix_module.chain, "load_pool", lambda *a, **k: None)
    settings = ProjectSettings(tracks=tracks, audio=AudioSettings(
        enabled=True, plugin_path="", debleed=True, duck=True))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(
        {"xml_path": str(source), "settings": settings.to_json(), "force": True})))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    assert worker.main() == 0
    monkeypatch.undo()
    done = [json.loads(line) for line in out.getvalue().splitlines()
            if line.startswith("{") and '"kind": "done"' in line][-1]
    assert done["errors"] == {}
    assert sorted(done["replacements"]) == [
        "Mikko_001.wav", "Mikko_002.wav", "Tomi_001.wav", "Tomi_002.wav",
        "Vieras_001.wav"]

    state = AppState(xml_path=str(source))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    assert state.progress["ready"], "verhokäyrät eivät valmistuneet"
    client = TestClient(create_app(state))
    result = client.post("/api/settings", json={
        "tracks": {k: v.to_json() for k, v in tracks.items()},
        "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3,
                           min_overlap=0.4).to_json(),
        "audio": settings.audio.to_json(),
    }).json()
    assert result["ok"], result.get("problems")
    assert (result["program"]["start"], result["program"]["end"]) == (0.0, 36.0)
    assert {s["angle"] for s in result["segments"]} >= {"FOCUS CAM 1", "FOCUS CAM 3"}

    exp = client.post("/api/export").json()
    assert exp["ok"], exp.get("problems")
    root = ET.fromstring(pathlib.Path(exp["path"]).read_text(encoding="utf-8"))
    mics = {"1": {"Tomi", "Vieras", "Mikko"}, "2": {"Tomi", "Mikko"}}
    for clip in root.findall(".//spine/mc-clip"):
        part = clip.get("ref")[-1]
        heard = [r.get("role").split(".")[1]
                 for source in clip.findall("mc-source")
                 if source.get("srcEnable") in ("all", "audio")
                 for r in source.findall("audio-role-source")
                 if r.get("active") != "0"]
        assert sorted(heard) == sorted(mics[part]), (part, heard)
    # Käsitelty ääni on vientiin ohjattu mikin assettiin, ei kameraan.
    srcs = [rep.get("src", "") for rep in root.iter("media-rep")]
    assert sum("%5Bmix%5D" in s for s in srcs) == 5, srcs


@needs_ffmpeg
def test_multicam_speech_selects_the_right_camera(fixture_dir):
    """Sama tarkistus kuin synkkaklipille, mutta puhe jatkuu osien yli."""
    timeline = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    analysis = analyze(timeline)
    assert not analysis.errors
    tracks = _multicam_tracks()
    grid, start, end = build_grid(analysis, tracks, resolve_roles(timeline, tracks))
    # Ohjelma kattaa molemmat osat, ei vain jälkimmäistä.
    assert float(start) == 0.0 and float(end) > 30.0
    decision = decide(
        grid, Globals(min_shot=1.5, lead=0.15, confirm=0.3, min_overlap=0.4)
    )
    to_timeline = source_to_timeline(timeline, "host a Track1.wav")

    for spans, other, expected in (
        (SPEECH_A, SPEECH_B, "Host"),
        (SPEECH_B, SPEECH_A, "Guest"),
    ):
        for lo, hi in spans:
            mid = (lo + hi) / 2
            if any(o0 < mid < o1 for o0, o1 in other):
                continue
            at = to_timeline(mid)
            if not (float(start) + 1 < at < float(end) - 1):
                continue
            assert angle_at(decision.segments, at) == expected, f"kohta {mid}"


@needs_ffmpeg
def test_multicam_server_round_trip(scratch_xml):
    """Sama silmukka kuin käyttöliittymässä, monikameralähteellä."""
    source = scratch_xml("multicam.fcpxml")
    state = AppState(xml_path=str(source))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    client = TestClient(create_app(state))
    fetched = client.get("/api/state").json()
    assert fetched["kind"] == "multicam"
    assert fetched["parts"] == 2
    assert len(fetched["tracks"]) == 5
    assert all(len(t["parts"]) == 2 for t in fetched["tracks"])

    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": Globals(
            min_shot=1.5,
            lead=0.15,
            confirm=0.3,
            min_overlap=0.4,
            project_name="Monikamera",
        ).to_json(),
    }
    result = client.post("/api/settings", json=payload).json()
    assert result["ok"], result.get("problems")
    assert len(result["segments"]) > 4

    exported = client.post("/api/export", json=payload).json()
    assert exported["ok"]
    written = ET.parse(exported["path"]).getroot()
    clips = written.findall(".//spine/mc-clip")
    assert clips, "vienti ei tuottanut monikameraklippejä"
    # Rajaylitykset pilkkoutuvat, joten klippejä on vähintään yhtä monta.
    assert len(clips) >= exported["cuts"]
    assert {c.get("ref") for c in clips} == {"mA", "mB"}


def test_multicam_wide_can_be_excluded(scratch_xml):
    """Monikamerasta voi jättää laajan kulman pois."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)

    client = TestClient(create_app(state))
    tracks = {k: v.to_json() for k, v in _multicam_tracks().items()}
    tracks["WIDE"]["role"] = "unused"
    payload = {
        "tracks": tracks,
        "globals": Globals(
            min_shot=1.5,
            lead=0.15,
            confirm=0.3,
            min_overlap=0.4,
            project_name="Monikamera",
        ).to_json(),
    }
    result = client.post("/api/settings", json=payload).json()
    assert result["ok"], result.get("problems")
    assert all(s["label"] in ("Host", "Guest") for s in result["segments"])
    assert all(s["angle"] in ("CLOSE_A", "CLOSE_B") for s in result["segments"])

    exported = client.post("/api/export", json=payload).json()
    assert exported["ok"]
    written = ET.parse(exported["path"]).getroot()
    clips = written.findall(".//spine/mc-clip")
    assert clips
    # Varmistetaan että kaikki leikkaukset käyttävät vain lähikuvakulmia
    sources = [c.find("mc-source") for c in clips if c.find("mc-source") is not None]
    wide_angle_ids = set({t.key: t for t in state.timeline.tracks}["WIDE"].angle_ids)
    assert not any(s.get("angleID") in wide_angle_ids for s in sources)



def test_multicam_defaults_guess_speakers_from_mic_names(scratch_xml):
    """Mikin ensimmäinen sana on käytännössä aina puhujan nimi."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    assert state.settings.tracks["host Track1"].role == "mic"
    assert state.settings.tracks["host Track1"].speaker == "Host"
    assert state.settings.tracks["guest Track2"].speaker == "Guest"
    # Kameroita ei arvata: kulmat ovat 1, 2, 3 eikä niistä näe mitään.
    assert state.settings.tracks["CLOSE_A"].role == "unused"


def test_all_wide_is_a_problem_not_a_result(scratch_xml):
    """Ilman lähikuvia leikkaus olisi yhtä laajaa kuvaa — se on puute."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    tracks = {k: v.to_json() for k, v in _multicam_tracks().items()}
    tracks["CLOSE_A"]["role"] = "unused"
    tracks["CLOSE_B"]["role"] = "unused"
    result = client.post("/api/settings", json={"tracks": tracks, "globals": {}}).json()
    assert not result["ok"]
    assert any("lähikuvaa" in p or "close-up" in p.lower() for p in result["problems"])


def test_roles_are_inherited_from_the_previous_episode(fixture_dir, tmp_path):
    """Kamera ei kerro kumpaa puhujaa se kuvaa, mutta viime jakso kertoo."""
    import shutil

    from autoraffkat import project

    previous = tmp_path / "jakso53.fcpxmld"
    previous.mkdir()
    project.save(
        str(previous / "Info.fcpxml"),
        project.ProjectSettings(
            tracks=dict(_multicam_tracks().items()),
            globals=Globals(min_shot=4.0),
        ),
    )

    current = tmp_path / "jakso54.fcpxmld"
    current.mkdir()
    shutil.copy(fixture_dir / "multicam.fcpxml", current / "Info.fcpxml")

    state = AppState(xml_path=str(current / "Info.fcpxml"))
    state.load()
    assert state.settings.tracks["CLOSE_A"].role == "close"
    assert state.settings.tracks["CLOSE_A"].speaker == "Host"
    assert state.settings.tracks["WIDE"].role == "wide"
    assert state.settings.globals.min_shot == 4.0
    assert state.inherited_from.endswith("jakso53.autoraffkat.json")


def test_audio_settings_are_inherited_too(fixture_dir, tmp_path):
    """Kanavanauha ja vaimennus ovat samat viikosta toiseen."""
    import shutil

    from autoraffkat import project
    from autoraffkat.model import AudioSettings

    previous = tmp_path / "jakso53.fcpxmld"
    previous.mkdir()
    project.save(
        str(previous / "Info.fcpxml"),
        project.ProjectSettings(
            tracks=dict(_multicam_tracks().items()),
            audio=AudioSettings(
                enabled=True, duck=True, duck_db=-20.0, target_lufs=-17.0
            ),
        ),
    )

    current = tmp_path / "jakso54.fcpxmld"
    current.mkdir()
    shutil.copy(fixture_dir / "multicam.fcpxml", current / "Info.fcpxml")

    state = AppState(xml_path=str(current / "Info.fcpxml"))
    state.load()
    assert state.settings.audio.enabled and state.settings.audio.duck
    assert state.settings.audio.duck_db == -20.0
    assert state.settings.audio.target_lufs == -17.0


def test_own_settings_beat_the_previous_episode(fixture_dir, tmp_path):
    import shutil

    from autoraffkat import project

    other = tmp_path / "jakso53.fcpxmld"
    other.mkdir()
    project.save(
        str(other / "Info.fcpxml"),
        project.ProjectSettings(
            tracks={"WIDE": TrackConfig(role=ROLE_CLOSE, speaker="Väärin")}
        ),
    )

    current = tmp_path / "jakso54.fcpxmld"
    current.mkdir()
    xml = current / "Info.fcpxml"
    shutil.copy(fixture_dir / "multicam.fcpxml", xml)
    project.save(
        str(xml), project.ProjectSettings(tracks={"WIDE": TrackConfig(role=ROLE_WIDE)})
    )

    state = AppState(xml_path=str(xml))
    state.load()
    assert state.settings.tracks["WIDE"].role == "wide"
    assert state.inherited_from == ""


def test_audio_settings_survive_a_round_trip(scratch_xml):
    """Ääniasetukset tallentuvat XML:n viereen kuten muutkin."""
    from autoraffkat import project

    source = scratch_xml("multicam.fcpxml")
    state = AppState(xml_path=str(source))
    state.load()
    client = TestClient(create_app(state))
    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": {},
        "audio": {
            "enabled": True,
            "target_lufs": -18.0,
            "room_track": "WIDE",
            "room_db": -20.0,
        },
    }
    client.post("/api/settings", json=payload)
    saved = project.load(str(source)).audio
    assert saved.enabled and saved.target_lufs == -18.0
    assert saved.room_track == "WIDE" and saved.room_db == -20.0


def test_unknown_room_track_is_refused(scratch_xml):
    """Tuntematon raita jäisi hiljaa pois; se nollataan heti."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    client.post(
        "/api/settings",
        json={
            "tracks": {},
            "globals": {},
            "audio": {"enabled": True, "room_track": "EI OLE"},
        },
    )
    assert state.settings.audio.room_track == ""


def test_plugin_parameters_belong_to_their_plugin(scratch_xml, tmp_path):
    """Säätimet nollataan kun liitännäinen vaihtuu.

    Toisen liitännäisen nimet eivät osu mihinkään — ja jos osuvat, ne osuvat
    väärään säätimeen. Se olisi huomaamaton virhe: käsittely menisi läpi ja
    kuulostaisi väärältä.
    """
    first = tmp_path / "Yksi.vst3"
    second = tmp_path / "Kaksi.vst3"
    first.mkdir()
    second.mkdir()
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))

    def post(path, params):
        client.post(
            "/api/settings",
            json={
                "tracks": {},
                "globals": {},
                "audio": {"plugin_path": str(path), "plugin_params": params},
            },
        )

    post(first, {"input_gain": 3.0})
    assert state.settings.audio.plugin_params == {"input_gain": 3.0}
    post(second, {})
    assert state.settings.audio.plugin_params == {}
    assert state.settings.audio.plugin_path == str(second)


def test_plugin_parameters_accept_only_scalars(scratch_xml, tmp_path):
    """Arvot menevät ulkopuoliselle liitännäiselle, joten muu kuin luku,
    totuusarvo tai teksti ei pääse läpi."""
    fake = tmp_path / "Vale.vst3"
    fake.mkdir()
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    client.post(
        "/api/settings",
        json={
            "tracks": {},
            "globals": {},
            "audio": {
                "plugin_path": str(fake),
                "plugin_params": {
                    "gain": 3,
                    "bypass": True,
                    "mode": "Voice",
                    "roska": [1, 2],
                    "tyhja": None,
                },
            },
        },
    )
    assert state.settings.audio.plugin_params == {
        "gain": 3.0,
        "bypass": True,
        "mode": "Voice",
    }


def test_plugin_parameters_endpoint_lists_the_controls(scratch_xml, monkeypatch):
    """Säätimet ovat oma pyyntönsä: liitännäisen lataus kestää sekunteja."""
    from speechmix import chain

    monkeypatch.setattr(
        chain,
        "parameter_specs",
        lambda path: ([{"name": "mix", "label": "Mix", "type": "float"}], 7),
    )
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    client = TestClient(create_app(state))
    data = client.get("/api/plugin-params", params={"path": "/x/Vale.vst3"}).json()
    assert data["total"] == 7 and data["params"][0]["name"] == "mix"


def test_plugin_parameters_endpoint_reports_a_missing_plugin(scratch_xml):
    """Virhe tulee heti eikä minuuttien päästä käsittelyn keskeltä.

    Viesti on käyttäjän kielellä, joten sitä ei verrata tekstinä: kieli on
    ContextVar eikä testin ajojärjestys saa ratkaista tulosta. Polku on siinä
    molemmilla kielillä, ja juuri se kertoo mikä meni pieleen.
    """
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    client = TestClient(create_app(state))
    response = client.get("/api/plugin-params", params={"path": "/ei/ole.vst3"})
    assert response.status_code == 400
    assert "/ei/ole.vst3" in response.json()["detail"]


def test_export_ignores_processed_audio_that_is_not_there(scratch_xml):
    """Puuttuvaan [mix]-tiedostoon ei viitata, vaikka se olisi kirjattu."""
    from autoraffkat.audio import mix as mixer

    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    state.mix_result = mixer.MixResult(
        replacements={"host a Track1.wav": "/ei/ole [mix].wav"}
    )
    state.settings.audio.enabled = True

    client = TestClient(create_app(state))
    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": {},
        "audio": {"enabled": True},
    }
    result = client.post("/api/export", json=payload).json()
    assert result["ok"] and result["mixed"] == 0
    assert "%5Bmix%5D" not in ET.tostring(
        ET.parse(result["path"]).getroot(), encoding="unicode"
    )


def test_second_export_writes_a_new_file(scratch_xml):
    """Toinen vienti ei korvaa ensimmäistä.

    Edellinen leikkaus on tyypillisesti jo tuotu Final Cutiin ja sitä on
    ehditty muokata, eikä siihen työhön ole enää muuta lähdettä.
    """
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)

    client = TestClient(create_app(state))
    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": {},
    }
    first = client.post("/api/export", json=payload).json()
    second = client.post("/api/export", json=payload).json()
    assert first["ok"] and second["ok"]
    assert first["path"] != second["path"]
    assert second["path"].endswith("-cut broadcast v2.fcpxml")
    assert os.path.exists(first["path"]) and os.path.exists(second["path"])
    # Ruudulla näkyvä polku kertoo mihin seuraava vienti menee.
    assert second["next_path"].endswith("-cut broadcast v3.fcpxml")
    assert client.get("/api/state").json()["output_path"] == second["next_path"]


def test_export_warns_when_audio_is_still_processing(scratch_xml):
    """Kesken käsittelyn vietäessä tulos on ehjä mutta käsittelemätön.

    Sitä ei huomaa Final Cutissa ennen kuin kuuntelee, ja silloin leikkaus on
    jo tehty — uusi vienti ei tuo tehtyjä muokkauksia mukanaan.
    """
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    state.settings.audio.enabled = True
    state.mix_progress["running"] = True

    client = TestClient(create_app(state))
    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": {},
        "audio": {"enabled": True},
    }
    result = client.post("/api/export", json=payload).json()
    assert result["ok"] and result["mixed"] == 0
    assert any("kesken" in w or "running" in w.lower() for w in result["warnings"])


def test_export_is_quiet_when_audio_is_off(scratch_xml):
    """Ilman äänenkäsittelyä ei ole mitään varoitettavaa."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    client = TestClient(create_app(state))
    result = client.post(
        "/api/export",
        json={
            "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
            "globals": {},
            "audio": {"enabled": False},
        },
    ).json()
    assert result["ok"] and result["warnings"] == []


def test_export_warns_when_the_source_has_no_multicam_clip(scratch_xml):
    """Littana vienti ei saa jäädä sanomatta.

    Lähde tehty «Synkronoi klipit»-komennolla (liitetyt lanet, ei
    monikameraa) tuottaa aina littanan viennin, mutta se ei saanut mitään
    varoitusta: käyttäjä huomasi vasta Final Cutissa, ettei kuvakulmaa voi
    vaihtaa, eikä syy näkynyt sinä.
    """
    from autoraffkat.i18n import t

    state = AppState(xml_path=str(scratch_xml("sync.fcpxml")))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    assert not state.timeline.multicams
    client = TestClient(create_app(state))
    result = client.post(
        "/api/export",
        json={"tracks": {k: v.to_json() for k, v in _tracks().items()}, "globals": {}},
    ).json()
    assert result["ok"], result.get("problems")
    assert t("export.flat_no_multicam") in result["warnings"]


def test_defaults_are_available_for_resetting(scratch_xml):
    """Säätimiä on kolmisenkymmentä ja ne periytyvät seuraavaan jaksoon.

    Ilman paluuta yhdestä huonosta arvosta ei pääsisi takaisin.
    """
    from autoraffkat.model import AudioSettings, Globals

    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    data = client.get("/api/defaults").json()
    assert data["globals"] == Globals().to_json()
    assert data["audio"] == AudioSettings().to_json()
    assert data["audio"]["duck_db"] == -9.0


def test_changing_the_plugin_drops_its_saved_state(scratch_xml):
    """Tila on liitännäiskohtainen, joten se ei saa jäädä roikkumaan.

    Se on läpinäkymätön tavujono, jonka vain sen kirjoittanut liitännäinen
    osaa lukea. Toiselle liitännäiselle jätettynä se on parhaassa
    tapauksessa hyödytön ja pahimmassa se asettaa jotain — eikä kumpaakaan
    näkisi mistään.
    """
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    state.settings.audio.plugin_path = "/oli/joskus.vst3"
    state.settings.audio.plugin_state = "dGlsYQ=="
    state.settings.audio.plugin_params = {"mix": 46.3}
    client.post(
        "/api/settings",
        json={"tracks": {}, "globals": {}, "audio": {"enabled": True, "plugin_path": ""}},
    )
    assert state.settings.audio.plugin_state == ""
    assert state.settings.audio.plugin_params == {}


def test_declick_sensitivity_round_trips(scratch_xml):
    """Naksujen herkkyys riippuu puhujasta, joten se on säädettävissä."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    client.post(
        "/api/settings",
        json={
            "tracks": {},
            "globals": {},
            "audio": {"enabled": True, "declick": True, "declick_sensitivity": 0.8},
        },
    )
    assert state.settings.audio.declick_sensitivity == 0.8


def test_tracks_carry_kind_and_file_facts(scratch_xml):
    """Roolitus tarvitsee tiedon siitä mikä tiedosto on kyseessä."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    tracks = {t["key"]: t for t in client.get("/api/state").json()["tracks"]}
    assert tracks["WIDE"]["kind"] == "video"
    assert tracks["host Track1"]["kind"] == "audio"
    # Kesto ja koko lasketaan yhteen kaikista osista.
    assert tracks["WIDE"]["total_duration"] > 0
    assert tracks["WIDE"]["total_size"] > 0


def test_index_versions_its_assets(scratch_xml):
    """Vanha tyyli uuden skriptin kanssa rikkoo asettelun huomaamatta."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    body = TestClient(create_app(state)).get("/").text
    assert "/static/app.js?v=" in body
    assert "/static/style.css?v=" in body


def test_server_messages_follow_the_language(scratch_xml):
    """Suomenkielinen banneri englanninkielisessä käyttöliittymässä on
    huonompi kuin ei käännöstä lainkaan."""
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))

    client.post("/api/language", json={"language": "en"})
    result = client.post("/api/settings", json={"tracks": {}, "globals": {}}).json()
    assert not result["ok"]
    assert any("No speaker has a close-up" in p for p in result["problems"]), result[
        "problems"
    ]

    client.post("/api/language", json={"language": "fi"})
    result = client.post("/api/settings", json={"tracks": {}, "globals": {}}).json()
    assert any("Yhdelläkään puhujalla" in p for p in result["problems"]), result[
        "problems"
    ]


def test_language_is_remembered_and_inherited(fixture_dir, tmp_path):
    """Kieli valitaan kerran, ei joka jaksossa."""
    import shutil

    from autoraffkat import project

    previous = tmp_path / "jakso53.fcpxmld"
    previous.mkdir()
    settings = project.ProjectSettings(
        tracks=dict(_multicam_tracks().items())
    )
    settings.language = "en"
    project.save(str(previous / "Info.fcpxml"), settings)

    current = tmp_path / "jakso54.fcpxmld"
    current.mkdir()
    shutil.copy(fixture_dir / "multicam.fcpxml", current / "Info.fcpxml")
    state = AppState(xml_path=str(current / "Info.fcpxml"))
    state.load()
    assert state.language == "en"


def test_unknown_language_falls_back(scratch_xml):
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    assert (
        client.post("/api/language", json={"language": "kl"}).json()["language"] == "fi"
    )


@needs_ffmpeg
def test_opening_another_xml_does_not_hang(scratch_xml):
    """«Avaa XML…» jumitti, eikä pyyntö palannut koskaan.

    Lukko otettiin kahdesti: reitti otti sen ja ``load()`` otti sen uudestaan,
    eikä ``threading.Lock`` ole rekursiivinen. Käyttöliittymässä se näkyi
    ikuisena «verhokäyrät 0/0» -tilana, koska ``load()`` nollaa edistymisen
    ennen kuin jää odottamaan lukkoa — eli vika näytti äänen laskennalta
    vaikka oli avauksessa.
    """
    first = scratch_xml("sync.fcpxml")
    second = scratch_xml("multicam.fcpxml")
    state = AppState(xml_path=str(first))
    state.load()
    client = TestClient(create_app(state))

    answer = {}

    def call():
        answer["data"] = client.post("/api/open", json={"path": str(second)}).json()

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(timeout=30)
    assert not worker.is_alive(), "avaus jäi jumiin"
    assert answer["data"]["kind"] == "multicam"
    assert state.xml_path == str(second)


def test_export_name_and_note_follow_the_controls(scratch_xml):
    """Säätimet näkyvät sekä tiedostonimessä että viedyssä XML:ssä."""
    source = scratch_xml("multicam.fcpxml")
    state = AppState(xml_path=str(source))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    client = TestClient(create_app(state))

    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": Globals(
            rhythm="hectic", min_shot=1.4, overlap_rule="louder"
        ).to_json(),
    }
    result = client.post("/api/settings", json=payload).json()
    assert result["ok"], result.get("problems")
    # Ruudulla näkyvä polku kertoo mitä vienti kirjoittaa.
    assert result["output_path"].endswith("-cut hectic louder.fcpxml")

    exported = client.post("/api/export", json=payload).json()
    assert exported["ok"]
    assert exported["path"].endswith("-cut hectic louder.fcpxml")
    assert exported["next_path"].endswith("-cut hectic louder v2.fcpxml")

    sequence = ET.parse(exported["path"]).getroot().find(".//sequence")
    assert [c.tag for c in sequence] == ["note", "spine", "metadata"]
    assert "1.4" in sequence.find("note").text
    md = {m.get("key"): m.get("value") for m in sequence.findall("metadata/md")}
    assert md["fi.autoraffkat.rhythm"] == "hectic"
    assert md["fi.autoraffkat.source"] == "multicam.fcpxml"


def test_rhythm_and_hang_reach_the_server(scratch_xml):
    """Säädin joka ei mene läpi jäisi nimeen ja metatietoon väärin.

    Rytmi ja häntä olivat käyttöliittymässä mutta puuttuivat vastaanotosta,
    joten tallennettu arvo pysyi oletuksena riippumatta siitä mitä ruudulla
    valittiin.
    """
    from autoraffkat import project

    source = scratch_xml("multicam.fcpxml")
    state = AppState(xml_path=str(source))
    state.load()
    client = TestClient(create_app(state))
    client.post(
        "/api/settings",
        json={
            "tracks": {},
            "globals": {"rhythm": "mellow", "hang": 1.0, "name_tags": False},
        },
    )
    saved = project.load(str(source)).globals
    assert saved.rhythm == "mellow"
    assert saved.hang == 1.0
    assert saved.name_tags is False
    # Tunnisteet pois: nimi on entisensä.
    assert project.next_output_path(
        str(source), project.name_tag(project.load(str(source)))
    ).endswith("-cut.fcpxml")


def test_reactions_on_without_measurements_warns_instead_of_silence(scratch_xml):
    """Asetus päällä ja lopputuloksessa ei mitään on tämän projektin vika.

    Reaktiokuvat tarvitsevat kuvan mittaukset, ja media voi olla irrotetulla
    levyllä. Vienti onnistuu silti — mutta ilman reaktiokuvia, ja sen on
    näyttävä, koska muuten käyttäjä luulee saaneensa ne.
    """
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    while not state.progress.get("ready"):
        time.sleep(0.05)
    state.settings.globals.reactions = True
    state.settings.tracks = _multicam_tracks()
    client = TestClient(create_app(state))
    exported = client.post("/api/export", json={}).json()
    # Ohitus olisi tässä pahempi kuin virhe: hiljaa ohittuva testi jättää
    # juuri tämän vikaluokan vartioimatta.
    assert exported.get("ok"), exported
    assert exported["reactions"] == 0
    assert any("mitattu" in w or "measured" in w for w in exported["warnings"]), \
        exported["warnings"]


def test_measuring_video_returns_only_its_own_state(scratch_xml):
    """Mittausvastaus ei saa kantaa asetuksia mukanaan.

    Koko tilan palauttaminen houkutteli selainta sijoittamaan sen suoraan
    `state`:en, jolloin juuri liikutettu portti hyppäsi takaisin siihen
    mitä palvelimelle oli ehditty tallentaa. Kapea vastaus tekee siitä
    virheestä mahdottoman.
    """
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    while not state.progress.get("ready"):
        time.sleep(0.05)
    state.settings.tracks = _multicam_tracks()
    client = TestClient(create_app(state))
    body = client.post("/api/video").json()
    assert set(body) == {"video"}, body
    assert "globals" in client.get("/api/state").json()   # /api/state yhä laaja


def test_the_export_warns_when_reactions_are_visible_but_switched_off(scratch_xml):
    """Esikatselu näyttää reaktiokuvat myös kytkin pois — vienti ei kirjoita.

    Se on tahallista: näin näkee mitä päälle laittaminen toisi. Mutta
    silloin lupaus ja lopputulos eroavat, ja ero on kerrottava. Vienti
    ilman varoitusta jättäisi käyttäjän luulemaan saaneensa ne.
    """
    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    while not state.progress.get("ready"):
        time.sleep(0.05)
    state.settings.tracks = _multicam_tracks()
    state.settings.globals.reactions = False
    client = TestClient(create_app(state))
    exported = client.post("/api/export", json={}).json()
    assert exported.get("ok"), exported
    # Kytkin pois: ei reaktioita eikä varoitusta niistä — varoitus kuuluu
    # vain silloin kun ne on pyydetty mutta ei saatu.
    assert exported["reactions"] == 0
    assert not any("reakti" in w.lower() or "reaction" in w.lower()
                   for w in exported["warnings"]), exported["warnings"]


def test_every_global_the_interface_shows_can_be_set(scratch_xml):
    """Vartio koko asetusluokalle, ei yhdelle kentälle.

    ``apply()`` poimii globaalit nimilistalta. Lista unohtui päivittää
    reaktiokuvia lisätessä, ja seuraus oli tämän projektin tyypillisin
    vika: rasti näkyi, liikkui, eikä koskaan päässyt palvelimelle. Joka
    tilan päivitys palautti sen pois ja vienti kirjoitti oikein nolla
    reaktiokuvaa — kaikki toimi paitsi se mitä käyttäjä pyysi.

    Tämä kokeilee jokaista ``Globals``in kenttää: jos kenttä ei mene läpi,
    se on joko lisättävä listalle tai kirjattava tähän syyn kanssa.
    """
    import dataclasses

    # Nämä eivät tule käyttöliittymästä vaan johdetaan muualta.
    NOT_FROM_UI = {
        "rhythm",            # oma esiasetusvalintansa
        "overlap_rule",      # oma valintansa, ei numero
        "long_take_rule",    # sama
        "project_name",      # oma kenttänsä
        "name_tags",         # oma rastinsa
        "reaction_detector",  # tunnistimen nimi, ei säädin
    }

    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    client = TestClient(create_app(state))
    missed = []
    for field in dataclasses.fields(Globals):
        if field.name in NOT_FROM_UI:
            continue
        current = getattr(state.settings.globals, field.name)
        if isinstance(current, bool):
            wanted = not current
        elif isinstance(current, (int, float)):
            wanted = round(float(current) + 0.25, 4) if current is not None else 0.25
        else:
            continue
        client.post("/api/settings", json={
            "tracks": {}, "globals": {field.name: wanted}, "audio": {}})
        if getattr(state.settings.globals, field.name) != wanted:
            missed.append(field.name)
    assert not missed, f"nämä eivät mene käyttöliittymästä läpi: {missed}"


@needs_ffmpeg
def test_opening_a_bundle_reads_the_xml_inside(scratch_xml, tmp_path):
    """«Avaa XML…» antaa ``.fcpxmld``-paketin polun, joka on hakemisto.

    Finderille paketti on tiedosto, joten sekä pywebview'n dialogi että
    Finderin oma valintaikkuna palauttavat paketin eivätkä sen sisältöä.
    Ilman ``pick.resolve``a avaus kaatui virheeseen «[Errno 21] Is a
    directory» eikä mitään latautunut — polku, jonka käyttäjä valitsi, on
    juuri se joka ei kelvannut.
    """
    first = scratch_xml("sync.fcpxml")
    inner = scratch_xml("multicam.fcpxml")
    bundle = tmp_path / "jakso.fcpxmld"
    bundle.mkdir()
    inner.rename(bundle / "Info.fcpxml")

    state = AppState(xml_path=str(first))
    state.load()
    client = TestClient(create_app(state))

    data = client.post("/api/open", json={"path": str(bundle)}).json()

    assert data["kind"] == "multicam"
    assert not state.load_error
    assert state.xml_path == str(bundle / "Info.fcpxml")


@needs_ffmpeg
def test_the_export_fades_the_programme_in_and_out(scratch_xml):
    """Ohjelma alkaa ja päättyy häivytykseen, ``FADE_FLOOR_DB``:stä ja siihen.

    Käyrä kirjoitetaan samoiksi ``<adjust-volume>``-keyframeiksi kuin
    vaimennuskin, joten tämä tarkistaa että pohja tosiaan päätyy tiedostoon:
    ``envelope_at`` palautti kuvan reunalla nollan, jolloin ensimmäinen ja
    viimeinen keyframe olivat 0 dB ja häivytys jäi tekemättä juuri niissä
    kahdessa kohdassa joita varten se on.
    """
    from speechmix.envelopes import FADE_FLOOR_DB

    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    while not state.progress.get("ready"):
        time.sleep(0.05)
    state.settings.tracks = _multicam_tracks()
    client = TestClient(create_app(state))

    exported = client.post("/api/export", json={}).json()
    assert exported.get("ok"), exported
    xml = pathlib.Path(exported["path"]).read_text(encoding="utf-8")

    floor = f'value="{FADE_FLOOR_DB:g}dB"'
    assert floor in xml, "häivytyksen pohjaa ei kirjoitettu lainkaan"
    # Yksi alkuun, yksi loppuun, jokaiselle mikkikulmalle.
    assert xml.count(floor) >= 2, xml.count(floor)


def test_vertical_export_without_measurements_warns(scratch_xml):
    """Pystyvienti päällä ja mitättömät kuvat: vienti syntyy letterboxilla,
    mutta hiljaa — «toimiva vienti joka ei tehnyt mitään» on tämän
    projektin toistuva vikaluokka ja se kerrotaan."""
    from autoraffkat.i18n import t

    source = scratch_xml("multicam.fcpxml")
    state = AppState(xml_path=str(source))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    client = TestClient(create_app(state))

    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": Globals(rhythm="hectic", vertical=True).to_json(),
    }
    # Mittausnappi kytketään pois: taustasäie voisi muuten ehtiä täyttää
    # taulukot viennin välissä ja varoitus vaihtuisi ajasta riippuen.
    def _no_measurement(*a, **k):
        return None

    state.measure_video = _no_measurement
    client = TestClient(create_app(state))

    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": Globals(rhythm="hectic", vertical=True).to_json(),
    }
    client.post("/api/settings", json=payload)
    exported = client.post("/api/export", json=payload).json()
    assert exported["ok"], exported.get("problems")
    assert t("export.vertical_unmeasured") in exported["warnings"]

    # Projekti on silti pysty: muoto ei ole mitä sattuu.
    sequence = ET.parse(exported["path"]).getroot().find(".//sequence")
    root = ET.parse(exported["path"]).getroot()
    fmt = next(f for f in root.iter("format")
               if f.get("id") == sequence.get("format"))
    assert fmt.get("height") == "1920"
    # Ja nimi kertoo variantin.
    assert exported["path"].endswith("vertical.fcpxml") or \
        "vertical" in exported["path"]


@needs_ffmpeg
def test_measuring_for_vertical_also_measures_the_crowd_shots(scratch_xml, monkeypatch):
    """Pystyvienti tarvitsee laajan ja ryhmäkuvien kaikki kasvot.

    Mittausnappi mittasi vain lähikuvat, joten laajaa ja kahden kuvaa ei
    voinut rajata puhujaan ilman erillistä pyyntöä — ja kun lähikuvat oli
    jo mitattu, automaattinen käynnistys ei käynnistynyt lainkaan.
    """
    from autoraffkat.video import analyse

    state = AppState(xml_path=str(scratch_xml()))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    for key, cfg in _tracks().items():
        state.settings.tracks[key] = cfg
    asked = []
    monkeypatch.setattr(analyse, "tables", lambda *a, **k: ({"CLOSE_A.mp4": {}}, {}))
    monkeypatch.setattr(analyse, "crowd_tables",
                        lambda roles, *a, **k: (asked.append(roles.wide_key)
                                                or {"WIDE.mp4": {"frame": []}}, {}))

    state.settings.globals.vertical = False
    state.measure_video()
    assert not asked and not state.crowd_tables

    state.settings.globals.vertical = True
    assert state.video_missing(), "lähikuvat mitattu, joukko ei: mittaus puuttuu"
    state.measure_video()
    assert asked == ["WIDE.mp4"] and "WIDE.mp4" in state.crowd_tables
    assert not state.video_missing()


@needs_ffmpeg
def test_render_draws_the_same_cut_as_the_export(scratch_xml):
    """«Renderöi video»: sama vienti, ja sen viereen MP4 joka näyttää sen.

    Kamerat ovat fixturessa eri värisiä (laaja harmaa, Host laivastonsininen,
    Guest viininpunainen), joten jokaisen kuvan keskiruudun väri kertoo
    näkyykö oikea kamera. Kesto on ohjelman ruutuina täsmälleen, ja Hostin
    puhe kuuluu siellä missä se aikajanalla on.
    """
    import subprocess

    import numpy as np

    state = AppState(xml_path=str(scratch_xml("multicam.fcpxml")))
    state.load()
    for _ in range(200):
        if state.progress.get("ready"):
            break
        time.sleep(0.05)
    client = TestClient(create_app(state))
    payload = {
        "tracks": {k: v.to_json() for k, v in _multicam_tracks().items()},
        "globals": Globals(min_shot=1.5, lead=0.15, confirm=0.3,
                           min_overlap=0.4, vertical=True).to_json(),
    }
    result = client.post("/api/settings", json=payload).json()
    assert result["ok"], result.get("problems")
    exp = client.post("/api/export", json={**payload, "render": True}).json()
    assert exp["ok"], exp.get("problems")
    movie = exp["render"]["path"]
    assert movie.endswith(".mp4") and movie[:-4] == exp["path"][:-7]
    for _ in range(1200):
        if not state.render_progress.get("running"):
            break
        time.sleep(0.1)
    assert not state.render_progress.get("error"), state.render_progress
    assert pathlib.Path(movie).exists()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames,width,height", "-of", "csv=p=0", movie],
        check=True, capture_output=True, text=True).stdout.strip().split(",")
    width, height, frames = map(int, probe)
    assert (width, height) == (1080, 1920)
    program = result["program"]["duration"]
    assert frames == round(program * 25)

    colours = {"Laaja": (128, 128, 128), "Host": (0, 0, 128), "Guest": (128, 0, 0)}
    start = result["program"]["start"]
    for seg in result["segments"]:
        middle = (seg["start"] + seg["end"]) / 2 - start
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{middle:.3f}", "-i", movie,
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            check=True, capture_output=True).stdout
        pixel = np.frombuffer(raw, np.uint8).reshape(1920, 1080, 3)[960, 540]
        want = colours[seg["label"]]
        assert np.abs(pixel.astype(int) - want).max() < 40, (seg, pixel)

    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", movie, "-ac", "1", "-ar", "8000",
         "-f", "f32le", "-"], check=True, capture_output=True).stdout
    audio = np.frombuffer(pcm, np.float32)
    level = lambda a, b: 20 * np.log10(np.sqrt(np.mean(audio[int(a * 8000):int(b * 8000)] ** 2)) + 1e-9)  # noqa: E731
    talk_a, talk_b = SPEECH_A[0]
    assert level(talk_a - start + 0.5, talk_b - start - 0.5) > level(0.2 - start + 0.2, 0.8) + 20
    # Tahdissa ruudun tarkkuudella: puheen alku kuuluu siinä kohdassa missä
    # se aikajanalla on (±1 ruutu = 40 ms).
    frame = 0.005
    blocks = np.sqrt(np.mean(audio[: len(audio) // 40 * 40].reshape(-1, 40) ** 2, axis=1))
    onset = np.flatnonzero(blocks > 10 ** (-30 / 20))[0] * frame
    assert abs(onset - (talk_a - start)) < 0.04, onset
