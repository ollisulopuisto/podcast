# Smooth ffmpeg zoom Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove visible side-to-side jitter from ffmpeg slow zooms.

**Architecture:** Keep the fixed source crop covering both endpoints, but replace independently rounded animated scaling and cropping with a per-frame subpixel perspective transform at source resolution, before the fixed output resize. Use the same source window geometry and preserve static rendering.

**Tech Stack:** Python, ffmpeg perspective, pytest marker video.

---

### Task 1: Reproduce

Parametrize `apps/autoraffkat/tests/test_render.py::test_a_slow_zoom_moves_smoothly_without_wobble` across ffmpeg and AVFoundation. Run the ffmpeg case red using `uv run --directory apps/autoraffkat pytest tests/test_render.py -k slow_zoom -q`.

### Task 2: Implement and verify

Change `apps/autoraffkat/src/autoraffkat/render.py::video_filter` so animated source windows use subpixel sampling. Run the zoom and existing endpoint geometry tests green. Cover zoom direction and fixed offsets. Preserve exact frame counts.

### Task 3: Document and integrate

Update the rendering facts in `apps/autoraffkat/CLAUDE.md` with synthetic marker measurements and constraints. Run the autoraffkat suite and root `uv run ruff check .`, then commit only these paths.
