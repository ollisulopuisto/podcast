"""Trailerin kolmikaistainen FCPXML.

Yksi trailer, pilkottu paloihin (``trailer.py``), kirjoitetaan kolmeen kaistaan
joilla on samat rajat ja sama tahti:

* **spine**: koko ruudun 9:16-rajaus (1080×1920), mukana trailerin ääni.
* **kaista 1**: yläpuolikas, 1080×960 ylhäällä, oletuksena päällä.
* **kaista 2**: alapuolikas, 1080×960 alhaalla, oletuksena pois päältä.

Puolikkaat ovat samankokoiset ja samoin kehystetyt, joten oma kuva voi
istua paikallaan kun Olli vaihtaa kaistaa Final Cutissa (Clip › Disable).
Kaistoilla ei ole omaa ääntä (``srcEnable="video"``): ääni soi yhdeltä
klipiltä, ei kolmelta. Ääntä ei vaimenneta; se on käyttäjän työtä.

Rajaus, konformi ja siirto ovat samat jotka pystyviennin pinon paneelit
kirjoittavat (``layout.fcp_panel``, ``write._panel_lines``): sama laskenta,
yksi paikka.
"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
from xml.sax.saxutils import quoteattr

from .. import layout as screen_layout
from ..i18n import t
from ..model import MediaItem
from ..timeline import format_time, frames_str, to_frames
from ..trailer import TrailerSource
from ..trailer import window as crop_window
from .write import (
    DIALECT_FCP,
    DIALECT_RESOLVE,
    DIALECTS,
    RESOLVE_VERSION,
    WriteError,
    _asset_lines,
    _Formats,
    _panel_lines,
    file_url,
)

LANES = ("top", "bottom", "none")


def _quantize(pieces, frame_duration: Fraction, total_frames: int):
    """Palat kehysrajoiksi ``(alku, loppu)``: tiiviisti, kasvavasti, ei aukkoja."""
    edges = [0]
    for start, _end in pieces[1:]:
        f = min(max(to_frames(start, frame_duration), edges[-1]), total_frames)
        edges.append(f)
    edges.append(min(to_frames(pieces[-1][1], frame_duration), total_frames))
    out = []
    for index, a in enumerate(edges[:-1]):
        b = edges[index + 1]
        if b > a:
            out.append((index, a, b))
    return out


def _panel_for(kind: str) -> screen_layout.Panel:
    if kind == "full":
        return screen_layout.Panel(0, 0, screen_layout.PROJECT_W,
                                   screen_layout.PROJECT_H)
    return screen_layout.stack_panel(1 if kind == "top" else -1)


def _lane_lines(kind: str, src: TrailerSource, x: float, indent: str) -> list[str]:
    panel = _panel_for(kind)
    win = crop_window(src.width, src.height, panel.w, panel.h, x)
    return _panel_lines(
        screen_layout.fcp_panel(panel, win, src.width, src.height), indent)


def build_trailer_fcpxml(
    src: TrailerSource,
    pieces: list[tuple[float, float]],
    xs: list[float],
    project_name: str,
    *,
    enabled_lane: str = "top",
    dialect: str = DIALECT_FCP,
    version: str = "1.10",
) -> str:
    """FCPXML-merkkijono. ``xs`` on kohteen vaakapaikka (0–1) palaa kohden."""
    if dialect not in DIALECTS:
        raise WriteError(t("trailer.err.dialect", value=dialect))
    if enabled_lane not in LANES:
        raise WriteError(t("trailer.err.lane", value=enabled_lane))
    if not pieces or len(pieces) != len(xs):
        raise WriteError(t("trailer.err.pieces"))
    if not src.width or not src.height:
        raise WriteError(t("trailer.err.no_size", name=src.name))
    if dialect == DIALECT_RESOLVE:
        version = RESOLVE_VERSION
    fd = src.frame_duration
    total = to_frames(src.duration, fd)
    cells = _quantize(pieces, fd, total)
    if not cells:
        raise WriteError(t("trailer.err.no_cell"))

    counter = [0]

    def next_id() -> str:
        counter[0] += 1
        return f"r{counter[0]}"

    formats = _Formats()
    seq_format = formats.get(screen_layout.PROJECT_W, screen_layout.PROJECT_H, fd, next_id)
    src_format = formats.get(src.width, src.height, fd, next_id)
    asset_id = next_id()
    item = MediaItem(
        key=src.name, name=src.name, path=src.path, src=file_url(src.path),
        asset_duration=src.duration, has_video=True, has_audio=src.has_audio,
        width=src.width, height=src.height, frame_duration=fd,
        audio_rate=src.audio_rate, audio_channels=src.audio_channels,
        placements=[], angle_ids=[])
    asset = _asset_lines(item, asset_id, src_format, dialect=dialect)
    # Liitetyt kaistat saavat oman, äänettömän assetin: Final Cut soittaa
    # äänellisen asset-clipin äänen vaikka srcEnable="video", ja päällä oleva
    # puolikas kaksinkertaistaisi spinen äänen.
    lane_asset_id = asset_id
    if src.has_audio:
        lane_asset_id = next_id()
        asset += _asset_lines(
            replace(item, name=f"{src.name} (video)", has_audio=False,
                    audio_rate=0, audio_channels=0),
            lane_asset_id, src_format, dialect=dialect)

    body: list[str] = []
    for index, a, b in cells:
        x = float(xs[index])
        dur = frames_str(b - a, fd)
        start = frames_str(a, fd)
        label = f"{index + 1:02d}"
        attrs = [
            f'ref="{asset_id}"', f'offset="{frames_str(a, fd)}"',
            f"name={quoteattr('Full ' + label)}", f'start="{start}"',
            f'duration="{dur}"', f'format="{src_format}"', 'tcFormat="NDF"',
        ]
        body.append("            <asset-clip " + " ".join(attrs) + ">")
        body += _lane_lines("full", src, x, "              ")
        for lane, kind in ((1, "top"), (2, "bottom")):
            on = enabled_lane == kind
            c = [
                f'ref="{lane_asset_id}"', f'lane="{lane}"', f'offset="{start}"',
                f"name={quoteattr(kind.capitalize() + ' ' + label)}",
                f'start="{start}"', f'duration="{dur}"', 'srcEnable="video"',
            ]
            if not on:
                c.append('enabled="0"')
            body.append("              <asset-clip " + " ".join(c) + ">")
            body += _lane_lines(kind, src, x, "                ")
            body.append("              </asset-clip>")
        body.append("            </asset-clip>")

    length = cells[-1][2]
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        f'<fcpxml version="{version}">',
        "  <resources>",
        *formats.lines,
        *asset,
        "  </resources>",
        "  <library>",
        f"    <event name={quoteattr(project_name)}>",
        f"      <project name={quoteattr(project_name)}>",
        f'        <sequence format="{seq_format}" '
        f'duration="{frames_str(length, fd)}" '
        f'tcStart="{format_time(Fraction(0))}" tcFormat="NDF" '
        'audioLayout="stereo" audioRate="48k">',
        "          <spine>",
        *body,
        "          </spine>",
        "        </sequence>",
        "      </project>",
        "    </event>",
        "  </library>",
        "</fcpxml>",
    ]
    return "\n".join(out) + "\n"
