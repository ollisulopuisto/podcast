# Changelog

All notable changes to the speechmix package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.7.6] - 2026-10-07

### Changed
- **Faster dynamics stage: the track is oversampled once for all limiter work.** The limiter, its budget check, the settle rounds and the PSR guard each oversampled the whole track 4× again; on pp 56 (87 min) that was 153 s of the 280 s dynamics stage. They now derive their limiter curves from one peak envelope (exact: oversampling is linear) and limit from the unlimited signal, so limiting no longer accumulates across rounds. On 20 min of real speech the output is identical (difference −145 dB) and the chain takes 31.8 s instead of 43.4 s; files that need settle rounds gain the most. The PSR guard still measures the limited signal's true peak exactly, and gets a third attempt.
- Short-term loudness in the PSR measure is computed blockwise instead of a Python loop over windows (~15 s on 87 min).

## [2026.10.7.5] - 2026-10-07

### Added
- `speechmix.log`: opt-in step timings inside the long stages (`SPEECHMIX_VERBOSE=1` or `log.enable()`): the chain's de-click, rider, de-esser, the three compressor stages, the limiter and its rounds, the PSR guard, each plug-in piece, de-bleed and every mastering pass.

## [2026.10.7.4] - 2026-10-07

### Fixed
- **Mastering was silently skipped when the mics differ in length or position on the timeline** (recorded on different devices, say). The ceiling grouped stems by identical placement and length, so each mic sat alone, nothing was summed or measured, and the log said "masterointi: 0.0 LUFS · nan" (pp 56). Stems that play at the same time are now summed on the programme timeline, and each stem gets the shared ceiling at its own file positions; stems with identical placement keep the previous path.
- **A single mic is mastered too** (lift to target and ceiling); it used to be skipped the same way.
- **If nothing can be measured, a note says so** instead of reporting 0.0 LUFS.

## [2026.10.7.3] - 2026-10-07

### Changed
- **Block cuts go up to 18 dB** (was 12): a cold open recorded much hotter than the show was still +1 dB louder after levelling because the cap held it. Boosts stay capped at +6 dB.

## [2026.10.7.2] - 2026-10-07

### Changed
- **Block-level gain corrects all the way,** not 80 %: the cold open, often recorded at another time, now comes out at the same loudness as the rest of the show (with 80 %, Olli's +12.5 dB intro stayed +2.5 dB hot).
- **Short hot lines are cut from 1 s of own voice;** boosts still need 3 s, because a short quiet stretch is usually a breath or bleed.

## [2026.10.7.1] - 2026-10-07

### Added
- `binaries.hw_decode_args()`: VideoToolbox hardware decode flags for ffmpeg on a Mac that has it, nothing elsewhere. For bulk decoding only: on keyframe extraction 1080p H.264 went 8.3 → 2.8 s and 4K HEVC 14.6 → 2.0 s, with bit-identical frames; for a single frame it is slower (decoder start-up), so it is not used there.

## [2026.10.6.7] - 2026-10-06

### Added
- `blocks.loud_spans`: loud stretches inside a block (momentary loudness, 0.4 s, more than 4 dB over the block for at least 1 s). These are **flagged, not changed**: on vst s13e03 the only two such places were emphasis, and the editor left both alone.

## [2026.10.6.6] - 2026-10-06

### Fixed
- **Block-level gain measured how much of a block was quiet, not how loud it was.** The median of 20 ms frames, checked against vst s13e03's raw audio, would have boosted a 27 s block of Olli's by +5.9 dB that the editor left alone, cut Olli's +12.8 dB intro by only 3.4 dB (editor: −12.2), and given Kari's intro the wrong sign. A block's level is now its energy over 3 s windows, median of the windows: it follows loudness like LUFS, and a burst shorter than half the block still does not move it. Blocks under 3 s of own voice are no longer corrected (1–2 s breaths and bleed at −51…−61 dB were being raised 12 dB), and boosts are capped at +6 dB (cuts stay at 12).

## [2026.10.6.5] - 2026-10-06

### Added
- **`speechmix.blocks`: block-level gain.** A speaker's own-voice blocks (pauses under 1.5 s closed) are each measured by their median level, so one emphatic or shouted burst does not move them. A block more than 3 dB from the speaker's own level is brought 80 % of the way back, capped at 12 dB, with the change made mid-pause over 50 ms. The constants were fitted to the editor's by-ear clip gains on vst s13e03 (Olli's intro +12.8/+10.0/+7.8 dB hot, set to −12.2/−7.5/−5.3; the blocks at 26:18 and 36:41 left alone); a check against that episode's raw audio is pending.

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
