# fcpxml

A reader for Final Cut Pro XML (`.fcpxml` and `.fcpxmld`), with exact times.
Standard library only.

It is shared so that autoraffkat and kuulas read an export one way. It knows
nothing about audio, pictures or any user interface: it takes a file and gives
back a `Timeline` of neutral types, with every time an exact `Fraction` of
seconds. An error is a stable `code`, never a text a person is meant to read.

```python
from fcpxml import ReadError, read_fcpxml

try:
    timeline = read_fcpxml("episode.fcpxmld")      # or a loose .fcpxml
except ReadError as error:
    print(error.code, error.detail)                # e.g. "bad_root", "notfcpxml"
```

## What it gives back

`Timeline`: `kind` (`"project"`, `"sync-clip"` or `"multicam"`), `name` (`""`
when the XML names nothing), `frame_duration`, `format` (`width`, `height`,
`frame_duration`, `rate`), `fcpxml_version`, `tc_start`, `media`, `tracks`,
`multicams`, `markers`, `transitions` and `skipped`.

`MediaItem`: `key`, `name`, `path` (the decoded file path, `""` if the XML has
none), `src` (the original `file://` URL), `asset_start`, `asset_duration`,
`has_video`, `has_audio`, `audio_channels`, `audio_rate`, and its `placements`.

`Placement`: `offset`, `start`, `duration`, `lane`, `role` (the audio role as
Final Cut names it), `muted`, `enabled`, `unsupported` and `markers`.

A timeline position is absolute and zero-based: the project's `tcStart` is taken
off while reading and kept in `tc_start`. A clip's `offset` is in its host's
local time, and the reader does the arithmetic (`host_absolute + (child_offset -
host_start)`), so a `Placement` is already on the timeline.

### Inactive clips

"Does not play" is two facts, and the reader keeps them apart:

* `muted` is true when a sync clip switched that audio role off
  (`<sync-source><audio-role-source role="…" active="0"/>`). Such audio is left
  out by default; `read_fcpxml(path, include_muted=True)` keeps it, with the
  flag set. Muting works downward: `dialogue` mutes `dialogue.dialogue-1`.
* `enabled` is false for a clip, or any container above it, that is switched
  off (`enabled="0"`). It is always kept; the consumer decides.

### What is flagged, not misread

A clip with a `timeMap` (retiming) or a `conform-rate` has times the placement
does not account for. Its `Placement.unsupported` names it
(`("timeMap",)`), and so does everything attached inside it. Trust no such
placement.

Titles, captions, generators and video effects are not read. They are counted
in `Timeline.skipped` (`title`, `caption`, `generator`, `filter-video`), for a
report, and nothing more.

### Markers and transitions

A clip's `<marker>` and `<chapter-marker>` are on its `Placement.markers`, with
their time on the timeline and in time order; a marker outside the clip's own
span is not shown by Final Cut and is not here. Markers on a gap, a sync clip or
a multicam clip are in `Timeline.markers`. `Timeline.transitions` lists every
`<transition>` with `has_audio` and `has_video`, so an audio cross fade can be
told from a picture dissolve.

## Errors

`ReadError.code` is one of `unreadable`, `bundle_without_info`, `bad_xml`,
`bad_root` (`detail` is the root tag), `bad_time`, `no_project`, `no_media`.
Translate the code; do not show `str(error)`.

## The frame rate

The XML's declared rate can lie: 60 fps material in an exported 25 fps project.
`read_fcpxml(path, probe_frame_duration=probe)` takes a function that is given a
`MediaItem` and answers the frame duration of its file (or `None`). The reader
asks it for the first video file that exists, and what it answers beats the
declaration. The package has no ffprobe; the caller brings one.

## Tests

`uv run --directory packages/fcpxml pytest -q`. They need no media and no
Final Cut: the fixtures are XML only. `test_stdlib_only.py` fails if the library
ever imports anything but the standard library.

## Writing: `conform`

```python
from fractions import Fraction as F
from fcpxml import ConformError, conform, snap_pieces

pieces = [(F(2), F(5)), (F(12), F(15))]      # kept ranges of the source timeline
data = conform("episode.fcpxml", pieces, name="Cut one")   # bytes: a new .fcpxml
```

`conform(source, pieces)` lays the kept ranges of a project back to back: a
ripple edit, nothing else. `source` is a path or a `Timeline` from the reader;
`pieces` are `(source_start, source_end)` in `Fraction` seconds on the source
timeline (zero-based, as the reader shows it), in order and not overlapping.
No gaps, no reordering, no range used twice.

* A piece of a spine item is the same element with its `start` and `duration`
  narrowed and its `offset` moved. What is attached to it (connected clips,
  titles, keywords, markers) is narrowed to the same range in the host's local
  time, as Final Cut's own ripple delete does; `mc-source` angle choices and
  roles are kept. A transition is kept only if all of it lies inside one piece.
* Every boundary is snapped to the sequence's frame grid (the boundary, not the
  duration, so nothing drifts over many cuts). The grid is the sequence's
  declared rate, not a probed one. `snap_pieces(pieces, frame_duration)` is the
  same function, so a caller can know the lengths, and so the new timeline
  positions, before it writes. Audio cuts are frame-accurate; sub-frame audio
  edits are not used, because it is not known that Final Cut accepts them.
* The document has the source's resources as they are (so Final Cut finds the
  same media), the source's FCPXML version and start timecode, one new event
  `"<name> (kuulas)"` and in it one new project with a fresh `uid` (`name` and
  `uid` can be given).
* What it cannot cut correctly it **refuses** with a `ConformError.code`:
  `no_pieces`, `empty_piece`, `unordered`, `overlap`, `outside_timeline` (the
  pieces), `not_a_project` (a sync clip has no spine), `unsupported` (a
  `timeMap` or `conform-rate` in what is kept), `nested_spine` (a secondary
  storyline), `keyframes_cross_cut`, `no_duration`. A keyframe animation that a
  cut would change is refused; `keyframes="clip"` accepts the cost instead (the
  keyframes outside the piece are dropped, and the value at its edge is the
  first keyframe's, not an interpolated one).

`Timeline.spine` lists the items on the project's spine (`SpineItem`: `id`,
`kind`, `name`, `offset`, `start`, `duration`, `ref`), and `Placement.container`
is the `id` of the one a placement is in or attached to.

The tests check what matters most, **sync**: a moment of the new timeline must
play the same moment of every media that the same moment of the source played
(`file_time_at` before and after, through a multicam and through a project with
attached clips). They cannot say whether Final Cut accepts the result. Nothing
here has been imported into Final Cut, and the DTD check (`xmllint --dtdvalid`
against the DTDs inside the app) has to be run by hand on a Mac that has it.
