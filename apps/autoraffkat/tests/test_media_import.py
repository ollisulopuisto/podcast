"""Raakamediasta muodostetun aloitusaikajanan lukukelpoisuus."""

from fractions import Fraction

import numpy as np
import pytest
from conftest import needs_ffmpeg

from autoraffkat import media_import
from autoraffkat.finalcut.read import read_fcpxml


def test_source_project_contains_camera_and_mic_tracks(tmp_path, monkeypatch):
    camera = tmp_path / "camera 1.mp4"
    microphone = tmp_path / "Peter.wav"
    camera.touch()
    microphone.touch()
    metadata = {
        str(camera): {
            "duration": 12.0,
            "video": {"width": 1920, "height": 1080, "fps": 25.0},
            "audio": {"channels": 2, "rate": 48000},
        },
        str(microphone): {
            "duration": 10.0,
            "audio": {"channels": 1, "rate": 48000},
        },
    }
    monkeypatch.setattr(media_import.probe, "info", metadata.__getitem__)

    source_path = media_import.write_source_project(
        [str(camera), str(microphone)], {str(microphone): 0.75}
    )

    timeline = read_fcpxml(source_path)
    camera_track, mic_track = timeline.tracks
    camera_item = timeline.track_media(camera_track.key)[0]
    mic_item = timeline.track_media(mic_track.key)[0]
    assert timeline.kind == "project"
    assert camera_track.has_video and camera_track.has_audio
    assert mic_track.has_audio and not mic_track.has_video
    assert camera_item.placements[0].offset == Fraction(0)
    assert mic_item.placements[0].offset == Fraction(3, 4)
    assert mic_item.path == str(microphone)


def test_negative_sync_shift_keeps_all_clip_offsets_nonnegative(tmp_path, monkeypatch):
    camera = tmp_path / "camera.mp4"
    microphone = tmp_path / "mic.wav"
    camera.touch()
    microphone.touch()
    monkeypatch.setattr(
        media_import.probe,
        "info",
        lambda path: {
            "duration": 8.0,
            **(
                {"video": {"width": 1280, "height": 720, "fps": 25.0},
                 "audio": {"channels": 2, "rate": 48000}}
                if path.endswith(".mp4")
                else {"audio": {"channels": 1, "rate": 48000}}
            ),
        },
    )

    source_path = media_import.write_source_project(
        [str(camera), str(microphone)], {str(microphone): -1.25}
    )

    timeline = read_fcpxml(source_path)
    assert min(item.timeline_start for item in timeline.media) == 0
    positions = {item.name: item.timeline_start for item in timeline.media}
    assert positions["camera"] == Fraction(5, 4)
    assert positions["mic"] == 0


def test_source_project_requires_camera_reference_audio(tmp_path, monkeypatch):
    camera = tmp_path / "silent.mp4"
    microphone = tmp_path / "mic.wav"
    camera.touch()
    microphone.touch()
    monkeypatch.setattr(
        media_import.probe,
        "info",
        lambda path: {
            "duration": 8.0,
            **(
                {"video": {"width": 1280, "height": 720, "fps": 25.0}}
                if path.endswith(".mp4")
                else {"audio": {"channels": 1, "rate": 48000}}
            ),
        },
    )

    with pytest.raises(media_import.MediaImportError, match="reference audio"):
        media_import.write_source_project([str(camera), str(microphone)], {})


def test_estimate_media_sync_compares_each_mic_to_selected_camera(
    tmp_path, monkeypatch
):
    camera = tmp_path / "camera.mp4"
    first_mic = tmp_path / "Peter.wav"
    second_mic = tmp_path / "Anna.wav"
    for path in (camera, first_mic, second_mic):
        path.touch()
    monkeypatch.setattr(
        media_import.probe,
        "info",
        lambda path: {
            "duration": 20.0,
            **(
                {"video": {"width": 1280, "height": 720, "fps": 25.0},
                 "audio": {"channels": 2, "rate": 48000}}
                if path.endswith(".mp4")
                else {"audio": {"channels": 1, "rate": 48000}}
            ),
        },
    )
    rng = np.random.default_rng(22)
    reference = rng.normal(size=1000)
    first = np.zeros(1000)
    first[13:] = reference[:-13]
    second = np.zeros(1000)
    second[:-9] = reference[9:]
    envelopes = {
        str(camera): reference,
        str(first_mic): first,
        str(second_mic): second,
    }

    result = media_import.estimate_sync(
        [str(camera), str(first_mic), str(second_mic)],
        reference_path=str(camera),
        envelope_loader=envelopes.__getitem__,
    )

    assert result["reference"] == str(camera)
    assert result["tracks"] == [
        {"path": str(first_mic), "name": "Peter", "shift_seconds": -0.26,
         "correlation": pytest.approx(1.0), "error": "", "window_expanded": False},
        {"path": str(second_mic), "name": "Anna", "shift_seconds": 0.18,
         "correlation": pytest.approx(1.0), "error": "", "window_expanded": False},
    ]


