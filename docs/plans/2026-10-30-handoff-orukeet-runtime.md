# Delegated task: shared Orukeet runtime

**Agent worktree:** /private/tmp/podcast-shared-orukeet-runtime  
**Branch:** codex/shared-orukeet-runtime  
**Base:** 5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc

## Goal
Remove duplicated Orukeet model initialization and inference between Podcast Magic and Colab Transcribe's local Orukeet route, while keeping each app's audio conversion, CTC alignment policy, progress, events, and output format intact.

## Constraints
- Read the repo and both app instructions before editing.
- Use red-green tests and run relevant member tests plus Ruff.
- Do not change API/output contracts or claim the adapter works on devices not actually tested.
- Keep Orukeet as an optional runtime dependency; do not package model weights.
- Work only in this worktree and commit only your task paths.
- If a stable shared boundary requires an unexpectedly broad package/lock migration, stop and document the specific blocker rather than forcing a generic backend framework.

## Handoff
Append decisions, files changed, tests, limits, and commit SHA to this file. Do not edit the root checkout or other branches.
