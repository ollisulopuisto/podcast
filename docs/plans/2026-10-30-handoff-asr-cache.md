# Delegated task: distinguish transcription backend caches

**Agent worktree:** /private/tmp/podcast-asr-cache-backend  
**Branch:** codex/asr-cache-backend  
**Base:** 5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc

## Goal
Ensure Podcast Magic actually reruns transcription when the user switches among MLX Whisper, faster-whisper, Orukeet, and Parakeet Ultra, including when auto resolves to a different installed backend.

## Constraints
- Read repo and Podcast Magic instructions before editing.
- Add red-green tests for cache path/fingerprint differences across backends.
- Resolve the actual backend before building the transcript cache key; do not change alignment cache meaning unnecessarily.
- Preserve stored options/API/UI and NHSX output contracts.
- Run Podcast Magic tests and Ruff; no real model inference required for this pure cache fix.
- Work only in this worktree and commit only your task paths. Do not push.

## Handoff
Append decisions, files changed, tests, and commit SHA here.

## Integrator implementation (2026-10-30)

Root cause confirmed: `Options.fingerprint()` normalized both `mlx` and `faster-whisper` to `whisper`; `auto` also had no resolved runtime represented. Added a regression test first; it failed because `cache_path` had no resolved-backend parameter. The fix adds an optional backend key to the fingerprint/cache path and supplies `backend.key` after `resolve()`. Alignment cache remains unchanged.

Files: `apps/podcast-magic/src/podcastmagic/transcribe/options.py`, `apps/podcast-magic/src/podcastmagic/transcribe/run.py`, `apps/podcast-magic/tests/test_transcribe.py`.