def test_estimate_media_sync_reports_progress_for_reference_and_each_mic(
    tmp_path, monkeypatch
):
    camera = tmp_path / "camera.mp4"
    microphone = tmp_path / "Peter.wav"
    camera.touch()
    microphone.touch()
    monkeypatch.setattr(
        media_import.probe,
        "info",
        lambda path: {
            "duration": 20.0,
            **(
                {"video": {"width": 1280, "height": 720, "fps": 25.0},
                 "audio": {"channels": 2, "rate": 48000}}
                if path.endswith(".mp4")
                else {"audio": {"channels": 1, "rate": 48000}}
            ),
        },
    )
    progress = []
    envelope = np.random.default_rng(8).normal(size=1000)

    media_import.estimate_sync(
        [str(camera), str(microphone)],
        envelope_loader=lambda _path: envelope,
        progress=lambda name, fraction: progress.append((name, fraction)),
    )

    assert progress == [("camera", 0.5), ("Peter", 1.0)]


def test_estimate_media_sync_also_aligns_other_camera_audio(tmp_path, monkeypatch):
    reference = tmp_path / "cam1.mp4"
    second_camera = tmp_path / "cam2.mp4"
    microphone = tmp_path / "Peter.wav"
    for path in (reference, second_camera, microphone):
        path.touch()
    monkeypatch.setattr(
        media_import.probe,
        "info",
        lambda path: {
            "duration": 20.0,
            **(
                {"video": {"width": 1280, "height": 720, "fps": 25.0},
                 "audio": {"channels": 2, "rate": 48000}}
                if path.endswith(".mp4")
                else {"audio": {"channels": 1, "rate": 48000}}
            ),
        },
    )
    rng = np.random.default_rng(77)
    envelope = rng.normal(size=1000)
    delayed = np.zeros(1000)
    delayed[5:] = envelope[:-5]
    results = media_import.estimate_sync(
        [str(reference), str(second_camera), str(microphone)],
        envelope_loader=lambda path: delayed if path == str(second_camera) else envelope,
    )

    assert [item["path"] for item in results["tracks"]] == [str(second_camera), str(microphone)]
    assert results["tracks"][0]["shift_seconds"] == -0.1


def _probe_durations(monkeypatch, durations):
    """Ffprobe-vale: pituudet sekunteina, mp4:llä kuvaa."""
    monkeypatch.setattr(
        media_import.probe,
        "info",
        lambda path: {
            "duration": durations[path],
            **(
                {"video": {"width": 1280, "height": 720, "fps": 25.0},
                 "audio": {"channels": 2, "rate": 48000}}
                if path.endswith(".mp4")
                else {"audio": {"channels": 1, "rate": 48000}}
            ),
        },
    )


def _long_sync_pair(tmp_path, monkeypatch, shift_samples, mic_samples=None, noise=0.0):
    """Kamera + mikki, jossa mikin signaali on kamerasta viivästetty kopio."""
    camera = tmp_path / "camera.mp4"
    microphone = tmp_path / "Peter.wav"
    camera.touch()
    microphone.touch()
    total = 35000  # 700 s verhoja 0.02 s hopilla
    _probe_durations(monkeypatch, {str(camera): 700.0, str(microphone): 700.0})
    rng = np.random.default_rng(5)
    reference = rng.normal(size=total)
    mic = rng.normal(size=total) * noise if noise else np.zeros(total)
    take = (mic_samples or total) - shift_samples
    mic[shift_samples:shift_samples + take] = reference[:take]
    return str(camera), str(microphone), {str(camera): reference, str(microphone): mic}


