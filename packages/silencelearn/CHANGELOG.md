# Changelog

All notable changes to the silencelearn package are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.12.1] - 2026-10-12

### Added
- The threshold calibration from podcast-magic's `silence/calibrate.py`, extracted so podcast-magic and colab-transcribe share one implementation instead of a copy and a drift test: threshold from the muted stretches, leak from other tracks, the speech guard, the cap from words left unmuted, and the learned gap limit.
