"""Reading FCPXML.

Three sources are supported, and all of them give the same information:

* ``<sync-clip>`` -- a synchronised clip in Final Cut, cameras and mics on lanes
* ``<project><sequence><spine>`` -- a timeline laid out by hand
* ``<mc-clip>`` -- a multicam clip, cameras and mics as angles

Sync is read from the XML, not computed. The frame rate is whatever the caller's
probe says of the first video file it can read: the media always beats the XML's
formats, which can lie (60 fps material in an exported 25 fps project). The
declaration is used only when no media can be read, and 1/25 comes last.

Time conversion: a clip's ``offset`` is in the host's local time base, whose
zero is the host's ``start``. A child's absolute timeline position is therefore
``host_absolute + (child_offset - host_start)``.

In a multicam the host is the ``<mc-clip>`` and the content is the angles of
``<media><multicam>``. An angle's content spans the whole multicam, so it must
be clipped to the ``mc-clip``'s duration -- else two parts of the same multicam
would produce overlapping occurrences.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from fractions import Fraction
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname
from xml.etree import ElementTree as ET

from .model import (
    Format,
    Marker,
    MediaItem,
    MulticamRef,
    Placement,
    SpineItem,
    Timeline,
    Track,
    Transition,
)
from .timeline import ZERO, parse_time

# Elements that refer straight to an asset.
LEAF_TAGS = {"asset-clip", "video", "audio"}
# Elements that are walked into.
CONTAINER_TAGS = {
    "clip",
    "sync-clip",
    "spine",
    "ref-clip",
    "mc-clip",
    "gap",
    "mc-angle",
}
# What a clip can carry that the times in a ``Placement`` do not account for.
UNSUPPORTED_TAGS = ("timeMap", "conform-rate")
# Left out, and counted in ``Timeline.skipped``.
SKIPPED_TAGS = {"title", "caption"}
# What can stand on the spine itself.
SPINE_TAGS = LEAF_TAGS | CONTAINER_TAGS | {"audition", "title"}

DEFAULT_FRAME_DURATION = Fraction(1, 25)

# The XML inside a ``.fcpxmld`` bundle.
BUNDLE_INNER = "Info.fcpxml"

# The span that occurrences are clipped to. ``None`` = no clipping.
Bounds = tuple[Fraction, Fraction] | None

# Given a media item, the frame duration of its file, or None when the file is
# not there or has none. Called for the first video items whose file exists.
FrameDurationProbe = Callable[[MediaItem], Fraction | None]


class ReadError(Exception):
    """The XML cannot be read. ``code`` is stable; ``detail`` is for a log.

    Codes: ``unreadable`` (the file cannot be opened), ``bundle_without_info``
    (a ``.fcpxmld`` folder with no ``Info.fcpxml``), ``bad_xml``, ``bad_root``
    (``detail`` is the root tag), ``bad_time`` (a time that is not a time),
    ``no_project`` (no project and no sync clip), ``no_media`` (a timeline with
    nothing on it). A host translates the code; the text of ``str(error)`` is
    not for people.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ------------------------------------------------------------------ resources


@dataclass
class _Asset:
    """An ``<asset>`` resource as it is. No timeline positions yet."""

    id: str
    name: str
    path: str
    src: str
    start: Fraction
    duration: Fraction
    has_video: bool
    has_audio: bool
    audio_rate: int
    audio_channels: int
    audio_sources: int
    video_sources: int
    format_id: str


def _src_to_path(src: str) -> str:
    """A ``media-rep src`` as a file path.

    Final Cut writes the path as a URL-encoded file URL, so umlauts and spaces
    come in percent form.
    """
    if not src:
        return ""
    if src.startswith("file://"):
        parsed = urlparse(src)
        # On Windows the path is ``/C:/...`` and has to become a drive and
        # backslashes; on POSIX ``url2pathname`` is just ``unquote``. A network
        # share is ``file://server/share``, in which case the netloc belongs to
        # the path.
        host = "" if parsed.netloc in ("", "localhost") else parsed.netloc
        return url2pathname(f"//{host}{parsed.path}" if host else parsed.path)
    return unquote(src)


def _int_attr(elem, name: str, default: int) -> int:
    """An integer attribute. Missing or invalid gives the default."""
    raw = elem.get(name)
    if raw is None:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _audio_rate(raw: str | None) -> int:
    """``audioRate`` is either a number or ``"48k"``."""
    if not raw:
        return 48000
    text = raw.strip().lower()
    try:
        if text.endswith("k"):
            return int(round(float(text[:-1]) * 1000))
        return int(round(float(text)))
    except ValueError:
        return 48000


