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

## Not here yet

Writing. `conform(source, pieces) -> bytes` (a new project spine made of pieces
of the original containers) is the next task for this package; autoraffkat's
writer is tied to its own decision layer and has not been extracted.
