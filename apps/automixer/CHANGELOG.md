# Changelog

All notable changes to automixer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.9.1] - 2026-10-09

### Fixed
- **Intro music no longer warbles or pumps.** The bed stem is exported with its duck depth (`ducked`, 20 Hz) and the mix leaves the music untouched at the plateau (speechmix 2026.10.9.1); the beds are generated with one long rise (nhsx 2026.10.9.1). The bed sits `BED_UNDER_SPEECH_DB` = +1.0 dB over the speech (by ear, not measured).

## [2026.10.8.3] - 2026-10-08

### Changed
- **Music beds and tracks are measured with the same loudness meter as the processing chain and mastering** (speechmix's, which matches libebur128). Session loading, `automixer-beds` and the older track path used pyloudnorm, which reads about 0.04 LU low, so beds now land about 0.04 dB quieter than before. Inaudible, but the same audio no longer reads two ways.

## [2026.10.8.2] - 2026-10-08

### Changed
- The log says how many speakers are processed at a time and why (free memory against the estimate), and two at a time now needs about 14 GB free for 47-min tracks instead of 20 (speechmix 2026.10.8.4).

## [2026.10.8.1] - 2026-10-08

### Changed
- **Speakers are processed two at a time when memory allows** (speechmix 2026.10.8.1). The mix is bit-identical to one at a time, and the log says "2 stems at a time" when it happens. `SPEECHMIX_PARALLEL_STEMS=1` forces one at a time.

## [2026.10.5.4] - 2026-10-05

### Fixed
- **`automixer-beds`: a click at the start of each bed.** The first 10 ms played near full level before the fade took over (on vst s13e03's end bed, a burst at −11 dBFS). Each bed now starts with a 200 ms fade from silence that covers it; the fades themselves are unchanged.

## [2026.10.7.2] - 2026-10-07

### Added
- `--verbose` / `-v`: prints each processing step inside the long stages and how long it took.

## [2026.10.7.1] - 2026-10-07

### Fixed
- **Music beds were far louder than the speech** in the finished mix: the intro bed of vst s13e03 was +7 to +10 dB over the speech (the editor's own master: +1.2), because the +7 dB target had been measured against unprocessed speech in Hindenburg. A bed's loudest moment (3 s short-term) is now set 1 dB under the **processed** speech, measured after the speech chain on the stereo output, so the relation survives mastering. Following the editor ("music at most at −16 LUFS, the same as the speech") and narrative-radio practice (music in the clear at about the voice's level).

## [2026.10.6.4] - 2026-10-06

### Added
- **A listening list next to every Hindenburg mix** (`<output> flags.txt`): the blocks that were levelled, with their gain, and the loud stretches inside blocks, which are only flagged and never changed (a shout or an emphatic line is usually content). One line per place, in time order.
- **`--flags-only`** writes just that list, without mixing: a few minutes instead of a full render.

## [2026.10.6.3] - 2026-10-06

### Added
- **Hot or quiet takes are levelled before processing** (Hindenburg sessions). Each speaker's blocks that sit more than 3 dB off their own level — another day, another take, a different distance from the mic — get a constant gain, as the editor does by hand with clip gain in Hindenburg. A shouted or emphatic moment inside a block does not count. Every correction is logged (`block Kari 23:56.5–24:03.1: +8.1 dB off, gain −6.5 dB`). `--no-block-level` turns it off.

## [2026.10.6.2] - 2026-10-06

### Fixed
- **Music beds were 3 dB too quiet against the speech** in the stems pipeline: speakers were panned with Final Cut's balance law, which plays a centred voice at full level on both channels (+3 dB in stereo), while the beds were matched to the speech's mono level. On vst s13e03 the beds came out +3.3 to +4.9 dB over the speech instead of +7. Speech is panned with constant power again, as automixer always did.

## [2026.10.6.1] - 2026-10-06

### Fixed
- **A full-length Hindenburg episode can be mixed on a 32 GB Mac.** A 47-minute session needed ~40 GB and stalled in swap, because every track and the whole mix were held in memory. Session mode now uses autoraffkat's pipeline (shared in `speechmix.stems`): each speaker is processed one at a time to a stem on disk, and the peak ceiling, mastering and final stereo mix stream over the stems in chunks. Synthetic 3-speaker session, peak memory: 5 min 7.1 → 1.8 GB, 10 min 9.9 → 3.1 GB (~13 GB projected for 47 min, was ~40). The output lands on the target loudness (−16.0 LUFS measured) with a −1 dBTP true-peak ceiling.

### Changed
- In session mode only the first `--speech-plugins` entry is used, and `--ad-spot` is ignored (edit the gap in Hindenburg).

## [2026.10.5.3] - 2026-10-05

### Fixed
- **Music beds in a Hindenburg session were mixed about 11 dB under the processed speech.** The loader matched each bed's whole raw clip to the speech level and then applied its fades, which put the bed's full-level section at −10.9 dB re the speech on a 2-minute dxRevive render of vst s13e03 (−26.9 vs −16.0 LUFS). A bed with fades is now matched at its plateau instead: the plateau sits +7 dB over the speech, measured from the editor's own beds on that episode (+8.2 / +7.1 / +7.0 for INTRO / MID / END). The same render now measures the plateau at +6.7 dB over the speech. Beds without fades are unchanged. Speech comes out about 1.4 dB lower in a mix with a loud bed, because the master normalises the sum. The +7 dB is measured from one episode.

## [2026.10.5.2] - 2026-10-05

### Fixed
- **`automixer-beds`: a long bed kept playing quietly after its fade-out.** On vst s13e03 the intro bed's fall ended at about −43 dB and the remaining 71 s of the region ramped slowly to silence, so the music sat at −43…−52 dB under the whole conversation. Silence now arrives within a fraction of a second.

## [2026.10.5.1] - 2026-10-05

### Added
- **`automixer-beds episode.nhsx`** writes music-bed fades into a new session next to the original (`episode beds.nhsx`; never overwrites). For each bed on the music track it reads when people talk from the audio, then writes the editor's measured shape: a rise from silence (or, for a bed named INTRO/ALKU, a hold 12 dB down under the cold open), full level reached 1.3 s after the last word, and a fall that ends before the bed ends or the next speaker starts. Full level is set to −18.7 LUFS. The curve is the editor's own fade shape, written as many short Hindenburg fades. Measured from one episode (vst s13e03); the numbers are starting values. Use the beds without burnt-in fades.

### Fixed
- **A stereo microphone was mixed as music** in Hindenburg sessions: a track whose sources were all stereo counted as music even when Hindenburg marked its regions as speech, so it skipped the speech chain and got music's level. Hindenburg's own speech flag now wins.