def _collect_resources(root) -> tuple[dict[str, _Asset], dict[str, dict], dict]:
    """Collects the ``<resources>`` block: assets, formats and media wrappers.

    Returns the triple ``(assets, formats, medias)`` keyed by id. ``medias``
    holds the ``<media>`` elements as they are, because a compound clip and a
    multicam are only entered in the walking phase.
    """
    assets: dict[str, _Asset] = {}
    formats: dict[str, dict] = {}
    medias: dict[str, ET.Element] = {}

    for res in root.iter():
        if res.tag == "format":
            formats[res.get("id", "")] = {
                "frame_duration": parse_time(res.get("frameDuration"), ZERO) or None,
                "width": _int_attr(res, "width", 0),
                "height": _int_attr(res, "height", 0),
                "name": res.get("name", ""),
            }
        elif res.tag == "asset":
            rep = res.find("media-rep")
            src = rep.get("src", "") if rep is not None else res.get("src", "")
            assets[res.get("id", "")] = _Asset(
                id=res.get("id", ""),
                name=res.get("name", "") or os.path.basename(_src_to_path(src)),
                path=_src_to_path(src),
                src=src,
                start=parse_time(res.get("start"), ZERO),
                duration=parse_time(res.get("duration"), ZERO),
                has_video=res.get("hasVideo") == "1"
                or _int_attr(res, "videoSources", 0) > 0,
                has_audio=res.get("hasAudio") == "1"
                or _int_attr(res, "audioSources", 0) > 0,
                audio_rate=_audio_rate(res.get("audioRate")),
                audio_channels=_int_attr(res, "audioChannels", 2),
                audio_sources=_int_attr(res, "audioSources", 1),
                video_sources=_int_attr(res, "videoSources", 1),
                format_id=res.get("format", ""),
            )
        elif res.tag == "media":
            medias[res.get("id", "")] = res

    return assets, formats, medias


# ------------------------------------------------------------------ walking


@dataclass(frozen=True)
class _State:
    """What a container hands down to everything inside it.

    ``muted`` is the audio roles a sync clip switched off, ``unsupported`` what
    an enclosing clip carries that the times do not account for (an attached
    clip inside a retimed clip is in the retimed time), ``enabled`` whether the
    path down to here is switched on.
    """

    muted: frozenset[str] = frozenset()
    unsupported: tuple[str, ...] = ()
    enabled: bool = True
    container: int | None = None


_NO_STATE = _State()


@dataclass
class _Hit:
    """One media occurrence that was found."""

    ref: str
    placement: Placement
    tag: str
    angle_id: str = ""


@dataclass
class _Ctx:
    """The state of the walk.

    ``hits`` collects the findings in order, ``seen`` stops a compound clip
    from recursing for ever if it refers to itself.
    """

    assets: dict[str, _Asset]
    formats: dict[str, dict]
    medias: dict[str, ET.Element]
    include_muted: bool = False
    hits: list[_Hit] = field(default_factory=list)
    seen: set[int] = field(default_factory=set)
    multicams: list[MulticamRef] = field(default_factory=list)
    angle_names: dict[str, str] = field(default_factory=dict)  # angleID -> name
    angle_owner: dict[str, str] = field(default_factory=dict)  # angleID -> media id
    markers: list[Marker] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    root: ET.Element | None = None  # the project's spine, when there is one
    spine: list[SpineItem] = field(default_factory=list)


def _intersect(outer: Bounds, inner: Bounds) -> Bounds:
    """The intersection of two spans. ``None`` means unbounded."""
    if outer is None:
        return inner
    if inner is None:
        return outer
    return (max(outer[0], inner[0]), min(outer[1], inner[1]))


def _muted_roles(elem) -> frozenset[str]:
    """The muted audio roles of a ``<sync-clip>``.

    Final Cut marks detached or switched-off audio with
    ``<sync-source><audio-role-source role="…" active="0"/></sync-source>``.
    Returns the roles that are explicitly off.
    """
    roles: set[str] = set()
    for source in elem.findall("sync-source"):
        for ars in source.findall("audio-role-source"):
            if ars.get("active") == "0" and ars.get("role"):
                roles.add(ars.get("role", ""))
    return frozenset(roles)


def _is_muted(elem, muted: frozenset[str]) -> bool:
    """Is the leaf element's audio muted?

    Compares the element's ``role`` or ``audioRole`` attribute with the muted
    set. FCPXML roles are hierarchical: ``dialogue.dialogue-1`` is a sub-role of
    the main role ``dialogue``. Muting works **downward**: muting ``dialogue``
    mutes ``dialogue.dialogue-1`` too, but muting the sub-role
    ``dialogue.dialogue-1`` does not mute the main role ``dialogue`` or the
    sibling ``dialogue.dialogue-2``.

    In ``<audio>`` elements the role is complete (``dialogue.dialogue-1``); an
    ``<asset-clip>``'s ``audioRole`` is usually just ``dialogue``.
    """
    if not muted:
        return False
    role = elem.get("role", "") or elem.get("audioRole", "")
    if not role:
        return False
    for m in muted:
        if m == role:
            return True
        # A muted parent role mutes the child:
        # m="dialogue" mutes role="dialogue.dialogue-1"
        if role.startswith(m + "."):
            return True
    return False


