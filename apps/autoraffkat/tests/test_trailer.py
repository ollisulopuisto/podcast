"""Trailerin pilkkominen ja kohteen paikka: puhtaat osat ja ffmpeg-ajot."""

import subprocess

import numpy as np
import pytest
from conftest import needs_ffmpeg

from autoraffkat import trailer


def test_cut_points_apply_threshold_and_minimum_length():
    table = {"times": np.array([1.0, 1.4, 3.0, 9.8], dtype=np.float32),
             "score": np.array([0.5, 0.9, 0.2, 0.8], dtype=np.float32)}
    # 3.0 jää kynnyksen alle, 9.8 on liian lähellä loppua, ja parista 1.0/1.4
    # jää vahvempi 1.4
    assert trailer.cut_points(table, 0.3, 1.0, 10.0) == [pytest.approx(1.4)]


def test_cut_points_keep_the_stronger_cut_of_a_close_pair():
    table = {"times": np.array([2.0, 2.4], dtype=np.float32),
             "score": np.array([0.4, 0.9], dtype=np.float32)}
    assert trailer.cut_points(table, 0.3, 1.0, 10.0) == [pytest.approx(2.4)]


def test_pieces_cover_the_whole_duration_without_gaps():
    got = trailer.pieces([2.0, 5.0], 8.0)
    assert got == [(0.0, 2.0), (2.0, 5.0), (5.0, 8.0)]
    assert trailer.pieces([], 8.0) == [(0.0, 8.0)]


def test_fixed_pieces_leave_no_short_tail():
    got = trailer.fixed_pieces(10.0, 4.0)
    assert got[0] == (0.0, 4.0)
    assert got[-1][1] == 10.0
    assert all(b - a >= 2.0 for a, b in got)


def test_spectral_saliency_finds_a_lone_bright_blob():
    img = np.zeros((72, 128), dtype=np.float32)
    img[26:46, 96:112] = 255.0  # kohde oikealla, x ~ 0.81
    x, y = trailer.subject_of(img)
    assert x == pytest.approx(0.81, abs=0.12)
    assert y == pytest.approx(0.5, abs=0.2)


def test_subject_x_is_the_median_of_the_samples_inside_a_piece():
    table = {"times": np.array([0.0, 0.5, 1.0, 1.5, 3.0], dtype=np.float32),
             "x": np.array([0.2, 0.3, 0.9, 0.3, 0.7], dtype=np.float32),
             "y": np.full(5, 0.5, dtype=np.float32)}
    assert trailer.piece_x(table, 0.0, 2.0) == pytest.approx(0.3)
    # Ei näytteitä: ei arvausta, vaan keskitys
    assert trailer.piece_x(table, 10.0, 11.0) == 0.5


def test_window_is_the_panel_aspect_and_stays_inside_the_source():
    # 16:9-lähde, puolikaspaneeli 1080x960: leveys = korkeus * 9/8
    wx, wy, ww, wh = trailer.window(1920, 1080, 1080, 960, 0.5)
    assert (wy, wh) == (0, 1080)
    assert ww == pytest.approx(1080 * 1080 / 960)
    assert wx == pytest.approx((1920 - ww) / 2)
    # kohde reunassa: ikkuna ei lähde lähteen ulkopuolelle
    wx, _, ww, _ = trailer.window(1920, 1080, 1080, 960, 0.99)
    assert wx + ww == pytest.approx(1920)
    wx, _, _, _ = trailer.window(1920, 1080, 1080, 960, 0.0)
    assert wx == 0


def test_window_for_the_full_lane_of_a_cinemascope_source_is_a_narrow_crop():
    _, _, ww, wh = trailer.window(2560, 1072, 1080, 1920, 0.5)
    assert wh == 1072
    assert ww == pytest.approx(1072 * 1080 / 1920)
    assert ww / 2560 < 0.25


def _synthetic(path, size="320x180"):
    """Kolme kohtausta, valkoinen laatikko eri kohdassa: vasen, keski, oikea."""
    w = int(size.split("x")[0])
    scenes = []
    for color, bx in (("black", 20), ("0x707070", w // 2 - 20), ("black", w - 60)):
        scenes.append(
            f"color=c={color}:s={size}:d=2:r=25,"
            f"drawbox=x={bx}:y=60:w=40:h=40:c=white:t=fill")
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    for s in scenes:
        cmd += ["-f", "lavfi", "-i", s]
    cmd += ["-filter_complex", "[0][1][2]concat=n=3:v=1:a=0[v]", "-map", "[v]",
            "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return str(path)


@needs_ffmpeg
def test_scene_table_finds_the_two_hard_cuts(tmp_path):
    path = _synthetic(tmp_path / "t.mp4")
    table = trailer.scene_table(path)
    cuts = trailer.cut_points(table, trailer.SCENE_DEFAULT, 1.0, 6.0)
    assert len(cuts) == 2
    assert cuts[0] == pytest.approx(2.0, abs=0.1)
    assert cuts[1] == pytest.approx(4.0, abs=0.1)


@needs_ffmpeg
def test_saliency_table_follows_the_box_from_left_to_right(tmp_path):
    path = _synthetic(tmp_path / "t.mp4")
    table = trailer.saliency_table(path)
    xs = [trailer.piece_x(table, a, b) for a, b in [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]]
    assert xs[0] < 0.35 < 0.4 < xs[1] < 0.6 < 0.65 < xs[2]