def test_estimate_sync_auto_expands_past_default_window(tmp_path, monkeypatch):
    # Siirto 400 s: oletusikkuna ±300 s ei riitä, auto laajentaa koko aineistoon.
    camera, microphone, envelopes = _long_sync_pair(tmp_path, monkeypatch, 20000)

    result = media_import.estimate_sync(
        [camera, microphone],
        reference_path=camera,
        envelope_loader=envelopes.__getitem__,
    )

    track = result["tracks"][0]
    assert track["shift_seconds"] == pytest.approx(-400.0, abs=0.05)
    assert track["correlation"] == pytest.approx(1.0)
    assert track["window_expanded"] is True


def test_estimate_sync_fixed_window_does_not_expand(tmp_path, monkeypatch):
    camera, microphone, envelopes = _long_sync_pair(tmp_path, monkeypatch, 20000)

    result = media_import.estimate_sync(
        [camera, microphone],
        reference_path=camera,
        envelope_loader=envelopes.__getitem__,
        window=300,
    )

    track = result["tracks"][0]
    assert track["window_expanded"] is False
    assert (
        track["shift_seconds"] is None
        or track["shift_seconds"] != pytest.approx(-400.0, abs=0.05)
    )


def test_estimate_sync_full_window_searches_everything(tmp_path, monkeypatch):
    camera, microphone, envelopes = _long_sync_pair(tmp_path, monkeypatch, 20000)

    result = media_import.estimate_sync(
        [camera, microphone],
        reference_path=camera,
        envelope_loader=envelopes.__getitem__,
        window="full",
    )

    track = result["tracks"][0]
    assert track["shift_seconds"] == pytest.approx(-400.0, abs=0.05)
    assert track["window_expanded"] is False


def test_estimate_sync_numeric_window_finds_without_expansion(tmp_path, monkeypatch):
    camera, microphone, envelopes = _long_sync_pair(tmp_path, monkeypatch, 20000)

    result = media_import.estimate_sync(
        [camera, microphone],
        reference_path=camera,
        envelope_loader=envelopes.__getitem__,
        window=500,
    )

    track = result["tracks"][0]
    assert track["shift_seconds"] == pytest.approx(-400.0, abs=0.05)
    assert track["window_expanded"] is False


def test_estimate_sync_auto_accepts_weak_match_only_after_expansion(tmp_path, monkeypatch):
    # Heikko (r<0.4) mutta oikea osuma 400 s kohdalla: kapea ikkuna ei löydä
    # mitään, laajennus hyväksyy parhaan löytämänsä vaikka se jää alle kynnyksen.
    camera, microphone, envelopes = _long_sync_pair(tmp_path, monkeypatch, 20000, noise=2.6)
    mic = envelopes[microphone]
    rng = np.random.default_rng(9)
    reference = envelopes[camera]
    mic[20000:] = reference[:15000] + rng.normal(size=15000) * 2.6

    result = media_import.estimate_sync(
        [camera, microphone],
        reference_path=camera,
        envelope_loader=envelopes.__getitem__,
    )

    track = result["tracks"][0]
    assert track["shift_seconds"] == pytest.approx(-400.0, abs=0.05)
    assert track["correlation"] < media_import.SYNC_AUTO_THRESHOLD
    assert track["window_expanded"] is True


def test_estimate_sync_rejects_nonpositive_window(tmp_path, monkeypatch):
    camera, microphone, envelopes = _long_sync_pair(tmp_path, monkeypatch, 20000)

    with pytest.raises(media_import.MediaImportError):
        media_import.estimate_sync(
            [camera, microphone],
            reference_path=camera,
            envelope_loader=envelopes.__getitem__,
            window=0,
        )