def _audio_role(elem) -> str:
    """The audio role of a leaf as Final Cut names it, ``""`` if it has none.

    An ``<audio>`` carries it in ``role``, an ``<asset-clip>`` in ``audioRole``
    or, in the newer form, in the first ``<audio-channel-source>``. A ``<video>``
    has only a picture role, which is not this.
    """
    if elem.tag == "video":
        return ""
    role = elem.get("audioRole") or (elem.get("role", "") if elem.tag == "audio" else "")
    if not role:
        channel = elem.find("audio-channel-source")
        role = channel.get("role", "") if channel is not None else ""
    return role or ""


def _unsupported(elem) -> tuple[str, ...]:
    """What ``elem`` carries that the reader does not account for."""
    return tuple(tag for tag in UNSUPPORTED_TAGS if elem.find(tag) is not None)


def _marker(elem, abs_offset: Fraction, local_start: Fraction) -> Marker:
    """A ``<marker>`` or ``<chapter-marker>`` on the timeline.

    Its ``start`` is in the time base of the clip it sits in, the same as that
    clip's ``start``, so the timeline position goes through the host's offset.
    """
    chapter = elem.tag == "chapter-marker"
    completed = elem.get("completed")
    return Marker(
        time=abs_offset + (parse_time(elem.get("start"), ZERO) - local_start),
        name=elem.get("value", ""),
        kind="chapter" if chapter else "marker",
        duration=ZERO if chapter else parse_time(elem.get("duration"), ZERO),
        completed=None if completed is None else completed == "1",
    )


def _in(bounds: Bounds, seconds: Fraction) -> bool:
    return bounds is None or bounds[0] <= seconds < bounds[1]


def _count(ctx: _Ctx, kind: str, n: int = 1) -> None:
    if n:
        ctx.skipped[kind] = ctx.skipped.get(kind, 0) + n


def _markers_of(elem, abs_offset: Fraction, local_start: Fraction) -> list[Marker]:
    """The markers that are direct children of ``elem``, in time order."""
    found = [
        _marker(mark, abs_offset, local_start)
        for mark in elem
        if mark.tag in ("marker", "chapter-marker")
    ]
    return sorted(found, key=lambda m: m.time)


def _register_spine_item(
    ctx: _Ctx, child, abs_offset: Fraction, local_start: Fraction
) -> int:
    """Records a top-level spine item and returns its id."""
    ref = child.get("ref", "")
    duration = parse_time(child.get("duration"), ZERO)
    if duration <= 0 and child.tag in LEAF_TAGS and ref in ctx.assets:
        duration = ctx.assets[ref].duration
    item = SpineItem(
        id=len(ctx.spine),
        kind=child.tag,
        name=child.get("name", ""),
        offset=abs_offset + (parse_time(child.get("offset"), ZERO) - local_start),
        start=parse_time(child.get("start"), ZERO),
        duration=duration,
        ref=ref,
    )
    ctx.spine.append(item)
    return item.id


