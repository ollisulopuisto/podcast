"""Puhe kuvasta: huulten liikkeestä verhokäyrä, joka kulkee ruudukon läpi kuin mikki.

Tunnistin ja purku ovat tynkiä: sopimus on se mitä niiltä luetaan, ei se
että Vision on koneella. Oikea mittaus on kirjattu moduulin dokumenttiin.
"""

import threading
import time
from pathlib import Path

import numpy as np

from autoraffkat.model import HOP
from autoraffkat.video import speech
from speechmix.rms import FLOOR_DB


class FakeDetector:
    """Palauttaa suun aukon jonon mukaan, yksi arvo per kuva."""

    name = "tynka"
    version = 1

    def __init__(self, mouths, delay=0.0):
        self.delay = delay
        self.mouths = list(mouths)
        self.i = 0
        self.threads = set()

    def measure_all(self, path):
        self.threads.add(threading.get_ident())
        if self.delay:
            time.sleep(self.delay)  # kuva vie aikaa: muuten yksi säie ehtii tehdä kaiken itse
        # Kuvan järjestys tiedostonimestä: mittaus voi tulla säikeistä missä
        # järjestyksessä tahansa.
        index = int(Path(path).stem)  # Windowsin polku ei erotu merkillä «/»
        m = self.mouths[index % len(self.mouths)]
        self.i += 1
        if m is None:
            return []
        return [{"x": 0, "y": 0, "w": 0.2, "h": 0.2, "mouth": m},
                {"x": 0, "y": 0, "w": 0.05, "h": 0.05, "mouth": 99.0}]  # pienempi: ei valita


def frames_of(n):
    def extract(path, start, dur, into):
        files = []
        for k in range(n):
            f = into / f"{k:06d}.jpg"
            f.write_bytes(b"x")
            files.append(f)
        return files
    return extract


def test_the_largest_face_is_the_one_measured(tmp_path):
    det = FakeDetector([0.1, 0.2, None, 0.3])
    series = speech.mouth_series("x.mp4", 0.0, 0.4, det, extract=frames_of(4))
    assert np.allclose(series[[0, 1, 3]], [0.1, 0.2, 0.3]) and np.isnan(series[2])


def test_a_still_mouth_is_quiet_and_a_moving_one_is_loud():
    still = speech.motion(np.full(50, 0.3))
    talking = speech.motion(0.3 + 0.2 * np.sin(np.arange(50) * 1.5))
    assert still.max() < 1e-9 and talking.mean() > 0.05
    # kasvon puuttuminen ei ole liikettä
    assert speech.motion(np.array([0.3, np.nan, np.nan, 0.3])).max() < 0.2


def test_levels_share_one_scale_across_the_parts_of_a_file():
    """Hiljainen osa ei saa normalisoitua omaan huippuunsa ja näyttää yhtä kovalta."""
    busy = np.full(100, 1.0)
    quiet = np.full(100, 0.05)
    a, b = speech.levels_db([busy, quiet])
    assert a.mean() > b.mean() + 15


def test_the_envelope_is_in_file_time_at_the_grid_step(tmp_path):
    ranges = [(2.0, 1.0)]
    env = speech.to_envelope(ranges, [np.full(10, -6.0)])
    assert env.dtype == np.float32
    assert env[int(2.5 / HOP)] == -6.0
    assert env[int(0.5 / HOP)] == FLOOR_DB  # mittaamaton


def test_the_result_is_cached_and_the_detector_is_in_the_key(tmp_path):
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x" * 10)
    cache = tmp_path / "c"
    cache.mkdir()
    det = FakeDetector([0.1, 0.4] * 20)
    first = speech.envelope(str(clip), [(0.0, 2.0)], det, extract=frames_of(20), cache=cache)
    seen = det.i
    again = speech.envelope(str(clip), [(0.0, 2.0)], det, extract=frames_of(20), cache=cache)
    assert det.i == seen and np.array_equal(first, again)  # ei uutta mittausta
    other = FakeDetector([0.1, 0.4] * 20)
    other.version = 2
    speech.envelope(str(clip), [(0.0, 2.0)], other, extract=frames_of(20), cache=cache)
    assert other.i > 0  # uusi tunnistin = uusi mittaus


