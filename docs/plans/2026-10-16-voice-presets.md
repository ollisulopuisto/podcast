# Voice Presets and Audition Implementation Plan

Three parts, one chain and one plug-in handling: **Part A** names mic conditions
as presets; **Part B** (`audition`) renders a window at several plug-in settings
so an editor can choose by ear; **Part C** asks whether tone should be matched
for consistency, and starts with a measurement.

**Status (2026-10-17):** audition's A0/A1 have a first result (`SHARED-AUDIO.md` §3.11); the two measurement scripts are written and tested:
`scripts/ab/audition_measure.py` (Part B, A0/A1) and `scripts/ab/tone_measure.py`
(Part C, C0). Their numbers wait for runs on the owner's Mac (dxRevive and real
episodes). Part A has no code yet and Part C's correction stage waits for C0.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Name the mic conditions a speech track can be in (`clean`, `room`,
`remote`, `phone`) and let every app pick a speech-chain setting by that name
instead of tuning parameters. `auto` measures the file and **suggests** one of
the four; a person confirms. Nothing is ever applied silently.

**Origin:** A proposal from the kuulas session (the multitrack spoken-word
editor that imports `speechmix` and `nhsx` as path dependencies and must not
reimplement the chain). kuulas only tags a track ("Speech · remote") and passes
the preset name to `speechmix`. The presets and their numbers belong here, so
automixer, autoraffkat and podcast-magic get them in the same commit. The
proposal's own copy lives uncommitted on the owner's Mac
(`docs/plans/2026-10-16-voice-presets.md`); this file is written from the
message that carried it, so **reconcile the two before Task 3**.

**Decisions (owner, 2026-10-16):**

1. **The set is four plus `auto`.** `clean`, `room`, `remote`, `phone`, `auto`.
   Studio-booth, car and outdoor wait until a measurement says the four do not
   cover real episodes.
2. **A preset chooses the dxRevive model too.** This is the expensive answer;
   see "The model selector" below. Task 0 decides how, before anything else is
   built.
3. **Numbers come from a scripted A/B on known episodes first**, then a
   listening check at matched loudness. Results go into `SHARED-AUDIO.md`.
4. **The repo owns the edit diff.** `docs/plans/2026-10-05-edit-diff.md` stays
   here as the one implementation; kuulas consumes `nhsx` as a path dependency
   and does not carry a second diff. It does not change this plan, and it is
   recorded here so the next plan does not reopen it.

**Architecture:** One new module, `speechmix/presets.py`, holds a frozen
`Preset` per condition (overrides for fields the chain already reads, plus the
plug-in parameters and a model reference). One new module, `speechmix/suggest.py`,
measures a track and returns `Suggestion(preset, reasons)`. `chain.process` does
not change signature: it already reads a duck-typed `settings`. A preset is
applied *to the host's settings object* by a small adapter, so a missing field
is reported and not dropped.

**Tech Stack:** Python 3.12+, numpy, pedalboard (via `speechmix.chain`), pytest,
ruff, CalVer per app (`uv run python scripts/bump_version.py <app>`).

---

## What was verified in the tree (2026-10-16)

- `chain.process(audio, rate, settings, gain_db, speech, target_lufs, plugin,
  stage, speaking)` is at `packages/speechmix/src/speechmix/chain.py:1960`.
  `settings` is duck-typed. Fields it reads include `high_pass_hz`, `declick`,
  `declick_sensitivity`, `rider` and `rider_max_db` (the last via `getattr`
  with a default).
- Each host owns its own settings class: `autoraffkat.model.AudioSettings`
  (has `plugin_path`, `plugin_params`, `plugin_state`) and
  `automixer.domain.processor.SpeechSettings` (six fields, **no** plug-in
  fields; the plug-in goes through `ExternalPluginProcessor`). A preset
  therefore cannot be "the settings object"; it is a set of overrides each host
  maps onto what it has.
- The chain has **no expander or gate** (no function by that name in
  `chain.py`), no band-limiting EQ and no intelligibility EQ. `room`, `remote`
  and `phone` as proposed need at least one new stage each, and each new stage
  is a measured addition, not a free parameter.