def _walk(
    elem,
    abs_offset: Fraction,
    local_start: Fraction,
    ctx: _Ctx,
    depth: int = 0,
    bounds: Bounds = None,
    angle_id: str = "",
    state: _State = _NO_STATE,
) -> None:
    """Collects the media occurrences of ``elem``'s children, with absolute times.

    ``bounds`` limits the findings to the host's duration. It is needed in a
    multicam and a compound clip, whose content is longer than the piece used.

    ``state.muted`` holds the muted audio roles collected from the host's
    ``sync-source``. ``<audio>`` and ``<asset-clip>`` leaves that match are
    skipped, because Final Cut has switched them off -- unless the caller asked
    for them (``include_muted``), in which case they come with ``muted`` set.
    """
    if depth > 12:
        return
    for child in elem:
        tag = child.tag
        item_state = state
        if elem is ctx.root and tag in SPINE_TAGS:
            item_state = replace(state, container=_register_spine_item(
                ctx, child, abs_offset, local_start))

        if tag in ("marker", "chapter-marker"):
            # A leaf's own markers go on its placement, below.
            if elem.tag not in LEAF_TAGS:
                marker = _marker(child, abs_offset, local_start)
                if _in(bounds, marker.time):
                    ctx.markers.append(marker)
            continue
        if tag == "transition":
            offset = abs_offset + (parse_time(child.get("offset"), ZERO) - local_start)
            if _in(bounds, offset):
                ctx.transitions.append(
                    Transition(
                        offset=offset,
                        duration=parse_time(child.get("duration"), ZERO),
                        name=child.get("name", ""),
                        has_audio=child.find("filter-audio") is not None,
                        has_video=child.find("filter-video") is not None,
                    )
                )
            continue
        if tag in SKIPPED_TAGS:
            _count(ctx, tag)
            continue
        if tag not in LEAF_TAGS and tag not in CONTAINER_TAGS and tag != "audition":
            continue

        child_offset = parse_time(child.get("offset"), ZERO)
        child_start = parse_time(child.get("start"), ZERO)
        child_dur = parse_time(child.get("duration"), ZERO)
        child_abs = abs_offset + (child_offset - local_start)
        lane = _int_attr(child, "lane", 0)
        child_state = replace(
            item_state,
            enabled=item_state.enabled and child.get("enabled") != "0",
            unsupported=item_state.unsupported + _unsupported(child),
        )

        if tag == "audition":
            # Only the active alternative, which is the first child.
            first = next(iter(child), None)
            if first is not None:
                _walk(child, abs_offset, local_start, ctx, depth + 1, bounds, angle_id,
                      item_state)
            continue

        if tag == "gap":
            _walk(child, child_abs, child_start, ctx, depth + 1, bounds, angle_id,
                  child_state)
            continue

        if tag == "spine":
            # A secondary storyline: the children's offsets are from the spine's own zero.
            _walk(child, child_abs, ZERO, ctx, depth + 1, bounds, angle_id, child_state)
            continue

        ref = child.get("ref", "")
        if tag in LEAF_TAGS and ref in ctx.assets:
            if child_dur <= 0:
                child_dur = ctx.assets[ref].duration
            # Muted audio is skipped: Final Cut has marked the role off in
            # the sync-source.
            muted = _is_muted(child, item_state.muted)
            if muted and not ctx.include_muted:
                continue
            placement = _clip(child_abs, child_start, child_dur, lane, bounds)
            if placement is not None:
                placement.role = _audio_role(child)
                placement.muted = muted
                placement.enabled = child_state.enabled
                placement.unsupported = child_state.unsupported
                placement.container = item_state.container
                placement.markers = [
                    m
                    for m in _markers_of(child, child_abs, child_start)
                    if placement.offset <= m.time < placement.end
                ]
                ctx.hits.append(_Hit(ref, placement, tag, angle_id))
            _count(ctx, "filter-video", len(child.findall("filter-video")))
            # Clips attached inside the asset-clip.
            _walk(child, child_abs, child_start, ctx, depth + 1, bounds, angle_id,
                  child_state)
            continue

        if tag == "mc-clip" and ref in ctx.medias:
            _walk_multicam(child, ctx, child_abs, child_start, child_dur, depth, bounds,
                           child_state)
            continue

        if tag == "ref-clip" and ref in ctx.medias:
            media_elem = ctx.medias[ref]
            if id(media_elem) in ctx.seen:
                continue
            ctx.seen.add(id(media_elem))
            inner = media_elem.find("sequence")
            if inner is not None:
                spine = inner.find("spine")
                tc = parse_time(inner.get("tcStart"), ZERO)
                if spine is not None:
                    span = _intersect(bounds, _span(child_abs, child_dur))
                    _walk(
                        spine,
                        child_abs - (child_start - tc),
                        ZERO,
                        ctx,
                        depth + 1,
                        span,
                        angle_id,
                        child_state,
                    )
            ctx.seen.discard(id(media_elem))
            _walk(child, child_abs, child_start, ctx, depth + 1, bounds, angle_id,
                  child_state)
            continue

        if tag == "video" and ref:
            # A ``<video>`` that refers to something that is not an asset is a
            # generator: a colour, a placeholder. Counted, nothing more.
            _count(ctx, "generator")

        # clip / sync-clip and unknown references.
        # A sync-clip can mute audio roles: collect them for the children.
        if tag == "sync-clip":
            child_state = replace(child_state, muted=item_state.muted | _muted_roles(child))
        _walk(child, child_abs, child_start, ctx, depth + 1, bounds, angle_id,
              child_state)


def _span(offset: Fraction, duration: Fraction) -> Bounds:
    """A clip's own span, or ``None`` if no duration was stated."""
    return (offset, offset + duration) if duration > 0 else None


def _clip(
    offset: Fraction, start: Fraction, duration: Fraction, lane: int, bounds: Bounds
) -> Placement | None:
    """An occurrence clipped to the host's span.

    When it is clipped from the left, the source time moves by the same amount,
    so the correspondence between timeline time and file time holds.
    """
    lo, hi = offset, offset + duration
    if bounds is not None:
        lo = max(lo, bounds[0])
        hi = min(hi, bounds[1])
    if hi <= lo:
        return None
    return Placement(lo, start + (lo - offset), hi - lo, lane)


