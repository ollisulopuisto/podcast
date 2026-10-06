# Changelog

All notable changes to the speechmix package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.6.1] - 2026-10-06

### Fixed
- **True-peak measurement no longer holds the whole episode 4× oversampled in memory.** The programme limiter (`_needed_gain`) and the per-track peak diagnostic (`peak_to_short_term`, now via `true_peak`) work in one-second chunks with overlap. The results are unchanged. On a synthetic session automixer's peak use dropped from 7.1 to 3.6 GB at 5 minutes. A 47-minute episode still does not fit in 32 GB: the speech chain keeps whole-episode arrays at every stage.
