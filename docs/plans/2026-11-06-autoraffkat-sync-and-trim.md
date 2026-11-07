# Autoraffkat Automatic Sync and In/Out Implementation Plan

**Goal:** Let an editor bring camera scratch audio and separate microphone recordings into Autoraffkat, align them automatically, set programme in/out points, and render/export only the chosen range.

**Architecture:** Keep audio measurement out of the fast decision loop. Decode low-rate audio envelopes in a background task, estimate each microphone's timeline shift against camera reference audio, and require a reviewable estimate before changing placements. Store the selected programme range as rational timeline times and pass the same range to the timeline preview, FCPXML export, and on-demand video render.

**Tech Stack:** Python 3.13, NumPy/FFmpeg, shared `fcpxml` timeline types, FastAPI server state, browser canvas UI, existing AVFoundation video renderer.

---

## Decisions and boundaries

- Autoraffkat must accept a set of original media files without a pre-synced Final Cut project. The source files remain untouched; generated project/export files live beside the sources.
- Camera embedded audio is the reference signal. A separate microphone may be shifted only when there is enough shared programme content and a clear correlation peak; otherwise the app reports the track for manual sync.
- Start with a bounded, coarse envelope correlation, not full-rate waveform correlation. The algorithm must report the proposed shift and confidence so a user can review or correct it.
- In/out points use sequence time and frame-accurate `Fraction` values. They are saved with project settings, clamped to the programme bounds, and applied consistently to the preview, FCPXML export, and render.
- Do not modify the original media or source XML. Do not silently accept an ambiguous sync estimate.

## Milestones

### 1. Audio offset measurement core — complete

Added `audio/sync.py` with bounded FFT cross-correlation, source-shift sign semantics, a normalized correlation score, and a no-result outcome for flat/insufficient data. Five synthetic tests cover both shift directions, bounded search, silence, and invalid dimensions. The score is a review aid, not a calibrated accept/reject threshold.

### 2. Media import and sync review — implementation complete, real-media validation pending

Added multi-file camera/microphone selection, source inspection, background envelope decoding with progress, and an estimate against a selected camera reference. Other audible camera tracks and standalone microphones receive proposed shifts. Estimates remain editable; when there is no clear estimate the editor can enter a manual shift. Accepting the review writes a new source FCPXML beside the media and opens it in the existing editor. Camera scratch audio is disabled in the edit while remaining the sync reference. Synthetic and API/UI smoke tests cover shift direction, progress, camera-to-camera and camera-to-mic offsets, import, and status. The correlation score still needs validation on representative real recordings before it can be treated as an accuracy guarantee.

### 3. Programme in/out controls — implementation complete

Added timeline click marking with explicit in/out mode buttons, visible selection overlay, numeric seconds fields, clear action, undo/redo snapshots, and project-settings persistence. The selected range is clamped and quantized to the nearest sequence frame; an empty or reversed range safely falls back to the full programme.

### 4. Range-aware output — implementation complete, real-project review pending

The same quantized bounds now reach both FCPXML writers and the on-demand renderer. An end-to-end test checks the FCPXML sequence duration and render start/frame count. The preview remains the full programme and shades the selected output region. Boundary behavior for real multi-part projects still needs owner review.

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

**Task 2 check-in (2026-11-06):** media import, API, and UI smoke tests pass. Source clips are aligned to the selected camera reference, and the editor must accept the editable offsets before a source project is written. No real episode recording has been measured yet.

**Tasks 3–4 check-in (2026-11-06):** frame-quantized in/out marks persist in project settings and constrain both XML export and render. A fixture-driven end-to-end test passes; the owner should review a real multicamera project before relying on sync estimates in a production export.

**Integration check-in (2026-11-07):** rebased the three feature commits onto current `main`; documented raw-media sync, reviewable offsets, frame-snapped in/out marks, and range rendering in both READMEs. Focused sync/import/range tests passed (20), and UI plus XML/render integration tests passed (8). Accuracy on real camera/microphone recordings and review in Final Cut remain owner validation items; the synthetic score is not presented as an accuracy guarantee.