def _walk_multicam(
    child,
    ctx: _Ctx,
    child_abs: Fraction,
    child_start: Fraction,
    child_dur: Fraction,
    depth: int,
    bounds: Bounds,
    state: _State,
) -> None:
    """``<mc-clip>``: every angle, each with its own angleID.

    The angles' content is in the multicam's own time base, whose zero is
    ``tcStart``. The correspondence between timeline and multicam comes from the
    ``mc-clip``'s ``start``, and the duration clips everything found.
    """
    media_elem = ctx.medias[child.get("ref", "")]
    mcam = media_elem.find("multicam")
    if mcam is None or id(media_elem) in ctx.seen:
        return
    ctx.seen.add(id(media_elem))

    tc = parse_time(mcam.get("tcStart"), ZERO)
    base = child_abs - (child_start - tc)
    span = _intersect(bounds, _span(child_abs, child_dur))

    # The clip's own markers: in the clip's time base, which is ``start``.
    ctx.markers += [
        m for m in _markers_of(child, child_abs, child_start) if _in(span, m.time)
    ]

    angle_ids: list[str] = []
    for angle in mcam.findall("mc-angle"):
        aid = angle.get("angleID", "")
        if not aid:
            continue
        angle_ids.append(aid)
        ctx.angle_names.setdefault(aid, angle.get("name", "") or aid)
        ctx.angle_owner.setdefault(aid, media_elem.get("id", ""))
        _walk(angle, base, ZERO, ctx, depth + 1, span, aid, state)

    ctx.seen.discard(id(media_elem))
    ctx.multicams.append(
        MulticamRef(
            media_id=media_elem.get("id", ""),
            name=child.get("name", "") or media_elem.get("name", ""),
            offset=child_abs,
            duration=child_dur,
            start=child_start,
            angle_ids=angle_ids,
            angle_roles=_source_roles(child),
        )
    )


def _source_roles(mc_clip) -> dict[str, str]:
    """The ``<mc-clip>``'s per-angle audio roles as they are."""
    roles: dict[str, str] = {}
    for source in mc_clip.findall("mc-source"):
        aid = source.get("angleID", "")
        role = source.find("audio-role-source")
        if aid and role is not None and role.get("role"):
            roles[aid] = role.get("role", "")
    return roles


# ------------------------------------------------------------------ tracks


def _group_key(name: str) -> str:
    """An angle's name as a grouping key.

    The parts are usually told apart by a single letter -- ``"host a Track2"``
    and ``"host b Track2"`` are the same mic -- so one-letter words are dropped.
    A bare number is a valid angle name (``"1"``), so numbers are left alone.
    """
    tokens = [t for t in re.split(r"[\s_]+", name.strip().lower()) if t]
    kept = [t for t in tokens if not (len(t) == 1 and t.isalpha())]
    return " ".join(kept or tokens)


def _common_name(names: list[str]) -> str:
    """What the names have in common: the words that differ left out, order kept.

    A group's key comes from the file names and not from the angle's name,
    because angle names and angleIDs change from one export to the next.
    ``"CAM 1 01"`` and ``"CAM 1 02"`` give ``"CAM 1"``, which points at the same
    camera even when the angles have been numbered anew.
    """
    if len(set(names)) <= 1:
        return names[0]
    split = [re.split(r"\s+", n.strip()) for n in names]
    if len({len(t) for t in split}) != 1:
        return names[0]
    kept = [tokens[0] for tokens in zip(*split, strict=True) if len(set(tokens)) == 1]
    return " ".join(kept) or names[0]


def _part_name(stem: str) -> str:
    """A file name without the part number: ``"Tomi_001"`` -> ``"Tomi"``.

    A part number is recognised by its leading zero (``01``, ``001``): a bare
    ``1`` is a camera's number (``"FOCUS CAM 1 01"`` -> ``"FOCUS CAM 1"``) and
    is not dropped.
    """
    tokens = _tokens(stem)
    kept = [t for t in tokens if not (t.isdigit() and len(t) >= 2 and t[0] == "0")]
    return " ".join(kept or tokens)


def _tokens(stem: str) -> list[str]:
    return [t for t in re.split(r"[\s_\-]+", stem.strip()) if t]


def _counter(token: str) -> str | None:
    """A word's pattern as a part counter, or ``None`` if it cannot be one.

    A counter is a single letter (``Vieras-A``) or a word with digits
    (``Tomi 1``, ``ZOOM0001``); the digits are replaced by a mark in the
    pattern so that ``ZOOM0001`` and ``ZOOM0002`` have the same pattern.
    """
    if len(token) == 1 and token.isalpha():
        return "<letter>"
    if any(c.isdigit() for c in token):
        return re.sub(r"\d+", "#", token.lower())
    return None


