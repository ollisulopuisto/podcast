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


def test_a_centred_square_needs_no_crop_and_unit_scale():
    """Sama laskenta kuin ``write._square_lines``: neliö 1080×1080,
    keskipiste 540 px ylös keskeltä = 28,125 %. Peittävä skaala on 1 ja
    ikkuna on jo keskellä, joten vain sijainti jää."""
    panel = layout.Panel(0, -120, 1080, 1080)
    fcp = layout.fcp_panel(panel, (420, 0, 1080, 1080), 1920, 1080)
    assert fcp.scale == pytest.approx(1.0)
    assert fcp.pos_x == pytest.approx(0)
    assert fcp.pos_y == pytest.approx(28.125)


def test_an_off_centre_window_is_centred_by_the_position():
    """Kasvot vasemmalla: ilman rajausta skaala on paneelin peittävä
    tasainen skaala ja sijainti keskittää ikkunan paneeliin (malli
    varmistettu Final Cutissa 2026-11-19, ks. ``fcp_render_point``)."""
    panel = layout.panels(layout.LAYOUT_WIDE_TOP).close  # 1080×1312
    window = (200.0, 0.0, 889.0, 1080.0)  # keskipiste 644,5; lähteen 960
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    s = 1312 / 1080
    assert fcp.scale == pytest.approx(s)
    cx, cy = panel.centre
    assert fcp.pos_x == pytest.approx((cx - 540 - (644.5 - 960) * s) / 19.2)
    assert fcp.pos_y == pytest.approx((960 - cy) / 19.2)


def test_a_window_off_centre_vertically_shifts_the_position_too():
    """Sama kuin vaakasuunnassa: ikkuna 95 px lähteen keskikohdan alla
    siirtää sijaintia skaalattuna (y ylöspäin)."""
    panel = layout.panels(layout.LAYOUT_WIDE_TOP).close
    window = (515.0, 190.0, 889.0, 1080 - 190.0 - 0.0)   # keskipiste y = 635
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    s = fcp.scale
    cx, cy = panel.centre
    assert fcp.pos_x == pytest.approx((cx - 540 - (515 + 889 / 2 - 960) * s) / 19.2)
    assert fcp.pos_y == pytest.approx((960 - cy + (635 - 540) * s) / 19.2)


def fcp_render_point(fcp, x, y, src_w=1920, src_h=1080, proj_w=1080,
                     proj_h=1920):
    """Final Cutin varmistettu säätö ilman rajausta (2026-11-19): alue on
    koko lähde, kehys = lähde × skaala asettuu projektin keskelle +
    sijainti (% projektin korkeudesta, y ylöspäin), ja projektin
    ulkopuolelle jäävä osa leikkautuu. Palauttaa lähdepisteen (x, y)
    projektikoordinaatit (y alas)."""
    unit = proj_h / 100
    fx = (proj_w - src_w * fcp.scale) / 2 + fcp.pos_x * unit
    fy = (proj_h - src_h * fcp.scale) / 2 - fcp.pos_y * unit
    return fx + x * fcp.scale, fy + y * fcp.scale


def test_fcp_render_model_centres_the_window_on_the_panel():
    """Ikkunan keskipiste osuu paneelin keskipisteeseen ja skaala on
    tasainen — sekä pinon puolikas että koko ruutu."""
    panel = layout.stack_panel(1)  # 1080×960
    window = (476.0, 0.0, 1215.0, 1080.0)
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    assert fcp.scale == pytest.approx(960 / 1080)  # peittävä
    assert fcp_render_point(fcp, 476 + 1215 / 2, 540) == pytest.approx(
        panel.centre)
    full = layout.Panel(0, 0, 1080, 1920)
    fcp = layout.fcp_panel(full, layout.window_of(1920, 1080, 1080, 1920),
                           1920, 1080)
    assert fcp.scale == pytest.approx(1920 / 1080)  # peittävä
    assert fcp_render_point(fcp, 960, 540) == pytest.approx((540, 960))


def test_the_stack_is_two_panels_that_fill_the_screen_without_a_gap():
    top, bottom = layout.stack_panel(1), layout.stack_panel(-1)
    assert (top.x, top.y, top.w, top.h) == (0, 0, 1080, 960)
    assert (bottom.x, bottom.y, bottom.w, bottom.h) == (0, 960, 1080, 960)
    fcp = layout.fcp_panel(top, layout.window_of(1920, 1080, 1080, 960), 1920, 1080)
    assert fcp.pos_y == pytest.approx(25.0)


def test_there_is_no_crop_anymore():
    """``adjust-crop`` poistettiin 2026-11-19: Final Cut skaalaa rajatun
    alueen akselikohtaisesti täyttämään kehyksen, joten rajaus käytti
    ikkunan kahteen kertaan. FcpPanelilla ei ole rajauskenttiä."""
    panel = layout.stack_panel(1)
    fcp = layout.fcp_panel(panel, (392.0, 0.0, 1215.0, 1080.0), 1920, 1080)
    assert not hasattr(fcp, "left")
    assert fcp.scale == pytest.approx(960 / 1080)
    # Ikkunan keskipiste (999,5) siirtyy paneelin keskipisteeseen:
    assert fcp.pos_x == pytest.approx(-(999.5 - 960) * (960 / 1080) / 19.2)
