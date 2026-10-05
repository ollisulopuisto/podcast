"""Milloin joku puhuu, istunnon aikajanalla.

Verhokäyrä annetaan testissä suoraan, jotta sääntö testataan ilman
ffmpegiä: lukija on ``speechmix.rms.envelope_for``, ja sen oma testi on
siellä.
"""

from __future__ import annotations

import numpy as np

from nhsx import activity, read
from speechmix.grid import HOP_SEC

FLOOR = -70.0
VOICE = -30.0


def _curve(seconds: float, spans) -> np.ndarray:
    """Tiedoston verhokäyrä: pohjakohina ja puhetta väleillä ``spans``."""
    db = np.full(int(round(seconds / HOP_SEC)), FLOOR, dtype=np.float32)
    for a, b in spans:
        db[int(a / HOP_SEC):int(b / HOP_SEC)] = VOICE
    return db


def _session(tmp_path, tracks: str) -> str:
    for name in ("a.wav", "b.wav", "m.wav"):
        (tmp_path / name).write_bytes(b"")
    path = tmp_path / "s.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session>
  <AudioPool Path="" Location="{tmp_path}">
    <File Id="1" Name="a.wav"/><File Id="2" Name="b.wav"/>
    <File Id="3" Name="m.wav" Channels="2"/>
  </AudioPool>
  <Tracks>{tracks}</Tracks>
</Session>""", encoding="utf-8")
    return read(path)


def _intervals(session, curves, **kw):
    return activity.speech_intervals(
        session, envelope=lambda path: curves[path.rsplit("/", 1)[-1]], **kw
    )


def test_region_offset_places_speech_on_the_timeline(tmp_path):
    session = _session(tmp_path, """
      <Track Name="Olli"><Region Ref="1" Start="10.000" Length="20.000" Offset="05.000"/></Track>""")
    curves = {"a.wav": _curve(60, [(8.0, 12.0)])}
    (span,) = _intervals(session, curves, tracks=["Olli"])
    # Tiedoston 8–12 s on aikajanalla 10 + (8 − 5) = 13 … 17.
    assert abs(span[0] - 13.0) <= 2 * HOP_SEC
    assert abs(span[1] - 17.0) <= 2 * HOP_SEC


def test_any_track_counts_and_short_gaps_close(tmp_path):
    session = _session(tmp_path, """
      <Track Name="Olli"><Region Ref="1" Length="30.000"/></Track>
      <Track Name="Kari"><Region Ref="2" Length="30.000"/></Track>""")
    curves = {
        "a.wav": _curve(30, [(1.0, 5.0), (6.0, 8.0)]),   # 1 s tauko: suljetaan
        "b.wav": _curve(30, [(8.5, 10.0), (20.0, 22.0)]),
    }
    spans = _intervals(session, curves, tracks=["Olli", "Kari"])
    assert len(spans) == 2
    assert abs(spans[0][0] - 1.0) <= 2 * HOP_SEC
    assert abs(spans[0][1] - 10.0) <= 2 * HOP_SEC
    assert abs(spans[1][0] - 20.0) <= 2 * HOP_SEC


def test_muted_regions_and_other_tracks_are_not_speech(tmp_path):
    session = _session(tmp_path, """
      <Track Name="Olli"><Region Ref="1" Length="30.000" Muted="True"/></Track>
      <Track Name="musa"><Region Ref="3" Length="30.000"/></Track>""")
    curves = {"a.wav": _curve(30, [(1.0, 5.0)]), "m.wav": _curve(30, [(0.0, 30.0)])}
    assert _intervals(session, curves, tracks=["Olli"]) == []


def test_threshold_is_over_the_tracks_own_floor(tmp_path):
    """Hiljainen mikki: puhe −60 dB, pohja −100. Kiinteä kynnys ei näkisi
    sitä; pohja + ``FLOOR_MARGIN_DB`` näkee."""
    session = _session(tmp_path, """
      <Track Name="Olli"><Region Ref="1" Length="30.000"/></Track>""")
    quiet = np.full(int(30 / HOP_SEC), -100.0, dtype=np.float32)
    quiet[int(2 / HOP_SEC):int(4 / HOP_SEC)] = -60.0
    (span,) = _intervals(session, {"a.wav": quiet}, tracks=["Olli"])
    assert abs(span[0] - 2.0) <= 2 * HOP_SEC