def test_a_speaking_face_goes_over_the_lane_threshold_and_a_still_one_does_not(tmp_path):
    """Tämä on koko tarkoitus: sama ``grid.lane`` kuin mikillä, kynnys pohjan päällä."""
    from speechmix import grid as grid_lib

    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x" * 10)
    # 10 s: 0-5 s hiljaa (suu ei liiku), 5-10 s puhetta
    mouths = [0.3] * 50 + [0.3 + 0.25 * (i % 2) for i in range(50)]
    det = FakeDetector(mouths)
    env = speech.envelope(str(clip), [(0.0, 10.0)], det, extract=frames_of(100), cache=tmp_path)
    db = grid_lib.smooth(env, 0.1, hop_sec=HOP)
    floor = grid_lib.noise_floor(db, None, grid_lib.NOISE_PERCENTILE)
    lane = grid_lib.lane("A", [(db, None, floor, speech.VISUAL_MARGIN_DB, 0.0)])
    quiet, talk = lane.on[int(1 / HOP):int(4 / HOP)], lane.on[int(6 / HOP):int(9 / HOP)]
    assert quiet.mean() < 0.05 and talk.mean() > 0.9


# ------------------------------------------------------------ roolit ja ruudukko

from fractions import Fraction  # noqa: E402

from autoraffkat.analysis import Analysis, build_grid, resolve_roles  # noqa: E402
from autoraffkat.fcpxml.read import Timeline, Track  # noqa: E402
from autoraffkat.model import (  # noqa: E402
    ROLE_CLOSE,
    ROLE_MIC,
    ROLE_SHOT,
    ROLE_WIDE,
    MediaItem,
    Placement,
    TrackConfig,
)


def _item(key, seconds=40, audio=False):
    return MediaItem(
        key=key, name=key, path=f"/x/{key}.mp4", src="", asset_start=Fraction(0),
        asset_duration=Fraction(seconds), has_video=not audio, has_audio=audio,
        placements=[Placement(offset=Fraction(0), start=Fraction(0), duration=Fraction(seconds))],
    )


def _scene():
    """Kaksi puhujaa: A:lla mikki ja lähikuva, B:llä vain lähikuva. Laaja kuva rajaa."""
    media = [_item("WIDE"), _item("CAM A"), _item("CAM B"), _item("MIC A", audio=True)]
    timeline = Timeline(
        media=media, frame_duration=Fraction(1, 25), kind="project", name="t",
        tracks=[Track(key=m.key, name=m.key, media_keys=[m.key]) for m in media],
    )
    tracks = {
        "WIDE": TrackConfig(role=ROLE_WIDE),
        "CAM A": TrackConfig(role=ROLE_CLOSE, speaker="A"),
        "CAM B": TrackConfig(role=ROLE_CLOSE, speaker="B"),
        "MIC A": TrackConfig(role=ROLE_MIC, speaker="A"),
    }
    return timeline, tracks


def test_a_speaker_with_a_close_up_but_no_mic_is_a_visual_speaker():
    timeline, tracks = _scene()
    roles = resolve_roles(timeline, tracks)
    assert roles.visual_speakers == ["B"]
    assert not any("B" in p for p in roles.problems), roles.problems  # ei enää «ei mikkiä»
    off = resolve_roles(timeline, tracks, visual=False)
    assert off.visual_speakers == [] and any("B" in p for p in off.problems)


def test_no_mics_at_all_is_fine_when_the_close_ups_can_speak():
    timeline, tracks = _scene()
    del tracks["MIC A"]
    tracks["CAM A"] = TrackConfig(role=ROLE_CLOSE, speaker="A")
    roles = resolve_roles(timeline, tracks)
    assert roles.visual_speakers == ["A", "B"]
    assert not any("mic" in p.lower() or "mikki" in p.lower() for p in roles.problems), roles.problems


