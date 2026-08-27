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
4. ~~**automixer's mlx failure.**~~ Done. It was not a version problem:
   mlx's default stream is thread-local, and three call sites ran mlx work
   in a `ThreadPoolExecutor`, so an array made on a worker raised on first
   use back on the calling thread. 0.30.6 allowed it silently. Fixed
   forward in all three places — `processor.py` and `bus.py` run on the
   calling thread, and `cli_mix.py` keeps the pool for reading files while
   the mlx conversion happens on the caller (`Track.read` / `Track.to_mlx`).
   Both `continue-on-error` lines are gone and CI is one gate again.

## Poistettu: kahdeksan moduulia joilla ei ollut kuluttajaa

`packages/speechmix` kasvoi kahdessa päivässä kahdeksan moduulin verran,
joita mikään ei tuonut sisään: `ceiling`, `loudness`, `grid`, `fingerprint`,
`timeline`, `verify`, `dsp` ja `errors`, yhteensä 761 riviä lähdettä ja 480
riviä testejä — sekä `reference/automixer-parallel/`, 1774 riviä eli kolmas
täysi toteutus samasta ketjusta.

Kolme niistä oli **toisinto elävästä koodista**: `ceiling.programme_ceiling`
ja `loudness.programme_target` ovat yhä autoraffkatin `mix.py`:ssä
(`program_ceiling`, `program_trim`), ja `grid.speech_grid` on
`analysis.build_grid`, jolla on neljä kutsujaa. `fingerprint` oli oman
sisarensa `freshness` toisinto — `FINGERPRINT_VERSION = 1` vastaan `= 8`, ja
kenttänimet eivät osuneet toisiinsa (`highpass_hz` vastaan `high_pass_hz`,
`declick_enabled` vastaan `declick`). Kaksi eri vastausta siihen mikä tekee
välimuistista vanhentuneen, samassa paketissa.

Mikään niistä ei kaatanut mitään. Ne olivat tarkalleen se vika jota vastaan
tämä repositorio on: kolme kopiota ketjusta, nyt vain yhden hakemiston
sisällä.

`tests/test_workspace_agrees.py::test_every_shared_module_has_a_consumer`
estää seuraavan. Se lukee tuonnit `ast`illa eikä grepillä, koska
kommentissa mainittu nimi ei ole kuluttaja — ja `grid` näytti eläväitä juuri
siksi, että `masks.py`:ssä on parametri nimeltä `grid`.

Mitä jäi: `chain`, `masks`, `envelopes`, `debleed`, `freshness`, `messages`.
Jokaisella on tuoja.

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
