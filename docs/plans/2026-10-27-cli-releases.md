# CLI Release Builds Implementation Plan

> Execute the steps in this chat; the user has authorized implementation.

**Goal:** Build tested, pinned automixer and colab-transcribe releases on GitHub.

**Architecture:** Build each app and its transitive workspace libraries from one
commit. Export third party requirements from the existing lockfile, bundle them
with wheels and an installer, test installation outside the source tree, and
publish only app-specific version tags after both platform jobs pass.

**Tech Stack:** Python standard library, uv, pytest, GitHub Actions.

### Task 1: Bundle builder and installer

Create `tests/test_cli_release.py` first. Verify dependency closure, tag mismatch
rejection, portable wheel references, commit provenance, and refusal to install
tampered or incompatible bundles. Run it with the existing workspace Python and
observe failures before adding `scripts/build_cli_release.py` and
`scripts/install_cli_release.py`. Build both real apps and inspect the archives.

### Task 2: GitHub builds and releases

Create `.github/workflows/build-cli.yml`: PR and manual builds, plus
`automixer-v*` / `colab-transcribe-v*` tag releases. Run lint, workspace tests,
the app and library tests, then build and install wheels in an isolated
environment on macOS ARM64 and Linux x86_64. Publish only after every build
passes; require tag and project version agreement. Validate the YAML and run
root tests and Ruff.

### Task 3: Installation and handoff

Create `docs/CLI-RELEASES.md`, update `CONTRIBUTING.md` and link it from the
Kuulas integration document. Document pinned downloads, checksums, installation,
rollback, external system dependencies and release commands. Commit only these
paths on `codex/cli-release-builds`, push and open a PR when possible.
