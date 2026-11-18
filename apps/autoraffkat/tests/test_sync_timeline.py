"""Synkkapaneelin aikajana: asettelu, nimikkeet ja käännökset."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "autoraffkat" / "server" / "static"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node puuttuu")

SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const ctx = { LANG: 'fi', out: {} };
vm.createContext(ctx);
vm.runInContext(src, ctx);
vm.runInContext(`
  out.layout = syncTimelineLayout([
    { name: 'cam', duration: 100, shift: 5, reference: true },
    { name: 'a', duration: 90, shift: 2.5 },
    { name: 'b', duration: 90, shift: -10 },
    { name: 'c', duration: 90, shift: 'abc' },
    { name: 'd', duration: 90, shift: 1e99 },
  ]);
  out.hour = syncTimelineLayout([
    { name: 'cam', duration: 3600, shift: 0, reference: true },
    { name: 'mic', duration: 3570, shift: 12.24 },
  ]);
  out.fi = syncOffsetLabel(0.24) + '|' + syncOffsetLabel(-1.8);
  LANG = 'en';
  out.en = syncOffsetLabel(0.24);
  const est = { shift_seconds: 1.0, correlation: 0.9 };
  out.status = [
    syncRowStatus(est, 1.0, true), syncRowStatus({ shift_seconds: 1.0, correlation: 0.2 }, 1.0, true),
    syncRowStatus(est, 2.0, true), syncRowStatus({ shift_seconds: null }, 0, true),
    syncRowStatus({ shift_seconds: null }, 3, true), syncRowStatus(est, 1.0, false),
    syncRowStatus(undefined, 0, true), syncRowStatus(undefined, 2.5, false, true),
    syncRowStatus(est, 1.0, true, true), syncRowStatus({ shift_seconds: null }, 0, true, true),
  ];
`, ctx);
console.log(JSON.stringify(ctx.out));
"""


@pytest.fixture(scope="module")
def result():
    if shutil.which("node") is None:
        pytest.skip("node puuttuu")
    proc = subprocess.run(
        ["node", "-e", SCRIPT, str(STATIC / "sync_timeline.js")],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


@needs_node
def test_reference_is_pinned_to_zero_and_bars_stay_inside_track(result):
    items = result["layout"]["items"]
    assert items[0]["shift"] == 0
    for item in items:
        assert 0 <= item["left"] <= 100
        assert item["left"] + item["width"] <= 100.0001 or item["width"] == 0.5
        assert item["width"] >= 0.5
    assert 0 <= result["layout"]["zero"] <= 100


@needs_node
def test_negative_offset_sits_left_of_positive(result):
    by_name = {item["name"]: item for item in result["layout"]["items"]}
    assert by_name["b"]["left"] < by_name["cam"]["left"] < by_name["a"]["left"]


@needs_node
def test_non_numeric_and_huge_offsets_are_sanitised(result):
    by_name = {item["name"]: item for item in result["layout"]["items"]}
    assert by_name["c"]["shift"] == 0
    assert by_name["d"]["shift"] == 1e7


@needs_node
def test_offset_label_uses_language_decimal_and_sign(result):
    assert result["fi"] == "+0,24 s|−1,80 s"
    assert result["en"] == "+0.24 s"


@needs_node
def test_row_status_classification(result):
    assert result["status"] == [
        "good", "check", "manual", "notFound", "manual", "none",
        "none",    # arvion jälkeen lisätty tiedosto: ei tietuetta, ei "ei löytynyt"
        "manual",  # käsin syötetty siirto ennen arviota
        "manual",  # käsin muokkaus voittaa myös tuoreen arvion
        "manual",  # käsin kirjoitettu 0 epäonnistuneen arvion jälkeen
    ]


def test_timeline_container_exists_and_strings_in_both_languages():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="media-sync-timeline"' in html
    js = (STATIC / "i18n.js").read_text(encoding="utf-8")
    for key in ("timelineTitle", "timelineHelp", "timelineAria", "timelineScale", "clock", "notYet",
                "status.good", "status.check", "status.none", "status.notFound", "status.manual"):
        assert js.count(f"'sync.{key}'") == 2, key


@needs_node
def test_axis_covers_offsets_not_file_length(result):
    # Tunnin tiedostot, 12 s siirto: akseli on sekunteja, ei tunti, ja
    # siirretty palkki alkaa selvästi nollakohdan oikealta puolelta.
    hour = result["hour"]
    assert hour["span"] < 30
    assert hour["items"][1]["left"] - hour["items"][0]["left"] > 50


def test_timeline_container_keeps_children_readable_to_screen_readers():
    """role="img" piilottaisi tiedostonimet ja tilat ruudunlukijalta
    (Devin-arvio 2026-11-18); ryhmä säilyttää ne."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    line = next(row for row in html.splitlines() if 'id="media-sync-timeline"' in row)
    assert 'role="group"' in line
    assert 'role="img"' not in line


def test_sync_timeline_module_loads_before_app_and_is_versioned():
    """Puhtaat funktiot ovat omassa tiedostossaan; sivun on ladattava se ennen
    app.js:ää, ja versiotunniste kattaa sen (muuten selain tarjoaisi vanhan)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index("/static/sync_timeline.js") < html.index("/static/app.js")
    server = (STATIC.parent / "app.py").read_text(encoding="utf-8")
    assert '"sync_timeline.js"' in server
