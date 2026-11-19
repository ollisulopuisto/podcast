"""Työkalurivin supistuminen natiivivalikon alla (body.native-menus).

Sopimus: valikon painamat napit jäävät DOM:iin (valikko painaa niitä edelleen),
vain näkyvät ryhmät katoavat, eikä `hidden`-luokkaa käytetä — `nativeUsable`
lukisi sen nappia itsessään ja lamauttaisi valikon kohdan.
"""

import re
from pathlib import Path

APP = Path(__file__).parents[1] / "src" / "autoraffkat"
CSS = (APP / "server" / "static" / "style.css").read_text(encoding="utf-8")
HTML = (APP / "server" / "static" / "index.html").read_text(encoding="utf-8")
JS = (APP / "server" / "static" / "app.js").read_text(encoding="utf-8")


def _header_rule() -> str:
    match = re.search(r"^header\s*\{([^}]*)\}", CSS, re.M)
    assert match, "header-sääntö puuttuu"
    return match.group(1)


def test_the_sticky_header_is_opaque():
    body = _header_rule()
    assert "transparent" not in body
    assert "border-bottom" in body


def test_the_slim_bar_hides_only_the_menu_covered_groups():
    for selector in ("#document-controls", "#history-controls", "#export-dest"):
        assert re.search(r"body\.native-menus\s+[^{}]*" + re.escape(selector), CSS), selector


def test_the_menu_pressed_buttons_stay_in_the_dom():
    for ident in ("open-media", "open", "reload", "history-undo", "history-redo"):
        assert f'id="{ident}"' in HTML, ident


def test_the_slim_bar_class_comes_from_a_drawn_native_menu():
    assert "native-menus" in JS
    assert re.search(r"classList\.add\(['\"]native-menus['\"]\)", JS)
