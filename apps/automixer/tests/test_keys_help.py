"""The keyboard shortcuts can be found from inside the terminal interface.

Both TUIs list their keys in ``BINDINGS``, and Textual draws the Footer and
the keys panel from that one list. The panel was reachable only through the
command palette (Ctrl+P, then "Keys"), which is itself a thing you have to
know about. ``?`` now opens it and closes it again, and Esc closes it.

The main window imports the mixer, which needs mlx, so its tests are marked
``mlx`` and run on macOS; the spot picker needs only Textual and runs
everywhere.
"""

from __future__ import annotations

import asyncio
import io

import pytest
from rich.console import Console
from textual.widgets import HelpPanel, Input


def _panel_open(app) -> bool:
    return bool(app.screen.query(HelpPanel))


def _shown_keys(app) -> dict[str, str]:
    """The keys the Footer shows, as the Footer displays them."""
    return {
        app.get_key_display(binding): binding.description
        for (_, binding, enabled, _tooltip) in app.screen.active_bindings.values()
        if binding.show and enabled
    }


def _panel_text(app) -> str:
    """What the keys panel draws, as plain text."""
    console = Console(width=120, record=True, file=io.StringIO())
    for widget in app.screen.query(HelpPanel).first().query("*"):
        console.print(widget.render())
    return console.export_text()


def _main_app(tmp_path):
    from automixer.app import AutomixerApp

    return AutomixerApp(work_dir=str(tmp_path))


def _spot_app(tmp_path):
    from automixer.tui_select import SpotSelectionApp

    spots = tmp_path / "spots.txt"
    spots.write_text("12.5\n61.0\n", encoding="utf-8")
    return SpotSelectionApp(str(spots), str(tmp_path / "config.yaml"))


async def _toggle(app):
    async with app.run_test() as pilot:
        await pilot.pause()
        was = _panel_open(app)
        await pilot.press("question_mark")
        await pilot.pause()
        opened = _panel_open(app)
        panel_text = _panel_text(app) if opened else ""
        footer = _shown_keys(app)
        await pilot.press("question_mark")
        await pilot.pause()
        closed_by_question = not _panel_open(app)
        await pilot.press("question_mark")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        closed_by_escape = not _panel_open(app)
        # Esc ilman paneelia ei kuulu meille: se ei saa kadota sovellukseen.
        escape_shown = any(
            b.key == "escape" and enabled
            for (_, b, enabled, _t) in app.screen.active_bindings.values()
        )
    return {
        "was": was,
        "opened": opened,
        "panel_text": panel_text,
        "footer": footer,
        "closed_by_question": closed_by_question,
        "closed_by_escape": closed_by_escape,
        "escape_bound_when_closed": escape_shown,
    }


def _check_toggle(got, app_cls_bindings):
    assert not got["was"]
    assert got["opened"], "? did not open the keys panel"
    assert got["closed_by_question"], "a second ? did not close it"
    assert got["closed_by_escape"], "Esc did not close it"
    assert not got["escape_bound_when_closed"], "Esc is taken even with the panel closed"
    # Footer: ? näkyy alarivillä, joten sen löytää lukematta mitään.
    assert got["footer"].get("?") == "Keys", got["footer"]
    # Paneeli luetteloi jokaisen sovelluksen näppäimen selityksineen.
    for binding in app_cls_bindings:
        description = binding[2] if isinstance(binding, tuple) else binding.description
        assert description in got["panel_text"], (description, got["panel_text"][:400])


def test_question_mark_toggles_the_keys_panel_in_the_spot_picker(tmp_path):
    from automixer.tui_select import SpotSelectionApp

    got = asyncio.run(_toggle(_spot_app(tmp_path)))
    _check_toggle(got, SpotSelectionApp.BINDINGS)


@pytest.mark.mlx
def test_question_mark_toggles_the_keys_panel_in_the_mixer(tmp_path):
    from automixer.app import AutomixerApp

    got = asyncio.run(_toggle(_main_app(tmp_path)))
    _check_toggle(got, AutomixerApp.BINDINGS)


@pytest.mark.mlx
@pytest.mark.parametrize("columns", [80, 120])
def test_the_footer_shows_the_way_in_even_when_it_is_full(tmp_path, columns):
    """The mixer's Footer runs out of room before its last key: at 120
    columns everything fits, at 80 the row ends in "space Play" and a
    ``? Keys`` after it is never seen. It is the one entry that leads to all
    the others, so it comes first."""

    async def scenario():
        app = _main_app(tmp_path)
        async with app.run_test(size=(columns, 30)) as pilot:
            await pilot.pause()
            return app.export_screenshot()

    svg = asyncio.run(scenario())
    assert "Keys" in svg.replace("&#160;", " ")


@pytest.mark.mlx
def test_question_mark_typed_into_a_field_is_a_character(tmp_path):
    """A ``?`` typed into a text field is text, not a command."""

    async def scenario():
        app = _main_app(tmp_path)
        async with app.run_test() as pilot:
            field = app.query(Input).first()
            field.focus()
            field.value = ""
            await pilot.pause()
            focused = app.focused is field
            await pilot.press("question_mark")
            await pilot.pause()
            return focused, field.value, _panel_open(app)

    # Textual pitää kirjoitettavan merkin kohdistetulla kentällä myös
    # etusijaisen sidoksen edellä (`Input.check_consume_key`); tämä varmistaa
    # että se pätee tässäkin ja että kenttä todella oli kohdistettuna.
    focused, value, opened = asyncio.run(scenario())
    assert focused, "the test typed into a field that did not have focus"
    assert value == "?"
    assert not opened


def _all_bindings():
    from automixer.app import AutomixerApp, LogScreen
    from automixer.tui_select import SpotSelectionApp

    for cls in (AutomixerApp, LogScreen, SpotSelectionApp):
        for binding in cls.BINDINGS:
            yield cls.__name__, binding


@pytest.mark.mlx
def test_every_binding_says_what_it_does():
    """The panel and the Footer print the description; an empty one is a key
    nobody can find."""
    for owner, binding in _all_bindings():
        description = binding[2] if isinstance(binding, tuple) else binding.description
        assert description, (owner, binding)


def test_enter_selects_a_spot_in_the_picker(tmp_path):
    """The Footer promised "Select Spot" on Enter, and Enter did nothing.

    The list has the focus, and a ListView takes Enter for itself, so the
    app's binding never ran: no spot was chosen and the config was never
    written. The binding is now a priority binding, so the key the panel
    lists is the key that works.
    """
    import yaml

    async def scenario():
        app = _spot_app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
        return app.return_value

    assert asyncio.run(scenario()) == 61.0
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved == {"ad_spot": 61.0}
