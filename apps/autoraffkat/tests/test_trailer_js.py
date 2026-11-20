"""Trailerin kaksi kehystä per pala: koko ruutu ja puolikaspaneeli.

Yksi x ei voi kehystää sekä koko 9:16-ruutua että leveää puolikaspaneelia,
joten palalla on kaksi arvoa: tavallinen raahaus ja nuolet siirtävät koko
ruudun kehystä (x), Option-muunnos paneelin (x_panel). Mittaus tehdään
valeselaimessa (`ui_trailer.js`), väitteet ovat tässä.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


def _pct(row):
    """Rivin prosenttiosa: '80 %' tai '80 % | 40 %'."""
    return re.search(r"\d+ %( \| \d+ %)?", row).group(0)

STATIC = (
    Path(__file__).resolve().parents[1] / "src" / "autoraffkat" / "server" / "static"
)
HARNESS = Path(__file__).parent / "ui_trailer.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node puuttuu")


@pytest.fixture(scope="module")
def run():
    done = subprocess.run(
        ["node", str(HARNESS), str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    return json.loads(done.stdout)


@needs_node
def test_untouched_pieces_show_one_percentage(run):
    assert "40 %" in run["initialRows"][0]
    assert "|" not in run["initialRows"][0]


@needs_node
def test_plain_drag_moves_only_the_full_slice(run):
    piece = run["plainExport"][0]
    assert piece["x"] == pytest.approx(0.8)
    assert piece["x_panel"] == pytest.approx(0.4)   # paneeli ei liikkunut


@needs_node
def test_rows_show_both_percentages_only_when_the_slices_differ(run):
    row = run["afterPlainDrag"]["rows"][0]
    assert "80 % | 40 %" in row


@needs_node
def test_option_drag_moves_only_the_panel_slice(run):
    piece = run["optionExport"][1]
    assert piece["x"] == pytest.approx(0.6)         # koko ruutu paikallaan
    assert piece["x_panel"] == pytest.approx(0.95)


@needs_node
def test_the_modifier_latches_at_pointer_down(run):
    # Option päästettiin irti kesken raahauksen (clientX 900 → 950 ilman
    # Optionia): paneeli silti liikkui koko matkan, eikä koko ruutu
    # hypähtänyt mukaan.
    piece = run["optionExport"][1]
    assert piece["x_panel"] == pytest.approx(0.95)


@needs_node
def test_arrows_steer_the_full_slice_and_option_arrows_the_panel(run):
    piece = run["keysExport"][1]
    # 0.6 - 0.01 + 0.05 = 0.64 koko ruudulle
    assert piece["x"] == pytest.approx(0.64)
    # 0.95 - 0.01 + 0.05 = 0.99 paneelille
    assert piece["x_panel"] == pytest.approx(0.99)


@needs_node
def test_a_manual_slice_marks_the_row_manual(run):
    assert "käsin" in run["afterOptionDrag"]["rows"][1]


@needs_node
def test_split_copies_both_slices_and_merge_keeps_the_previous(run):
    rows = run["afterSplit"]["rows"]
    assert len(rows) == 3
    # toinen puolikas perii ensimmäisen molemmat kehykset
    assert _pct(rows[1]) == _pct(rows[0])
    merged = run["afterMerge"]["rows"]
    assert len(merged) == 2
    assert _pct(merged[0]) == _pct(rows[0])


@needs_node
def test_layout_preview_and_export_keep_the_same_panel_and_remaining_space(run):
    """Molemmat asettelut ja sijainnit piirretään ja lähetetään vientiin."""
    assert run["defaultLayout"] == "wide"
    assert run["remembered"]["autoraffkat.trailer.layout"] == "halves"
    for sample in run["layouts"]:
        assert sample["body"]["layout"] == sample["choice"]
        assert sample["body"]["lane"] == sample["lane"]
        # Kanvas 540×960, ulostulo 1080×1920.
        height = 304 if sample["choice"] == "wide" else 480
        if sample["lane"] == "none":
            assert len(sample["draws"]) == 1
            assert sample["outlines"] == []
            continue
        full, panel = sample["draws"]
        assert full[4:] == [0, 0, 540, 960]
        top = sample["lane"] == "top"
        assert panel[4:] == [0, 0 if top else 960-height, 540, height]
        sx, sy, sw, sh = panel[:4]
        assert 0 <= sx <= 1920-sw+1e-6
        assert sy >= 0 and sy+sh <= 1080+1e-6
        assert sw/sh == pytest.approx(540/height)
        assert sample["outlines"][0][1] == (height+2 if top else 2)
        assert sample["outlines"][0][3] == 960-height-4