def _group_sounds(stems: list[str], owners: list[set[str]]) -> list[tuple[str, list[int]]]:
    """Mic files as tracks across the parts: ``(name, indices)``.

    First the same name without a zero-led part number (``Tomi_001``,
    ``Tomi_002``). Then those that are left, whose names differ in one counter
    position (``Tomi 1``/``Tomi 2``, ``Vieras-A``/``Vieras-B``,
    ``ZOOM0001_Tr2``/``ZOOM0002_Tr2``). ``owners`` is each file's multicams:
    two files of one multicam are never merged, and if two files of the same
    multicam fit a pattern, nothing is merged -- there is no telling which
    carries on, and a wrong guess would make two people one track. A file left
    unmerged is only one card too many.
    """
    groups: list[list[int]] = []
    for index, stem in enumerate(stems):
        name = _part_name(stem).lower()
        for members in groups:
            taken = set().union(*(owners[m] for m in members))
            if _part_name(stems[members[0]]).lower() == name and not owners[index] & taken:
                members.append(index)
                break
        else:
            groups.append([index])

    classes: dict[tuple, list[int]] = {}
    for members in groups:
        if len(members) != 1:
            continue
        tokens = _tokens(stems[members[0]])
        for pos, token in enumerate(tokens):
            pattern = _counter(token)
            if pattern is None:
                continue
            shape = tuple(pattern if k == pos else t.lower() for k, t in enumerate(tokens))
            classes.setdefault((pos, shape), []).append(members[0])
    joined: dict[int, tuple[int, list[int]]] = {}
    for (pos, _shape), members in classes.items():
        if len(members) < 2 or any(m in joined for m in members):
            continue
        seen: set[str] = set()
        for m in members:
            if owners[m] & seen:
                break
            seen |= owners[m]
        else:
            for m in members:
                joined[m] = (pos, members)

    result: list[tuple[str, list[int]]] = []
    done: set[int] = set()
    for members in groups:
        first = members[0]
        if first in done:
            continue
        if len(members) == 1 and first in joined:
            pos, together = joined[first]
            done.update(together)
            tokens = _tokens(stems[together[0]])
            varying = re.sub(r"\d+", "", tokens[pos])
            kept = tokens[:pos] + ([varying] if len(varying) > 1 else []) + tokens[pos + 1:]
            result.append((" ".join(kept), list(together)))
        else:
            result.append((_part_name(stems[first]), list(members)))
    return result


def _group_angles(
    order: list[str], names: dict[str, str], owner: dict[str, str]
) -> list[list[str]]:
    """Angles into groups: the exact name first, then a loose part-mark skip.

    Two angles of the same multicam are never merged even if the names
    normalise to the same: they are certainly different pictures.
    """
    exact: dict[str, list[str]] = {}
    for aid in order:
        exact.setdefault(names.get(aid, aid), []).append(aid)

    groups: list[list[str]] = []
    by_norm: dict[str, int] = {}
    for name, aids in exact.items():
        norm = _group_key(name)
        index = by_norm.get(norm)
        if index is not None:
            owners = {owner.get(a, "") for a in groups[index]}
            if not owners & {owner.get(a, "") for a in aids}:
                groups[index].extend(aids)
                continue
        by_norm.setdefault(norm, len(groups))
        groups.append(list(aids))
    return groups


def _build_tracks(
    media: list[MediaItem], ctx: _Ctx, angles_of: dict[str, list[str]]
) -> list[Track]:
    """Tracks from the media and the angles.

    Without a multicam every media is its own track, and the key is the file
    name as it always was, so old settings files stay valid.
    """
    by_key = {m.key: m for m in media}
    order = [
        aid for aid in ctx.angle_names if any(aid in v for v in angles_of.values())
    ]
    grouped = _group_angles(order, ctx.angle_names, ctx.angle_owner)

    tracks: list[Track] = []
    claimed: set[str] = set()
    used_keys: dict[str, int] = {}

    def add(key: str, name: str, media_keys: list[str], angle_ids: list[str]) -> None:
        count = used_keys.get(key, 0)
        used_keys[key] = count + 1
        unique = key if count == 0 else f"{key}#{count + 1}"
        items = [by_key[k] for k in media_keys if k in by_key]
        tracks.append(
            Track(
                key=unique,
                name=name,
                media_keys=media_keys,
                angle_ids=angle_ids,
                has_video=any(m.has_video for m in items),
                has_audio=any(m.has_audio for m in items),
            )
        )

    # The audio-only files of synced angles: grouped by file name below,
    # because the angle does not say whose mic is in it.
    synced_sounds: list[str] = []
    for group in grouped:
        keys = [k for k in by_key if any(a in angles_of.get(k, ()) for a in group)]
        if not keys:
            continue
        pictures = [k for k in keys if by_key[k].has_video]
        sounds = [k for k in keys if not by_key[k].has_video]
        if pictures and sounds:
            # The angle is a sync clip: a camera and a mic synchronised, as in
            # Final Cut when pairs are made into a multicam. As one track they
            # could not be given two roles, and the same angle can carry a
            # different person's mic in different parts -- part 1 the guest's,
            # part 2 Mikko's, when the guest was no longer there. The camera is
            # grouped by angle, the mic by file name.
            claimed.update(pictures)
            stems = [os.path.splitext(by_key[k].name or k)[0] for k in pictures]
            name = _part_name(_common_name(stems))
            add(name, name, pictures, list(group))
            synced_sounds += [k for k in sounds if k not in synced_sounds]
            continue
        claimed.update(keys)
        # The angle's name groups, the file name names: names and angleIDs
        # change from one export to the next, but the key ends up in the
        # settings file and has to survive a new export of the same project.
        stems = [os.path.splitext(by_key[k].name or k)[0] for k in keys]
        add(_common_name(stems), _common_name(stems), keys, list(group))

    # The same mic in different parts is one track: ``Tomi_001`` and
    # ``Tomi_002``. Two files of the same multicam are never merged -- they are
    # certainly different mics. One file can be in two angles (a part with fewer
    # mics than cameras), and it is still one track: on two tracks it would play
    # twice in the export.
    synced_sounds.sort(key=lambda k: min(
        (pl.offset for pl in by_key[k].placements), default=ZERO))
    for name, indices in _group_sounds(
        [os.path.splitext(by_key[k].name or k)[0] for k in synced_sounds],
        [{ctx.angle_owner.get(a, "") for a in angles_of.get(k, ())}
         for k in synced_sounds],
    ):
        members = [synced_sounds[i] for i in indices]
        claimed.update(members)
        angle_ids = list(dict.fromkeys(a for m in members for a in angles_of.get(m, ())))
        add(name, name, members, angle_ids)

    # Media outside the multicam are tracks of their own.
    for item in media:
        if item.key not in claimed:
            add(item.key, item.name, [item.key], [])

    # Order: pictures first, then sounds -- the same as the media list had it.
    order_index = {m.key: i for i, m in enumerate(media)}
    tracks.sort(
        key=lambda t: min(
            (order_index[k] for k in t.media_keys), default=len(order_index)
        )
    )
    return tracks


