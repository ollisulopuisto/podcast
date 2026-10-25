"""Writing: a new project spine made of pieces of the original's.

``conform`` takes a project that was read and an ordered list of kept ranges of
its timeline, and returns a new FCPXML document in which those ranges are laid
back to back. It is a ripple edit and nothing else: no gaps, no reordering, no
range used twice. Everything it cannot cut correctly it refuses with a
``ConformError`` and a stable code, instead of writing XML that looks right and
plays wrong.

What a piece of a spine item is: the same element, with its ``start`` and
``duration`` narrowed to the piece and its ``offset`` moved to where the piece
now sits. What is attached to it (connected clips, titles, keywords) is narrowed
to the same range in the host's local time, which is what Final Cut's own
ripple delete does. The resources are copied as they are, so Final Cut finds the
same media.

Every boundary is snapped to the sequence's frame grid, and the boundary is
what is snapped, not the duration, so nothing drifts over many cuts. Audio cuts
are therefore frame-accurate here: whether sub-frame audio edits are allowed in
FCPXML is not known and is not used.
"""

from __future__ import annotations

import copy
import os
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from .model import Timeline
from .read import (
    LEAF_TAGS,
    SPINE_TAGS,
    _collect_resources,
    _pick_container,
    _resolve,
    read_fcpxml,
)
from .timeline import ZERO, format_time, frames_to_time, parse_time, to_frames

# What stands on a clip with a time of its own: it is narrowed to a range.
TIMED_TAGS = SPINE_TAGS | {"caption"}
# What cannot be cut without changing what it means.
UNSUPPORTED_TAGS = ("timeMap", "conform-rate")

Piece = tuple[Fraction, Fraction]


class ConformError(Exception):
    """The pieces cannot be laid out, or the source cannot be cut. ``code`` is stable.

    Codes: ``no_pieces``, ``empty_piece``, ``unordered``, ``overlap``,
    ``outside_timeline`` (about the pieces); ``not_a_project`` (the source has no
    spine); ``unsupported`` (a ``timeMap`` or ``conform-rate`` in what is kept),
    ``nested_spine`` (a secondary storyline in what is kept),
    ``keyframes_cross_cut`` (an animation that a cut would change), ``no_duration``
    (an element with no way to tell its length). ``detail`` says where.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def snap_pieces(pieces: Sequence[Piece], frame_duration: Fraction) -> list[Piece]:
    """The pieces with every boundary on the frame grid; what ``conform`` will use.

    A boundary goes to the nearest frame (a half rounds up), so two pieces that
    share a boundary keep sharing it. A piece shorter than half a frame snaps to
    nothing and is dropped. Kuulas can call this to know the lengths, and so the
    positions on the new timeline, before it writes.
    """
    snapped: list[Piece] = []
    for lo, hi in pieces:
        a = frames_to_time(to_frames(lo, frame_duration), frame_duration)
        b = frames_to_time(to_frames(hi, frame_duration), frame_duration)
        if b > a:
            snapped.append((a, b))
    return snapped


@dataclass
class _Plan:
    """What the cutting needs to know about the source."""

    assets: dict
    keyframes: str


def _check_pieces(pieces: Sequence[Piece], end: Fraction) -> None:
    if not pieces:
        raise ConformError("no_pieces")
    previous: Piece | None = None
    for lo, hi in pieces:
        if hi <= lo:
            raise ConformError("empty_piece", f"{format_time(lo)}..{format_time(hi)}")
        if lo < 0 or hi > end:
            raise ConformError(
                "outside_timeline", f"{format_time(lo)}..{format_time(hi)} of {format_time(end)}"
            )
        if previous is not None:
            if lo < previous[0]:
                raise ConformError("unordered", f"{format_time(lo)} after {format_time(previous[0])}")
            if lo < previous[1]:
                raise ConformError("overlap", f"{format_time(lo)} inside {format_time(previous[1])}")
        previous = (lo, hi)


def _extent(elem, plan: _Plan) -> tuple[Fraction, Fraction, Fraction]:
    """An element's ``offset``, ``start`` and ``duration``, as the reader takes them."""
    duration = parse_time(elem.get("duration"), ZERO)
    ref = elem.get("ref", "")
    if duration <= 0 and elem.tag in LEAF_TAGS and ref in plan.assets:
        duration = plan.assets[ref].duration
    if duration <= 0:
        raise ConformError("no_duration", _label(elem))
    return parse_time(elem.get("offset"), ZERO), parse_time(elem.get("start"), ZERO), duration


