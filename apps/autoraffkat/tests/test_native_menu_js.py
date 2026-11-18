"""Sivun natiivivalikko: speksi, valinnan ajo ja päivitysten karsinta.

Puhtaat funktiot (`native_menu.js`) ladataan sellaisenaan nodeen
(`ui_native_menu.js`); väitteet ovat tässä, jotta jokainen lupaus on oma testinsä.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
STATIC = TESTS.parents[0] / "src" / "autoraffkat" / "server" / "static"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node puuttuu")


@pytest.fixture(scope="module")
def run():
    done = subprocess.run(
        ["node", str(TESTS / "ui_native_menu.js"), str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    return json.loads(done.stdout)


@needs_node
def test_the_menus_are_the_five_the_app_documents(run):
    assert run["menuIds"] == ["file", "edit", "audio", "view", "help"]


@needs_node
def test_items_carry_their_key_hint_and_radio_and_history_state(run):
    assert run["mixKeys"] == "K:mix"
    assert run["exportRadios"] == [["fcp", True], ["resolve", False]]
    assert run["historyItems"] == [["1", False], ["2", True]]


@needs_node
def test_clipboard_items_are_left_to_the_native_ones(run):
    assert run["clipboardEnabled"] == [False, False, False, False]


@needs_node
def test_an_item_the_button_refuses_is_disabled_in_the_menu(run):
    assert run["disabledWhenUnusable"] is True


@needs_node
def test_while_the_shortcut_sheet_is_open_only_its_own_command_is_enabled(run):
    assert run["sheetEnabled"] == ["shortcuts"]


@needs_node
def test_a_chosen_item_runs_the_command_with_its_argument(run):
    assert run["runOk"] is True and run["runArgs"] is True
    assert run["runCalls"] == [["render", None], ["export-dest", "resolve"]]


@needs_node
def test_the_sheet_blocks_every_choice_but_its_own(run):
    assert run["sheetBlocksRender"] is False
    assert run["sheetAllowsShortcuts"] is True
    assert run["sheetRuns"] == [["shortcuts", None]]


@needs_node
def test_a_choice_the_button_would_refuse_or_a_malformed_one_is_not_run(run):
    assert run["unusableRefused"] is False
    assert run["garbageRefused"] == [False, False]


@needs_node
def test_the_sync_sends_changes_only_and_only_from_the_focused_window(run):
    # push, sama, pakotettu, muuttunut, ilman kohdistusta
    assert run["sync"] == [True, False, True, True, False]
    assert run["sent"] == 3
    assert run["noApi"] is False


def test_the_script_loads_before_app_js_and_is_versioned():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index("/static/native_menu.js") < html.index("/static/app.js")
    server = (STATIC.parent / "app.py").read_text(encoding="utf-8")
    assert '"native_menu.js"' in server


def test_boot_starts_the_native_menu():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    boot = app[app.index("async function boot()") :]
    assert "startNativeMenu();" in boot.split("\n}\n", 1)[0]
