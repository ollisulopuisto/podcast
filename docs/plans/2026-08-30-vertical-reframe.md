# Vertical Reframe Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A `vertical` toggle (default off) in autoraffkat that exports an
already-vertical 1080×1920 project: each close-up spine clip gets a measured,
static `adjust-transform` (scale + position) that puts the speaker's face on
the centreline — no Smart Conform round-trip in Final Cut — composing with
the existing micro-movement feature.

**Architecture:** New fast, file-less planner `reframe.py` (median face-x over
each shot from the *existing* reaction-measurement cache; `cx`/`cy` are
already measured per keyframe per file). The writer gains a `reframer`
parameter and a vertical sequence format; the server builds the reframer from
`video_tables` at export time. Wides are letterboxed in v1 (measured framing
of a room is meaningless; the blurred-background variant is deliberately out
of scope). Position math follows Apple's own FCPXML documentation; the
derived constants carry the derivation and are the first thing to re-check at
the first real import.

**Tech Stack:** Python 3.12+, numpy (tables), pytest, the repo's red-green +
ruff + CalVer rules (`CLAUDE.md`).

---

## Facts this plan rests on (verified in code)

- `video/detect.py` `VISION_FIELDS` includes `cx`, `cy` (mean of all Vision
  landmarks, normalized 0–1), `size` (face-box height, normalized) —
  detect.py:45–46, 161–174.
- Tables are cached per file at `~/Library/Caches/autoraffkat/video`, keyed
  by sha1(path|size|mtime|WIDTH|CACHE_VERSION|detector.name|version) —
  measure.py:54–64. `AppState.video_tables` is a dict **media key → table**
  (`{"times", "found", <fields>}` numpy arrays) — app.py:117,
  video_analyse.tables.
- Timeline → file mapping: `MediaItem.file_time_at(t) = p.source_at(t) −
  asset_start` (model.py:154–159). Track key → part items:
  `timeline.track_media(key)` (read.py:134–140; used by reactions._gather:328).
- `Segment.angle` is a **track key** in the multicam writer and a **media
  key** in the flat writer.
- Position units in FCPXML `adjust-transform`: **percent of project height,
  both axes** — Apple's FCPXML "Animation" doc: `position="-5 10"` reads
  "moved left 5 percent and up 10 percent **of the project's height**".
  Scale is a fraction pair relative to the clip's *fitted* baseline.
  ⚠ **Both to be re-verified at first import into Final Cut** (repo rule:
  settled by importing, not by reasoning). All derived numbers live in
  `reframe.py` constants.
- `_merge_multicam_spans` already merges adjacent same-angle spans "to avoid
  re-crops in a 9:16 conform" (write.py:737–741) — the reframe is computed
  per written span, so a merged span keeps one framing.
- Geometry of 16:9-in-9:16 (derived, to be verified):
  - fit scale `s_fit = min(1080/W, 1920/H)`; for 1920×1080 source:
    0.5625 → displayed 1080×607.5.
  - fill-height scale attribute `s = 1920/(H·s_fit)` = 3.1605 for 16:9.
  - displayed width `D = W·s_fit·s` = 3413 for 16:9; visible fraction of
    source width = 1080/D ≈ 0.3165.
  - position-x (percent of height) = `−(cx − 0.5)·D/1920·100`.
  - After fill, displayed content height = project height exactly → the
    whole source height is visible; **vertical offset is never needed and
    any nonzero y would reveal an edge** → `pos_y = 0` always.
  - Horizontal clamp: `|offset| ≤ (D − 1080)/2` → clamp `cx` into
    `[(1 − 1080/D)/2, (1 + 1080/D)/2]` so no gap shows.

## Design decisions (and why)

- **Wides excluded** (like micro-movement): a full-height crop of a wide is
  a 3.2× zoom into a slice; v1 letterboxes them. The blurred-background
  variant is a separate feature (background clip per wide on a lane — drift
  risk, FCP-never-writes-it construction).
- **Fallback is silence + a count, never a guess.** A shot with fewer than
  `MIN_SAMPLES` measured keyframes (or no table) gets no transform — the
  clip letterboxes. Export reports how many shots went unframed (the
  pan/reaction warning precedent, app.py:1358–1369); "vertical on and
  nothing measured" is reported separately from "measured but nothing
  qualified" (same two-case rule as reactions).
- **Turning the switch on starts the scan** if no tables exist (the panning
  precedent: a feature that silently requires another feature's button is a
  feature that looks broken). The button stays, because a minutes-long run
  may be wanted deliberately.
- **No preview of framing in v1.** The preview bar draws shots/labels, not
  picture geometry, so nothing drawn can disagree with the export. The
  measured-face counts already shown (`_video_json`) are the checkability
  that exists.
