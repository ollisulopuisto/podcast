# Changelog

All notable changes to the silencelearn package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [Unreleased]

### Added
- **`calibrate_clips`: learn from clips, with no words.** For an editor that has clips (a stretch of a media file, muted by the user or not) and level windows, but no transcript. `Clip(ref, start, end, muted)` examples and a `Levels` source (`level` and `missing`, no `words`). Muted clips give the threshold as before (`PERCENTILE` of the windows plus `MARGIN_DB`, adjacent muted clips of one file merged, at least `MIN_SECONDS`); unmuted clips give the speech level and the guard (the threshold must stay `GUARD_DB` below it, else "vaimennettiinko puhetta?"). A kept clip holds pauses, so the speech level is the upper quarter of its windows, not the lower. The guard needs `MIN_SPEECH_WINDOWS` kept windows. `Calibration` gets `unmuted_frames` and `kept_share` (the share of the kept windows at or above the threshold). No leak gap and no ceiling clamp: they need words and other tracks. The new numbers are taste values, not measured.

### Fixed
- **The speech guard no longer measures noise words as speech.** The guard that refuses a learned threshold compared it with the 25th percentile of the first 400 transcribed words, which include noise-floor words, so valid thresholds were refused (07 uutiset: Perttu and Olli). The speech level is now the quietest quarter of the words the user left unmuted before the horizon; without such words it is the upper quarter of the transcribed words. `Calibration.speech_p25` is renamed `speech_level`.
- **Adjacent muted pieces are one block.** One turn cut into many muted regions counted as many tiny regions, each too short for a measurement window. Pieces closer than `BLOCK_GAP` are merged before `MIN_SECONDS` and the windows are counted.
- Ported from PR 57, written before the library was extracted. The numbers (25th/75th percentile, 0.01 s) are from that PR's measurements and were not re-measured here.

## [2026.10.12.1] - 2026-10-12

### Added
- The threshold calibration from podcast-magic's `silence/calibrate.py`, extracted so podcast-magic and colab-transcribe share one implementation instead of a copy and a drift test: threshold from the muted stretches, leak from other tracks, the speech guard, the cap from words left unmuted, and the learned gap limit.
