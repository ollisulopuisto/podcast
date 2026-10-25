# Changelog

All notable changes to the fcpxml package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [Unreleased]

## [2026.10.24.1] - 2026-10-24

### Added
- **The FCPXML reader as a shared package.** Extracted from autoraffkat's `fcpxml/read.py` and `timeline.py` (the rational time) so that autoraffkat and kuulas read an export one way. Standard library only; `read_fcpxml(path)` takes a `.fcpxml` or a `.fcpxmld` bundle and returns a `Timeline` of neutral types with every time an exact `Fraction`. The reading itself is unchanged: sync clips, projects and multicams, the muted-role hierarchy, the grouping of angles and mics into tracks.
- **A stable `ReadError.code`** (`unreadable`, `bundle_without_info`, `bad_xml`, `bad_root`, `bad_time`, `no_project`, `no_media`) instead of a translated text; a host translates the code. A time that is not a time (`offset="soon"`, `1/0s`) is `bad_time` and no longer escapes as a `ValueError`.
- **What kuulas asked for** (docs/PODCAST-MAGIC.md, "A shared fcpxml package"): `Timeline.format` (width, height, frame duration, rate), `fcpxml_version`; per placement `role`, `muted`, `enabled`; `include_muted=True` to keep what a sync clip switched off; `Placement.markers` and `Timeline.markers` (`<marker>` and `<chapter-marker>` with a to-do state, on the timeline, in time order); `Timeline.transitions` with `has_audio` and `has_video`; `Placement.unsupported` for a `timeMap` or `conform-rate` (and what is attached inside it); `Timeline.skipped` counting titles, captions, generators and video effects.
- **`probe_frame_duration`**, a hook for the one thing the reader cannot know: the real rate of a media file. The package has no ffprobe; autoraffkat passes its own.
- **Tests with no media and no Final Cut**: the fixtures of autoraffkat's `make_fixture.py` as XML only, the rational times of `vertical2.fcpxmld` (1001/30000, 100/2500, /5644800), a two-hour synthetic timeline (1440 clips) exact to the last frame, `%20`, `ä` and Windows `file:` URLs, a bundle with and without `Info.fcpxml`, garbage XML. A test fails if the library imports anything but the standard library.

### Changed
- An unnamed project has the name `""` instead of the Finnish `"Projekti"`; a host that wants a default supplies it (autoraffkat does).
- Not run against a real Final Cut file: the new fields (markers, transitions, `timeMap`, `conform-rate`, `enabled`) are written from the DTD and from hand-made XML, not from an export.