- **Thresholds are constants in `reframe.py`, not sliders** (the pan-width /
  movement rule): median is the measurement; "how much reframe" is the
  number this tool exists to decide.

---

### Task 1: `reframe.py` — the per-shot math (pure, no I/O)

**Files:**
- Create: `apps/autoraffkat/src/autoraffkat/reframe.py`
- Test: `apps/autoraffkat/tests/test_reframe.py`

**Step 1: Write the failing tests**

```python
"""Reframing: the face lands on the centreline and the maths is known."""
import pytest
from autoraffkat import reframe


def test_fill_scale_of_16x9_source():
    """16:9 source in a 9:16 project: filling the height scales 1920/1080·16/9."""
    r = reframe.plan_shot(0.5, 1920, 1080)
    assert r is not None
    assert abs(r.scale - 3.1605) < 0.001
    assert r.pos_x == 0.0
    assert r.pos_y == 0.0


def test_face_left_of_centre_moves_picture_right():
    """cx 0.3 → the picture shifts right so the face lands on the centreline."""
    r = reframe.plan_shot(0.3, 1920, 1080)
    assert r.pos_x > 0
    assert abs(r.pos_x - 35.56) < 0.5   # (0.5-0.3)*3413/1920*100


def test_position_never_reveals_a_gap():
    """The clamp holds inside the content even for a face right at the edge."""
    for cx in (0.0, 0.05, 0.5, 0.95, 1.0):
        r = reframe.plan_shot(cx, 1920, 1080)
        assert abs(r.pos_x) * 19.2 <= (3413.0 - 1080) / 2 + 0.01


def test_no_source_dims_gives_nothing():
    assert reframe.plan_shot(0.5, 0, 0) is None


def test_source_narrower_than_project_is_identity():
    """A source already filling the frame needs no crop — and none is written."""
    assert reframe.plan_shot(0.3, 1080, 1920) is None
```

**Step 2: Run to verify failure**

Run: `uv run pytest apps/autoraffkat/tests/test_reframe.py -q`
Expected: FAIL / collection error (module missing).

**Step 3: Minimal implementation**

```python
"""Vertical reframing: per-shot framing from measured face positions.

The source is already Vision-measured per keyframe per file (the same cache
the reaction layer uses); this module turns the measurement into a clip
transform: the source fills the project height and the face lands on the
centreline. No file is opened here — same rule as decide.py.

Geometry (Apple FCPXML Animation doc; VERIFY at first import):
position is percent of project height on both axes, scale is a fraction of
the clip's fitted baseline. Derived for a 1920x1080 source in 1080x1920:
fill scale 3.1605, displayed width 3413 px, visible source-width share 0.3165.
"""
from dataclasses import dataclass

PROJECT_W = 1080
PROJECT_H = 1920

# A face sample count below this is not a framing, it is a coincidence.
# Three keyframes ≈ three seconds of the shot; a median of fewer is noise.
MIN_SAMPLES = 3

# Time tolerance when picking a table's rows for a shot, seconds. Keyframe
# timestamps drift a frame either way at GOP edges.
EPS_S = 0.05


@dataclass
class Reframe:
    """One clip's framing: fill scale and horizontal offset, percent-y=0.

    After fill, the displayed height is exactly the project height, so the
    whole source height is visible and any nonzero pos_y would reveal an
    edge. Vertical reframing is therefore not done at all.
    """
    scale: float
    pos_x: float
    pos_y: float = 0.0


def plan_shot(cx: float, width: int, height: int) -> Reframe | None:
    """Framing for one shot from a median face-x and the source dimensions."""
    if not width or not height:
        return None
    fit = min(PROJECT_W / width, PROJECT_H / height)
    displayed_w = width * fit
    extra = PROJECT_H / (height * fit)
    if displayed_w <= PROJECT_W:
        return None  # the source already fills the width; no crop, no transform
    # Clamp the offset so the crop window never leaves the content.
    half_gap = (displayed_w - PROJECT_W) / 2 / displayed_w
    cx = min(0.5 + half_gap, max(0.5 - half_gap, cx))
    pos_x = -(cx - 0.5) * displayed_w / PROJECT_H * 100
    return Reframe(scale=extra, pos_x=pos_x)
```

**Step 4: Run to verify pass**

Run: `uv run pytest apps/autoraffkat/tests/test_reframe.py -q` → PASS.

**Step 5:** `uv run ruff check apps/autoraffkat` → clean. Commit.

---

### Task 2: `Reframer` — tables to per-span framing (in-memory only)

**Files:**
- Modify: `apps/autoraffkat/src/autoraffkat/reframe.py`
- Test: `apps/autoraffkat/tests/test_reframe.py`

**Step 1: Failing tests** (mirror `tests/test_reactions.py:18–31` table factory)

