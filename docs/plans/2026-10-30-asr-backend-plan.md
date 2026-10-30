# Shared ASR Backends Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Whisper, Orukeet, and Parakeet Ultra available through Podcast Magic and Colab Transcribe with shared backend contracts and a fresh Apple Silicon DMG.

**Architecture:** Keep device-specific inference adapters thin while moving backend names, capability metadata, result normalization, and reusable runtime adapters into a workspace package. Colab will receive the same shared source files through its existing upload mechanism because its remote runtime cannot import the workspace. Preserve existing CLI, word JSON, progress, and event contracts.

**Tech Stack:** Python workspace packages, optional ASR dependencies, Photon/Moondream, Orukeet, faster-whisper, MLX, pytest, Ruff, GitHub Actions macOS DMG release workflow.

---

### Task 1: Establish an exact coverage matrix

**Files:**
- Create: docs/plans/2026-10-30-asr-backend-handoff.md
- Review: Podcast Magic and Colab Transcribe backend modules and CLI options

**Steps:**
1. Record which engine/backend combinations currently work on local Apple Silicon, local CPU/CUDA, and Colab.
2. Distinguish model availability from runtime availability and mark any unverified Colab path.
3. Identify inference/result-normalization code that is genuinely shared versus runtime-specific.
4. Do not edit implementation files during the audit.

### Task 2: Design the shared backend boundary

**Files:**
- Review: packages/, apps/podcast-magic/src/podcastmagic/transcribe/backends/, colab-transcribe/src/colabtranscribe/
- Create: packages/asr only if the audit proves a stable shared contract

**Steps:**
1. Write contract tests for engine IDs, capabilities, result shape, and word timing normalization.
2. Verify the tests fail against current duplicated behavior for the intended gap.
3. Implement the smallest shared module possible without importing platform-only dependencies at module load.
4. Keep runtime-specific model loading in adapters and avoid packaging model weights.

### Task 3: Complete supported backend paths

**Files:**
- Modify: apps/podcast-magic/src/podcastmagic/transcribe/backends/
- Modify: colab-transcribe/src/colabtranscribe/
- Modify: Colab upload planning and colab-transcribe/src/colabtranscribe/colab/pipeline.py

**Steps:**
1. Add failing tests for each supported path and explicit rejection of unsupported combinations.
2. Make Whisper, Orukeet, and Parakeet Ultra selectable in the relevant local and Colab routes.
3. Preserve local MLX acceleration and Photon on Colab where those are the supported runtimes.
4. Ensure the Colab driver uploads shared runtime modules before executing the script.
5. Run member tests, workspace contract tests, and Ruff; report any real Colab/model-hardware checks that cannot run here.

### Task 4: Release a current Podcast Magic DMG

**Files:**
- Modify only Podcast Magic version files via scripts/bump_version.py
- Release workflow only if Task 1 proves the current publisher still blocks valid DMGs

**Steps:**
1. Confirm the exact merged commit includes all intended backend and sharing changes.
2. Bump the Podcast Magic CalVer version and verify all version locations and lockfile.
3. Build/test the Apple Silicon app and DMG from the exact release commit.
4. Ensure the release publisher tolerates the Linux archive 2 GiB limit without losing the macOS DMG.
5. Publish the tag and report the DMG URL, SHA-256, and source commit.

### Task 5: Handoff and operational notes

**Files:**
- Update: docs/plans/2026-10-30-asr-backend-handoff.md

**Steps:**
1. Record merged PRs, test evidence, hardware validation limits, and release links.
2. State whether Podcast Magic and Colab now use the same backend source modules.
3. Leave no claim of a real Colab or podcast-accuracy test unless that run was actually performed.
