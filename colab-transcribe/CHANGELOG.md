# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.9.1] - 2026-10-09

### Added
- **Speaker-turn script next to the finished session** (`colab/pipeline.py`): after the run, `<jakso>_processed.md` (or `<jakso> litteroitu.md` with `--transcribe-only`) is written next to the session and downloaded with the rest. The track name is the speaker; consecutive regions on one track are one paragraph. A snapshot of podcast-magic's `script/core.py`, held to it by `test_the_snapshot_script_matches_podcast_magics`.

## [2026.10.8.5] - 2026-10-08

### Fixed
- **Drive sign-in is now recognised.** 2026.10.8.4 stopped waiting for Enter, but it checked for success in a way Colab never confirms, so the Drive mount still timed out after 10 minutes although access was granted in the browser. It now completes the sign-in while it waits, prints a note every 30 s while it waits, and computers that already had 2026.10.8.4 are updated on their next run.

## [2026.10.8.4] - 2026-10-08

### Fixed
- **Drive mount no longer hangs after the browser sign-in.** The current Colab CLI waited for an Enter key press it never showed on screen, so runs stopped at "[2/10] Liitetään Google Drive...". The run now continues by itself once access is granted in the browser (waits up to 10 minutes).

## [2026.10.8.3] - 2026-10-08

### Added
- **Transcribe only:** `--transcribe-only` on the command line, or the new Auto-Silence switch in the TUI, skips the silencing step. The result is then only `<episode> litteroitu.nhsx`. Auto-Silence stays on by default. `COLAB_TRANSCRIBE_ONLY=1` does the same from the environment.

## [2026.10.8.2] - 2026-10-08

### Added
- **One command from a fresh Mac with Homebrew:** `curl -fsSL https://raw.githubusercontent.com/ollisulopuisto/podcast/main/run.sh | sh` installs `uv` and `ffmpeg` if missing, runs the Google sign-in the first time, and opens colab-transcribe. Naming another tool after `sh -s --` starts that one instead (autoraffkat, automixer, podcast-magic…).

## [2026.10.8.1] - 2026-10-08

### Added
- **Runs with one command and nothing installed but uv:** `uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe`. Google's `colab` tool now comes along as a dependency, pinned to the build with Google's own `jupyter-kernel-client` that works, so it no longer needs installing separately.
- **`colab-transcribe --login`:** a first-time Google sign-in through the `colab` tool (open an address in the browser, paste the code back). It covers Colab and the Drive transfer, so `gcloud` is no longer needed. The setup check points here first when credentials are missing.

### Fixed
- The setup check and the two `colab` fixes this app applies now find `colab`'s Python behind uv's `#!/bin/sh` launcher. Before, they read `/bin/sh` as the Python, reported a working `colab` as broken and silently skipped the fixes.

## [colab-transcribe-v2026.9.12.1] - 2026-09-12

### Fixed
- **Drive API Quota Project Isolation & Cache in Tests** (`gdrive.py`, `tests/conftest.py`, `tests/test_gdrive.py`):
  - Isolate test suite from host's Google Cloud ADC (`~/.config/gcloud/application_default_credentials.json`) and Colab token (`~/.config/colab-cli/token.json`) by setting isolated test paths and default test quota project in `conftest.py`.
  - Prevent unintended Cloud Resource Manager network requests from consuming mocked `urllib.request.urlopen` responses in unit tests when ADC is missing (e.g. clean CI runners).
  - Add `lru_cache` to `_fetch_quota_project_from_api` to avoid repeated remote Cloud Resource Manager calls during Google Drive requests.
  - Added unit tests for quota project resolution and fallback.
