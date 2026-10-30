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
