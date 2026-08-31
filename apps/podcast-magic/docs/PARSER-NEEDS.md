# What the parser still needs

The `.nhsx` reader was built to mute and to render, and everything it
needed for that has been **measured**, not guessed (`tests/test_measured_session.py`,
`CLAUDE.md`, `SHARED-AUDIO.md`). Everything it did not need is still
unknown — and the unknowns are exactly what will bite when autoraffkat and
automixer start reading Hindenburg sessions. This file is the list, and the
recipe for closing it. Companion to
`docs/hindenburg-session-spec.md` (how editing works) and
`viewer/Conformance/` (the shared answer two parsers test against).

## Measured, and safe to rely on

| fact | value | measured where |
|---|---|---|
| geometry | `Start`, `Length`, `Offset`, `Muted` | the reader's foundation, day one |
| pan law | linear, standard-sum, **positive = left**: `R/L = (1-p)/(1+p)` | rendered session, `mix.py` docstring |
| fades | ramp **to a level** and stays there (`<Fade Start= Length= Gain>`) | `Gain="-11.2"` held for 26 s |
| `ClipGain` vs `Gain` | `ClipGain` wins and does **not** sum with `Gain` | 22.50 dB measured on one region |
| mute spelling | `True` / `true` / `1` all occur in the wild | `mix.py` note |
| unknown attributes | reported (`Mix.unknown`, `nhsx-render` warns), never skipped silently | `KNOWN_REGION_ATTRS` et al. |

The `KNOWN_*_ATTRS` lists are hand-written guards: a new attribute name
never slips into the known set without a person deciding that.

## Unknown, and how it would bite

These are ordered by how badly they hurt an autoraffkat/automixer
adoption, not by curiosity.

1. **Track-level `Gain` and `Pan`.** Read into the model, never verified
   against a render. If a track fader applies *where the sum is computed*
   and we ignore it, every level decision the chain makes is off by that
   amount — the same shape as the `ClipGain` miss, which cost 22.2 dB and
   was noticed by listening.
2. **The fade curve's shape.** We know the ramp's endpoints, not its
   trajectory. Speech dynamics hid it on the measured material; white
   noise will not. Guessing linear when Hindenburg does something else
   makes every preview wrong in exactly the fades.
3. **What writes `Gain` vs `ClipGain`.** We know the precedence, not when
   Hindenburg writes which. Without that, writing back can produce a file
   Hindenburg interprets differently from what we intended.
4. **Time base at the edges.** `time_to_seconds` handles `HH:MM:SS(.fff)`
   and bare seconds; frame-rate-bearing formats, negative times and
   midnight wraps are unmeasured. A multicam part starting at a timecode
   offset is where this shows up.
5. **Stereo regions and channel routing.** The chain converts everything
   to mono by decision (`pipeline.py` docstring), but the reader cannot
   yet say what a stereo region's two channels *were* — combined? one
   side? A session that sounds fine in Hindenburg can lose a channel
   silently in ours.
6. **Buses, auxes, effects, master fader.** Not read at all. `nhsx-render`
   renders plain regions, which is honest, but nothing says when a session
   is *more* than that — the warning that should exist does not.
7. **Track types and speaker semantics.** Track names are load-bearing
   (speaker identity in the chain, `dominant_words` comparisons), and
   nothing distinguishes a music bed from a microphone.
8. **Multiple `<Fade>` children, ordering, automation.** One fade per edge
   is all we have seen; the DTD-adjacent truth is unknown, and an
   unrecognized fade is a level decision made by nobody.

## What to send: three files, one export each

One session carrying everything is harder to decode than three that each
answer one question. White noise throughout, so every number in the export
is attributable. Record the Hindenburg version and the export settings
(bit depth, rate) alongside — both go into the conformance answer.

**File A — the laws.** The current knowledge, re-proved, plus the curve:

* regions at known noise levels (−20, −35, −50 dBFS) → level reading
* `Pan` at 0, ±0.55, ±0.625, ±1.0 → the pan law, per Hindenburg version
* fades: short (0.5 s), long with a **plateau** (ramp 2.5 s, hold 10 s),
  and a fade *without* `Gain` → endpoint reading + curve shape
* one region with `Gain` set, one with `ClipGain`, one with both →
  precedence again, and a chance to see what the UI writes when
* track fader at −6 dB on one track → **gap 1**

**File B — the formats.** 16-bit and 24-bit WAV, one mono and one stereo
source, regions starting mid-file (`Offset`), overlapping regions on two
lanes, one muted region, one session with a music track type → gaps 5 and 7.

**File C — the structure.** Buses/auxes, an effect on a track, master
fader, automation, several `<Fade>` children if the UI allows making them
→ gaps 2, 6, 8.

**The export is the ground truth, not the screenshots.** From each export:

* per-region peak in dBFS (fit the level stage)
* L/R RMS ratio inside panned regions (fit the pan law)
* the envelope around fades, sampled densely (fit the curve)
* overall programme peak and length (fit the sum)

The screenshots stay useful for one thing: confirming that track names,
order and region placement parsed the way the UI shows them — the same
check `viewer/Conformance/session.nhsx` carries structurally.

## Decode recipe

Make every region identifiable mechanically: frequency or level says *which*
region a second of export came from — the same trick as
`apps/autoraffkat/tests/make_fixture.py` (frequency = second) and
`tests/test_measured_session.py`. Then the fitting is a script, and the
resulting numbers land where the house keeps them:

* laws → `mix.py` docstrings and `SHARED-AUDIO.md`, with the measurement
* new attribute names → `KNOWN_*_ATTRS` only after a person decides
* anything two parsers must agree on → `viewer/Conformance/` answer, regenerated deliberately and diff-read

## The adoption seam (for autoraffkat / automixer)

The reader-to-chain translation already exists
(`nhsx/pipeline.py:tracks()` → `speechmix.timeline.Track`), so the work is
not parsing but placement:

* promote `read.py` + the `pipeline.py` translation into a workspace
  package (`packages/nhsx`), depending on speechmix timeline types —
  speechmix itself stays session-format-blind;
* automixer consumes `Track`s nearly as-is;
* autoraffkat gets Hindenburg as an *audio* input and nothing for its
  picture layer — a session has no video, no angles, no roles. That limit
  should be stated in the UI, not discovered.
