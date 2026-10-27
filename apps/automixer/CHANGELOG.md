# Changelog

All notable changes to automixer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [Unreleased]

## [2026.10.27.1] - 2026-10-27

### Added
- **`?` shows every key in the terminal interface.** Both the mixer and the ad-spot picker open Textual's keys panel with `?` and close it with `?` or `Esc`. The panel lists every binding with what it does; before, it opened only from the command palette (Ctrl+P, "Keys"), which you had to know about first. `?` typed into a text field is still a `?`, and `Esc` is only taken while the panel is open. In the mixer `? Keys` comes first on the bottom row, because at 80 columns the row runs out at "space Play" and an entry after it was never seen.

### Fixed
- **Enter selects a spot in the ad-spot picker.** The bottom row promised "⏎ Select Spot", but the focused list took Enter for itself, so nothing was chosen and the config was never written. The binding now takes precedence over the list.

## [2026.10.23.2] - 2026-10-23

### Changed
- **The mastering of a stems mix prepares two programme pieces ahead instead of one.** The audio files are identical bit for bit (SHA-256 of `mix.wav`) to those of 2026.10.23.1 at every depth. Measured on synthetic voices with music on 4 cores, 8 min x 3 speakers, not on a real episode: mastering 46.3 s -> 36.3 s, the whole mix 134 s -> 123 s, peak memory 1.71 GB -> 1.73 GB. Three pieces ahead gained only 2 s more and cost 2.0 GB. The gain needs spare cores; on a 2-core machine it will be smaller. `SPEECHMIX_PREFETCH=N` sets the depth (default 2, `1` is the previous behaviour, `0` turns it off). Measured on one machine only; not on a Mac.

## [2026.10.23.1] - 2026-10-23

### Changed
- **The stems mix is up to 45 % faster, with the same sound.** The audio files are identical bit for bit (SHA-256 of `mix.wav`) to those of 2026.10.21.2. Measured on synthetic voices with music on 4 cores, not on a real episode: 2 min x 2 speakers 38.0 s -> 21.1 s, 8 min x 3 speakers about 245 s -> 138 s. Three causes:
  - The peak envelope that the limiter and the mastering ceiling are computed from is calculated on several threads (3.9x faster on 4 cores). `SPEECHMIX_ENVELOPE_THREADS=1` runs it on one thread as before.
  - The final writing pass of the mastering no longer computes and measures the programme again: it writes with the gain curve of the last measuring pass (5.3 s -> 0.8 s on 2 min, about 18 s -> 2.6 s on 8 min). The curves are kept in memory, at most 2 GiB and a quarter of the free memory; above that the pass computes them again, as before.
  - The next 60 s piece of the programme is prepared on a thread while the previous one is measured (mastering 57 s -> 49 s on 8 min; a short episode gains nothing). `SPEECHMIX_PREFETCH=0` turns it off.

## [2026.10.21.2] - 2026-10-21

### Added
- **`--keep-music-level`: the music keeps the balance you made.** Instead of fitting the beds to the processed speech (`--bed-under-speech-db`), each music stem gets the same gain change the speech got (processed speech level minus raw speech level, measured gated like the `beds:` rule), so a music-to-speech balance made by ear survives the automatic levelling. The `beds:` line says `kept your levels`; the `bed` event has `mode` `keep` (and `fit` for the old rule) and, for `keep`, `speech_raw_lufs`. Not together with `--bed-under-speech-db`. The track fader (`gain_db`) is not read: bake it into the stems if it should count. Checked on synthetic voices only, not on a real episode.

## [2026.10.21.1] - 2026-10-21

### Added
- **`--events`: live, structured progress for a host such as kuulas.** Besides the text lines (unchanged) the automixer prints one line per event on stdout: `@@kuulas ` and a JSON object with `schema` and `event` (`progress`, `track`, `stage`, `bed`, `balance`, `block`, `loud`, `mastered`, `warning`, `done`). A stage is announced when it starts, not only when it is done, so a slow plug-in stage no longer looks like the one before it. Fields may be added, never renamed. The flag is listed in `--help`. Works for a stems folder and a Hindenburg session.

### Changed
- **The stems route runs without mlx.** `automixer <stems-folder>` no longer imports Apple's mlx, so it runs on Linux and on a Colab VM. mlx is still installed on macOS (the terminal interface and the in-memory mixer use it).

### Fixed
- **A crash on computers without AVX-512.** `import pedalboard` died with SIGILL for pedalboard 0.9.20 and 0.9.24 on CPUs without AVX-512 (measured on AMD EPYC 7763 and 9V74, 4 of 4 each; most AMD Ryzen 5000 desktops and many Intel ones are in that group). The requirement is now `pedalboard>=0.9.26`. The measured results of the test suites did not change with it; not listened to on a real episode.

## [2026.10.20.1] - 2026-10-20

### Added
- **`--bed-under-speech-db`: the music bed level against the speech.** The loudest moment of a bed sits this many dB from the processed speech (default +1.0, range -30..+6). The log says where each bed landed.
- **`--balance-speakers-max-db` and `--balance-speakers-tolerance-db`: how far speakers are levelled.** Every speech track is lifted to -23 LUFS by the chain, so a balance made by hand was always levelled away. The first flag bounds how far a speaker may move towards the group's median (0 keeps the relative levels, default is full levelling as before); the second leaves speakers already within that many dB of each other alone. Checked on synthetic voices only, not on a real episode.

## [2026.10.14.1] - 2026-10-14

### Changed
- **Microphone ducking is on by default.** `--mic-duck` was off because the gate pumped by ear; a listen on diet woke 05 (-6, -9 and -15 dB, compared blind and open) kept the -9 dB default. `--no-mic-duck` turns it off; `--mic-duck` is accepted and does nothing. `--minimal` still turns it off.

## [2026.10.13.1] - 2026-10-13

### Added
- **Plug-ins by name: `--speech-plugins dxRevive`.** The option takes a path, a name or part of one (case, dashes and `.vst3` don't matter; a near miss like `dxrevise` is matched too) and says which plug-in it picked. Without a value it lists the installed plug-ins. If the name is ambiguous or unknown, a terminal asks you to pick from a numbered list; without a terminal the run stops with the list. The check happens before anything is analysed: a wrong name used to fail minutes in, after the block analysis. Same for `--music-plugins`.
- **`automixer-beds --leave TRACK`: leave a music track's fades alone.** For beds exported with their fades already in the audio (or fades you drew yourself), `automixer-beds` no longer has to write its own curve over them, which played the fade twice. Repeatable, case-insensitive. A name that matches no music track is an error that lists the music tracks, not a silent no-op; if every music track is left alone nothing is written. The mixer itself needed no change: it plays the session's own fades and adds no rides to music.

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
