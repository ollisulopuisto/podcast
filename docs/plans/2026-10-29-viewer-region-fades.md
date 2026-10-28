# Viewer Region Fades Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Apply NHSX FadeIn/FadeOut attributes in viewer playback, including after seeking.

**Architecture:** Parse bounded fade durations into Region and Clip. Preserve existing ramp-level semantics and add a sample envelope used by playback, matching Python's midpoint-sampled raised-cosine edge fades. Keep unfaded clips on the streaming path.

**Tech Stack:** SwiftPM, XCTest, AVFoundation; Python pytest for shared conformance.

### Task 1: Regression tests

Create viewer/Tests/NhsxKitTests/RegionFadeTests.swift. Stage synthetic XML/audio files, verify FadeIn/FadeOut are recognized, bounded and preserved in clips, and check sampled edge fades, overlaps, ramps and seek offsets against manually calculated raised-cosine factors. Run `swift test --package-path viewer --filter RegionFadeTests` and observe failure before implementation.

### Task 2: Parse and apply fades

Modify viewer/Sources/NhsxKit/{Session,Mix,Player}.swift. Read durations, retain sample-based envelope geometry, route faded clips through buffer processing and evaluate original clip frame coordinates after seeking. Existing level(at:) keeps its ramp-only contract.

### Task 3: Verify and document

Run `swift test --package-path viewer`, `uv run --directory apps/podcast-magic pytest -q tests/test_conformance.py`, and `uv run ruff check .`. Update viewer/README.md and automixer roadmap to reflect supported edge fades, while stating their shape is assumed rather than measured. Commit only these paths on codex/viewer-region-fades.