def test_pick_preview_spans_finds_shared_and_solo_moments(tmp_path):
    # Viite aktiivinen 16-36 s, raita (siirto +1 s) aktiivinen viiteaikana
    # 1-7 s yksinään ja 16-36 s yhdessä viitteen kanssa.
    n = 2000  # 40 s
    reference = np.full(n, 0.01)
    reference[800:1800] = 1.0
    mic = np.full(n, 0.01)
    mic[0:300] = 1.0      # viiteaika 1-7 s (siirto +1 s = 50 näytettä)
    mic[750:1750] = 1.0   # viiteaika 16-36 s
    envelopes = {"camera.mp4": reference, "Peter.wav": mic}
    tracks = [{"path": "Peter.wav", "shift_seconds": 1.0}]

    spans = media_import.pick_preview_spans(envelopes, "camera.mp4", tracks)

    # Kaikkien yhteinen pätkä (10 s) mahtuu kokonaan yhteisalueelle.
    assert 16.0 - 0.5 <= spans["all"]
    assert spans["all"] + spans["all_seconds"] <= 36.0 + 0.5
    # Kaiutinraadan pätkä valitsee soolo-alueen alun (n. 1 s).
    assert spans["per_speaker"]["Peter.wav"] == pytest.approx(1.0, abs=0.5)


def test_pick_preview_spans_without_activity_falls_back_to_middle(tmp_path):
    n = 1000
    silence = np.zeros(n)
    envelopes = {"camera.mp4": silence, "Peter.wav": silence.copy()}
    tracks = [{"path": "Peter.wav", "shift_seconds": 0.0}]

    spans = media_import.pick_preview_spans(envelopes, "camera.mp4", tracks)

    assert spans["all"] == pytest.approx(5.0)


def test_preview_cache_key_changes_with_shifts(tmp_path):
    first = media_import.preview_cache_key(["a.wav"], "a.wav", {"a.wav": 1.0}, "all", "", 8.0, 10.0)
    second = media_import.preview_cache_key(["a.wav"], "a.wav", {"a.wav": 1.5}, "all", "", 8.0, 10.0)
    again = media_import.preview_cache_key(["a.wav"], "a.wav", {"a.wav": 1.0}, "all", "", 8.0, 10.0)

    assert first != second
    assert first == again


def test_best_window_includes_boundary_windows():
    # Aktiivisuus täysin ensimmäisessä tai viimeisessä mahdollisessa
    # ikkunassa: molempien pitää olla ehdokkaina oikealla summalla.
    width = 5
    first = np.zeros(20)
    first[:width] = 1.0
    last = np.zeros(20)
    last[-width:] = 1.0

    total_first, start_first = media_import._best_window(np.cumsum(first), 20, width)
    total_last, start_last = media_import._best_window(np.cumsum(last), 20, width)

    assert (total_first, start_first) == (5.0, 0)
    assert (total_last, start_last) == (5.0, 15)




@needs_ffmpeg
def test_render_preview_clip_stacks_camera_and_audio_only(tmp_path):
    # 16:9-kamera + pelkkä ääniraita: sarakkeiden korkeudet poikkeavat,
    # joten hstack vaatii normalisoinnin. (Regressio Devin-katselmoinnista.)
    import subprocess

    camera = tmp_path / "camera.mp4"
    microphone = tmp_path / "Peter.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=8:size=640x360:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
         "-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(camera)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=550:duration=8", str(microphone)],
        check=True, capture_output=True,
    )
    out = tmp_path / "preview.mp4"

    media_import.render_preview_clip(
        [str(camera), str(microphone)], str(camera),
        {str(camera): 0.0, str(microphone): 0.0}, 1.0, 3.0, str(out),
    )

    assert out.exists() and out.stat().st_size > 0


def test_preview_cache_key_covers_media_identity_and_layout(tmp_path):
    # Sama polku, uusi tiedosto: aikaleima muuttuu -> uusi avain.
    # Viitteen vaihto tai järjestyksen muutos -> uusi avain.
    base = media_import.preview_cache_key(
        ["cam.mp4", "mic.wav"], "cam.mp4", {"mic.wav": 1.0}, "all", "", 8.0, 10.0,
        stamps={"cam.mp4": [100, 111], "mic.wav": [50, 222]},
    )
    replaced = media_import.preview_cache_key(
        ["cam.mp4", "mic.wav"], "cam.mp4", {"mic.wav": 1.0}, "all", "", 8.0, 10.0,
        stamps={"cam.mp4": [100, 111], "mic.wav": [50, 333]},
    )
    swapped_reference = media_import.preview_cache_key(
        ["mic.wav", "cam.mp4"], "mic.wav", {"mic.wav": 1.0}, "all", "", 8.0, 10.0,
        stamps={"cam.mp4": [100, 111], "mic.wav": [50, 222]},
    )

    assert base != replaced
    assert base != swapped_reference