# ------------------------------------------------------------------ public


def _pick_container(root) -> tuple[ET.Element, str, str]:
    """Picks the structure to read: a project first, otherwise a sync clip.

    The name is the XML's own, ``""`` if it has none.
    """
    for project in root.iter("project"):
        sequence = project.find("sequence")
        if sequence is not None and sequence.find("spine") is not None:
            return sequence, "project", project.get("name", "")
    for sync in root.iter("sync-clip"):
        return sync, "sync-clip", sync.get("name", "")
    # A last resort: a loose sequence, or a clip at event level.
    for event in root.iter("event"):
        for sequence in event.iter("sequence"):
            if sequence.find("spine") is not None:
                return sequence, "project", event.get("name", "")
    raise ReadError("no_project")


def _stable_keys(items: list[MediaItem]) -> None:
    """Gives the media identifiers that survive a re-export of the XML."""
    used: dict[str, int] = {}
    for item in items:
        base = (
            os.path.basename(item.path) if item.path else (item.name or item.asset_id)
        )
        count = used.get(base, 0)
        used[base] = count + 1
        item.key = base if count == 0 else f"{base}#{count + 1}"


def _merge_occurrence(kept: Placement, other: Placement) -> None:
    """The same asset in the same place twice is one occurrence.

    ``<video>`` and ``<audio>`` of one asset-clip are the picture and the sound
    of it. What is known of either is known of the occurrence; it is muted only
    if everything of it is, and enabled if anything of it is.
    """
    kept.role = kept.role or other.role
    kept.muted = kept.muted and other.muted
    kept.enabled = kept.enabled or other.enabled
    kept.unsupported = tuple(dict.fromkeys(kept.unsupported + other.unsupported))
    for marker in other.markers:
        if marker not in kept.markers:
            kept.markers.append(marker)


def _resolve(path: str) -> str:
    """The XML to open: a ``.fcpxmld`` bundle is a folder with ``Info.fcpxml``."""
    if os.path.isdir(path):
        inner = os.path.join(path, BUNDLE_INNER)
        if not os.path.isfile(inner):
            raise ReadError("bundle_without_info", path)
        return inner
    return path


def read_fcpxml(
    path: str,
    *,
    include_muted: bool = False,
    probe_frame_duration: FrameDurationProbe | None = None,
) -> Timeline:
    """Reads an FCPXML file or a ``.fcpxmld`` bundle as a timeline.

    ``include_muted`` keeps the audio that a sync clip switched off, with
    ``Placement.muted`` set, instead of leaving it out.

    ``probe_frame_duration`` lets the caller say what rate a media file really
    has: the reader asks it for the first video file that exists, and what it
    answers beats the XML's declared rate.

    Raises ``ReadError``; see there for its codes.
    """
    source = _resolve(path)
    try:
        tree = ET.parse(source)
    except ET.ParseError as exc:
        raise ReadError("bad_xml", str(exc)) from exc
    except OSError as exc:
        raise ReadError("unreadable", str(exc)) from exc
    root = tree.getroot()
    if root.tag != "fcpxml":
        raise ReadError("bad_root", root.tag)
    try:
        return _read(root, path, include_muted, probe_frame_duration)
    except (ValueError, ZeroDivisionError) as exc:
        # ``parse_time`` on something that is not a time: ``int("x")``, ``1/0s``.
        raise ReadError("bad_time", str(exc)) from exc


