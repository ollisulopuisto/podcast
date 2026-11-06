"""Raakamediasta muodostetun aloitusaikajanan lukukelpoisuus."""

from fractions import Fraction

import numpy as np
import pytest

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
         "correlation": pytest.approx(1.0), "error": ""},
        {"path": str(second_mic), "name": "Anna", "shift_seconds": 0.18,
         "correlation": pytest.approx(1.0), "error": ""},
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
