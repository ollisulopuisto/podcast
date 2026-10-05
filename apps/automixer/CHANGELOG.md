# Changelog

All notable changes to automixer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.5.2] - 2026-10-05

### Fixed
- **`automixer-beds`: a long bed kept playing quietly after its fade-out.** On vst s13e03 the intro bed's fall ended at about −43 dB and the remaining 71 s of the region ramped slowly to silence, so the music sat at −43…−52 dB under the whole conversation. Silence now arrives within a fraction of a second.

## [2026.10.5.1] - 2026-10-05

### Added
- **`automixer-beds episode.nhsx`** writes music-bed fades into a new session next to the original (`episode beds.nhsx`; never overwrites). For each bed on the music track it reads when people talk from the audio, then writes the editor's measured shape: a rise from silence (or, for a bed named INTRO/ALKU, a hold 12 dB down under the cold open), full level reached 1.3 s after the last word, and a fall that ends before the bed ends or the next speaker starts. Full level is set to −18.7 LUFS. The curve is the editor's own fade shape, written as many short Hindenburg fades. Measured from one episode (vst s13e03); the numbers are starting values. Use the beds without burnt-in fades.

### Fixed
- **A stereo microphone was mixed as music** in Hindenburg sessions: a track whose sources were all stereo counted as music even when Hindenburg marked its regions as speech, so it skipped the speech chain and got music's level. Hindenburg's own speech flag now wins.
