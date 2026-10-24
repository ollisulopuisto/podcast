"""What the reader gives back: neutral types, every time an exact Fraction.

Nothing here knows about a user interface. A time is seconds as a
``Fraction``; a path is the decoded file path, ``""`` when the XML has none.
Timeline positions are absolute and zero-based: the project's ``tcStart`` is
taken off while reading and kept in ``Timeline.tc_start``, so a writer can put
it back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .timeline import ZERO


@dataclass
class Marker:
    """A ``<marker>`` or ``<chapter-marker>`` at a point on the timeline."""

    time: Fraction  # absolute timeline position
    name: str  # the marker's ``value``
    kind: str = "marker"  # "marker" or "chapter"
    duration: Fraction = ZERO
    completed: bool | None = None  # a to-do marker: done or not; ``None`` if not one


@dataclass
class Transition:
    """A ``<transition>`` on a spine: a cross dissolve and the like.

    ``offset`` is where it starts on the timeline. An audio cross fade has a
    ``filter-audio`` (``has_audio``); a picture dissolve has a ``filter-video``
    (``has_video``); Final Cut's own cross dissolve has both.
    """

    offset: Fraction
    duration: Fraction
    name: str = ""
    has_audio: bool = False
    has_video: bool = False


@dataclass
class Placement:
    """One occurrence of a media on the timeline.

    ``offset`` is the timeline moment at which the clip's ``start`` falls. A
    source time t (in the asset's time base) is therefore the timeline moment
    ``offset + (t - start)``.

    ``role`` is the audio role as Final Cut names it (``dialogue.dialogue-1``),
    ``""`` when the clip has none. ``muted`` is true when a sync clip turned
    that role off (``<audio-role-source role="…" active="0"/>``); ``enabled`` is
    false for a clip or a container that is switched off (``enabled="0"``). A
    consumer that wants "does not play" reads both. ``unsupported`` names what
    the clip carries that the times above do not account for (``timeMap``,
    ``conform-rate``): a placement with it must not be trusted.
    """

    offset: Fraction
    start: Fraction
    duration: Fraction
    lane: int = 0
    role: str = ""
    muted: bool = False
    enabled: bool = True
    unsupported: tuple[str, ...] = ()
    markers: list[Marker] = field(default_factory=list)

    @property
    def end(self) -> Fraction:
        return self.offset + self.duration

    def covers(self, seconds: Fraction) -> bool:
        return self.offset <= seconds < self.end

    def source_at(self, seconds: Fraction) -> Fraction:
        return self.start + (seconds - self.offset)


@dataclass
class MediaItem:
    """One media found in the XML and its occurrences on the timeline.

    All times are Fraction seconds. ``asset_start`` is the first moment of the
    source material in the asset's time base; the file's t=0 corresponds to it.
    An envelope is indexed by file time, the timeline by asset time, and the
    difference is this.
    """

    key: str  # stable identifier, for storing settings
    name: str
    path: str  # decoded file path, "" if missing
    src: str  # the original media-rep src (file://...)
    asset_start: Fraction = ZERO
    asset_duration: Fraction = ZERO
    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0
    frame_duration: Fraction | None = None
    audio_rate: int = 48000
    audio_channels: int = 2
    audio_sources: int = 1
    video_sources: int = 1
    asset_id: str = ""  # the resource id in the source XML
    format_id: str = ""
    placements: list[Placement] = field(default_factory=list)
    angle_ids: list[str] = field(default_factory=list)  # the multicam's angleIDs
    angle_name: str = ""  # the angle's name, "" if not a multicam

    @property
    def timeline_start(self) -> Fraction:
        return min((p.offset for p in self.placements), default=ZERO)

    @property
    def timeline_end(self) -> Fraction:
        return max((p.end for p in self.placements), default=ZERO)

    def placement_at(self, seconds: Fraction) -> Placement | None:
        for p in self.placements:
            if p.covers(seconds):
                return p
        return None

    def file_time_at(self, seconds: Fraction) -> Fraction | None:
        """The time from the start of the file at a timeline moment, or None."""
        p = self.placement_at(seconds)
        if p is None:
            return None
        return p.source_at(seconds) - self.asset_start


@dataclass
class MulticamRef:
    """One ``<mc-clip>`` on the timeline.

    ``start`` is the multicam's own time at the point where the clip begins on
    the timeline. A writer needs it so that the pieces it cuts can set their
    own ``start`` in the same time base.
    """

    media_id: str
    name: str
    offset: Fraction
    duration: Fraction
    start: Fraction
    angle_ids: list[str] = field(default_factory=list)
    # angleID -> the name of the source's audio role. A writer repeats the same
    # role switched off for the picture angle, as Final Cut itself does.
    angle_roles: dict[str, str] = field(default_factory=dict)

    @property
    def end(self) -> Fraction:
        return self.offset + self.duration

    def covers(self, seconds: Fraction) -> bool:
        return self.offset <= seconds < self.end

    def source_at(self, seconds: Fraction) -> Fraction:
        """A timeline moment as the multicam's local time."""
        return self.start + (seconds - self.offset)


@dataclass
class Track:
    """The unit of role assignment.

    In an ordinary timeline a track is one media. In a multicam the same angle
    is a separate asset in each part -- three cameras in two parts are six
    assets but three tracks -- so a track gathers them. Roles, controls and a
    decision layer's keys always refer to a track.
    """

    key: str
    name: str
    media_keys: list[str] = field(default_factory=list)
    angle_ids: list[str] = field(default_factory=list)
    has_video: bool = False
    has_audio: bool = False


@dataclass
class Format:
    """A ``<format>`` resource: the picture size and frame rate."""

    width: int = 0
    height: int = 0
    frame_duration: Fraction | None = None
    name: str = ""

    @property
    def rate(self) -> Fraction | None:
        """Frames per second, or None when the format declares no frame duration."""
        return None if not self.frame_duration else 1 / self.frame_duration


@dataclass
class Timeline:
    """A timeline that has been read."""

    media: list[MediaItem]
    frame_duration: Fraction
    kind: str  # "project", "sync-clip" or "multicam"
    name: str  # "" when the XML names nothing
    source_path: str = ""
    tracks: list[Track] = field(default_factory=list)
    multicams: list[MulticamRef] = field(default_factory=list)
    # The source project's ``tcStart``. The timeline here is always zero-based
    # (the reader takes it off), but an export needs the original to write the
    # same start timecode back -- else an import into Final Cut shows a
    # different time than the source project.
    tc_start: Fraction = ZERO
    # ``<fcpxml version="…">``, so an export can write the source's own version.
    fcpxml_version: str = ""
    # The picture size and rate of the sequence (or sync clip) itself; None when
    # the XML does not say.
    format: Format | None = None
    # Markers that belong to no clip with media: on a gap, a sync clip, a
    # multicam clip. A clip's own markers are on its ``Placement``.
    markers: list[Marker] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    # What the reader met and left out: titles, captions, generators and video
    # effects, counted by kind. For a report; nothing more is read of them.
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def start(self) -> Fraction:
        """The first moment that has media."""
        return min((m.timeline_start for m in self.media), default=ZERO)

    @property
    def end(self) -> Fraction:
        return max((m.timeline_end for m in self.media), default=ZERO)

    def media_by_key(self) -> dict[str, MediaItem]:
        return {m.key: m for m in self.media}

    def track_media(self, key: str) -> list[MediaItem]:
        """The track's media. An empty list if there is no such track."""
        by_key = self.media_by_key()
        for track in self.tracks:
            if track.key == key:
                return [by_key[k] for k in track.media_keys if k in by_key]
        return []

    def track_span(self, key: str) -> tuple[Fraction, Fraction] | None:
        """The track's timeline span: from the first part to the last."""
        items = self.track_media(key)
        if not items:
            return None
        return (
            min(m.timeline_start for m in items),
            max(m.timeline_end for m in items),
        )

    def multicam_at(self, seconds: Fraction) -> MulticamRef | None:
        for mc in self.multicams:
            if mc.covers(seconds):
                return mc
        return None
