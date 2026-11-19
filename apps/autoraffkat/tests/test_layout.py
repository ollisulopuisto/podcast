"""Asettelut: paneelien geometria ja sen käännös Final Cutin yksiköihin."""

from __future__ import annotations

import pytest

from autoraffkat import layout


def test_single_has_no_panels():
    assert layout.panels(layout.LAYOUT_SINGLE) is None
    assert layout.panels("tuntematon") is None


def test_wide_on_top_is_native_sixteen_nine_over_the_full_width():
    """Laaja täyttää leveyden ja on 16:9, joten siitä ei leikata mitään;
    lähikuva saa loput korkeudesta (kuvakaappauksen asettelu)."""
    p = layout.panels(layout.LAYOUT_WIDE_TOP)
    assert (p.wide.x, p.wide.y, p.wide.w, p.wide.h) == (0, 0, 1080, 608)
    assert (p.close.x, p.close.y, p.close.w, p.close.h) == (0, 608, 1080, 1312)
    assert p.wide.h + p.close.h == layout.PROJECT_H


def test_wide_at_the_bottom_mirrors_it():
    p = layout.panels(layout.LAYOUT_WIDE_BOTTOM)
    assert (p.close.y, p.close.h) == (0, 1312)
    assert (p.wide.y, p.wide.h) == (1312, 608)


def test_the_window_of_a_wide_in_its_panel_is_the_whole_picture():
    """1920×1080 → 1080×608: sovitus on täyttö, ja 0,5 px:n ero rajaa
    lähteen alle kahden pikselin."""
    p = layout.panels(layout.LAYOUT_WIDE_TOP)
    x, y, w, h = layout.window_of(1920, 1080, p.wide.w, p.wide.h)
    assert y == pytest.approx(0)
    assert h == pytest.approx(1080)
    assert w == pytest.approx(1918.4, abs=0.1)
    assert x == pytest.approx((1920 - w) / 2, abs=0.1)


def test_the_window_of_a_closeup_has_the_panels_aspect():
    p = layout.panels(layout.LAYOUT_WIDE_TOP)
    _x, _y, w, h = layout.window_of(1920, 1080, p.close.w, p.close.h)
    assert w / h == pytest.approx(p.close.w / p.close.h)
    assert h == pytest.approx(1080)  # korkeus täynnä, sivuilta rajattu


def test_a_positive_position_moves_the_window_the_other_way():
    """Kuva oikealle = ikkuna vasemmalle: zoomattuna näkyy vasen reuna."""
    x0, *_ = layout.window_of(1920, 1080, 1080, 1312, scale=1.5)
    x1, *_ = layout.window_of(1920, 1080, 1080, 1312, scale=1.5, pos_x=10.0)
    assert x1 < x0


def test_the_window_never_leaves_the_source():
    x, y, w, h = layout.window_of(1920, 1080, 1080, 1312, scale=1.2, pos_x=-90, pos_y=90)
    assert 0 <= x and x + w <= 1920 + 1e-6
    assert 0 <= y and y + h <= 1080 + 1e-6


def test_a_centred_square_matches_the_stack_export_numbers():
    """Sama laskenta kuin ``write._square_lines``: neliö 1080×1080,
    keskipiste 540 px ylös keskeltä = 28,125 %, rajaus 38,889 % korkeudesta per puoli (420 px)."""
    panel = layout.Panel(0, -120, 1080, 1080)
    fcp = layout.fcp_panel(panel, (420, 0, 1080, 1080), 1920, 1080)
    assert fcp.left == pytest.approx(38.889, abs=1e-3)
    assert fcp.right == pytest.approx(38.889, abs=1e-3)
    assert fcp.top == pytest.approx(0)
    assert fcp.bottom == pytest.approx(0)
    # Kehys on paneeli: akselikohtainen skaala on paneeli / lähde.
    assert fcp.scale_x == pytest.approx(1080 / 1920)
    assert fcp.scale_y == pytest.approx(1.0)
    assert fcp.pos_x == pytest.approx(0)
    assert fcp.pos_y == pytest.approx(28.125)


def test_an_off_centre_window_needs_no_position_compensation():
    """Kasvot vasemmalla: ikkuna siirtyy lähteessä vasemmalle. Final Cut
    skaalaa rajatun alueen TÄYTTÄMÄÄN muunnetun kehyksen (varmistettu
    2026-11-19, ks. ``fcp_render_rect``), joten ikkuna keskittyy itsestään
    eikä sijaintiin tarvita skaalan kompensointia."""
    panel = layout.panels(layout.LAYOUT_WIDE_TOP).close
    window = (200.0, 0.0, 889.0, 1080.0)  # keskipiste 644,5; lähteen 960
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    assert fcp.scale_x == pytest.approx(panel.w / 1920)
    assert fcp.scale_y == pytest.approx(panel.h / 1080)
    cx, cy = panel.centre
    assert fcp.pos_x == pytest.approx((cx - 540) / 19.2)
    assert fcp.pos_y == pytest.approx((960 - cy) / 19.2)


