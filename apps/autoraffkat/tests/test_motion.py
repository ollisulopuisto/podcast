"""Liikemittaus ja sen ruudukkomuoto päätöskerrokselle."""

from types import SimpleNamespace

import numpy as np
import pytest
from conftest import needs_ffmpeg

from autoraffkat.model import HOP
from autoraffkat.video import motion


def _item(key="m1"):
    placement = SimpleNamespace(start=0.0, offset=0.0, end=1e9)
    return SimpleNamespace(key=key, asset_start=0.0, placements=[placement])


def _grid(n=None):
    return SimpleNamespace(n=n or int(40 / HOP))


def test_marks_maps_motion_to_grid_cells():
    table = {"times": np.array([1.0, 2.0, 3.0], dtype=np.float32),
             "motion": np.array([0.0, 12.0, 0.0], dtype=np.float32)}

    result = motion.marks({"CA": [_item()]}, {"m1": table}, _grid(), 0.0)

    keys, marks = result
    assert keys == ["CA"]
    assert marks.shape == (1, _grid().n)
    assert marks[0, int(2.0 / HOP)]
    assert not marks[0, int(1.0 / HOP)]
    assert not marks[0, int(3.0 / HOP)]


def test_marks_returns_none_without_hits():
    table = {"times": np.array([1.0]), "motion": np.array([0.0])}

    assert motion.marks({"CA": [_item()]}, {"m1": table}, _grid(), 0.0) is None
    assert motion.marks({"CA": [_item()]}, {}, _grid(), 0.0) is None


def test_marks_respects_program_start():
    # Ohjelma alkaa vasta 10 sekunnista: tiedostoaika 11 s osuu ruudukon
    # soluun 1 s, ei 11 s.
    table = {"times": np.array([11.0]), "motion": np.array([12.0])}

    _keys, marks = motion.marks({"CA": [_item()]}, {"m1": table}, _grid(), 10.0)

    assert marks[0, int(1.0 / HOP)]
    assert not marks[0, int(11.0 / HOP)] if int(11.0 / HOP) < _grid().n else True


@needs_ffmpeg
def test_measure_motion_detects_sudden_change(tmp_path):
    # 4 s mustaa, 2 s valkoista: liikettä vain vaihtokohdassa (~4 s).
    import subprocess

    video = tmp_path / "liike.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "color=c=black:size=320x240:rate=25:duration=4",
         "-f", "lavfi", "-i",
         "color=c=white:size=320x240:rate=25:duration=2",
         "-filter_complex", "concat=n=2:v=1", "-g", "12", str(video)],
        check=True, capture_output=True,
    )

    table = motion.measure_motion(str(video))

    times = np.asarray(table["times"])
    values = np.asarray(table["motion"])
    assert len(times) == len(values) and len(times) > 4
    assert values[0] == 0.0
    peak = int(np.argmax(values))
    assert values[peak] > motion.MOTION_MIN
    assert times[peak] == pytest.approx(4.0, abs=0.6)
    # Statiivinen jakso pysyy kynnyksen alla.
    assert values[1:peak].max() < motion.MOTION_MIN
