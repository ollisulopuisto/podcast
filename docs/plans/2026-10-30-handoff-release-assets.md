# Delegated task: publish the oversized Linux release asset safely

**Agent worktree:** /private/tmp/podcast-release-split-assets  
**Branch:** codex/release-split-assets  
**Base:** 5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc

## Goal
Prevent a Linux release asset larger than GitHub's 2 GiB per-file limit from blocking publication of the already-successful macOS DMG, while retaining a clear, tested route to provide the Linux build.

## Constraints
- Read repo instructions and inspect the failed tag workflow/log report before editing.
- Do not use continue-on-error, suppress an unexpected upload failure, replace an existing release asset, or publish a false green status.
- Add regression tests before implementation. Cover files below, at, and above the reported boundary using sparse/temp files; test the publisher's command/file selection without network calls.
- Keep release notes accurate and give Linux users exact reconstruction instructions if the archive is split.
- Do not alter an existing tag/release or change app version files.
- Work only in this worktree and commit only your task paths.

## Handoff
Append decisions, files changed, tests, limits, and commit SHA to this file. Do not edit the root checkout or other branches.
