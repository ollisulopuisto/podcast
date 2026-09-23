# Roadmap: Multi-NLE Support (DaVinci Resolve & Adobe Premiere Pro)

> **Looking to contribute?** Multi-NLE support is one of the highest-impact areas to work on in `autoraffkat`. If you use DaVinci Resolve or Adobe Premiere Pro, this is a fantastic project to tackle as an open-source contribution!

---

## Background & Architecture

`autoraffkat` was originally built around Final Cut Pro XML (`.fcpxml` / `.fcpxmld`), but its internal architecture is already decoupled from Final Cut Pro.

As described in [`DESIGN.md`](DESIGN.md):
```
   [Input File]  ──►  Reader (e.g. fcpxml/read.py)  ──►  Timeline (MediaItem + Placement)
                                                                   │
                                                ┌──────────────────┴──────────────────┐
                                                │                                     │
                                          audio/envelope.py                     User Roles &
                                          ffmpeg + RMS 20 ms                      Controls
                                                │                                     │
                                                └──────────────►  analysis.py  ◄──────┘
                                                                  MILLISECONDS
                                                                       │
                                                                       ▼
                                                                  decide.py
                                                                  thresholds, durations, overlap
                                                                       │
                                                       ┌───────────────┴───────────────┐
                                                       ▼                               ▼
                                                 preview.py                     Writer (e.g. fcpxml/write.py)
                                                 web browser bar                New project / timeline
```

Everything in the middle—audio decoding, speaker energy envelopes, turn detection, cut decisions (`decide.py`), reaction shots, reframing, and the web preview—operates purely on the abstract [`Timeline`](src/autoraffkat/model.py) structure.

Supporting other Non-Linear Editors (NLEs) is therefore **purely an I/O interchange task**: reading the NLE's timeline format into `Timeline`, and serializing the cut list back into that format.

---

## Target NLEs & Implementation Phases

### Phase 1: DaVinci Resolve Compatibility via FCPXML (Starter PR / Good First Issue)

**Goal:** Allow users to round-trip projects between Blackmagic DaVinci Resolve (Free & Studio) and `autoraffkat` using `.fcpxml`.

* **The Opportunity:** DaVinci Resolve natively imports and exports `.fcpxml` (*File → Import → Timeline → Import AAF/EDL/XML*). Resolve has a very popular free tier widely used by podcast editors.
* **The Challenge:** Resolve's FCPXML parser is pickier than Apple's Final Cut Pro. It tends to prefer FCPXML v1.8 or v1.9, and handles certain elements (such as `<sync-source>`, timecode formats, or `<mc-clip>` multicam containers) with slight schema differences.
* **Tasks:**
  1. Export a multicam project from DaVinci Resolve as `.fcpxml` and test opening it in `autoraffkat`.
  2. Verify if autoraffkat's flat export (`export_flat`) already imports cleanly into Resolve.
  3. Identify any XML elements or attributes rejected by Resolve's XML importer when importing the cut multicam.
  4. Add an export option or dialect profile (e.g. `format="resolve"`) that writes Resolve-compatible FCPXML.
  5. Add test fixtures and assertions in `tests/test_write.py`.

---

### Phase 2: Classic FCP 7 XML (`xmeml`) — Unlocks BOTH Premiere Pro & DaVinci Resolve

**Goal:** Enable native import and export for Adobe Premiere Pro and DaVinci Resolve using the universal FCP 7 XML standard.

* **The Opportunity:** Adobe Premiere Pro **cannot** natively import modern Final Cut `.fcpxml` without commercial 3rd-party plugins. However, Premiere Pro AND DaVinci Resolve BOTH natively support classic Final Cut Pro 7 XML (`<xmeml version="4">` or `5`) via standard *File → Import* and *File → Export*.
* **Implementation:**
  1. **Reader (`src/autoraffkat/xmeml/read.py`):**
     * Parse `<xmeml>` sequences into `Timeline` (translating tracks, `<clipitem>`, media file paths, and timecodes).
     * Time in FCP 7 XML uses integer frames and timebase rates (simpler than FCPX rational fractions).
  2. **Writer (`src/autoraffkat/xmeml/write.py`):**
     * Generate an `<xmeml>` sequence with the cuts placed on video tracks and dialogue audio attached with appropriate roles.
  3. **Tests:**
     * Add round-trip tests in `tests/test_xmeml.py` with real Premiere Pro and DaVinci Resolve exported XML fixtures.
  4. **UI Integration:**
     * Accept `.xml` alongside `.fcpxml` in the file picker and auto-detect the parser based on root XML tag (`<xmeml>` vs `<fcpxml>`).

---

### Phase 3: DaVinci Resolve Live Python API (`DaVinciResolveScript`)

**Goal:** Zero-file-export editing directly inside running DaVinci Resolve instances.

* **The Opportunity:** DaVinci Resolve ships with a native Python scripting API (`DaVinciResolveScript`), available in both free and Studio versions on macOS, Windows, and Linux.
* **Implementation:**
  1. Add a bridge module that connects to Resolve (`dvr_script.GetResolve()`).
  2. Read active timeline tracks, clips, and timecodes directly into `Timeline`.
  3. Execute cut decisions by splitting clips or creating a cut timeline track via the API.
  4. Add a "Cut Active Resolve Timeline" button in the web UI.

---

## How to Get Started

If you'd like to work on this:
1. Open an issue on GitHub discussing your plan and the NLE version you're testing against.
2. Check [`CONTRIBUTING.md`](../../CONTRIBUTING.md) and [`CLAUDE.md`](../../CLAUDE.md) for local setup, test running, and code conventions.
3. Start small: Phase 1 (validating and adjusting FCPXML for DaVinci Resolve) is the fastest way to get a working PR merged!

---

## Editing: cut on movement

Cutting on a movement — a hand, a turn of the head — hides the cut, and is
what an editor does by eye. The video layer already measures faces per
keyframe (`video/`); a motion measure there could move a speaker change to
the nearest movement within a short reach, the same way a long-take break
moves to a measured reaction (`decide.REACTION_REACH`). Wanted after the
turn-taking fixes of 2026-09-23 have been listened to.
