# Changelog

All notable changes to the speechmix package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.8.4] - 2026-10-08

### Changed
- **Two stems at once on smaller machines too:** the memory estimate per stem drops from 15× to 10× its float32 size. Measured after today's memory work, two stems at once cost about 7× each. Two 47-min stems now need about 14 GB free instead of 20.
- The log always says how many stems run at a time and why, e.g. "1 stem at a time: 2 would need 14.1 GB, 9.8 GB free".

## [2026.10.8.3] - 2026-10-08

### Changed
- **A stem's memory peak fell another third, with identical output:**
  - the track is handed over to the chain rather than held by the caller throughout;
  - the dry/compressed mix and the two wideband compressors work in place;
  - mono tracks are measured without copying them;
  - the limiter rounds measure loudness, true peak and short-term level without building the limited track;
  - the GPU's peak envelope stays in float32, which is what the GPU computes.

  On 20 min of real speech with de-click, the peak went from 9.0× to 6.0× the track's float32 size. On a 69-min mic that is about 7.1 GB → 4.7 GB of live memory.

## [2026.10.8.2] - 2026-10-08

### Fixed
- **De-click no longer takes gigabytes on long tracks:** it filtered the whole track at once into four float64 copies, two bands in parallel. On a 69-min mic that was 15.6 GB, the largest memory peak of an automixer run, where de-click is on by default. It now works in one-minute pieces with a one-second overlap, and decides its threshold from the click candidates of the whole track as before. Output is identical (same hash on 20 min of real speech) and so is the speed; memory on 20 min went from 2.65 GB to 0.45 GB, and it no longer grows with track length.

## [2026.10.8.1] - 2026-10-08

### Added
- **Two stems processed at once when memory allows:** `parallel_count` decides from free RAM before the run (15× each stem's float32 size plus 4 GB for the rest of the machine), and falls back to one at a time when a size is unknown or memory is short. Measured on two 20-min stems of real speech: 27.9 → 17.7 s, peak memory 3.2 → 5.7 GB. Output is bit-identical. The restoration plug-in still runs for one stem at a time, since it already uses most cores. `SPEECHMIX_PARALLEL_STEMS=1` forces the old one-at-a-time behaviour.

## [2026.10.7.14] - 2026-10-07

### Changed
- **De-bleed's memory peak per track went from 6× to under 4× the track's size, with identical audio:** the solo masking is applied a piece at a time instead of to whole float64 copies, the leak is subtracted in place, and the partner's raw audio is released once it is aligned. The "own speech kept" check now computes its correlation in place instead of with `np.corrcoef`, and the reading can differ in the last digit (0.9999999999999999 → 1.0).

## [2026.10.7.13] - 2026-10-07

### Changed
- **The chain's memory peak per track roughly halved, with identical output:** the limiter rounds no longer build a limited copy of the track each time. Their loudness and PSR checks are computed piece by piece and the track is written once at the end, and the compressed branch is released as soon as it is mixed in. On 5 min of real speech the peak went from 17× to 8× the track's size (float32), so the limiter is no longer the most memory-hungry stage. This makes room for processing stems in parallel.

## [2026.10.7.12] - 2026-10-07

### Changed
- **Multiband compressor and de-esser use threads, with identical output:** the three bands compress in parallel while the next second of audio is split, and the de-esser filters the next piece while compressing the current one. On 20 min of real speech: multiband 2.61 → 1.39 s, de-esser 1.07 → 0.69 s, whole chain 14.4 → 12.7 s (it was 43.4 s before today's work). At most four threads per stage. Stems are still processed one at a time to keep memory down.

## [2026.10.7.11] - 2026-10-07

### Changed
- **De-click is 1.75× faster with identical output:** its high-pass and low-pass filters run in parallel threads. 20 min of real speech: 3.38 → 1.93 s. De-click is on by default in automixer, off in autoraffkat.

## [2026.10.7.10] - 2026-10-07

### Changed
- **One loudness meter everywhere, and it is 3× faster:** the chain's own loudness readings (and the in-memory programme master) used pyloudnorm, which reads 0.042 LU low against libebur128, the reference implementation; mastering used speechmix's own meter, which matches libebur128 to 1e-10 LU. Everything now uses the latter, so processed tracks land about 0.04 dB differently than before. K-weighting and power are one compiled pass: 20 min 1.1 → 0.35 s; the chain on 20 min of real speech 16.9 → 14.4 s.

## [2026.10.7.9] - 2026-10-07

### Changed
- **De-bleed is about 3× faster with identical results:** the leak-path estimate computes both correlations in one pass, transforming the source once and skipping stretches where the source isn't solo; the leak subtraction transforms its 8192-tap filter once instead of per chunk. 10 min: 4.15 → 1.40 s; the correlation sums agree with the old ones to 1e-15.

## [2026.10.7.8] - 2026-10-07

### Changed
- **Compressors and de-esser run as compiled loops (numba):** envelope follower, gain computer and dB conversions in one pass instead of a dozen whole-array numpy passes. Bit-identical output; on 20 min of real speech multiband 4.4 → 2.6 s, de-esser 1.7 → 1.4 s, the two wideband stages 1.1 → 0.5 s each. numba is now a declared dependency.

## [2026.10.7.7] - 2026-10-07

### Changed
- **True-peak oversampling runs on the GPU (Metal, via MLX) on a Mac:** the limiter's peak envelope, the PSR guard's checks and most of every mastering pass. 10 min: 2.07 → 0.20 s with the same filter as the CPU path, within 0.00001 dB. The chain on 20 min of real speech went from 31.8 to 19.7 s with identical output (−140 dB difference); a mastering pass on two 10-min stems from 6.0 to 2.7 s. Falls back to scipy where MLX is missing, or with `SPEECHMIX_NO_GPU=1`.

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
