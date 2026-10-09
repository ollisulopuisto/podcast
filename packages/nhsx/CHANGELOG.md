# Changelog

All notable changes to the nhsx package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.9.2] - 2026-10-09

### Added
- `nhsx.fades.long_segments`: each change between plateaus is one `<Fade>` ramp (a rise over 30 dB is two), found by grid search, instead of the many short ramps of `segments`. On vst s13e03's INTRO bed `segments` wrote 21 ramps whose zero velocity at every joint was audible as twitching.

## [2026.10.9.1] - 2026-10-09

### Changed
- `musicbed.COLD_RISE` is one long rise (−68 → −8 dB in 8 s, then to 0 dB at 10 s) instead of several steps, so the intro bed comes up in a single move.

## [2026.10.5.3] - 2026-10-05

### Fixed
- `nhsx.fades.write` sets the region's `FadeIn` to 200 ms when the curve starts below 0 dB, so the 10 ms first ramp from unity no longer clicks (peak −62 dB instead of 0 dB on a ramp to −56.7 dB).

## [2026.10.5.2] - 2026-10-05

### Fixed
- `nhsx.fades`: below the audible line the written curve may now differ from the target by at most 12 dB (it was unbounded), so a fall into silence is no longer written as one minute-long ramp.

## [2026.10.5.1] - 2026-10-05

### Added
- `nhsx.fades`: any gain curve as a series of `<Fade>` ramps, within 0.5 dB of the target where it is audible (checked by reading it back the way automixer plays it).
- `nhsx.activity`: when anyone is speaking on the session timeline, from the microphones' own levels (speechmix's floor + margin rule).
- `nhsx.musicbed`: a music bed's curve from the speech around it, with the rules and shapes measured from the editor's by-ear fades on vst s13e03.
