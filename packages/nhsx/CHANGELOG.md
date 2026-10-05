# Changelog

All notable changes to the nhsx package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.5.2] - 2026-10-05

### Fixed
- `nhsx.fades`: below the audible line the written curve may now differ from the target by at most 12 dB (it was unbounded), so a fall into silence is no longer written as one minute-long ramp.

## [2026.10.5.1] - 2026-10-05

### Added
- `nhsx.fades`: any gain curve as a series of `<Fade>` ramps, within 0.5 dB of the target where it is audible (checked by reading it back the way automixer plays it).
- `nhsx.activity`: when anyone is speaking on the session timeline, from the microphones' own levels (speechmix's floor + margin rule).
- `nhsx.musicbed`: a music bed's curve from the speech around it, with the rules and shapes measured from the editor's by-ear fades on vst s13e03.
