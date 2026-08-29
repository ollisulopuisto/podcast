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

1. ~~**`envelope.py` + `binaries.py`**~~ — both moved: `speechmix/rms.py`
   and `speechmix/binaries.py`.
2. ~~**`mix.py`'s timeline arithmetic**~~ — done. `item.placements` and
   `asset_start` reached the library in about a dozen places; they are now
   the `Track` protocol from `packages/speechmix/README.md`, in
   `speechmix/timeline.py`, and `mix.track_of` is the one place that knows
   FCPXML. `overlaps`, `_mask_samples` and `_aligned` followed, because
   automixer subtracts the same leak from its own wav tracks and cannot
   import autoraffkat to reach them.
3. ~~**`editor.py`**~~ — moved, with **both ends**. `speechmix/editor.py`
   is the child process and `open_editor` is the parent that reads it; the
   line-JSON parser was open-coded in autoraffkat's `/api/plugin-editor`
   and would have been open-coded again in automixer. The endpoint went
   from 45 lines to 10. `audio.editor_timeout`, `audio.editor_failed` and
   the new `audio.editor_behind` gained English fallbacks in
   `speechmix.messages`; autoraffkat still says them in Finnish, through
   the translator seam.

   automixer's `ExternalPluginProcessor` now calls `chain.load_plugin` and
   `chain.apply_plugin`, and its own `pedalboard` loader is gone. It had
   three silent differences from the library, none of which ever raised:
   **the plug-in's state never reached it** (so it always ran dxRevive's
   default model, with no way to say which), **no `reset=True`** (so a
   plug-in's state carried from one track to the next), and **no length
   check** (a plug-in's latency shortened the result — 4641 samples
   measured — and shifted everything after it). `app.py`'s
   `scan_system_plugins` was a fourth copy, macOS-only and listing the same
   plug-in twice when it is installed as both VST3 and AU; it is
   `chain.plugins()` now.

   The length check turned out to be missing from the library too, on the
   path automixer uses: `apply_plugin` checked every piece of a split run
   but returned a single instance's output untouched, because the guard
   lived in `chain.process` and automixer does not go through it. It is in
   `apply_plugin` now, where the docstring already claimed it was.

   **`worker.py` stays in autoraffkat.** It is not the plug-in child
   process — it reads FCPXML, resolves roles and calls `mix.process`. What
   was shareable about it was the *protocol*, and that went with the
   editor. A host-specific worker in the library would be the eighth
   module nothing can call.
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

`grid` on sittemmin palannut, ja ero edelliseen on juuri se jonka testi ei
osaa katsoa: silloin sillä ei ollut yhtään kuluttajaa ja se oli rinnakkainen
toteutus `analysis.build_grid`ille. Nyt sillä on kuluttaja — automixerin
`domain/room.py`, jolle se on alun perin kirjoitettukin — ja sen ainoa
ruudukko. Kirjastoon saa siirtää ja sinne saa kirjoittaa sen mitä joku kutsuu;
sinne ei saa kirjoittaa **toista vastausta** samaan kysymykseen. Kaksi
ruudukkomuotoa yhdessä paketissa oli tarkalleen sitä, ja se korjattiin
yhdistämällä ne (`SpeechGrid.speakers`) eikä lisäämällä kolmatta.

## automixer's missing decision layer — done

automixer had the shared **chain** but not the shared **decision layer**, and
`SPEECHMIX-INVENTORY.md` twice recorded the reason as "automixer has no
microphones to build a speech grid from". Wrong premise: every `type: speech`
track is one person's microphone. What was missing was the timeline shape, and
that is item 2 above. With it, three stages that were already written and
tested in the library started running here — cross-bleed removal, the level
rider and per-microphone ducking — through `automixer/domain/room.py`, which
holds no arithmetic of its own. That is the whole design working as intended:
the next measured fix on autoraffkat's side reaches automixer without anybody
carrying it across.

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
