"""Folder discovery waits for stable files and persists successful fingerprints."""
from automixer import folder_watch


def test_stable_files_only_and_outputs_ignored(tmp_path):
    watch = tmp_path / 'watch'
    watch.mkdir()
    source = watch / 'episode.wav'
    source.write_bytes(b'audio')
    (watch / 'episode-mixed.wav').write_bytes(b'output')
    (watch / 'unfinished.wav.part').write_bytes(b'part')
    tracker = folder_watch.FolderState(tmp_path / 'state.json')
    assert tracker.scan(watch, now=0) == []
    assert tracker.scan(watch, now=1) == []
    assert tracker.scan(watch, now=2) == [source]
    assert tracker.scan(watch, now=3) == []


def test_growth_restarts_stability_and_success_survives_restart(tmp_path):
    folder = tmp_path / 'watch'
    folder.mkdir()
    source = folder / 'episode.wav'
    source.write_bytes(b'a')
    tracker = folder_watch.FolderState(tmp_path / 'state.json')
    tracker.scan(folder, now=0)
    source.write_bytes(b'longer')
    assert tracker.scan(folder, now=2) == []
    assert tracker.scan(folder, now=4) == [source]
    tracker.complete(source)
    fresh = folder_watch.FolderState(tmp_path / 'state.json')
    assert fresh.scan(folder, now=6) == []
    assert fresh.scan(folder, now=8) == []


def test_failure_requires_explicit_retry_and_changed_file_can_run_again(tmp_path):
    source = tmp_path / 'episode.mp3'
    source.write_bytes(b'a')
    tracker = folder_watch.FolderState(tmp_path / 'state.json')
    tracker.scan(tmp_path, now=0)
    assert tracker.scan(tmp_path, now=2) == [source]
    tracker.fail(source)
    assert tracker.scan(tmp_path, now=4) == []
    tracker.retry(source)
    assert tracker.scan(tmp_path, now=6) == [source]
    tracker.complete(source)
    source.write_bytes(b'different')
    assert tracker.scan(tmp_path, now=8) == []
    assert tracker.scan(tmp_path, now=10) == [source]


def test_corrupt_state_fails_closed(tmp_path):
    import pytest
    state = tmp_path / 'state.json'
    for value in ['broken', '[]', '{"version":1,"completed":{"x":[1]}}']:
        state.write_text(value)
        with pytest.raises(folder_watch.WatchError):
            folder_watch.FolderState(state)
        assert state.read_text() == value


def test_failed_history_write_keeps_pending_and_previous_file(tmp_path, monkeypatch):
    import pytest
    source = tmp_path / 'episode.wav'
    source.write_bytes(b'a')
    state = tmp_path / 'state.json'
    tracker = folder_watch.FolderState(state)
    tracker.scan(tmp_path, now=0)
    tracker.scan(tmp_path, now=2)
    def fail(*args):
        raise PermissionError('blocked')
    monkeypatch.setattr(folder_watch.os, 'replace', fail)
    with pytest.raises(folder_watch.WatchError):
        tracker.complete(source)
    assert not state.exists()
    assert tracker.scan(tmp_path, now=4) == []
    assert not list(tmp_path.glob('.automixer-history-*'))


def test_recreated_file_waits_again_and_symlinks_are_not_processed(tmp_path):
    source = tmp_path / 'episode.wav'
    source.write_bytes(b'a')
    (tmp_path / 'linked.wav').symlink_to(source)
    tracker = folder_watch.FolderState(tmp_path / 'state.json')
    tracker.scan(tmp_path, now=0)
    source.unlink()
    assert tracker.scan(tmp_path, now=2) == []
    source.write_bytes(b'b')
    assert tracker.scan(tmp_path, now=3) == []
    assert tracker.scan(tmp_path, now=5) == [source]