def _read(
    root,
    path: str,
    include_muted: bool,
    probe: FrameDurationProbe | None,
) -> Timeline:
    assets, formats, medias = _collect_resources(root)
    container, kind, name = _pick_container(root)

    ctx = _Ctx(assets, formats, medias, include_muted=include_muted)
    if kind == "project":
        spine = container.find("spine")
        tc_start = parse_time(container.get("tcStart"), ZERO)
        ctx.root = spine
        _walk(spine, -tc_start, ZERO, ctx)
    else:
        tc_start = ZERO
        state = _State(muted=_muted_roles(container))
        _walk(container, ZERO, parse_time(container.get("start"), ZERO), ctx, state=state)
    fmt = formats.get(container.get("format", ""))
    declared = (
        None
        if fmt is None or fmt.get("name") == "FFVideoFormatRateUndefined"
        else fmt.get("frame_duration")
    )

    if not ctx.hits:
        raise ReadError("no_media")

    # Group the occurrences by asset.
    items: dict[str, MediaItem] = {}
    order: list[str] = []
    angles_of: dict[str, list[str]] = {}
    hits_by_ref: dict[str, list[_Hit]] = {}
    occurrences: dict[tuple[str, Fraction, Fraction], Placement] = {}
    for hit in ctx.hits:
        hits_by_ref.setdefault(hit.ref, []).append(hit)

    for hit in ctx.hits:
        asset = assets[hit.ref]
        item = items.get(hit.ref)
        if item is None:
            asset_fmt = formats.get(asset.format_id, {})
            # If an asset appears on the timeline only as ``<video>`` tags it is
            # picture alone (the user detached and deleted the audio).
            # Likewise a bare ``<audio>`` is sound alone.
            ref_hits = hits_by_ref[hit.ref]
            tags = {h.tag for h in ref_hits}
            if tags == {"video"}:
                has_video, has_audio = True, False
            elif tags == {"audio"}:
                has_video, has_audio = False, True
            else:
                has_video, has_audio = asset.has_video, asset.has_audio
            item = MediaItem(
                key="",
                name=asset.name,
                path=asset.path,
                src=asset.src,
                asset_start=asset.start,
                asset_duration=asset.duration,
                has_video=has_video,
                has_audio=has_audio,
                width=asset_fmt.get("width", 0),
                height=asset_fmt.get("height", 0),
                frame_duration=asset_fmt.get("frame_duration"),
                audio_rate=asset.audio_rate,
                audio_channels=asset.audio_channels,
                audio_sources=asset.audio_sources,
                video_sources=asset.video_sources,
                asset_id=asset.id,
                format_id=asset.format_id,
            )
            items[hit.ref] = item
            order.append(hit.ref)
        # ``<video>``/``<audio>`` of the same asset in the same place are one occurrence.
        spot = (hit.ref, hit.placement.offset, hit.placement.duration)
        twin = occurrences.get(spot)
        if twin is None:
            occurrences[spot] = hit.placement
            item.placements.append(hit.placement)
        else:
            _merge_occurrence(twin, hit.placement)
        if hit.angle_id and hit.angle_id not in item.angle_ids:
            item.angle_ids.append(hit.angle_id)

    media = [items[ref] for ref in order]
    for item in media:
        item.placements.sort(key=lambda p: p.offset)

    frame_duration = _probed_frame_duration(media, probe)
    if frame_duration is not None and declared is not None and declared != frame_duration:
        # The format's false rate must not stay in the other items' data: an
        # export writes the asset format from it, and Final Cut would conform
        # the file to the wrong rate.
        for item in media:
            if item.frame_duration == declared:
                item.frame_duration = frame_duration
    if frame_duration is None:
        frame_duration = declared
    if frame_duration is None:
        video_durations = [
            item.frame_duration
            for item in media
            if item.has_video and item.frame_duration
        ]
        frame_duration = video_durations[0] if video_durations else DEFAULT_FRAME_DURATION

    _stable_keys(media)
    for item in media:
        angles_of[item.key] = item.angle_ids
        item.angle_name = (
            ctx.angle_names.get(item.angle_ids[0], "") if item.angle_ids else ""
        )

    ctx.multicams.sort(key=lambda mc: mc.offset)
    tracks = _build_tracks(media, ctx, angles_of)
    if ctx.multicams:
        kind = "multicam"

    return Timeline(
        media=media,
        frame_duration=frame_duration,
        kind=kind,
        name=name,
        source_path=os.path.abspath(path),
        tracks=tracks,
        multicams=ctx.multicams,
        tc_start=tc_start,
        fcpxml_version=root.get("version", ""),
        format=None
        if fmt is None
        else Format(
            width=fmt.get("width", 0),
            height=fmt.get("height", 0),
            frame_duration=declared,
            name=fmt.get("name", ""),
        ),
        markers=sorted(ctx.markers, key=lambda m: m.time),
        transitions=sorted(ctx.transitions, key=lambda t: t.offset),
        spine=ctx.spine,
        skipped=dict(sorted(ctx.skipped.items())),
    )


def _probed_frame_duration(
    items: list[MediaItem], probe: FrameDurationProbe | None
) -> Fraction | None:
    """The frame duration of the first video file that exists, or None.

    The media always beats the XML's format: the format can say 1/25s, a file
    cannot. The answer is written into the item itself too, so that an export
    does not conform the file to the wrong rate.
    """
    if probe is None:
        return None
    for item in items:
        if not (item.has_video and item.path and os.path.exists(item.path)):
            continue
        answer = probe(item)
        if answer:
            item.frame_duration = answer
            return answer
    return None
