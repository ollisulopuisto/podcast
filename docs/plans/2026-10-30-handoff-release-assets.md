# Delegated task: publish the oversized Linux release asset safely

**Agent worktree:** /private/tmp/podcast-release-split-assets  
**Branch:** codex/release-split-assets  
**Base:** 5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc

## Goal
Prevent a Linux release asset larger than GitHub's 2 GiB per-file limit from blocking publication of the already-successful macOS DMG, while retaining a clear, tested route to provide the Linux build.

## Constraints
- Read repo instructions and inspect the failed tag workflow/log report before editing.
- Do not use continue-on-error, suppress an unexpected upload failure, replace an existing release asset, or publish a false green status.
- Add regression tests first. Cover files below, at, and above the reported boundary using sparse/temp files; test the publisher's command/file selection without network calls.
- Keep release notes accurate and give Linux users exact reconstruction instructions if the archive is split.
- Do not alter an existing tag/release or change app version files.
- Work only in this worktree and commit only your task paths.

## Handoff
Append decisions, files changed, tests, limits, and commit SHA to this file. Do not edit the root checkout or other branches.

## Implementation plan

Use a standard-library publisher in `scripts/publish_podcast_magic.py` and
regressions in `tests/test_podcast_magic_release.py`. Keep the build matrix
unchanged. In `.github/workflows/build-podcast-magic.yml`, download/publish Mac
first; only afterward download other platform artifacts and upload them.

1. Add sparse-file boundary tests, a small real split/reassembly/checksum test,
   and mocked release-command tests (Mac first, later failure remains failure,
   missing Mac rejected, existing releases never overwritten).
2. Run the new tests and observe missing publisher/workflow behavior fail.
3. Implement bounded-memory splitting at the measured API boundary; publish
   parts with reconstruction instructions and checksums. Use `gh` with checked
   exit status, no clobber or automatic deletion/recreation.
4. Wire the two publisher stages into the workflow, then run the regression
   suite, root tests, and strict Ruff. Document unavailable validation.
5. Commit only the publisher, regression tests, workflow, and this handoff.
