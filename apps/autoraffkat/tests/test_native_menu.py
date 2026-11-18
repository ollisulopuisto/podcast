"""macOS-valikkorivi (sivun valikon peilikuva) vale-AppKitillä."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from autoraffkat import gui, native_menu


@pytest.fixture(autouse=True)
def _fresh_module_state():
    native_menu._kept.update({"edit": [], "view": []})
    native_menu._target = None


class FakeItem:
    def __init__(self, title="", action=None, key="", separator=False):
        self._title, self._action, self._key = title, action, key
        self._separator = separator
        self._sub = None
        self._menu = None
        self.target = None
        self.represented = None
        self.enabled = True
        self.state = 0
        self.tag_value = 0

    @classmethod
    def alloc(cls):
        return cls()

    def initWithTitle_action_keyEquivalent_(self, title, action, key):
        self._title, self._action, self._key = title, action, key
        return self

    def init(self):
        return self

    @classmethod
    def separatorItem(cls):
        return cls(separator=True)

    def title(self):
        return self._title

    def setTitle_(self, title):
        self._title = title

    def action(self):
        return self._action

    def isSeparatorItem(self):
        return self._separator

    def setSubmenu_(self, menu):
        self._sub = menu

    def submenu(self):
        return self._sub

    def menu(self):
        return self._menu

    def setTarget_(self, target):
        self.target = target

    def setRepresentedObject_(self, obj):
        self.represented = obj

    def representedObject(self):
        return self.represented

    def setEnabled_(self, flag):
        self.enabled = flag

    def setState_(self, state):
        self.state = state

    def setTag_(self, tag):
        self.tag_value = tag

    def tag(self):
        return self.tag_value


class FakeMenu:
    def __init__(self, title=""):
        self._title = title
        self.items: list[FakeItem] = []
        self.autoenables = True

    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return self

    def initWithTitle_(self, title):
        self._title = title
        return self

    def setTitle_(self, title):
        self._title = title

    def title(self):
        return self._title

    def setAutoenablesItems_(self, flag):
        self.autoenables = flag

    def addItem_(self, item):
        item._menu = self
        self.items.append(item)

    def insertItem_atIndex_(self, item, index):
        item._menu = self
        self.items.insert(index, item)

    def removeItem_(self, item):
        self.items.remove(item)
        item._menu = None

    def itemArray(self):
        return list(self.items)

    def numberOfItems(self):
        return len(self.items)


class FakeApp:
    def __init__(self, main):
        self.main = main

    def mainMenu(self):
        return self.main


class FakeAppKit:
    NSMenu = FakeMenu
    NSMenuItem = FakeItem

    def __init__(self, main):
        self._app = FakeApp(main)

        class NSApplication:
            @staticmethod
            def sharedApplication():
                return self._app

        self.NSApplication = NSApplication


def pywebview_menu():
    """What pywebview 6 builds with no custom menu: app menu, Edit, View."""
    main = FakeMenu("main")
    for title, entries in (
        (
            "kuulas",
            [("About kuulas", "orderFrontStandardAboutPanel:"), ("Quit", "terminate:")],
        ),
        (
            "Edit",
            [
                ("Cut", "cut:"),
                ("Copy", "copy:"),
                ("Paste", "paste:"),
                ("Select All", "selectAll:"),
            ],
        ),
        ("View", [("Enter Full Screen", "toggleFullScreen:")]),
    ):
        top = FakeItem(title)
        sub = FakeMenu(title)
        for name, action in entries:
            sub.addItem_(FakeItem(name, action))
        top.setSubmenu_(sub)
        main.addItem_(top)
    return main


def item(id_, label=None, **extra):
    return {
        "kind": "item",
        "id": id_,
        "label": label or id_,
        "keys": "",
        "enabled": True,
        **extra,
    }


SPEC = [
    {
        "id": "file",
        "label": "Tiedosto",
        "items": [
            item("app.save", "Tallenna", keys="⌘S", enabled=False),
            {"kind": "separator"},
            {
                "kind": "submenu",
                "label": "Versiot",
                "items": [item("app.backup_now", "Varmuuskopioi")],
            },
            item("open", "Projekti A", arg="/p/a.kuulas"),
        ],
    },
    {
        "id": "edit",
        "label": "Muokkaa",
        "items": [
            item("edit.undo", "Kumoa", keys="⌘Z"),
            {"kind": "separator"},
            item("edit.cut", "Leikkaa", keys="⌘X"),
            item("edit.copy", "Kopioi", keys="⌘C"),
            item("edit.paste", "Liitä", keys="⌘V"),
            item("edit.select_all", "Valitse kaikki", keys="⌘A"),
            {"kind": "separator"},
            item("edit.split", "Jaa", keys="B"),
        ],
    },
    {
        "id": "view",
        "label": "Näytä",
        "items": [item("view.zoom", "Lähennä", checked=True)],
    },
]


def run_install(main, spec=SPEC, runs=None, **kw):
    runs = runs if runs is not None else []
    made = {}

    def target_factory(run):
        made["target"] = type("T", (), {"run": staticmethod(run)})()
        return made["target"]

    ok = native_menu.install(
        spec,
        runs.append,
        platform="darwin",
        appkit=FakeAppKit(main),
        main_thread=lambda fn: fn(),
        target_factory=target_factory,
        **kw,
    )
    return ok, made.get("target"), runs


def titles(menu):
    return [i.title() for i in menu.items]


def test_normalize_spec_rejects_garbage_and_keeps_good_items():
    assert native_menu.normalize_spec(None) == []
    assert native_menu.normalize_spec("x") == []
    assert native_menu.normalize_spec([{"label": "A", "items": "no"}]) == []
    spec = native_menu.normalize_spec(
        [{"id": "a", "label": "A", "items": [item("x", "X"), {"kind": "bogus"}, 5]}]
    )
    assert [i["id"] for i in spec[0]["items"]] == ["x"]


def test_normalize_spec_caps_size_depth_and_text():
    many = [item(f"c{n}") for n in range(native_menu.MAX_ITEMS + 10)]
    spec = native_menu.normalize_spec([{"id": "a", "label": "A", "items": many}])
    assert len(spec[0]["items"]) == native_menu.MAX_ITEMS
    deep = {"kind": "submenu", "label": "1", "items": [item("leaf")]}
    for level in range(native_menu.MAX_DEPTH + 2):
        deep = {"kind": "submenu", "label": str(level), "items": [deep]}
    spec = native_menu.normalize_spec([{"id": "a", "label": "A", "items": [deep]}])
    assert "leaf" not in json.dumps(spec)
    long = native_menu.normalize_spec(
        [{"id": "a", "label": "L" * 500, "items": [item("x", "Y" * 500)]}]
    )
    assert len(long[0]["label"]) <= native_menu.MAX_LABEL
    assert len(long[0]["items"][0]["label"]) <= native_menu.MAX_LABEL


def test_off_macos_nothing_is_touched():
    ok = native_menu.install(
        SPEC, lambda _c: None, platform="linux", appkit=FakeAppKit(pywebview_menu())
    )
    assert ok is False


def test_the_menus_follow_the_app_menu_and_replace_pywebviews_edit_and_view():
    main = pywebview_menu()
    ok, _target, _runs = run_install(main)
    assert ok is True
    assert titles(main) == ["kuulas", "Tiedosto", "Muokkaa", "Näytä"]


def test_the_native_clipboard_items_stay_pywebviews_and_ours_for_them_are_dropped():
    main = pywebview_menu()
    run_install(main)
    edit = main.items[2].submenu()
    assert [i.title() for i in edit.items if not i.isSeparatorItem()] == [
        "Kumoa" + native_menu.hint_suffix("⌘Z"),
        "Cut",
        "Copy",
        "Paste",
        "Select All",
        "Jaa" + native_menu.hint_suffix("B"),
    ]
    assert [
        i.action()
        for i in edit.items
        if i.title() in ("Cut", "Copy", "Paste", "Select All")
    ] == ["cut:", "copy:", "paste:", "selectAll:"]


def test_pywebviews_view_items_close_our_view_menu():
    main = pywebview_menu()
    run_install(main)
    view = main.items[3].submenu()
    assert view.items[-1].title() == "Enter Full Screen"
    assert view.items[-2].isSeparatorItem()


def test_items_carry_state_and_the_command_to_run():
    main = pywebview_menu()
    _ok, target, runs = run_install(main)
    file_menu = main.items[1].submenu()
    save = file_menu.items[0]
    assert save.enabled is False
    assert save.action() == "invoke:"
    assert save.target is target
    assert json.loads(save.representedObject()) == {"id": "app.save"}
    assert file_menu.autoenables is False
    sub = file_menu.items[2].submenu()
    assert sub.items[0].title().startswith("Varmuuskopioi")
    recent = file_menu.items[3]
    assert json.loads(recent.representedObject()) == {
        "id": "open",
        "arg": "/p/a.kuulas",
    }
    zoom = main.items[3].submenu().items[0]
    assert zoom.state == 1
    assert runs == []


def test_choosing_an_item_hands_its_command_to_the_runner():
    main = pywebview_menu()
    _ok, target, runs = run_install(main)
    save = main.items[1].submenu().items[0]
    native_menu.dispatch(target, save)
    assert runs == [{"id": "app.save"}]


def test_a_second_install_replaces_the_first_and_keeps_the_native_items():
    main = pywebview_menu()
    run_install(main)
    run_install(main, spec=[SPEC[1]])
    assert titles(main) == ["kuulas", "Muokkaa"]
    edit = main.items[1].submenu()
    assert [
        i.title()
        for i in edit.items
        if i.action() in ("cut:", "copy:", "paste:", "selectAll:")
    ] == ["Cut", "Copy", "Paste", "Select All"]


def test_an_appkit_error_leaves_the_menu_and_returns_false():
    main = pywebview_menu()

    class Boom(FakeAppKit):
        class NSMenuItem(FakeItem):
            def initWithTitle_action_keyEquivalent_(self, *_a):
                raise RuntimeError("appkit")

    ok = native_menu.install(
        SPEC,
        lambda _c: None,
        platform="darwin",
        appkit=Boom(main),
        main_thread=lambda fn: fn(),
        target_factory=lambda run: object(),
    )
    assert ok is False
    bar = [i.title() for i in main.items]
    assert bar == ["kuulas", "Edit", "View"]
    edit = main.items[1].submenu()
    assert [i.title() for i in edit.items] == ["Cut", "Copy", "Paste", "Select All"]
    assert [i.title() for i in main.items[2].submenu().items] == ["Enter Full Screen"]


def test_no_main_menu_returns_false():
    ok = native_menu.install(
        SPEC,
        lambda _c: None,
        platform="darwin",
        appkit=FakeAppKit(None),
        main_thread=lambda fn: fn(),
        target_factory=lambda run: object(),
    )
    assert ok is False


def test_the_hint_is_part_of_the_title_when_there_is_no_attributed_string():
    assert native_menu.hint_suffix("") == ""
    assert "⌘S" in native_menu.hint_suffix("⌘S")


@pytest.mark.parametrize("bad", [{"id": 5}, {"kind": "item"}, {"kind": "item", "id": ""}])
def test_an_item_without_a_usable_id_is_dropped(bad):
    spec = native_menu.normalize_spec(
        [{"id": "a", "label": "A", "items": [bad, item("ok")]}]
    )
    assert [i["id"] for i in spec[0]["items"]] == ["ok"]


def test_without_pywebviews_native_clipboard_items_our_own_stay():
    main = pywebview_menu()
    main.removeItem_(
        main.items[1]
    )  # ei Muokkaa-valikkoa (pywebview ei nimennyt sitä "Edit")
    run_install(main)
    edit = next(i for i in main.items if i.title() == "Muokkaa").submenu()
    assert [i.title().split("  ")[0] for i in edit.items if not i.isSeparatorItem()][
        1:5
    ] == ["Leikkaa", "Kopioi", "Liitä", "Valitse kaikki"]


def test_the_bridge_draws_the_menu_and_runs_a_chosen_command_in_its_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        gui.native_menu,
        "install",
        lambda spec, run: seen.update(spec=spec, run=run) or True,
    )
    bridge = gui.DesktopApi()
    scripts = []
    done = threading.Event()
    bridge.window = SimpleNamespace(
        evaluate_js=lambda script: (scripts.append(script), done.set())
    )
    assert bridge.set_native_menu(SPEC) is True
    assert seen["spec"] == SPEC
    seen["run"]({"id": "open", "arg": "/p/a.kuulas"})
    assert done.wait(2)
    assert scripts == [
        'window.__autoraffkatNativeRun && window.__autoraffkatNativeRun({"id": "open", '
        '"arg": "/p/a.kuulas"})'
    ]


def test_a_bridge_without_a_window_ignores_a_chosen_command():
    gui.DesktopApi()._run_native_command({"id": "app.save"})
