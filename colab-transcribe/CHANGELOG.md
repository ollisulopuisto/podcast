# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [colab-transcribe-v2026.10.9.1] - 2026-10-09

### Added
- **Speaker-turn script next to the finished session** (`colab/pipeline.py`): after the run, `<jakso>_processed.md` (or `<jakso> litteroitu.md` with `--no-silence`) is written next to the session and downloaded with the rest. The track name is the speaker; consecutive regions on one track are one paragraph. A snapshot of podcast-magic's `script/core.py`, held to it by `test_the_snapshot_script_matches_podcast_magics`.

## [colab-transcribe-v2026.9.12.1] - 2026-09-12

### Fixed
- **Drive API Quota Project Isolation & Cache in Tests** (`gdrive.py`, `tests/conftest.py`, `tests/test_gdrive.py`):
  - Isolate test suite from host's Google Cloud ADC (`~/.config/gcloud/application_default_credentials.json`) and Colab token (`~/.config/colab-cli/token.json`) by setting isolated test paths and default test quota project in `conftest.py`.
  - Prevent unintended Cloud Resource Manager network requests from consuming mocked `urllib.request.urlopen` responses in unit tests when ADC is missing (e.g. clean CI runners).
  - Add `lru_cache` to `_fetch_quota_project_from_api` to avoid repeated remote Cloud Resource Manager calls during Google Drive requests.
  - Added unit tests for quota project resolution and fallback.
