"""Portable role-command tests, using the real Textual dispatch and widgets."""
import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Button, Input, SelectionList

from automixer.keys import KEYS_BINDINGS, KeysHelp
from automixer.roles import ROLE_BINDINGS, TrackRoleActions


class RoleApp(TrackRoleActions, KeysHelp, App):
    BINDINGS = [*KEYS_BINDINGS, *ROLE_BINDINGS]

    def __init__(self):
        super().__init__()
        self.config = {"tracks": [{"path": "/a.wav", "name": "a.wav", "type": "speech"}]}
        self.updates = 0

    def compose(self) -> ComposeResult:
        yield SelectionList(("a", "/a.wav", True), ("b", "/b.wav", True), id="track_selection_list")
        yield Input(id="typing")
        yield Button("Music", id="mark_music_btn")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "mark_music_btn":
            self.action_mark_music()

    def update_track_roles_display(self):
        self.updates += 1


def test_keyboard_and_shared_button_action_match_for_multi_selection():
    async def scenario():
        keyboard = RoleApp()
        async with keyboard.run_test() as pilot:
            keyboard.query_one(SelectionList).focus()
            await pilot.press("m")
            assert keyboard.updates == 1
            music = list(keyboard.config["tracks"])
            await pilot.press("s")
            assert {t["type"] for t in keyboard.config["tracks"]} == {"speech"}
        button = RoleApp()
        async with button.run_test() as pilot:
            await pilot.click("#mark_music_btn")
            assert music == button.config["tracks"]
            assert len(music) == 2
            assert {t["type"] for t in music} == {"music"}
    asyncio.run(scenario())


def test_typing_and_empty_selection_do_not_assign_roles():
    async def scenario():
        app = RoleApp()
        async with app.run_test() as pilot:
            original = list(app.config["tracks"])
            field = app.query_one(Input)
            field.focus()
            await pilot.press("m", "s")
            assert field.value == "ms"
            assert app.config["tracks"] == original
            assert app.updates == 0
            selection = app.query_one(SelectionList)
            selection.deselect_all()
            selection.focus()
            await pilot.press("m", "s")
            assert app.config["tracks"] == original
            assert app.updates == 0
    asyncio.run(scenario())


def test_bindings_are_discoverable_and_not_priority():
    assert [(b.key, b.action) for b in ROLE_BINDINGS] == [("s", "mark_speech"), ("m", "mark_music")]
    assert all(b.description and b.show and not b.priority for b in ROLE_BINDINGS)


def test_role_commands_are_listed_in_real_keys_panel():
    from test_keys_help import _panel_text

    async def scenario():
        app = RoleApp()
        async with app.run_test() as pilot:
            app.query_one(SelectionList).focus()
            await pilot.press("question_mark")
            text = _panel_text(app)
            assert "Mark Speech" in text
            assert "Mark Music" in text
    asyncio.run(scenario())


def test_other_selection_does_not_change_track_roles():
    async def scenario():
        app = RoleApp()
        async with app.run_test() as pilot:
            other = SelectionList(("plugin", "plugin", True), id="other_selection")
            await app.mount(other)
            other.focus()
            before = list(app.config["tracks"])
            await pilot.press("m", "s")
            assert app.config["tracks"] == before
            assert app.updates == 0
    asyncio.run(scenario())
