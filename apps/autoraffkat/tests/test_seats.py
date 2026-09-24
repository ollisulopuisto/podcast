"""Kuka on kukin kasvo laajassa ja ryhmäkuvassa.

Pelkkää numpyä: taulukot ja ruudukko annetaan valmiina, kuten
päätöskerroksessa.
"""

from fractions import Fraction

import numpy as np

from autoraffkat import seats
from autoraffkat.decide import Grid, SpeakerLanes
from autoraffkat.model import HOP, MediaItem, Placement
from autoraffkat.timeline import ZERO

SECONDS = 200


def _grid(talks: dict[str, list[tuple[float, float]]]) -> Grid:
    n = int(SECONDS / HOP)
    lanes = []
    for name, spans in talks.items():
        on = np.zeros(n, dtype=bool)
        for start, end in spans:
            on[int(start / HOP):int(end / HOP)] = True
        lanes.append(SpeakerLanes(name, np.where(on, -30.0, -60.0).astype(np.float32),
                                  on, None))
    return Grid(n=n, program_start=0.0, speakers=lanes, wide_key="W")


def _item(key="CAM 3 01.mp4", start=0, end=SECONDS):
    item = MediaItem(key=key, name=key, path="", src="", width=1920, height=1080)
    item.placements.append(Placement(Fraction(start), Fraction(start), Fraction(end - start)))
    item.asset_start = ZERO
    return item


# Mikko ja vieras vuorotellen kymmenen sekunnin jaksoissa; Tomi ei kuvassa.
ALTERNATE = {
    "Tomi": [],
    "Mikko": [(t, t + 10) for t in range(0, SECONDS, 20)],
    "Vieras": [(t, t + 10) for t in range(10, SECONDS, 20)],
}


def _two_shot(mikko_x=0.65, vieras_x=0.15, seconds=SECONDS):
    """Kaksi kasvoa joka sekunti; puhujan suu auki joka toisella ruudulla."""
    rows = []
    for t in range(seconds):
        mikko_talks = (t // 10) % 2 == 0
        for x, talking in ((mikko_x, mikko_talks), (vieras_x, not mikko_talks)):
            rows.append((t, x, 0.4 * talking * (t % 2)))
    return {
        "times": np.arange(seconds, dtype=np.float32),
        "frame": np.array([r[0] for r in rows], dtype=np.int32),
        "x": np.array([r[1] for r in rows], dtype=np.float32),
        "w": np.full(len(rows), 0.1, dtype=np.float32),
        "y": np.full(len(rows), 0.5, dtype=np.float32),
        "h": np.full(len(rows), 0.2, dtype=np.float32),
        "mouth": np.array([r[2] for r in rows], dtype=np.float32),
    }


def test_faces_are_matched_to_mics_by_mouth_movement():
    """Kumpi kasvo on Mikko: se jonka suu aukeaa kun Mikon mikki puhuu.

    Järjestys vasemmalta ei kerro sitä — tässä Mikko istuu oikealla — joten
    testi kaatuisi jos yhdistäminen tehtäisiin paikan mukaan.
    """
    grid = _grid(ALTERNATE)
    found = seats.seat_file(_two_shot(), _item(), grid, [0, 1, 2])
    assert found is not None and not found.manual
    assert abs(found.seats[1].x - 0.70) < 1e-6   # Mikko, laatikon keskellä
    assert abs(found.seats[2].x - 0.20) < 1e-6   # vieras
    assert 0 not in found.seats                  # Tomi ei puhu tässä kuvassa
    assert found.margin > 0


def test_one_face_and_one_talker_needs_no_evidence():
    """Osa jossa vieras on jo lähtenyt: sama kamera, yksi kasvo, yksi puhuja."""
    grid = _grid({"Tomi": [], "Mikko": [(0, SECONDS)], "Vieras": []})
    table = _two_shot()
    keep = table["x"] > 0.5
    single = {k: (v[keep] if k != "times" else v) for k, v in table.items()}
    found = seats.seat_file(single, _item(), grid, [0, 1, 2])
    assert list(found.seats) == [1]


def test_a_manual_order_wins():
    """Käsin annettu järjestys vasemmalta oikealle ohittaa mittauksen."""
    grid = _grid(ALTERNATE)
    found = seats.seat_file(_two_shot(), _item(), grid, [0, 1, 2], order=[1, 2])
    assert found.manual
    assert abs(found.seats[1].x - 0.20) < 1e-6   # Mikko vasemmalla, koska niin sanottiin
    assert abs(found.seats[2].x - 0.70) < 1e-6


def test_small_background_faces_are_not_seats():
    """Taustalla näkyvä pieni kasvo ei ole kolmas puhuja."""
    grid = _grid(ALTERNATE)
    table = _two_shot()
    extra = len(table["times"])
    for name, value in (("x", 0.45), ("w", 0.02), ("y", 0.8), ("h", 0.03), ("mouth", 0.0)):
        table[name] = np.concatenate([table[name], np.full(extra, value, np.float32)])
    table["frame"] = np.concatenate([table["frame"], np.arange(extra, dtype=np.int32)])
    found = seats.seat_file(table, _item(), grid, [0, 1, 2])
    assert sorted(found.seats) == [1, 2]
    assert all(abs(s.x - 0.46) > 0.1 for s in found.seats.values())
