# Changelog

All notable changes to automixer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

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
