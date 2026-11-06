# Autoraffkat Automatic Sync and In/Out Implementation Plan

**Goal:** Let an editor bring camera scratch audio and separate microphone recordings into Autoraffkat, align them automatically, set programme in/out points, and render/export only the chosen range.

**Architecture:** Keep audio measurement out of the fast decision loop. Decode low-rate audio envelopes in a background task, estimate each microphone's timeline shift against camera reference audio, and require a reviewable confidence result before changing placements. Store the selected programme range as rational timeline times and pass the same range to preview, FCPXML export, and video rendering.

**Tech Stack:** Python 3.13, NumPy/FFmpeg, shared `fcpxml` timeline types, FastAPI server state, browser canvas UI, existing AVFoundation video renderer.

---

## Decisions and boundaries

- Autoraffkat must accept a set of original media files without a pre-synced Final Cut project. The source files remain untouched; generated project/export files live beside the sources.
- Camera embedded audio is the reference signal. A separate microphone may be shifted only when there is enough shared programme content and a clear correlation peak; otherwise the app reports the track for manual sync.
- Start with a bounded, coarse envelope correlation, not full-rate waveform correlation. The algorithm must report the proposed shift and confidence so a user can review or correct it.
- In/out points use sequence time and frame-accurate `Fraction` values. They are saved with project settings, clamped to the programme bounds, and applied consistently to the preview, FCPXML export, and render.
- Do not modify the original media or source XML. Do not silently accept an ambiguous sync estimate.

## Milestones

### 1. Audio offset measurement core — started

Added `audio/sync.py` with bounded FFT cross-correlation, source-shift sign semantics, a normalized correlation score, and a no-result outcome for flat/insufficient data. Five synthetic tests cover both shift directions, bounded search, silence, and invalid dimensions. The primitive has not yet been connected to FFmpeg or the UI, and its score is not yet a calibrated accept/reject confidence threshold.

### 2. Media import and sync review

Add a media-selection flow for camera and microphone files, read embedded camera audio and external audio through FFmpeg, estimate microphone offsets against the camera reference, and show the measured shift and confidence per track. Let the user accept or adjust the result. Build the initial timeline from those placements and continue through the existing speaker/shot workflow.

### 3. Programme in/out controls

Add persistent range state and draggable in/out handles to the timeline. Show the selected region clearly, allow keyboard-numeric edits, validate non-empty ranges, and include undo/redo and reload behavior.

### 4. Range-aware output

Apply the exact same frame-quantized range to the FCPXML writer and on-demand video renderer. Add boundary tests for clips crossing either edge, attached audio, multicam parts, and ranges at sequence ends. Update English/Finnish UI strings and workflow documentation.

## Task 1: Correlation primitive

**Files:**
- Create `apps/autoraffkat/src/autoraffkat/audio/sync.py`.
- Create `apps/autoraffkat/tests/test_audio_sync.py`.
- Modify this plan as each milestone is completed.

**Steps:**
1. Done: write synthetic offset tests and confirm they fail before implementation.
2. Done: implement the bounded FFT correlation primitive and explicit shift sign.
3. Run the full Autoraffkat suite and Ruff before committing this measurement-only slice.
4. Keep real-media accuracy unclaimed until integration is measured on camera/mic material.

## Validation

- Focused tests use deterministic synthetic signals; they prove lag math and failure handling, not real-recording accuracy.
- Integration tests use generated audio/video fixtures and FFmpeg where available.
- A real project must be checked by the user in Final Cut before treating the first automatic-sync export as production-safe.
- Run `uv run ruff check .` and `uv run --directory apps/autoraffkat pytest -q` per `CONTRIBUTING.md`; when `uv run` stalls, use the repository virtualenv's Python as documented by the task owner.

**Task 1 check-in (2026-11-06):** `ruff check .` passed. Focused sync tests passed (5). The full Autoraffkat suite passed (665 passed, 18 skipped) when run with access to its normal macOS cache directory; the sandboxed run could not write that cache and aborted in an unrelated native audio test.
