"""App Nap -assertion elinkaari macOS:ssa."""

import sys
from types import SimpleNamespace

import pytest

from autoraffkat import activity


def _fake_foundation(monkeypatch):
    calls = []

    class ProcessInfo:
        def beginActivityWithOptions_reason_(self, options, reason):
            token = object()
            calls.append(("begin", options, reason, token))
            return token

        def endActivity_(self, token):
            calls.append(("end", token))

    process = ProcessInfo()
    foundation = SimpleNamespace(
        NSActivityUserInitiatedAllowingIdleSystemSleep=0x00FFFFFF ^ 0x00100000,
        NSProcessInfo=SimpleNamespace(processInfo=lambda: process),
    )
    monkeypatch.setitem(sys.modules, "Foundation", foundation)
    monkeypatch.setattr(activity.sys, "platform", "darwin")
    return calls


def test_activity_brackets_work_and_allows_system_idle_sleep(monkeypatch):
    calls = _fake_foundation(monkeypatch)

    with activity.prevent_app_nap("Render video"):
        assert [call[0] for call in calls] == ["begin"]

    assert calls[0][1:3] == (
        0x00FFFFFF ^ 0x00100000,
        "Render video",
    )
    assert calls[1] == ("end", calls[0][3])


def test_activity_is_released_when_work_fails(monkeypatch):
    calls = _fake_foundation(monkeypatch)

    with pytest.raises(ValueError, match="failed"):
        with activity.prevent_app_nap("Audio processing"):
            raise ValueError("failed")

    assert [call[0] for call in calls] == ["begin", "end"]


def test_decorated_job_runs_inside_the_app_activity(monkeypatch):
    calls = _fake_foundation(monkeypatch)

    @activity.app_activity("Test job")
    def job():
        assert [call[0] for call in calls] == ["begin"]
        return "finished"

    assert job() == "finished"
    assert [call[0] for call in calls] == ["begin", "end"]


def test_activity_is_a_noop_off_macos(monkeypatch):
    monkeypatch.setattr(activity.sys, "platform", "linux")

    with activity.prevent_app_nap("Portable test"):
        assert True


@pytest.mark.skipif(sys.platform != "darwin", reason="NSProcessInfo on macOS")
def test_native_macos_activity_can_be_started_and_ended():
    with activity.prevent_app_nap("Autoraffkat App Nap test"):
        assert True


def test_long_running_app_jobs_are_guarded():
    from autoraffkat.audio.worker import main as audio_worker_main
    from autoraffkat.server.app import AppState

    assert AppState._analyze.__app_nap_reason__ == "Analyze project audio"
    assert AppState.measure_video.__app_nap_reason__ == "Measure video"
    assert AppState.measure_seating.__app_nap_reason__ == "Measure seating"
    assert AppState.measure_speech.__app_nap_reason__ == "Measure speech"
    assert AppState.measure_audio_preview.__app_nap_reason__ == "Prepare audio preview"
    assert AppState.run_mix.__app_nap_reason__ == "Process audio"
    assert AppState.run_render.__app_nap_reason__ == "Render video"
    assert audio_worker_main.__app_nap_reason__ == "Process audio"
