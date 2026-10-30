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
