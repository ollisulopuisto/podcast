# Speaker-to-Shot Coverage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users assign each speaker to every video track where they appear, and let the editor choose among those shots without requiring a special “wide” role.

**Architecture:** Keep track keys as stable shot identities. Store speaker coverage and an optional context-shot preference on each video track, while keeping microphone ownership on audio tracks. Migrate saved `close`, `group`, and `wide` roles into that representation, then adapt selection and downstream consumers to the generalized shot list while retaining legacy behavior through compatibility views where needed.

**Tech Stack:** Python dataclasses, pytest, vanilla JavaScript UI, existing autoraffkat settings and preview pipeline.

---

### Task 1: Canonical shot settings and migration

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/model.py`
- Modify: `apps/autoraffkat/src/autoraffkat/project.py`
- Test: `apps/autoraffkat/tests/test_roles.py`
- Test: `apps/autoraffkat/tests/test_project.py`

**Steps:** Add a canonical video-shot setting with `covers` and `context`; migrate legacy close/group/wide data on load; retain mic and unused roles. First test multiple tracks covering the same speaker and migration from each legacy role; run those tests red; implement; run the focused tests green.

### Task 2: Resolve roles into a general shot inventory

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/analysis.py`
- Test: `apps/autoraffkat/tests/test_roles.py`

**Steps:** Test that resolved roles retain every shot, its covered speakers, and the context preference; verify unknown speakers and empty enabled shots produce actionable problems. Implement `Roles.shots` and compatibility views needed by remaining consumers; run focused tests.

### Task 3: Select among shots by coverage

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/decide.py`
- Test: `apps/autoraffkat/tests/test_decide.py`

**Steps:** Add failing cases for two shots covering one speaker, multiple all-speaker/context shots, overlap coverage, and deterministic selection. Extend the grid and selection logic so all eligible shots can be chosen, preserving current opening, long-take, minimum-duration, reaction, and overlap behavior. Run decision tests after each change.

### Task 4: Adapt preview and video/export consumers

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/preview.py`
- Modify: `apps/autoraffkat/src/autoraffkat/server/app.py`
- Modify: `apps/autoraffkat/src/autoraffkat/reactions.py`
- Modify: `apps/autoraffkat/src/autoraffkat/reframe.py`
- Modify: `apps/autoraffkat/src/autoraffkat/video/analyse.py`
- Modify: `apps/autoraffkat/src/autoraffkat/fcpxml/write.py`
- Test: relevant `apps/autoraffkat/tests/test_*.py`

**Steps:** Add focused tests for selected shot identity, context shots, and face/reaction eligibility. Update consumers to use shot inventory and explicit context preference; retain only valid single-speaker shots for close-up face analysis. Run relevant tests.

### Task 5: Replace the patch-bay wide/close setup with visibility assignments

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/server/static/app.js`
- Modify: `apps/autoraffkat/src/autoraffkat/server/static/i18n.js`
- Modify: `apps/autoraffkat/src/autoraffkat/server/static/style.css`
- Modify: `apps/autoraffkat/src/autoraffkat/server/app.py`
- Test: `apps/autoraffkat/tests/test_ui.py`
- Test: `apps/autoraffkat/tests/ui_smoke.js`

**Steps:** Add a failing UI test that each speaker can be checked on multiple video tracks and that the inverse track view reflects the same assignments. Replace role-specific placements with visible-on assignments and an optional context-shot marker. Add English and Finnish strings. Run UI tests and smoke checks.

### Task 6: Integration verification and docs

**Files:**
- Modify: `apps/autoraffkat/CLAUDE.md`
- Modify: `apps/autoraffkat/src/autoraffkat/server/CLAUDE.md`
- Modify: `apps/autoraffkat/README.md`
- Test: `apps/autoraffkat/tests/`

**Steps:** Update domain and UI guidance to match the canonical model. Run the autoraffkat test suite and `uv run ruff check .`. Inspect the diff for settings compatibility and user-visible translations.