def _label(elem) -> str:
    return elem.get("name") or elem.tag


def _trim(elem, lo: Fraction, hi: Fraction, plan: _Plan):
    """A copy of ``elem`` narrowed to ``[lo, hi)`` of its parent's local time, or None.

    Content time ``t`` is parent time ``offset + (t - start)``. The copy keeps the
    same content at the same parent times and only shortens it, so ``start``
    moves by the amount cut from the front and what is attached keeps its own
    offsets, which are in this element's local time.
    """
    offset, start, duration = _extent(elem, plan)
    first, last = max(lo, offset), min(hi, offset + duration)
    if last <= first:
        return None
    new = ET.Element(elem.tag, dict(elem.attrib))
    new_start = start + (first - offset)
    new.set("offset", format_time(first))
    new.set("start", format_time(new_start))
    new.set("duration", format_time(last - first))
    for child in elem:
        kept = _child(child, elem, new_start, new_start + (last - first), plan)
        if kept is not None:
            new.append(kept)
    return new


def _child(child, owner, lo: Fraction, hi: Fraction, plan: _Plan):
    """What becomes of one child of a cut element, in its local time ``[lo, hi)``."""
    tag = child.tag
    if tag in UNSUPPORTED_TAGS:
        raise ConformError("unsupported", f"{tag} on {_label(owner)}")
    if tag == "spine":
        raise ConformError("nested_spine", f"on {_label(owner)}")
    if tag == "transition":
        return None
    if tag in ("marker", "chapter-marker"):
        at = parse_time(child.get("start"), ZERO)
        return copy.deepcopy(child) if lo <= at < hi else None
    if tag == "keyword":
        return _trim_range(child, lo, hi)
    if tag == "audition":
        new = ET.Element(tag, dict(child.attrib))
        for alternative in child:
            kept = _trim(alternative, lo, hi, plan)
            if kept is not None:
                new.append(kept)
        if not len(new):
            return None
        if "offset" in new.attrib:
            # The alternatives share one offset, and the audition stands where they do.
            new.set("offset", new[0].get("offset"))
        return new
    if tag in TIMED_TAGS:
        return _trim(child, lo, hi, plan)
    if child.find(".//keyframe") is not None:
        return _clip_keyframes(child, owner, lo, hi, plan)
    return copy.deepcopy(child)


def _trim_range(elem, lo: Fraction, hi: Fraction):
    """An element with only a ``start`` and a ``duration`` (a keyword), narrowed."""
    start = parse_time(elem.get("start"), ZERO)
    first, last = max(lo, start), min(hi, start + parse_time(elem.get("duration"), ZERO))
    if last <= first:
        return None
    new = copy.deepcopy(elem)
    new.set("start", format_time(first))
    new.set("duration", format_time(last - first))
    return new


def _clip_keyframes(elem, owner, lo: Fraction, hi: Fraction, plan: _Plan):
    """An effect whose animation is cut only if the caller accepted the cost.

    Keyframe times are in the clip's local time, which does not move, so those
    inside ``[lo, hi]`` stay as they are. One outside means the cut changes the
    curve at the edge of the piece (the value there was between two keyframes
    and is now the first one's); that is refused unless ``keyframes="clip"``.
    """
    new = copy.deepcopy(elem)
    parents = {child: parent for parent in new.iter() for child in parent}
    for animation in list(new.iter("keyframeAnimation")):
        outside = [
            k for k in animation.findall("keyframe")
            if not lo <= parse_time(k.get("time"), ZERO) <= hi
        ]
        if not outside:
            continue
        if plan.keyframes == "refuse":
            raise ConformError("keyframes_cross_cut", f"{elem.tag} on {_label(owner)}")
        for key in outside:
            animation.remove(key)
        if not len(animation):
            holder = parents[animation]
            holder.remove(animation)
            if holder.tag == "param" and not len(holder) and holder.get("value") is None:
                parents[holder].remove(holder)
    return new


