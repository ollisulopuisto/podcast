# Where the migration stands

Written 2026-08-27, at the end of the session that created this repo. Delete
this file once the extraction is finished — it describes a state, not a rule.

## Done

* **Three apps in, with full history**, via `git subtree` from their own
  remotes: autoraffkat (122 commits), automixer (36), podcast-magic. The
  standalone repos carry a "moved" banner and are kept for history only.
* **`packages/speechmix` exists and is consumed for real.** `debleed`,
  `messages` and `chain` live there; autoraffkat imports them from the
  workspace, not from a release. 41 tests in the package, 291 in
  autoraffkat, lint clean across both.
* **The translator seam.** The chain's only tie to autoraffkat was
  `from ..i18n import t`. `speechmix.messages` now carries an English
  fallback and takes an optional host translator; autoraffkat registers its
  own in `i18n.py`, so Finnish messages still come from one catalogue.

## Not done, in the order I would do it

1. **`envelope.py` + `binaries.py`** — small. They depend on `model.HOP`
   and on ffmpeg discovery. `HOP` is a constant of the analysis, so it
   belongs in the package; ffmpeg discovery is per-app (each bundles its
   own binaries) and probably wants the same hook shape as the translator.
2. **`mix.py`** — the real work, and where a silent regression would hide.
   It reaches into `item.placements`, `asset_start` and `sibling()` paths in
   about a dozen places, and every one has to become the `Track` protocol
   described in `packages/speechmix/README.md`. Write the failing test
   first; this is the module where "valid output, wrong result" lives.
3. **`editor.py`, `worker.py`** — the plug-in child process. Mostly
   mechanical once `chain` is in place.
4. **automixer's mlx failure.** `test_multiband_dynamics` fails with
   `RuntimeError: There is no Stream(gpu, 3) in current thread` on mlx
   0.32.2, and passes on 0.30.6. The workspace shares one lockfile and so
   one mlx, which is how this surfaced at all — automixer's `mlx>=0.30.6`
   was a claim it had never tested. Its CI job is `continue-on-error` until
   this is fixed; **remove that line as part of the fix**, and fix it
   forward rather than pinning mlx backwards.

## Two things not to undo

* **Level decisions after the chain can be automation; before it, they
  must be baked in.** Ducking is written as Final Cut volume keyframes and
  a level rider is not. `duck_envelopes` returns `{speaker: [(t, dB)]}` and
  lets the host decide whether that becomes samples or automation — that is
  the second seam, and it is what makes automixer able to share the code
  despite having nothing to write automation into.
* **The numbers in the comments are the design.** Every constant that came
  from measuring real material says what was measured. `SHARED-AUDIO.md`
  collects them. Changing one without a new measurement is how the three
  copies drifted apart in the first place.