```python
import numpy as np
from autoraffkat.model import MediaItem, Placement
from autoraffkat.timeline import ZERO


def _table(n=10, cx=0.5, found=True):
    return {
        "times": np.arange(n, dtype=np.float32),
        "found": np.full(n, found),
        "cx": np.full(n, cx, dtype=np.float32),
    }


def _item(key="CLOSE_A", table=None, offset=0.0, dur=36.0):
    item = MediaItem(key=key, name=key, src="", width=1920, height=1080)
    item.placements.append(Placement(ZERO, ZERO, __import__("fractions").Fraction(dur)))
    return item


def _reframer(item, table):
    from autoraffkat.reframe import Reframer
    return Reframer({item.key: table})


def test_median_over_the_shots_rows():
    """The framing is the median of the shot's own rows, not the file's."""
    item = _item()
    table = _table(10, cx=0.5)
    table["cx"][:5] = 0.2                     # rows the shot doesn't cover
    table["times"] = np.arange(10, dtype=np.float32)
    r = _reframer(item, table).from_item(item, 5.0, 9.0)
    assert abs(r.pos_x - (-(0.5 - 0.5)) ) == 0  # covered rows are cx=0.5
    # and a shot over the first rows sees 0.2:
    r2 = _reframer(item, table).from_item(item, 0.0, 4.0)
    assert r2.pos_x > 10


def test_too_few_samples_gives_nothing():
    item = _item()
    table = _table(10, cx=0.4)
    table["found"][:] = False
    table["found"][4] = True
    assert _reframer(item, table).from_item(item, 0.0, 9.0) is None


def test_missing_table_gives_nothing():
    item = _item(key="UNMEASURED")
    assert _reframer(item, _table()).from_item(item, 0.0, 9.0) is None
```

**Step 2:** run → fail.

**Step 3: Implement**

```python
import numpy as np

class Reframer:
    """Faces measured per media key; answers per span. Reads no files."""

    def __init__(self, tables: dict):
        self.tables = tables

    def from_item(self, item, t0: float, t1: float) -> Reframe | None:
        table = self.tables.get(item.key)
        if table is None or not item.width or not item.height:
            return None
        f0 = item.file_time_at(t0)
        f1 = item.file_time_at(t1)
        if f0 is None or f1 is None:
            return None
        rows = (table["times"] >= f0 - EPS_S) & (table["times"] < f1 + EPS_S) \
            & table["found"]
        if int(rows.sum()) < MIN_SAMPLES:
            return None
        return plan_shot(float(np.median(table["cx"][rows])),
                         item.width, item.height)
```

**Step 4:** run → pass. **Step 5:** ruff, commit.

---

### Task 3: `Globals.vertical` + plumbing (round-trip, tag, metadata, note)

**Files:**
- Modify: `model.py` (after `movement`), `server/app.py` `apply()`
  (auto-start scan, panning precedent at lines 509–516), `project.py`
  `name_tag` (after `movement`), `pick.py` `_TAG_WORDS`, `i18n.py`
  (`export.note` + `export.vertical_on/off`), `fcpxml/write.py`
  `settings_metadata` + `settings_note`.
- Test: existing `test_every_global_the_interface_shows_can_be_set`
  (test_endtoend.py:969) goes RED the moment the field exists; add
  `test_name_tag_mentions_vertical` to test_project.py.

**Step 1:** add `vertical: bool = False` to `Globals` → run the walking
round-trip test → RED ("vertical" cannot be set).
**Step 2:** handle in `apply()` (bool, plus auto-start):

```python
if "vertical" in raw:
    was = g.vertical
    g.vertical = bool(raw["vertical"])
    # Same rule as panning: the switch starts its own scan. A feature that
    # silently requires another feature's button to have been pressed first
    # is a feature that looks broken.
    if g.vertical and not was and not self.video_tables \
            and not self.video_progress.get("running"):
        threading.Thread(target=self.measure_video, daemon=True).start()
```

**Step 3:** tag `"vertical"` in `name_tag` + `_TAG_WORDS`; md key
`_md("vertical", ...)`; note param `vertical=t("export.vertical_on" …)`
(fi «pysty», en «vertical») with strings in both languages. RED-GREEN with
`test_name_tag_mentions_vertical` (write it first, watch it fail by
reverting, as done for `move`).
**Step 4:** full suite + ruff. Commit.

---

### Task 4: writer — vertical format + composed transforms