- `speechmix.grid.noise_floor(db, valid, percentile)` exists
  (`grid.py:71`) and is already used by `nhsx.activity`, `stems.py`,
  `autoraffkat.analysis`. The auto-suggestion's floor measurement reuses it.
- **The dxRevive model selector is not a parameter.** It lives in the plug-in's
  opaque state (`speechmix/editor.py` docstring; `SHARED-AUDIO.md` §3.9).
  `chain.load_plugin(path, params, state)` applies state before parameters.
  `FINGERPRINT_FIELDS` already includes the state, because a different model is
  a different result.
- `scripts/ab/compare.py` exists: it measures LUFS, true peak, crest and PSR
  and serves a synced A/B page with loudness matching. The scripted A/B in
  Task 2 builds on it rather than beside it.
- `SHARED-AUDIO.md` is `apps/autoraffkat/SHARED-AUDIO.md`, not at the root.
  New measurements go there as a new §3.x in the existing style: what was
  measured, on what, with which function.
- The episodes the proposal names (s13e03 and others) are **not in the cloud
  checkout**. Every measurement step below runs on the owner's Mac.

## Rules this plan keeps

- **Red-green.** Each task's test is written and watched failing first.
- **No number without a measurement.** A preset value that has no row in
  `SHARED-AUDIO.md` is not allowed to merge. Until measured, a preset field is
  absent (the host's default applies), not filled with a plausible guess.
- **Nothing silent.** A preset field the host cannot apply is returned in an
  `unapplied` list and shown. `auto` returns a suggestion and never applies it.
- **Model choice is in the fingerprint.** A preset that selects a model changes
  the result and must make an old render stale.
- **Lint and members agree.** `uv run ruff check .` clean; one Python floor,
  one lockfile; a change that breaks a `tests/` assertion about that changes
  the assertion in the same commit and says why.
- **One branch per change, squash-merged.** This file is its own PR; the code
  tasks below are separate PRs from `main`.

---

## The model selector (the hard part of decision 2)

Because the model is inside the plug-in's opaque state, a preset cannot say
"use Studio 2" the way it says `high_pass_hz = 80`. The only handle is a
**captured state blob per model**. Task 0 settles whether that is workable:

- Capture the state with each model chosen, through `speechmix.editor`
  (`open_editor`), on the owner's Mac where the plug-in is installed.
- Compare the blobs. The question is whether they differ only in the model
  bytes, or also carry the four parameters (input/output gain, bypass, Mix) and
  window geometry. If the blob carries Mix, applying it and then the preset's
  `plugin_params` is fine (state first, parameters override, as `load_plugin`
  already does); if it carries things that should not travel, a preset needs
  the *model-only* delta, which may not be separable.
- Check that a blob captured on one plug-in version still selects the same model
  on the next version, and that a state from a different plug-in is ignored, as
  `load_plugin` already does.
- Decide where blobs live. They are small and opaque; they are the owner's
  captures of a licensed plug-in's own state, not the plug-in. Keep them out of
  the repo if there is any doubt about redistribution, and keep a
  `presets/models.json` that maps `(plugin id, version, model label)` to a file
  the host looks up.

**If Task 0 finds the model cannot be set reliably** (state not separable, or
not stable across versions), the fallback is: the preset names the model by
label, the host asks once per project to capture the state under that label
with the existing editor window, and the preset refuses to run without it. That
keeps decision 2's intent (a preset *knows* which model it wants) without
pretending the library can set it. This fallback needs the owner's agreement
before Task 3 is built on it.

## What "250 % of dxRevive" means here

The plug-in's Mix parameter probably stops at 100 %, and running it twice usually
adds artefacts. This repo has measured the cost of more dxRevive: at 50 % it
lifts above 16 kHz by +4…+7 dB and takes 0.3–0.6 dB of crest; 25 % was
preferred (`SHARED-AUDIO.md` §3.10). So `remote` is read as: the strongest model
and settings the plug-in offers, plus extra chain steps, with the amount decided
by the A/B. Running the plug-in twice is a candidate only if the A/B shows it
beats the single strongest run **and** the >16 kHz lift and crest cost stay
inside what the listening check accepts. The plug-in still has exactly one slot
and still runs first (see autoraffkat `CLAUDE.md`, "The plug-in slot is flavour,
not a replacement mechanism"); two runs would be two applications of the same
slot and would need that rule restated, not bypassed.

---

## Tasks

### Task 0: dxRevive model capture (spike, owner's Mac)

**Files:** a throwaway script in the scratch area, then a note in this file.

Open the plug-in with `open_editor`, select each model in turn, save
`raw_state`. Answer the four questions in "The model selector". Write the result
into this plan (a short "Task 0 result" section) and stop if the answer is "not
separable": decision 2 needs the owner before more is built.

### Task 1: A corpus with labels

**Owner supplies:** at least 5 speech tracks per condition (`clean`, `room`,
`remote`, `phone`), from real episodes including s13e03, each labelled by the
owner's ear, with the source and the condition recorded in a manifest next to
the files (same pattern as `test_signals/*/manifest.json`). A held-out third is
never used to set thresholds, only to score them. Audio stays on the Mac.

### Task 2: A scripted A/B harness

**Files:**
- Create: `scripts/ab/presets.py` (extends `compare.py`; do not fork it)
- Test: `packages/speechmix/tests/test_presets_metrics.py`

For a track and a candidate chain, write the processed file and print, on the
same measurements §3.10 already uses: loudness (`chain.loudness`), true peak,
crest/PSR, band-energy difference against the unprocessed file (below 60 Hz,
at 2 kHz, above 3 kHz, above 16 kHz), noise-floor change
(`grid.noise_floor`), and the null depth between two candidates. Add a
**reverb metric**: energy decay after speech offsets, from the speaking mask's
edges, in dB per 100 ms. Loudness-match every pair before comparing. Red:
synthetic tests (noise, a band-limited signal, a signal convolved with an
exponentially decaying impulse response) prove each metric moves the right way
and by a known amount.

### Task 3: The seam: `Preset`, `apply`, `unapplied`

**Files:**
- Create: `packages/speechmix/src/speechmix/presets.py`
- Test: `packages/speechmix/tests/test_presets.py`

A frozen `Preset` (name, overrides, `plugin_params`, model reference or `None`).
`apply(preset, settings)` returns `(new_settings, unapplied)`, where
`new_settings` is `dataclasses.replace(settings, ...)` for the fields the
settings object has and `unapplied` lists the preset fields it lacks, with
their values. Red tests: applying to a settings object that lacks a field
returns it in `unapplied`; applying changes nothing outside the preset's own
fields; the chosen preset name and model reference reach the fingerprint (extend
`FINGERPRINT_FIELDS`, and the autoraffkat test at `test_mix.py:202` that pins
it). **No preset values yet:** every field is absent, so `apply` is a no-op
until Task 5 fills them, and a test asserts that.

### Task 4: New chain stages the presets need (only the ones measured to help)

Candidates from the proposal: expansion between phrases (`room`, `remote`),
band limiting and intelligibility EQ (`phone`: about 300–3400 Hz, nothing that
boosts the empty highs, since that only lifts noise). Each is a separate
sub-task with its own A/B row in Task 2's output, its own red test on a
synthetic signal, and its own default-off setting, so the existing chain output
stays byte-identical until a preset turns it on. A stage that does not beat the
current chain in the A/B is dropped and the reason written down. The existing
rule applies: a `declick`-style stage is calibrated against how often the
artefact really occurs, and keeps a ceiling.

### Task 5: Fill the presets from measurement

For each preset, run Task 2 on the labelled corpus and fill only the fields the
measurement supports. Record each in `SHARED-AUDIO.md` as a new §3.x: what was
measured, on which tracks, with which function, and the numbers. Then a listening
check at matched loudness on at least two episodes per preset, with the result
written next to the numbers, the same way §3.10 records "25 % beat 50 %".
`remote`'s amount (Mix, model, extra steps) is decided here, including whether
the double-run candidate earns a place.

### Task 6: `auto`: measure and suggest

**Files:**
- Create: `packages/speechmix/src/speechmix/suggest.py`
- Test: `packages/speechmix/tests/test_suggest.py`

`suggest(audio, rate) -> Suggestion(preset, reasons)`, where `reasons` is a list
of measured facts the host can show ("3.4 kHz bandwidth", "floor -52 dBFS",
"reverb tail 480 ms", "4 clipped runs"). Inputs: noise floor (`grid.noise_floor`),
bandwidth (spectral roll-off, with the `phone` cut-off near 4 kHz as a *starting*
hypothesis to be set from the corpus), reverb (the Task 2 metric), clipping
count (runs of samples at full scale). Thresholds come from the labelled corpus
and are scored on its held-out third; the accuracy and the confusion matrix go in
`SHARED-AUDIO.md`. Red tests use synthetic tracks built to be unambiguous
(band-limited, reverberant, clipped, noisy) and assert the preset **and** that
each reason carries its number. `chain.process` never calls `suggest`; a host
calls it and shows the result.

### Task 7: Host integration

- **autoraffkat:** `AudioSettings.preset` (name) and the model reference; the
  settings panel shows the suggestion with its reasons and a confirm control;
  the fingerprint carries both. English and Finnish strings through `i18n.py`
  and `i18n.js`, per `autoraffkat/CLAUDE.md`. The UI smoke test must still
  exercise every new function.
- **automixer:** `SpeechSettings` has no plug-in fields, so its mapping goes
  through `ExternalPluginProcessor`. Decide in the PR whether the preset's
  plug-in half belongs there; `unapplied` makes the gap visible rather than
  hiding it.
- **podcast-magic:** only if its silence presets are meant to consume voice
  presets. Check before adding; do not couple the two preset concepts by name.
- **kuulas:** passes the preset name; nothing to do in this repo beyond keeping
  the public surface (`Preset`, `apply`, `Suggestion`, `suggest`) stable and
  documented in `packages/speechmix/README.md`.

### Task 8: Release

`uv run python scripts/bump_version.py <app>` for each app whose behaviour
changed, all three version locations matching; changelog entries in
`packages/speechmix/CHANGELOG.md` and each app's. CI stays unskipped.

---

## Part B: `audition`, parallel renders of one window at several settings

**Origin:** a second request from the kuulas session (2026-10-16), added to this
plan at the owner's word ("samaan PR:ään"). dxRevive and similar restoration
plug-ins probably cannot run in real time, so kuulas will not put them in the
playback path. Instead it loops a short window around the playhead and switches
between pre-rendered versions with keys 1–4 (0 = original), loudness-matched.
When the owner changes a setting in the plug-in's own window
(`speechmix.editor`), kuulas re-renders the window in the background and swaps
it in. The function belongs in `speechmix`, so automixer's and autoraffkat's
plug-in editors can use it too.

**Choices made here (flag them if wrong):**

- **Generalised signature.** `audition(source, rate, start, end, plugin_path,
  plugin_state, variants, preroll, workers)` takes `variants`, a list of
  parameter dicts, and returns one render per variant in the same order. The
  single-parameter case (`{"mix": v}` for v in 25/50/75/100) is the common call,
  not a separate function.
- **Loudness is reported, not applied.** Each result carries its
  `chain.loudness` value, so the host can match levels (kuulas switches between
  renders and needs the gains). Applying gain inside `audition` would hide a
  decision the host needs to display. A helper `match_loudness(renders)` can
  live beside it if two hosts end up writing the same three lines.
- **No new parallel machinery.** `PluginPool` and `apply_plugin` already give one
  instance per worker and full `reset=True` runs. `audition` is a thin function
  over them.

**Plug-in semantics it must get right (all already known to this package):**

- Every render is a **full run** with `reset=True`. A window is never fed in
  pieces; a window is its own file.
- **Preroll** before `start` so the plug-in has warmed up, then trimmed back to
  `[start, end)`. The preroll length is a measurement (Task A1), not a guess.
- **Delay compensation** with `chain.lag_samples`; the plug-in's reported
  latency is wrong (`apply_plugin`'s length check exists because dxRevive lost
  4641 samples).
- Parameters through `chain.apply_parameters` and `parameter_specs`; the
  **model selector stays in `plugin_state`**, applied before parameters as
  `load_plugin` already does. A variant cannot change the model; a preset can
  (Part A, Task 0).
- Plug-ins load only on the main thread (see autoraffkat `CLAUDE.md`):
  `PluginPool` builds every instance in its constructor. A background re-render
  must therefore go through the same child-process route as `speechmix.editor`,
  not a worker thread that loads lazily.

### Result of A0 and A1 (2026-10-17, first runs, one window)

Recorded in `SHARED-AUDIO.md` §3.11. In short: dxRevive repeats itself only to
about −38 dB, so every comparison needs the repeat control. **Mix is not a plain
dry/wet blend but a gain-preserving crossfade with a steep taper**: dry weight
`a(m) = (1 − m)^2.37`, fitted to seven levels within the weights' own rounding
(0.50 / 0.20 / 0.04 at 25 / 50 / 75 %). A continuous Mix slider from one 100 %
render plus the raw is therefore possible **by that law**, and kuulas can have
it. Preroll needs about 8 s (4 s is not enough). Four renders of a 10 s window
take about 5 s on four workers. Open: the other model (Studio), a second
window and speaker, input gain.

### Task A0: The level parameter, linear or not (measure first)

Question: is dxRevive's Mix a linear dry/wet blend? On a few 10 s windows, align
the 50 % render, the raw window and the 100 % render by `lag_samples`, build the
50/50 blend of raw and 100 %, and take the null against the 50 % render.
**Residual below about −60 dB after alignment** means linear: kuulas can offer a
continuous level slider from one 100 % render. Anything else, and only discrete
auditions are honest. Record the number in `SHARED-AUDIO.md` whichever way it
falls. Red test: a fake plug-in with a known linear mix passes the null check, a
fake with a non-linear curve fails it, so the check itself is proved.

### Task A1: Time and preroll, on the owner's Mac

Measure render time per 10 s window per value, with 1, 2 and 4 workers, and the
preroll after which the output stops depending on it (render with preroll 0, 1,
2, 4, 8 s and find where the trimmed window stops changing). Record both in
`SHARED-AUDIO.md` as a new §3.x, same style as §3.9 (what, on what, with which
function). The preroll default in code comes from this row.

### Task A2: `audition`

**Files:**
- Create: `packages/speechmix/src/speechmix/audition.py`
- Test: `packages/speechmix/tests/test_audition.py`

Red tests, using the fake plug-ins `test_chain.py` already defines: output
length equals `end - start` for every variant; a fake with a known latency comes
back aligned; a fake whose output depends on its history shows that preroll
changes the result and that `reset=True` makes two identical variants identical;
the result order matches `variants`; an unknown parameter name is reported
rather than silently ignored (`apply_parameters` already returns the unknown
ones, so surface them); loudness values are present. Then the minimum code over
`PluginPool` and `apply_plugin`.

### Task A3: Host use

kuulas calls `audition` and owns the keys, the loop and the swap. automixer and
autoraffkat adopt it in their plug-in editors only if the owner wants it there;
decide in that PR, not here. Document the public surface in
`packages/speechmix/README.md`, bump the CalVer of every app whose behaviour
changes.

---

## Part C: tone consistency (measure first, build only if the numbers ask for it)

**Origin:** the owner's roadmap question (2026-10-16): do we need EQ profiles
like Hindenburg's? The owner was never sure those worked well enough to be
usable; the idea of matching tone may still be useful. Gain is already matched.
**The goal is consistency, not turning a cheap microphone into an expensive
one.** A library of per-microphone profiles is out of scope; the voice presets
of Part A already cover clearly poor conditions (`remote`, `phone`).

**Today:** the chain applies one fixed house tone to everyone (`TONE_*` in
`chain.py`: 250 Hz +1.5 dB, 400 Hz −2 dB, a 3 kHz shelf +1.5 dB), tuned by ear
once against one reference chain (`SHARED-AUDIO.md` §3.10). It never measures
the speaker, so differences between speakers survive the chain unchanged.

**What could be useful, in order of expected value:**

1. **The same speaker across episodes.** A speaker's long-term speech spectrum
   is stored per show, and a new episode is pulled toward it. This is the
   consistency the listener actually hears week to week.
2. **Speakers within an episode, toward a common target, not toward each
   other.** Pairwise matching is a moving target (A follows B while B follows A).
   Each speaker is pulled toward one fixed target curve, partially (about 50–60 %)
   and bounded (about ±3 dB).
3. **Drift inside one track** (proximity effect at 250 Hz as the speaker moves).
   Only if the measurement shows drift larger than the level rider already hides.

**Shape of a correction, if built:**

- The spectrum is measured on **speech frames only** (the speaking mask already
  exists) and only in bands where speech stands clearly above the noise floor.
  A band dominated by noise is never boosted; this is the `phone` lesson, that
  anything lifting empty highs lifts only noise.
- Four broad bands (low end, body 150–400 Hz, presence 2–5 kHz, air above
  8 kHz), not narrow filters. Voices stay different from each other; only what
  the recording chain added is corrected.
- It sits where the existing tone stage sits, **after the plug-in**: dxRevive at
  100 % lifts 3–20 kHz by +4…+5.7 dB (`SHARED-AUDIO.md` §3.9), so tone must be
  measured on what the plug-in produced, not on the raw file.
- The fixed `TONE_*` house curve is either the target or is replaced by it;
  decide after the measurement, not before.

**Hindenburg's profiles.** What exactly they do and why they disappointed is not
known here and is not assumed. The usual failure of a match to the whole
long-term spectrum is that it chases content and noise and over-corrects; the
shape above is designed against that, not against Hindenburg specifically.

### Task C0: Measure the spread (owner's Mac, no code in the chain)

**Files:**
- Create: `scripts/ab/tone_measure.py` (next to `audition_measure.py`)
- Test: `tests/test_tone_measure.py`

For each speaker track of several episodes (the same speakers in more than one),
compute the speech-frame spectrum in the four bands, with the noise-clearance
rule above. Print, per band: the spread **between speakers** within an episode,
and the spread of the **same speaker across episodes**. The meter is proved on
synthetic tracks first: two voices with a known 3 dB tilt difference must read
3 dB; a band under the noise floor must be reported as unmeasured, not as zero.

**Decision rules, set before looking at the numbers:**

- The larger of the two spreads (between speakers, same speaker across
  episodes) under about 2 dB in a band: that band is not worth correcting. (As
  built in `tone_measure.verdicts`: a band where speakers are alike but one
  speaker moves 3 dB between episodes is still worth a per-show profile.)
- Same-speaker spread across episodes larger than the between-speaker spread:
  item 1 above is the feature, and the stored per-show profile is built first.
- Frame-to-frame band movement within a track that the rider and compressors
  already hide: item 3 is dropped.

Results go in `SHARED-AUDIO.md` as a new §3.x, same style as the others.

### Task C1+: Only after C0 says so

Correction stage (default off, A/B through `scripts/ab/compare.py` at matched
loudness, then a listening check), the per-show profile store, and host
integration. Each is planned from the C0 numbers, not before.

---

## Open questions

These go back to the owner and are not decided here:

1. **Task 0's outcome.** If the model state is not separable or not stable across
   plug-in versions, is the "capture once per project" fallback acceptable?
2. **Corpus.** Who labels the tracks and from which episodes? The A/B and `auto`
   are only as good as the labels.
3. **Blob storage.** Are captured plug-in state blobs fine to commit, or do they
   stay local?
4. **podcast-magic.** Should its silence presets read the voice preset, or do the
   two stay independent?
5. **Part B.** Is the generalised `variants` list and "loudness reported, not
   applied" what is wanted, or should `audition` also apply the match?
6. **Part B.** Do automixer and autoraffkat get `audition` in their plug-in
   editors, or only kuulas for now?
7. **Part C.** Which episodes and speakers go into C0? It needs the same speakers
   in at least two episodes.

## Not in this plan

Studio-booth, car and outdoor presets; applying `auto` without confirmation;
changing the plug-in slot rule; the edit diff and rough cut (their own plans,
with the ownership decision recorded above).
