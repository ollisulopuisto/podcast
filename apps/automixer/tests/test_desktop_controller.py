"""The desktop stages references until Start; folder jobs record only success."""
from automixer import desktop_controller


class Queue:
    def __init__(self, **kwargs):
        self.event = kwargs['on_event']
        self.added = []
    def add(self, source, **kwargs):
        self.added.append((source, kwargs))
    def close(self):
        pass
    def cancel(self):
        pass


def test_files_are_staged_without_copying_or_starting(tmp_path):
    source = tmp_path / 'one.wav'
    source.write_bytes(b'audio')
    c = desktop_controller.Controller(tmp_path / 'state', queue_factory=Queue)
    c.add_paths([source, source])
    assert c.queue.added == []
    assert c.files == [source]
    c.start()
    assert c.queue.added == [(source, {'target_lufs': -16})]
    assert source.read_bytes() == b'audio'


def test_folder_success_persists_and_failure_does_not(tmp_path):
    folder = tmp_path / 'watch'
    folder.mkdir()
    source = folder / 'one.wav'
    source.write_bytes(b'audio')
    events = []
    c = desktop_controller.Controller(tmp_path / 'state', queue_factory=Queue, on_event=events.append)
    c.add_paths([folder])
    assert c.folder == folder
    c.start(mode="folder")
    c.scan(now=0)
    c.scan(now=2)
    assert c.queue.added == [(source, {'target_lufs': -16})]
    c.queue.event({'source': str(source), 'state': 'done', 'target': str(folder / 'one-mixed.wav')})
    c.close()
    fresh = desktop_controller.Controller(tmp_path / 'state', queue_factory=Queue)
    fresh.add_paths([folder])
    fresh.start(mode="folder")
    fresh.scan(now=4)
    fresh.scan(now=6)
    assert fresh.queue.added == []


def test_commands_have_one_registry_for_menus_and_shortcuts():
    commands = desktop_controller.COMMANDS
    ids = [c.id for c in commands]
    assert len(ids) == len(set(ids))
    assert {'add', 'folder', 'start', 'cancel', 'reveal', 'changes', 'quit'} <= set(ids)
    assert all(c.title_en and c.title_fi and c.menu for c in commands)


def test_symlink_and_explicit_files_mode_do_not_start_folder(tmp_path):
    source = tmp_path / 'one.wav'
    source.touch()
    link = tmp_path / 'link.wav'
    link.symlink_to(source)
    c = desktop_controller.Controller(tmp_path / 'state', queue_factory=Queue)
    c.add_paths([link])
    assert c.files == []
    c.add_paths([tmp_path])
    c.start(mode='files')
    assert not c.watching
