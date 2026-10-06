# Changelog

All notable changes to the speechmix package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.6.5] - 2026-10-06

### Added
- **`speechmix.blocks`: block-level gain.** A speaker's own-voice blocks (pauses under 1.5 s closed) are each measured by their median level, so one emphatic or shouted burst does not move them. A block more than 3 dB from the speaker's own level is brought 80 % of the way back, capped at 12 dB, with the change made mid-pause over 50 ms. The constants are fitted to the editor's by-ear clip gains on vst s13e03 (Olli's intro +12.8/+10.0/+7.8 dB hot, set to −12.2/−7.5/−5.3; the blocks at 26:18 and 36:41 left alone); a check against that episode's raw audio is pending.

## [2026.10.6.4] - 2026-10-06

### Added
- `stems.Source.pan_law` / `pan_gains(..., law)`: `"balance"` (Final Cut, the default, unchanged for autoraffkat) or `"power"` (constant power, centre −3 dB per channel).

## [2026.10.6.3] - 2026-10-06

### Changed
- **The loudness meter reads stereo the way BS.1770 does:** each channel is K-weighted and the powers are summed. It used to average the channels, which read dual-mono 3 dB low. Mono input reads as before.
- **The programme passes accept a `layout`** describing how the stems land in the host's own stereo output, so mastering measures what is actually written. autoraffkat passes none (Final Cut plays the stems), so its results are unchanged.
- **Lower memory, identical results:** the multiband compressor, the other compressor stages, the de-esser and the de-bleed subtraction now run in chunks with their filter state carried across. Measured on 60 s of speech: multiband 22× → 2.3× the input, de-bleed's convolution ~6× → the output plus a fixed 10 s chunk.

### Added
- `stems.grid_from_files`: a speech grid from cached level curves of timeline-length stems, never holding the audio itself.

## [2026.10.6.2] - 2026-10-06

### Added
- **`speechmix.stems`: the stems-on-disk pipeline, moved from autoraffkat.** Processing one file at a time into a stem (`process_stem`, with de-bleed), the programme's shared peak ceiling and loudness mastering streamed over the stems in 60 s chunks (`program_ceiling`, `program_deliver`), the programme trim (`program_trim`), and block-wise summing to a stereo file (`sum_to_file`, which now keeps a stereo music source in stereo). The behaviour is unchanged: autoraffkat's 478 tests pass against it. automixer will use the same pipeline, so a full episode no longer has to fit in memory.

## [2026.10.6.1] - 2026-10-06

### Fixed
- **True-peak measurement no longer holds the whole episode 4× oversampled in memory.** The programme limiter (`_needed_gain`) and the per-track peak diagnostic (`peak_to_short_term`, now via `true_peak`) work in one-second chunks with overlap. The results are unchanged. On a synthetic session automixer's peak use dropped from 7.1 to 3.6 GB at 5 minutes. A 47-minute episode still does not fit in 32 GB: the speech chain keeps whole-episode arrays at every stage.
