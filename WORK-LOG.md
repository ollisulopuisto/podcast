# Work log

## CUDA 13 command-line test, 2026-11-21

Owner: Instinct. Branch: agent/cuda13-test-script. Status: Review. Adds scripts/cuda13_test.py and stage/fail-closed tests for the owner-requested Linux/Colab/WSL2 experiment. No app dependencies, drivers, releases or main changes. See docs/CUDA13-TEST.md for checks and unrun GPU acceptance. No merge authorized for this PR.

## CUDA runner safety follow-up

Fixed inherited uv project environment escape, selected-GPU validation and WSL probe lookup. 17 mocked regressions pass, including external environment preservation and visibility failures. Full Ruff passes. No real GPU acceptance claimed; PR remains unmerged.

Follow-up: disabled machine-wide pip settings and fail closed on an empty first GPU-list entry. 21 mock cases pass after three red-before regressions; Ruff passes.

Unposted review investigations: added the offline regression module to existing Linux CI and documented the optional transcription backend's CUDA 12/cuDNN runtime prerequisite. No GPU CI, driver install or dependency change added.
