# Autoraffkat Silence Pass Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an opt-in FCPXML automation pass that fades dialogue microphones down during long spans where Autoraffkat detects no speaker, while showing those exact spans on the editable preview timeline.

**Architecture:** Reuse the existing `Grid.speakers[*].on` activity lanes; do not import Podcast-Magic or read `.nhsx` files. A pure Autoraffkat helper will turn global dead-air runs into per-speaker dB keyframes and preview intervals. Export applies those keyframes only to `dialogue.*` mic roles; room tone, music, camera audio, and the default export remain untouched. The existing canvas preview gets a dedicated, zoom-aligned silence lane, and settings edits recompute it from the same grid used by export.

**Tech Stack:** Python 3.13, NumPy, pytest, FCPXML volume keyframes, browser canvas UI, Node smoke harness.

---

### Task 1: Define silence spans and faded envelopes

**Files:**
- Create: `apps/autoraffkat/src/autoraffkat/audio/silence.py`
- Test: `apps/autoraffkat/tests/test_silence.py`

**Steps:**
1. Test that only gaps at least `silence_min_gap` long qualify, and that a gap means no speaker lane is active.
2. Test that envelopes fade from 0 dB to the configured attenuation and back, and are emitted for dialogue speakers only.
3. Run the focused tests and confirm they fail before implementation.
4. Implement the pure grid-to-spans/envelopes helper using `HOP` and existing run utilities.

### Task 2: Persist settings and apply dialogue-only FCPXML automation

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/model.py`
- Modify: `apps/autoraffkat/src/autoraffkat/server/app.py`
- Modify: `apps/autoraffkat/src/autoraffkat/finalcut/write.py` only if envelope composition needs a writer change
- Test: `apps/autoraffkat/tests/test_write.py` and settings/export tests

**Steps:**
1. Test default-off settings and serialization of minimum gap, attenuation, and fade.
2. Test that export automation reaches dialogue role sources but never room-tone/music roles.
3. Run the focused tests red, then add settings and merge silence envelopes with existing duck/fade envelopes without duplicate-time keyframes.
4. Keep all behavior byte-compatible when the option is off.

### Task 3: Show the computed pass on the preview timeline

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/preview.py`
- Modify: `apps/autoraffkat/src/autoraffkat/server/app.py`
- Modify: `apps/autoraffkat/src/autoraffkat/server/static/app.js`
- Modify: `apps/autoraffkat/src/autoraffkat/server/static/i18n.js`
- Test: `apps/autoraffkat/tests/test_shot_domain.py` or a focused preview test
- Test: `apps/autoraffkat/tests/ui_smoke.js`

**Steps:**
1. Test that silence intervals are bucketed to the same view/window and columns as speaker/cut lanes.
2. Test that changing silence settings causes the displayed row and summary to use the fresh result.
3. Add a visually distinct timeline row and legend label/count; show it only when the pass is enabled.
4. Run the Python preview tests and Node-backed UI smoke test.

### Task 4: Document and validate

**Files:**
- Modify: `apps/autoraffkat/README.md`
- Modify: `apps/autoraffkat/README.fi.md`
- Modify: `apps/autoraffkat/CLAUDE.md`
- Modify: `apps/autoraffkat/src/autoraffkat/server/CLAUDE.md`

**Steps:**
1. Document what the pass changes, its controls, the timeline preview, and that non-dialogue roles remain unchanged.
2. Run the autoraffkat test suite and `ruff check .` per repository rules.
3. Inspect the export diff to confirm the disabled default writes no new automation.
4. Commit only feature paths.

## Implementation status (2026-10-30)

- Implemented opt-in dead-air envelopes, settings persistence, export wiring,
  and a zoom-aligned amber timeline lane with fade shoulders and a legend.
- Verified focused decision, writer, UI smoke, and silence tests: 163 passed,
  18 skipped. `ruff check .`, JavaScript syntax checks, and `git diff --check`
  pass.
- The full Autoraffkat test run is not clean in this checkout: an existing
  end-to-end cache test fails because its second analysis rereads a fixture;
  a subsequent full run aborts in SciPy's CPU audio worker. The focused
  feature/UI/writer tests above complete successfully.

