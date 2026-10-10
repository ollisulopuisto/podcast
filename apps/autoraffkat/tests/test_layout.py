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
    keskipiste 540 px ylös keskeltä = 28,125 %, rajaus 21,875 % per puoli."""
    panel = layout.Panel(0, -120, 1080, 1080)
    fcp = layout.fcp_panel(panel, (420, 0, 1080, 1080), 1920, 1080)
    assert fcp.left == pytest.approx(21.875)
    assert fcp.right == pytest.approx(21.875)
    assert fcp.top == pytest.approx(0)
    assert fcp.bottom == pytest.approx(0)
    assert fcp.scale == pytest.approx(1.0)
    assert fcp.pos_x == pytest.approx(0)
    assert fcp.pos_y == pytest.approx(28.125)


def test_an_off_centre_window_is_compensated_in_the_position():
    """Kasvot vasemmalla: ikkuna siirtyy lähteessä vasemmalle, ja koska
    Final Cut skaalaa klipin omaa keskipistettä ympäri, sijainnin pitää
    vetää ikkuna takaisin paneelin keskelle."""
    panel = layout.panels(layout.LAYOUT_WIDE_TOP).close
    window = (200.0, 0.0, 889.0, 1080.0)  # keskipiste 644,5; lähteen 960
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    s = 1080 / 889.0
    assert fcp.scale == pytest.approx(s)
    # Ikkunan keskipiste ruudulla: lähteen keskipiste + sijainti + s × poikkeama.
    assert (1080 / 2) + fcp.pos_x * 19.2 + s * (644.5 - 960) == pytest.approx(540)


def test_a_window_off_centre_vertically_is_compensated_in_the_position():
    """Sama kuin vaakasuunnassa, y ylöspäin: ikkunan keskipiste on lähteen
    keskipisteen alapuolella 100 px, joten skaalattuna se on s × 100 px
    keskipisteen alla, ja sijainnin pitää nostaa se takaisin paneelin
    keskelle (paneelin keskipiste 304 px projektin keskipisteen alla)."""
    panel = layout.panels(layout.LAYOUT_WIDE_TOP).close
    window = (515.0, 190.0, 889.0, 1080 - 190.0 - 0.0)   # keskipiste y = 635
    fcp = layout.fcp_panel(panel, window, 1920, 1080)
    s = fcp.scale
    off_y = 190.0 + (1080 - 190.0) / 2 - 540            # +95 px alas lähteen keskeltä
    assert fcp.pos_y * 19.2 - s * off_y == pytest.approx(-304)
