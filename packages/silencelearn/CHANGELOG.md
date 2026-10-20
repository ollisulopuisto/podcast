# Changelog

All notable changes to the silencelearn package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [Unreleased]

### Fixed
- **The speech guard no longer measures noise words as speech.** The guard that refuses a learned threshold compared it with the 25th percentile of the first 400 transcribed words, which include noise-floor words, so valid thresholds were refused (07 uutiset: Perttu and Olli). The speech level is now the quietest quarter of the words the user left unmuted before the horizon; without such words it is the upper quarter of the transcribed words. `Calibration.speech_p25` is renamed `speech_level`.
- **Adjacent muted pieces are one block.** One turn cut into many muted regions counted as many tiny regions, each too short for a measurement window. Pieces closer than `BLOCK_GAP` are merged before `MIN_SECONDS` and the windows are counted.
- Ported from PR 57, written before the library was extracted. The numbers (25th/75th percentile, 0.01 s) are from that PR's measurements and were not re-measured here.

## [2026.10.12.1] - 2026-10-12

### Added
- The threshold calibration from podcast-magic's `silence/calibrate.py`, extracted so podcast-magic and colab-transcribe share one implementation instead of a copy and a drift test: threshold from the muted stretches, leak from other tracks, the speech guard, the cap from words left unmuted, and the learned gap limit.
