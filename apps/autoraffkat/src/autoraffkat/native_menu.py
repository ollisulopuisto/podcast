"""macOS-valikkorivi: sivun valikko piirrettynä natiivina valikkona.

Sivu lähettää valmiin valikkonsa (``native_menu.js``); tämä moduuli piirtää sen
pywebviewin sovellusvalikon jälkeen. Natiivi kohta ei tee itse mitään: valittuna se antaa
``{"id", "arg"?}`` ``run``ille, joka lähettää sen takaisin sivulle ajettavaksi samalla
komennolla kuin työkalurivin nappi. Näppäimet näytetään otsikossa mutta niitä ei sidota,
joten ``SHORTCUTS`` jää näppäinten ainoaksi omistajaksi.

pywebviewin oma Edit ja View puretaan: niiden Cut, Copy, Paste ja Select All (tekstikenttä
tarvitsee ne) korvaavat omamme, ja Enter Full Screen päätyy Näytä-valikon loppuun. Mikään
tässä ei saa pysäyttää ikkunaa: virhe kirjataan ja oletusvalikot jäävät.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from typing import Any

log = logging.getLogger("autoraffkat.native_menu")

MAX_ITEMS = 800
MAX_DEPTH = 3
MAX_LABEL = 120

#: Merkitsee tämän moduulin lisäämät ylätason kohdat, jotta seuraava asennus poistaa ne.
MENU_TAG = 0x4B4D

#: Omat komentomme jotka pywebviewin natiivit kohdat korvaavat (tekstikenttä tarvitsee ne).
NATIVE_EDIT_IDS = frozenset({"edit.cut", "edit.copy", "edit.paste", "edit.select_all"})
_NATIVE_EDIT_ACTIONS = ("cut:", "copy:", "paste:", "selectAll:")

#: Näppäinvihjeen oikea reuna valikossa, pisteinä.
_HINT_TAB = 300.0

#: Mitä pywebviewin valikoissa oli; säilyy asennusten yli (asennus siirtää ne).
_kept: dict[str, list[Any]] = {"edit": [], "view": []}
_target: Any = None


def _text(value: Any) -> str:
    return str(value)[:MAX_LABEL] if isinstance(value, (str, int, float)) else ""


def normalize_spec(raw: Any) -> list[dict]:
    """Sivun valikko siistittynä: lista ``{id, label, items}``, muuten ``[]``."""
    budget = [MAX_ITEMS]

    def items(entries: Any, depth: int) -> list[dict]:
        out: list[dict] = []
        if not isinstance(entries, list) or depth > MAX_DEPTH:
            return out
        for entry in entries:
            if budget[0] <= 0:
                break
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            if kind == "separator":
                out.append({"kind": "separator"})
            elif kind == "submenu":
                budget[0] -= 1
                inner = items(entry.get("items"), depth + 1)
                if inner:
                    out.append(
                        {
                            "kind": "submenu",
                            "label": _text(entry.get("label")),
                            "items": inner,
                        }
                    )
            elif kind == "item":
                ident = entry.get("id")
                if not isinstance(ident, str) or not ident:
                    continue
                budget[0] -= 1
                clean = {
                    "kind": "item",
                    "id": ident[:MAX_LABEL],
                    "label": _text(entry.get("label")),
                    "keys": _text(entry.get("keys")),
                    "enabled": bool(entry.get("enabled")),
                }
                if isinstance(entry.get("arg"), str):
                    clean["arg"] = entry["arg"]
                if isinstance(entry.get("checked"), bool):
                    clean["checked"] = entry["checked"]
                out.append(clean)
        return out

    menus: list[dict] = []
    for menu in raw if isinstance(raw, list) else []:
        if not isinstance(menu, dict):
            continue
        inner = items(menu.get("items"), 1)
        if inner:
            menus.append(
                {
                    "id": _text(menu.get("id")),
                    "label": _text(menu.get("label")),
                    "items": inner,
                }
            )
    return menus


def hint_suffix(keys: str) -> str:
    """Näppäinvihje tekstinä otsikon jälkeen, kun otsikkoon ei voi laittaa sarkainta."""
    return f"  {keys}" if keys else ""


def dispatch(target: Any, sender: Any) -> None:
    """Natiivi kohta valittiin: komento annetaan ajajalle."""
    try:
        payload = json.loads(str(sender.representedObject()))
    except (TypeError, ValueError):
        return
    if isinstance(payload, dict) and isinstance(payload.get("id"), str):
        target.run(payload)


def _make_target(appkit: Any, run: Callable[[dict], None]) -> Any:
    """Olio jota valikon kohdat kutsuvat: yksi PyObjC-luokka prosessia kohti."""
    global _target
    if _target is None:

        class AutoraffkatMenuTarget(appkit.NSObject):
            def invoke_(self, sender):
                dispatch(self, sender)

        _target = AutoraffkatMenuTarget.alloc().init()
    _target.run = run
    return _target


def _titled(appkit: Any, title: str, keys: str) -> tuple[str, Any]:
    """(pelkkä otsikko, muotoiltu otsikko tai None): näppäin oikeaan reunaan jos AppKit osaa."""
    if not keys:
        return title, None
    try:
        style = appkit.NSMutableParagraphStyle.alloc().init()
        stop = appkit.NSTextTab.alloc().initWithTextAlignment_location_options_(
            appkit.NSTextAlignmentRight, _HINT_TAB, {}
        )
        style.setTabStops_([stop])
        text = appkit.NSMutableAttributedString.alloc().initWithString_(
            f"{title}\t{keys}"
        )
        text.addAttribute_value_range_(
            appkit.NSParagraphStyleAttributeName, style, (0, len(title) + 1 + len(keys))
        )
        return title + hint_suffix(keys), text
    except Exception:
        return title + hint_suffix(keys), None


def _leaf(appkit: Any, entry: dict, target: Any) -> Any:
    plain, attributed = _titled(appkit, entry["label"], entry["keys"])
    node = appkit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
        plain, "invoke:", ""
    )
    if attributed is not None:
        node.setAttributedTitle_(attributed)
    node.setTarget_(target)
    payload = {"id": entry["id"]}
    if "arg" in entry:
        payload["arg"] = entry["arg"]
    node.setRepresentedObject_(json.dumps(payload))
    node.setEnabled_(entry["enabled"])
    if entry.get("checked"):
        node.setState_(1)
    return node


def _fill(
    appkit: Any,
    menu: Any,
    entries: list[dict],
    target: Any,
    native: list[Any],
    *,
    swap: bool = False,
) -> None:
    """``swap``: pywebviewin leikepöytäkohdat tulevat omiemme tilalle (jos sillä oli)."""
    for entry in entries:
        kind = entry["kind"]
        if kind == "separator":
            menu.addItem_(appkit.NSMenuItem.separatorItem())
        elif kind == "submenu":
            node = appkit.NSMenuItem.alloc().init()
            node.setTitle_(entry["label"])
            sub = appkit.NSMenu.alloc().initWithTitle_(entry["label"])
            sub.setAutoenablesItems_(False)
            _fill(appkit, sub, entry["items"], target, [])
            node.setSubmenu_(sub)
            menu.addItem_(node)
        elif swap and entry["id"] in NATIVE_EDIT_IDS:
            if native:
                for kept in native:
                    _detach(kept)
                    menu.addItem_(kept)
                native.clear()
        else:
            menu.addItem_(_leaf(appkit, entry, target))


def _detach(node: Any) -> None:
    parent = node.menu()
    if parent is not None:
        parent.removeItem_(node)


def _take_pywebview_menus(main: Any, taken: list | None = None) -> None:
    """Siirtää pywebviewin Edit- ja View-sisällöt pois rivistä ``_kept``iin. ``taken`` kerää
    ``(ylätason kohta, alivalikko, sen kohdat, paikka)``, jotta ne voi palauttaa virheessä."""
    original = list(main.itemArray())
    for item in original:
        sub = item.submenu()
        if sub is None or item.tag() == MENU_TAG:
            continue
        name = str(item.title())
        if taken is not None and name in ("Edit", "View"):
            taken.append((item, sub, list(sub.itemArray()), original.index(item)))
        if name == "Edit":
            _kept["edit"] = [
                i for i in sub.itemArray() if str(i.action()) in _NATIVE_EDIT_ACTIONS
            ]
            main.removeItem_(item)
        elif name == "View":
            _kept["view"] = list(sub.itemArray())
            main.removeItem_(item)


def _build(
    spec: list[dict],
    run: Callable[[dict], None],
    appkit: Any,
    target_factory: Callable[[Callable[[dict], None]], Any] | None,
) -> bool:
    main = appkit.NSApplication.sharedApplication().mainMenu()
    if main is None:
        return False
    target = target_factory(run) if target_factory else _make_target(appkit, run)
    for old in [i for i in main.itemArray() if i.tag() == MENU_TAG]:
        main.removeItem_(old)
    taken: list = []
    _take_pywebview_menus(main, taken)
    try:
        _draw(spec, main, appkit, target)
    except Exception:
        _restore(main, taken)
        raise
    return True


def _restore(main: Any, taken: list) -> None:
    """Palauttaa pywebviewin oman Edit- ja View-valikon epäonnistuneen piirron jälkeen."""
    for old in [i for i in main.itemArray() if i.tag() == MENU_TAG]:
        main.removeItem_(old)
    for top, sub, items, position in sorted(taken, key=lambda t_: t_[3]):
        for node in items:
            _detach(node)
            sub.addItem_(node)
        _detach(top)
        main.insertItem_atIndex_(top, min(position, len(main.itemArray())))


def _draw(spec: list[dict], main: Any, appkit: Any, target: Any) -> None:
    position = 1  # sovellusvalikon jälkeen
    for menu in spec:
        top = appkit.NSMenuItem.alloc().init()
        top.setTitle_(menu["label"])
        top.setTag_(MENU_TAG)
        sub = appkit.NSMenu.alloc().initWithTitle_(menu["label"])
        sub.setAutoenablesItems_(False)
        native = list(_kept["edit"]) if menu["id"] == "edit" else []
        _fill(appkit, sub, menu["items"], target, native, swap=bool(native))
        if menu["id"] == "view" and _kept["view"]:
            sub.addItem_(appkit.NSMenuItem.separatorItem())
            for kept in _kept["view"]:
                _detach(kept)
                sub.addItem_(kept)
        top.setSubmenu_(sub)
        main.insertItem_atIndex_(top, position)
        position += 1


def install(
    spec: Any,
    run: Callable[[dict], None],
    *,
    platform: str | None = None,
    appkit: Any = None,
    main_thread: Callable[[Callable[[], None]], None] | None = None,
    target_factory: Callable[[Callable[[dict], None]], Any] | None = None,
) -> bool:
    """Piirtää ``spec``in natiivivalikoiksi. True kun jonossa; False muualla kuin macOS:llä,
    tyhjällä speksillä tai ilman AppKitia. Ei koskaan heitä."""
    platform = sys.platform if platform is None else platform
    if platform != "darwin":
        return False
    menus = normalize_spec(spec)
    if not menus:
        return False
    try:
        if appkit is None:
            import AppKit as appkit
        if main_thread is None:
            from PyObjCTools import AppHelper

            main_thread = AppHelper.callAfter
    except Exception as e:
        log.warning("Natiivi valikkorivi ei ole käytössä (%s); ikkunan nappirivi toimii.", e)
        return False
    result = {"ok": True}

    def work() -> None:
        try:
            result["ok"] = _build(menus, run, appkit, target_factory)
        except Exception as e:
            result["ok"] = False
            log.warning("Natiivi valikkorivi ei ole käytössä (%s); ikkunan nappirivi toimii.", e)

    main_thread(work)
    return result["ok"]
