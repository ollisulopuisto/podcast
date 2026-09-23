# Roadmap: automixer

What is planned, in order, and what has to be true before each step starts.

---

## 1. Prove the Hindenburg path on real episodes (now)

`automixer episode.nhsx` mixes a Hindenburg session: cuts, fades and region
clip gain from the session, levels and mastering from the shared chain.
Per-track plugin parameters (`--track-params`, TUI Plugins tab) let one
speaker get more cleanup than the others.

Before anything is built on top of it:

- A few real episodes, listened to against the hand-made render with
  `scripts/ab/compare.py` (loudness-matched).
- Settle which controls are actually touched per episode. So far: the
  programme target, dxRevive amount per speaker, and dxRevive's model. That
  list is the GUI's first screen; everything else stays one level down or
  is not a control.

First result (pikis 2026-09-11, loudness-matched): automixer with dxRevive
Studio 2 at 25 / 25 / 50 % (Olli / Kari / Panu — Panu's room is the
reverberant one) beat both the hand render and automixer without
dxRevive. Per-speaker cleanup is a real control.

## 2. A desktop GUI like autoraffkat's

**Why:** the TUI works, but choosing files, speakers and per-speaker cleanup
is easier to see than to type, and the result should be listenable in the
same window.

**Shape** — the pattern the repo already has, not a new one:

- A local FastAPI server with a browser UI in a pywebview window
  (autoraffkat's `server/`, podcast-magic's lighter `gui.py`).
- The render runs in a child process that reports progress as
  line-delimited JSON (autoraffkat's `audio/worker.py`): the plug-in must
  load on a main thread, and a crashing plug-in must take nothing with it.
- Screens: pick files or one `.nhsx` → speakers and music (role, per-speaker
  cleanup amount) → target and mastering → render with progress → A/B the
  result against a reference (reuse `scripts/ab/vertailu.html`).

**Rules that come with it** (see the root `CLAUDE.md` and autoraffkat's):

- Every user-visible string in Finnish and English.
- A UI smoke test that renders every view and fires every handler, and that
  fails on an uncalled function — as `apps/autoraffkat/tests/ui_smoke.js`.
- A measured default is not a slider on the first screen.

**Size:** medium, about two to three working sessions. automixer needs a
fraction of autoraffkat's UI: no picture, no cuts, no Final Cut export.

**Starts when** step 1 has settled which controls are real.

## 3. Later

- The Swift NHSX viewer does not yet apply `FadeIn`/`FadeOut`
  (`viewer/Sources/NhsxKit/Mix.swift`); `nhsx-render` and automixer do.
- An own cleanup model in place of dxRevive (reverb, noise, artefacts) —
  the long-term goal for the plug-in slot. Level and dynamics stay in the
  chain.
