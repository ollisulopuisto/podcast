# Changelog

## [2026.10.19.1] - 2026-10-19

### Added
- The aligner core, moved out of `podcast-magic` (`transcribe/align.py`) into one shared file so
  `colab-transcribe` can upload it to Colab. Behaviour is unchanged; the app's alignment tests
  run through it. New: `refined` (rows to word dicts), `run_jobs` and a command line for Colab.