def test_the_grid_gets_a_lane_from_the_visual_envelope():
    timeline, tracks = _scene()
    n = 40
    audio = np.full(int(n / HOP) + 1, -80.0, dtype=np.float32)
    audio[int(22 / HOP):int(32 / HOP)] = -20.0        # A puhuu 22-32 s
    visual = np.full(int(n / HOP) + 1, -30.0, dtype=np.float32)
    visual[int(6 / HOP):int(16 / HOP)] = 0.0          # B:n huulet liikkuvat 6-16 s
    analysis = Analysis(timeline=timeline, envelopes={
        "MIC A": audio, "CAM B" + speech.SUFFIX: visual})
    grid, _, _ = build_grid(analysis, tracks)
    lanes = {lane.name: lane for lane in grid.speakers}
    assert set(lanes) == {"A", "B"}
    assert lanes["B"].on[int(10 / HOP)] and not lanes["B"].on[int(27 / HOP)]
    assert lanes["A"].on[int(27 / HOP)] and not lanes["A"].on[int(10 / HOP)]
    assert lanes["B"].close_key == "CAM B"


def test_visual_speech_uses_all_singleton_shots_for_a_speaker():
    timeline, tracks = _scene()
    alternate = _item("CAM B ALT")
    timeline.media.append(alternate)
    timeline.tracks.append(Track(key=alternate.key, name=alternate.key,
                                 media_keys=[alternate.key]))
    tracks[alternate.key] = TrackConfig(role=ROLE_SHOT, covers=["B"])
    n = int(40 / HOP) + 1
    audio = np.full(n, -80.0, dtype=np.float32)
    audio[int(22 / HOP):int(32 / HOP)] = -20.0
    silent = np.full(n, -30.0, dtype=np.float32)
    alternate_voice = silent.copy()
    alternate_voice[int(6 / HOP):int(16 / HOP)] = 0.0
    analysis = Analysis(timeline=timeline, envelopes={
        "MIC A": audio,
        "CAM B" + speech.SUFFIX: silent,
        "CAM B ALT" + speech.SUFFIX: alternate_voice,
    })
    grid, _, _ = build_grid(analysis, tracks)
    lane = next(lane for lane in grid.speakers if lane.name == "B")
    assert lane.on[int(10 / HOP)]


def test_without_a_visual_envelope_the_speaker_has_no_lane_yet():
    """Mittaamaton kuva ei ole hiljaisuus: kaistaa ei tehdä ennen mittausta."""
    timeline, tracks = _scene()
    audio = np.full(int(40 / HOP) + 1, -80.0, dtype=np.float32)
    grid, _, _ = build_grid(Analysis(timeline=timeline, envelopes={"MIC A": audio}), tracks)
    assert [lane.name for lane in grid.speakers] == ["A"]


# ------------------------------------------------------------------ palvelin


def _state(monkeypatch, tmp_path):
    from autoraffkat.server.app import AppState

    timeline, tracks = _scene()
    audio = np.full(int(40 / HOP) + 1, -80.0, dtype=np.float32)
    audio[int(22 / HOP):int(32 / HOP)] = -20.0        # A puhuu 22-32 s
    state = AppState(xml_path=str(tmp_path / "j.fcpxml"))
    state.timeline = timeline
    state.analysis = Analysis(timeline=timeline, envelopes={"MIC A": audio})
    state.settings.tracks = tracks
    return state


def test_the_server_measures_speech_for_speakers_without_a_mic(monkeypatch, tmp_path):
    state = _state(monkeypatch, tmp_path)
    assert state.speech_missing() == ["B"]
    calls = []

    def fake_envelope(path, ranges, detector, progress=None, **_):
        calls.append((path, ranges))
        if progress:
            progress(1.0)
        env = np.full(int(40 / HOP) + 1, -30.0, dtype=np.float32)
        env[int(6 / HOP):int(16 / HOP)] = 0.0            # B puhuu 6-16 s
        return env

    monkeypatch.setattr(speech, "envelope", fake_envelope)
    monkeypatch.setattr("autoraffkat.video.detect.load", lambda name: object())
    state.measure_speech()
    assert calls == [("/x/CAM B.mp4", [(0.0, 40.0)])]
    assert state.speech_missing() == []
    assert "CAM B" + speech.SUFFIX in state.analysis.envelopes
    result = state.compute()
    assert result["ok"], result["problems"]
    labels = {seg["label"] for seg in result["segments"]}
    assert {"A", "B"} <= labels, labels  # B saa omat leikkauksensa kuvasta


