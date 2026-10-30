# ASR Backend Handoff / Coordination (2026-10-30)

## Goal
Audit the three transcription engines (Whisper, Orukeet, Parakeet Ultra) across Podcast Magic and Colab Transcribe, reduce code drift where technically safe, then deliver a fresh Apple Silicon Podcast Magic DMG.

## Current known state
- Current main: 5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc.
- Tag: podcast-magic-v2026.10.29.1, same source commit.
- A fresh Apple Silicon DMG is already on the release page. Release workflow build jobs passed; the all-platform publisher failed because the Linux archive exceeded GitHub's 2 GiB per-asset limit. The macOS DMG was recovered from the successful job and attached.
- Podcast Magic source at the tag has MLX Whisper, faster-whisper, Orukeet, and Parakeet Ultra adapters.
- Colab Transcribe's state needs verification on a clean main worktree. Local uncommitted changes in the primary checkout must not be overwritten or reset. Earlier inspection suggests the local route has MLX Parakeet and Orukeet, while Colab Photon supports Whisper and Parakeet Ultra.
- User explicitly asked to coordinate work through Markdown files and keep progressing until 08:00 Europe/Helsinki, with a new DMG available.

## Rules
- Read repo CLAUDE.md, CONTRIBUTING.md, and app CLAUDE.md before implementation.
- Do not overwrite the primary checkout's user changes.
- TDD, strict Ruff, tests for changed members.
- Branch from current main; commit only owned paths; do not bump a version or edit changelogs except the release task.
- Call out hardware/real-Colab checks that are not performed.
- Cross-platform release workflow failure must not hide a valid Mac DMG.

## Agent reports
Agents should append findings to this file or create a linked Markdown report in docs/plans/; make no overlapping implementation edits unless assigned.

## Integrator final status (2026-10-30 09:55 Europe/Helsinki)

### Verified commits pushed

- `codex/asr-backend-sharing` at `49e8742`: cloud Whisper/Ultra timing labels; Colab suite 398 passed; Ruff clean. Real Colab not run.
- `codex/colab-tui-engines` at `cf0d37e`: preserve/expose TUI cloud model and source; Colab suite 406 passed; Ruff clean.
- `codex/release-split-assets` at `a2420c0`: Mac-first publication and split/checksummed Linux archive; release regressions 17 passed; Ruff clean.
- `codex/asr-cache-backend` at `df73290`: transcript cache follows resolved backend while alignment cache names stay stable; Podcast Magic suite 369 passed; Ruff clean.
- `feat/colab-orukeet` at `50cb9d3`: local Orukeet plus Colab Whisper/Ultra and shared wordalign changes; Colab suite 382 passed, wordalign 47 passed, Ruff clean. This branch is 45 commits behind current `origin/main` and contains two older commits not in main; a port attempt conflicted and was aborted without altering the feature branch. It needs a deliberate main-based integration before PR.

All branch test results above are local; CI has not run. PR creation was attempted for the four current-main branches, but GitHub returned 403 `Resource not accessible by integration`. The local `gh` token is invalid. Branches are pushed and can be opened manually:

- https://github.com/ollisulopuisto/podcast/compare/main...codex/asr-backend-sharing?expand=1
- https://github.com/ollisulopuisto/podcast/compare/main...codex/colab-tui-engines?expand=1
- https://github.com/ollisulopuisto/podcast/compare/main...codex/release-split-assets?expand=1
- https://github.com/ollisulopuisto/podcast/compare/main...codex/asr-cache-backend?expand=1
- https://github.com/ollisulopuisto/podcast/compare/main...feat/colab-orukeet?expand=1 (stale base; integrate first)

No PR was created or merged, no tag was added, and no new DMG build was triggered. The existing `podcast-magic-v2026.10.29.1` Apple Silicon DMG remains available; the requested 08:00 Helsinki deadline passed before a new release could be produced.
