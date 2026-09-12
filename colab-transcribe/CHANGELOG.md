# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [colab-transcribe-v2026.9.12.1] - 2026-09-12

### Fixed
- **Drive API Quota Project Isolation & Cache in Tests** (`gdrive.py`, `tests/conftest.py`, `tests/test_gdrive.py`):
  - Isolate test suite from host's Google Cloud ADC (`~/.config/gcloud/application_default_credentials.json`) and Colab token (`~/.config/colab-cli/token.json`) by setting isolated test paths and default test quota project in `conftest.py`.
  - Prevent unintended Cloud Resource Manager network requests from consuming mocked `urllib.request.urlopen` responses in unit tests when ADC is missing (e.g. clean CI runners).
  - Add `lru_cache` to `_fetch_quota_project_from_api` to avoid repeated remote Cloud Resource Manager calls during Google Drive requests.
  - Added unit tests for quota project resolution and fallback.