def test_decisions_wait_for_the_measurement_and_say_why(monkeypatch, tmp_path):
    """Ilman B:n kaistaa päätös olisi leikkaus vain A:sta: hiljaa väärä."""
    state = _state(monkeypatch, tmp_path)
    result = state.compute()
    assert result["ok"] is False
    assert any("B" in p for p in result["problems"]), result["problems"]


def test_a_failed_measurement_is_reported_not_swallowed(monkeypatch, tmp_path):
    state = _state(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("purku epäonnistui")

    monkeypatch.setattr(speech, "envelope", boom)
    monkeypatch.setattr("autoraffkat.video.detect.load", lambda name: object())
    state.measure_speech()
    assert state.speech_errors and "purku" in " ".join(state.speech_errors.values())
    result = state.compute()
    assert result["ok"] is False and any("purku" in p for p in result["problems"])


def test_a_long_range_is_decoded_in_chunks_with_the_same_result(tmp_path):
    """Tunnin lähikuva on 36 000 ruutua: yhtenä palana ne kaikki ovat levyllä
    yhtä aikaa eikä edistymistä näy. Pala on enintään ``CHUNK_SECONDS``."""
    clip = tmp_path / "a.mp4"
    clip.write_bytes(b"x" * 10)
    spans = []

    def extract(path, start, dur, into):
        spans.append((start, dur))
        n = int(dur * speech.FPS)
        files = []
        for k in range(n):
            f = into / f"{k:06d}.jpg"
            f.write_bytes(b"x")
            files.append(f)
        return files

    mouths = [0.3 + 0.2 * (i % 2) for i in range(10_000)]
    reported = []
    det = FakeDetector(mouths)
    env = speech.envelope(str(clip), [(0.0, 2.5 * speech.CHUNK_SECONDS)], det,
                          progress=reported.append, extract=extract, cache=tmp_path)
    assert [round(d, 1) for _, d in spans] == [speech.CHUNK_SECONDS, speech.CHUNK_SECONDS,
                                               0.5 * speech.CHUNK_SECONDS]
    assert spans[1][0] == speech.CHUNK_SECONDS
    assert len(reported) == 3 and reported[-1] == 1.0 and reported == sorted(reported)
    assert env.size > 0


def test_a_mixdown_with_no_mic_roles_is_passed_through_to_the_export(monkeypatch, tmp_path):
    """pp 57: ei mikkirooleja, ainoa ääniraita käyttämätön. Vienti ilman ääntä on vika."""
    from autoraffkat.server.app import _passthrough_tracks

    state = _state(monkeypatch, tmp_path)
    state.settings.tracks["MIC A"] = TrackConfig(role="unused")
    assert _passthrough_tracks(state, []) == ["MIC A"]
    assert _passthrough_tracks(state, [("MIC A", "A")]) == []        # roolit päättävät
    state.settings.tracks["MIC A"] = TrackConfig(role=ROLE_MIC, speaker="A")
    assert _passthrough_tracks(state, []) == []                       # roolitettu mikki ei ole läpivienti


def test_the_render_plays_the_passed_through_track_too(monkeypatch, tmp_path):
    """Vienti toi läpivientiraidan äänen mutta oma MP4-renderi ei: ``render_job``
    rakensi äänilähteet vain mikeistä ja tilaäänestä, joten MP4 oli mykkä."""
    state = _state(monkeypatch, tmp_path)
    state.settings.tracks["MIC A"] = TrackConfig(role="unused")
    job = state.render_job([], [], {}, [], {}, 0, 10, str(tmp_path / "x.mp4"),
                           passthrough=["MIC A"])
    assert len(job["sources"]) == 1
    assert job["sources"][0].path.endswith(
        state.timeline.track_media("MIC A")[0].path.split("/")[-1])


# ------------------------------------------------------------ käyttöliittymän rajapinta


def test_visual_speech_is_a_global_that_is_on_by_default(monkeypatch, tmp_path):
    from autoraffkat.model import Globals

    assert Globals().visual_speech is True
    assert Globals.from_json({"visual_speech": False}).visual_speech is False
    state = _state(monkeypatch, tmp_path)
    assert state.speech_missing() == ["B"]
    state.apply({"globals": {"visual_speech": False}})
    assert state.settings.globals.visual_speech is False
    assert state.speech_missing() == []          # ei mitattavaa: puhuja on mikitön
    problems = state.compute()["problems"]
    assert any("B" in p for p in problems), problems   # kuten ennen: puhujalta puuttuu mikki


def test_the_state_tells_the_interface_who_is_read_from_the_picture(monkeypatch, tmp_path):
    from autoraffkat.server.app import _state_json

    state = _state(monkeypatch, tmp_path)
    speech_state = _state_json(state)["speech"]
    assert speech_state["candidates"] == ["B"]        # on mikitön, lähikuva löytyy
    assert speech_state["missing"] == ["B"] and speech_state["running"] is False
    state.apply({"globals": {"visual_speech": False}})
    off = _state_json(state)["speech"]
    assert off["candidates"] == ["B"] and off["missing"] == []   # rivi pysyy, jotta sen saa takaisin päälle


def test_the_speech_endpoint_starts_the_measurement_and_a_retry_clears_the_error(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from autoraffkat.server.app import create_app

    state = _state(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(type(state), "measure_speech", lambda self: started.append(1))
    state.speech_errors = {"B": "purku epäonnistui"}
    client = TestClient(create_app(state))
    answer = client.post("/api/speech").json()
    assert answer["speech"]["errors"] == {}            # uusinta tyhjentää vanhan virheen
    import time
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert started


def test_the_decision_carries_the_edits_and_the_speech_state(monkeypatch, tmp_path):
    state = _state(monkeypatch, tmp_path)
    env = np.full(int(40 / HOP) + 1, -30.0, dtype=np.float32)
    env[int(6 / HOP):int(16 / HOP)] = 0.0
    state.analysis.envelopes["CAM B" + speech.SUFFIX] = env
    result = state.compute()
    assert result["ok"] and result["edits"] == []
    assert result["speech"]["missing"] == []
    waiting = _state(monkeypatch, tmp_path).compute()
    assert waiting["ok"] is False and waiting["speech"]["missing"] == ["B"]


def test_frames_are_measured_in_threads_and_come_back_in_order(tmp_path):
    """Vision on 3,2x nopeampi neljällä säikeellä (63 -> 201 kuvaa/s, mitattu),
    mutta tulos on järjestyksessä: kuva ja aikaleima pariutuvat indeksillä."""
    mouths = [0.1 * k for k in range(1, 41)]
    det = FakeDetector(mouths, delay=0.003)
    series = speech.mouth_series("x.mp4", 0.0, 4.0, det, extract=frames_of(40))
    assert np.allclose(series, mouths)
    assert len(det.threads) > 1, "kuvat mitattiin yhdellä säikeellä"


def test_the_number_of_vision_threads_follows_the_cores(monkeypatch):
    """Ei vakio neljä: puolet koneen ytimistä (sama sääntö kuin verhokäyrillä,
    ``analysis.ENVELOPE_WORKERS``), vähintään kaksi, jotta kone jaksaa vielä
    käyttöliittymän ja purun."""
    monkeypatch.setattr(speech.os, "cpu_count", lambda: 16)
    assert speech.vision_workers() == 8
    monkeypatch.setattr(speech.os, "cpu_count", lambda: 2)
    assert speech.vision_workers() == 2
    monkeypatch.setattr(speech.os, "cpu_count", lambda: None)
    assert speech.vision_workers() == 2


def test_mouth_series_uses_the_core_based_count_by_default(monkeypatch):
    monkeypatch.setattr(speech.os, "cpu_count", lambda: 12)
    det = FakeDetector([0.1 * k for k in range(1, 61)], delay=0.003)
    speech.mouth_series("x.mp4", 0.0, 6.0, det, extract=frames_of(60))
    assert 2 <= len(det.threads) <= 6
