"""FCPXML:n rationaaliaika.

Aika elää nyt `fcpxml`-paketissa (`fcpxml.timeline`), jotta autoraffkat ja
kuulas lukevat ja kirjoittavat Final Cutin aikoja samalla koodilla. Tämä
moduuli on vain vanha tuontipolku: kaikki viennin ja luvun aika kulkee yhä
Fractionina tämän nimen kautta, mutta määritelmä on paketissa.
"""

from __future__ import annotations

from fcpxml.timeline import (
    FPS_LABELS,
    ZERO,
    format_name,
    format_time,
    fps_of,
    frames_str,
    frames_to_time,
    parse_fps,
    parse_time,
    to_frames,
)

__all__ = [
    "FPS_LABELS",
    "ZERO",
    "format_name",
    "format_time",
    "fps_of",
    "frames_str",
    "frames_to_time",
    "parse_fps",
    "parse_time",
    "to_frames",
]