**Files:**
- Modify: `fcpxml/write.py` (`_movement_lines` → `_transform_lines`,
  both builders' sequence-format selection, new `reframer` parameter)
- Test: `tests/test_write.py`

**Design:**
- Builders gain `reframer=None`. When `settings.globals.vertical`:
  sequence format becomes `1080×1920` (constants `VERT_W/VERT_H` in
  write.py); flat path lines 458–460 and multicam `_source_resources`
  (lines 1494–1505) receive those dims. `_format_name` returns `None` for
  height 1920 — an unnamed format, attributes carry the truth (intended;
  do NOT add 1920 to STANDARD_HEIGHTS: `FFVideoFormat1920p` is not a real
  FCP format name).
- `_transform_lines(reframe, move, frames, frame_duration, indent)`:
  composed `scale = (reframe.scale if reframe else 1.0) * move.start_scale`;
  static case writes `scale="s s"` + `position="x y"` (position only when
  reframe exists); animated case writes scale keyframes with composed
  values, position stays an attribute beside the params (Apple's own
  example shape). Nothing is written when reframe is None and move is
  identity.
- Multicam loop: resolve the span's item — `items = timeline.track_media(seg.angle)`
  → the item whose placements cover the span (parts; mirror
  reactions._gather:328) — then `reframer.from_item(item, t0, t1)`.
  Flat loop: `item = media_by_key[seg.angle]`. Wides skip: `seg.label ==
  WIDE_LABEL` → reframe None (movement already does this; the reframe
  check is separate and explicit).
- Both builders count unframed close-up spans? No — the *server* counts
  (Task 5); the writer stays silent.

**Tests (write first, watch fail):**

```python
def test_vertical_export_has_a_vertical_sequence(...):
    # sequence format element has width="1080" height="1920"
def test_vertical_close_up_is_reframed_on_the_angle(...):
    # video mc-source: adjust-transform with position attr, scale=3.1605
    # (within tolerance), wide clips get none
def test_reframe_composes_with_movement(...):
    # both on: keyframe values == reframe.scale * move scale (1e-6)
def test_vertical_without_measurements_letterboxes(...):
    # reframer with no tables → clips carry no transform, format still vertical
def test_vertical_multicam_passes_the_fcp_dtd(fixture_dir, validate_fcpxml):
```

Plus local xmllint validation against the downloaded CommandPost DTDs
(no Final Cut on this machine — the needs_dtd tests run in CI; the manual
check ran for micro-movement and is repeated here).

Run suite → green; ruff; commit.

---

### Task 5: server — reframer at export + warnings

**Files:**
- Modify: `server/app.py` export endpoint (lines ~1334–1370), `i18n.py`.
- Test: `tests/test_endtoend.py`

**Design:**
- Export builds `reframer = reframe.Reframer(state.video_tables)` when
  `settings.globals.vertical`, else None, and passes it to both builders.
- Warnings, two cases (reactions precedent):

```python
if g.vertical:
    if not state.video_tables:
        warnings.append(t("export.vertical_unmeasured"))
    elif not any_span_framed:
        warnings.append(t("export.vertical_unframed"))
```

`any_span_framed`: cheap — recompute the count from video_tables via a
small helper in `reframe.py` (`framed_count(segments, timeline,
video_tables)` mirrors reactions.candidates() existing for the same "show
the gate works" reason).
- i18n keys fi/en for both warnings. Tests mirror the reaction-warning
  endtoend tests: export with vertical on + empty tables → warning present.

Run suite → green; ruff; commit.

---

### Task 6: UI — the toggle row

**Files:**
- Modify: `server/static/app.js` (renderGlobals, after movement row),
  `server/static/i18n.js` (fi + en: `vertical.title/hint`, `why.vertical`).
- Test: existing ui_smoke + i18n parity cover it (no new top-level
  function without a reason; `verticalBody` is called by renderGlobals so
  coverage holds).

Content of `why.vertical`: what it does, that measured files drive it, that
wides are letterboxed on purpose, that the numbers live in `reframe.py`
with the reasoning, and that position units follow Apple's doc (verified at
first import). Run `uv run pytest apps/autoraffkat/tests/test_ui.py -q` →
green (parity + smoke). Commit.

---

### Task 7: docs, version, changelog, tag

- `CLAUDE.md` (app): a section — "Reframe is a measured transform or a
  letterbox": angle-not-clip rule shared with movement, cx/median/MIN_SAMPLES,
  pos_y=0 reasoning (fill ⇒ whole height visible), units warning and the
  import-verification note, wides-letterboxed decision.
- `README.md` + `README.fi.md`: user-facing paragraph + Layout line.
- `CHANGELOG.md` entry; `uv run python scripts/bump_version.py autoraffkat`;
  commit; tag `autoraffkat-v<new>`; push.
- Full suite + `uv run ruff check .` before the commit.

---

## Out of scope (deliberate)

- Blurred-background wides (background clip per wide on a lane).
- Keyframed drift correction (re-measure first: how often does the head
  leave the 1080-px window? That number decides if this exists).
- Preview drawing of the crop window.
- Framing by `cy`/eyes-at-upper-third (fill shows the whole height; nothing
  to fix until the measurement says otherwise).