def test_a_window_off_centre_vertically_needs_no_compensation_either():
    """Sama kuin vaakasuunnassa: ikkuna 100 px lähteen keskikohdan alla
    keskittyy paneeliin ilman korjausta."""
    panel = layout.panels(layout.LAYOUT_WIDE_TOP).close
    window = (515.0, 190.0, 889.0, 1080 - 190.0 - 0.0)   # keskipiste y = 635
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    assert fcp.scale_x == pytest.approx(panel.w / 1920)
    assert fcp.scale_y == pytest.approx(panel.h / 1080)
    cx, cy = panel.centre
    assert fcp.pos_x == pytest.approx((cx - 540) / 19.2)
    assert fcp.pos_y == pytest.approx((960 - cy) / 19.2)


def fcp_render_rect(fcp, src_w=1920, src_h=1080, proj_w=1080, proj_h=1920):
    """Final Cutin todellinen mode="crop"-säätö (varmistettu 2026-11-19
    diagnostiikkaviennillä Final Cut Prossa): rajattu alue skaalautuu
    AKSELEITTAIN täyttämään muunnetun kehyksen (lähde × transform-skaala,
    keskipisteen ympäri), ja kehys asettuu projektin keskelle + sijainti
    (prosentteja projektin korkeudesta, y ylöspäin). Palauttaa kehyksen
    suorakulmion projektin pikseleinä (y alas)."""
    fw, fh = src_w * fcp.scale_x, src_h * fcp.scale_y
    unit = proj_h / 100
    x0 = (proj_w - fw) / 2 + fcp.pos_x * unit
    y0 = (proj_h - fh) / 2 - fcp.pos_y * unit
    return x0, y0, x0 + fw, y0 + fh


def test_fcp_render_model_places_the_frame_exactly_on_the_panel():
    """Mikä tahansa ikkuna: kehys on tasan paneeli ja tehozoomi on se,
    joka renderöinnilläkin on (paneeli / ikkuna, molemmilla akseleilla)."""
    panel = layout.stack_panel(1)
    window = (476.0, 0.0, 1215.0, 1080.0)
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    fw, fh = 1920 * fcp.scale_x, 1080 * fcp.scale_y
    assert fw / window[2] == pytest.approx(panel.w / window[2])
    assert fh / window[3] == pytest.approx(panel.w / window[2])
    assert fcp_render_rect(fcp) == pytest.approx(
        (panel.x, panel.y, panel.x + panel.w, panel.y + panel.h))
    full = layout.Panel(0, 0, 1080, 1920)
    fcp = layout.fcp_panel(full, layout.window_of(1920, 1080, 1080, 1920), 1920, 1080)
    assert fcp_render_rect(fcp) == pytest.approx((0, 0, 1080, 1920))


def test_the_stack_is_two_panels_that_fill_the_screen_without_a_gap():
    top, bottom = layout.stack_panel(1), layout.stack_panel(-1)
    assert (top.x, top.y, top.w, top.h) == (0, 0, 1080, 960)
    assert (bottom.x, bottom.y, bottom.w, bottom.h) == (0, 960, 1080, 960)
    fcp = layout.fcp_panel(top, layout.window_of(1920, 1080, 1080, 960), 1920, 1080)
    assert fcp.pos_y == pytest.approx(25.0)


def test_crop_is_percent_of_the_source_height_not_width():
    """Final Cutin crop-rect on prosentteja lähteen KORKEUDESTA (Apple DTD).
    Käyttäjäraportti 2026-11-18: 1920×1080-lähteen ikkuna alkoi 392 px:stä,
    mutta Final Cut näytti vasemmalle 220,5 px, koska luku oli prosentteja
    leveydestä (20,42 % × 1080 = 220,5)."""
    panel = layout.stack_panel(1)
    window = (392.0, 0.0, 1215.0, 1080.0)
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    assert fcp.left / 100 * 1080 == pytest.approx(392.0)
    assert fcp.right / 100 * 1080 == pytest.approx(1920 - 392.0 - 1215.0)
    assert fcp.top == pytest.approx(0)
    # Pystyakselilla sama yksikkö: 100 px ylhäältä = 100 / 1080 %.
    tall = layout.fcp_panel(panel, (0.0, 100.0, 1215.0, 880.0), 1920, 1080)
    assert tall.top / 100 * 1080 == pytest.approx(100.0)
    assert tall.bottom / 100 * 1080 == pytest.approx(100.0)