def conform(
    source: Timeline | str | os.PathLike,
    pieces: Sequence[Piece],
    *,
    name: str | None = None,
    uid: str | None = None,
    keyframes: str = "refuse",
) -> bytes:
    """A new FCPXML document: the source project cut to ``pieces`` and laid back to back.

    ``source`` is a path or a ``Timeline`` the reader gave. ``pieces`` are
    ``(source_start, source_end)`` in Fraction seconds on the source timeline
    (zero-based, as the reader shows it), in order and not overlapping. The
    document has the source's resources as they are, one new event
    ``"<name> (kuulas)"`` and in it one new project ``name`` (the source
    project's own by default) with a fresh ``uid``; the source's FCPXML version
    and its start timecode are kept.

    ``keyframes`` says what to do with an animation that a cut would change:
    ``"refuse"`` (the default) or ``"clip"`` (drop the keyframes outside the
    piece and accept that the value at its edge is not interpolated).

    Raises ``ConformError``; see there for its codes.
    """
    if keyframes not in ("refuse", "clip"):
        raise ValueError(f"keyframes must be 'refuse' or 'clip', not {keyframes!r}")
    timeline = source if isinstance(source, Timeline) else read_fcpxml(os.fspath(source))
    if not timeline.spine:
        raise ConformError("not_a_project", f"a {timeline.kind} has no spine to cut")
    _check_pieces(pieces, max(item.end for item in timeline.spine))
    frame = (
        timeline.format.frame_duration
        if timeline.format is not None and timeline.format.frame_duration
        else timeline.frame_duration
    )
    snapped = snap_pieces(pieces, frame)
    if not snapped:
        raise ConformError("empty_piece", "every piece is shorter than a frame")

    root = ET.parse(_resolve(timeline.source_path)).getroot()
    sequence, _kind, project_name = _pick_container(root)
    plan = _Plan(_collect_resources(root)[0], keyframes)
    tc_start = parse_time(sequence.get("tcStart"), ZERO)

    spine = ET.Element("spine")
    program = ZERO
    for lo, hi in snapped:
        first, last = lo + tc_start, hi + tc_start  # in the sequence's own time
        for child in sequence.find("spine"):
            if child.tag == "transition":
                # Kept only if all of it is inside this piece: it spans a join
                # of two clips, and a cut there would leave it joining nothing.
                at, length = parse_time(child.get("offset"), ZERO), parse_time(
                    child.get("duration"), ZERO)
                if first <= at and at + length <= last:
                    moved = copy.deepcopy(child)
                    moved.set("offset", format_time(tc_start + program + (at - first)))
                    spine.append(moved)
                continue
            if child.tag not in SPINE_TAGS:
                continue
            kept = _trim(child, first, last, plan)
            if kept is not None:
                kept.set("offset", format_time(
                    tc_start + program + (parse_time(kept.get("offset")) - first)))
                spine.append(kept)
        program += hi - lo

    cut = ET.Element("sequence", dict(sequence.attrib))
    cut.set("duration", format_time(program))
    cut.append(spine)
    title = name or project_name or "Cut"
    project = ET.Element("project", {"name": title, "uid": uid or str(uuid.uuid4()).upper()})
    project.append(cut)
    event = ET.Element("event", {"name": f"{title} (kuulas)"})
    event.append(project)
    library = ET.Element("library")
    library.append(event)
    document = ET.Element("fcpxml", {"version": root.get("version", "")})
    resources = root.find("resources")
    document.append(copy.deepcopy(resources) if resources is not None else ET.Element("resources"))
    document.append(library)
    ET.indent(document, space="  ")
    text = ET.tostring(document, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n{text}\n'.encode()
