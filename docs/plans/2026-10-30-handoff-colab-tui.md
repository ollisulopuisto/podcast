# Delegated task: preserve and expose Colab TUI engine choices

**Agent worktree:** /private/tmp/podcast-colab-tui-engines  
**Branch:** codex/colab-tui-engines  
**Base:** 5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc

## Goal
Fix Colab Transcribe's TUI so it does not silently discard a selected backend/model/source/language/alignment option when constructing RunOptions, and expose the engine choices that the CLI already supports where the current TUI has an appropriate settings flow.

## Constraints
- Read the repo and Colab Transcribe instructions before editing.
- Use red-green tests and run Colab Transcribe tests plus Ruff.
- Preserve CLI, Colab command, word JSON, progress, exit-code, SIGTERM, and schema-1 event contracts.
- Keep local Orukeet/local MLX Parakeet audio-only validation; do not present local MLX Parakeet as Parakeet Ultra.
- Work only in this worktree and commit only your task paths.

## Handoff
Append decisions, files changed, tests, limits, and commit SHA to this file. Do not edit the root checkout or other branches.

## Implementation plan

1. Add a failing TUI regression test proving that collecting visible fields
   preserves every other initial `RunOptions` setting, including local
   audio-only settings. Use `dataclasses.replace` to fix reconstruction.
2. Add failing tests for selecting cloud Whisper/Ultra and tracks/downmix,
   including the resulting cloud command. Add selectors to the existing
   session form; keep native Orukeet and MLX Parakeet as audio-only CLI guidance.
3. Add failing tests proving that initial local/audio settings cannot enter
   the TUI's session-oriented cloud worker. Give actionable CLI guidance before
   cloud onboarding or job startup; preserve the options themselves.
4. Run the Colab suite and pinned Ruff against this worktree, inspect the diff,
   commit only task paths, and record evidence and runtime limitations here.

Scope agreed with the integrator: no new local-audio TUI execution flow.

## Integrator verification (2026-10-30)

- Reviewed the implementation; it preserves hidden `RunOptions` fields with `dataclasses.replace`, exposes cloud model/source selectors, and directs audio-only local backends to the CLI.
- TUI tests: 27 passed. Full Colab Transcribe suite and Ruff are being rerun by integrator.
