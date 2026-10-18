# kuulas and automixer

What automixer does today when kuulas drives it, what it would take to make
that better, and what is not decided. Written from the code on this branch
(`apps/automixer/src/automixer/`), answering the five questions the kuulas
session sent. Nothing here was run against kuulas: the one real kuulas file
seen so far is a `tracks.json` of 1030 bytes whose contents this repo has not
read. The field list in section 2 is as the kuulas session described it.

"Today" means verified in the code. "Proposed" means not built, and not
decided until the owner says so.

## Status (2026-10-19)

Built, in this branch, after the kuulas session's reply:

- **Disk route for a kuulas export.** `automixer "<folder>" -o out.wav`, where
  the folder holds the stems and `tracks.json`, runs the same `stems_mix`
  pipeline as a `.nhsx` session (stems on disk, never the whole episode in
  memory). `automixer <folder>/tracks.json` works too. The default output is
  `<folder>/<edit> automixer.wav`. kuulas must pass the folder, not a list of
  files: a file list still takes the in-memory route of section 0.
  See `automixer/stem_folder.py`; the tests are
  `apps/automixer/tests/test_stems_folder.py`.
- **`--progress`**: one line per step, `PROGRESS <0-100> <message>`, ending
  with `PROGRESS 100 done`. Percentages never fall. Both routes report.
- **Exit 1 when no tracks are found.** podcast-magic already treated any
  non-zero code as an error and also checks that the file exists.
- **`tracks.json` is read, not guessed**, and a manifest that does not match
  is refused with the track and the field named: `version` (only 1), `rate`
  (only 48000), `start_frame` (only 0), `processing` (only `"dry"`), `frames`
  against every file, the sample rate and channel count of every file, a
  missing file, a duplicate name, `music` that is not stereo. A track with
  `audible: false` is left out.
- **`gain_db` and `pan` are ignored**, as in a session (`session.load` drops
  the track fader). Speech is levelled to a reference and music is fitted to
  the speech, so a fader would be undone, and the speakers are spread
  automatically. The run prints a note for every track with a non-zero
  `gain_db`.
- **`speech-mix` is refused** with the reason. The owner said it is a speech
  bus with several speakers in one file. The speech chain needs one
  microphone per track (the speech grid decides who speaks by comparing
  microphones), so such a file would always look like speech and break the
  ducking and de-bleed of the others. kuulas should export the speakers as
  separate `speech` tracks or leave the bus out. A separate kind of
  treatment for a bus (level it, skip the chain and the grid) is possible
  but is its own decision.

Not built: `mix_tracks` (section 3), cancel by `SIGINT` testing,
`--progress` for the `.nhsx` route's flags-only mode.

Not run on this machine: the 25 automixer tests that need `mlx` or PortAudio
(they run on the macOS CI). The 157 others, including the 32 new ones, pass.

## 0. Two paths, and only one of them is safe for a full episode

`automixer <something>` takes one of two routes (`cli_mix.main`):

| Input | Route | Memory |
| --- | --- | --- |
| one `.nhsx` | `stems_mix.mix` | stems on disk, processed track by track |
| audio files | `Mixer(config).run()` | **all tracks decoded and processed in memory** |

The code comment above the session branch says why the first route exists:
the in-memory mix of a 47-minute episode did not fit a 32 GB machine. The
stem-folder command kuulas builds (`automixer <stems> -o out.wav`) goes
through the second, in-memory route. A 45-minute episode with four stems
(three speech, one stereo music) is the case that comment describes. Until
the stem route reads kuulas stems from disk the way it reads `.nhsx` stems,
a full episode from kuulas is a memory risk, and a short excerpt is not.

This is the main thing the podcast repo needs from the integration: a
disk-based route for a folder of stems.

## 1. CLI contract for step 1 (today)

- **Output (`-o`):** honoured exactly. `Mixer.run` writes
  `sf.write(output_path, ..., subtype="PCM_24")`, a 24-bit WAV, stereo, 48 kHz.
  Default is `final_mix.wav` in the working directory. The parent directory
  must exist: the write is the last step, so a missing directory fails after
  the whole mix has been computed. kuulas should create or check it first.
- **Other files:** the stem route writes nothing else. For `.nhsx` the mix
  makes a temporary folder `automixer-XXXX` beside the output, filled with
  timeline stems, and removes it when it finishes or fails.
  `--flags-only` (`.nhsx` only) writes `<output> flags.txt`.
- **Exit codes:** `0` on success, `1` on any uncaught exception (traceback on
  stderr), `2` on bad arguments. There are no other codes. **A wart:** "No
  tracks found or specified." also exits `0` and writes no file. kuulas must
  check that the output file exists, not only the exit code. *Proposed:* exit
  `1` there.
- **Progress:** the CLI prints lines, with no percent:
  `[HH:MM:SS] [MEM: 116MB] <message>` (stem route) and `[automixer] <message>`
  (`.nhsx` route). The percent exists (`update_progress(val, msg)`: 5, 10, 20,
  30, 40, 55, 65, 80, 85, 95, 100) but only reaches an in-process
  `progress_callback`, which the CLI does not pass. *Proposed:*
  `--progress`, one extra line per update: `PROGRESS 40 Engine: Running
  Speech Bus...`. The messages contain emoji and are free text; do not parse
  them.
- **Cancel:** there is no signal handling in `cli_mix.py` or `stems_mix.py`.
  `SIGTERM` kills the process at once. For the stem route that is harmless:
  no temporary folder. For `.nhsx` the `automixer-XXXX` folder stays beside
  the output, because the cleanup is a `finally` that `SIGTERM` skips.
  `SIGINT` raises `KeyboardInterrupt`, so the cleanup runs. Not tested here:
  whether `SIGINT` stops the plug-in worker threads promptly, and a process
  started in the background of a non-interactive shell may have `SIGINT`
  ignored. Until tested, treat cancel as `SIGTERM` and delete any
  `automixer-*` folder beside the output afterwards.

## 2. Roles from `tracks.json` (proposed; needs the real file)

Today the role of a stem comes from its file name (`detect_tracks` for the
CLI, `session.MUSIC_WORDS` for sessions): `MUSIC`, `THEME`, `TUNNARI`,
`MUSA`, `MUSIIKKI`, `TUNNUS`, `JINGLE`, anything else is speech. A stem
whose name has none of those words but is music will be mixed as speech.
The folder the owner is trying right now (`Pääeditio – musiikit MUSIC.wav`)
happens to carry one.

Yes: read the manifest instead of guessing. kuulas describes it as one entry
per track with `id`, `name`, `kind` (`speech` | `speech-mix` | `music`),
`speaker`, `channels`, `gain_db`, `pan`, `audible`, `file`. Proposed handling:

- **Where:** if the one positional argument is a folder containing
  `tracks.json`, or the argument is a `tracks.json` file, use it. No new
  flag needed; an explicit file list keeps today's name-based behaviour.
- `kind` -> role. `music` is music, `speech` is speech. `speech-mix` is not a
  role automixer has: need to know what it is (a pre-mixed speech bus? a
  stereo recording of two people?). Until answered, refuse it by name rather
  than pick one.
- `file` -> the stem, relative to the manifest. `name` -> the track name that
  `--track-params` matches on. `speaker` -> a speaker identity for de-bleed
  and panning; today it is the file name.
- `audible: false` -> not mixed. kuulas can also simply not export it.
- `gain_db`, `pan`: **not honoured today.** Speech panning is assigned
  automatically from the speaker count (`speaker_pans`); music is fitted to
  `level_lufs` (-30 LUFS in the stem route) and speech is levelled by the
  rider, so a track gain mostly gets undone. *Proposed:* apply `gain_db`
  before the chain; ignore `pan`. Decide whether the owner wants kuulas pan
  to win over the automatic spread.
- A manifest that is unreadable, lacks a field, or names a missing file is a
  refusal with the entry named. It does not fall back to file names silently.

Fields automixer would want that the description lacks: sample rate (it
refuses stems that are not 48 kHz in the session route), and whether a stem
is dry or already had clip gain applied (see 4).

## 3. Step 2: an importable entry point

Two things already exist and one does not.

- `automixer.cli_mix.Mixer(config).run(progress_callback=None,
  preview_start=None, preview_duration=None)` is importable, takes a plain
  dict, and returns the mix as an array in preview mode. The config's tracks
  are `{"name", "path", "type", "start_sec"}`. `start_sec` is a real
  timeline offset, so a track need not start at zero. Per track it takes no
  gain, mute or pan. `progress_callback(percent, message)` is called inline,
  so a callback that raises is a working cancel today (the mix aborts at the
  next update; between updates it keeps running).
- `automixer.stems_mix.mix(session_path, output, ...)` takes a path to an
  `.nhsx`, not tracks.
- **Missing:** a function that takes tracks with regions (source file,
  source offset, length, timeline start, gain), builds the timeline stems and
  mixes them. `session.load` does the building for `.nhsx` today, and it
  writes WAV stems to a work folder. So "no WAV export" is not on offer even
  in-process: the stem route still wants files. Skipping the export means
  either a mixer that reads arrays, which is a bigger change, or kuulas
  handing over source files with offsets and letting the podcast repo build
  its own temporary stems. Proposed signature, to be argued with:

  ```python
  def mix_tracks(tracks, output, *, target_lufs=-16.0, plugin=None,
                 track_params=None, progress=None) -> None
  # tracks: [{"name", "kind", "speaker", "regions": [
  #     {"file", "source_start", "length", "timeline_start", "gain_db"}]}]
  # progress(percent, message) may raise to cancel; mix_tracks cleans up.
  ```

  That wants from kuulas: regions with clip gain, per-track kind and
  speaker, the sample rate of the sources, and a statement of whether track
  gain is already in the audio.

## 4. What kuulas does that can hurt the mix

Unverified: this is read from the automixer side only.

- Stems are dry (clip gain applied, track gain not): fine. Automixer wants
  the raw level relationship between microphones. It measures the noise
  floor and who is speaking from the raw stems (`speechmix.grid`), so any
  noise gate, compression or normalisation applied per stem before export
  shifts those decisions. Do not export processed stems.
- Mono speech and stereo music: this is what the owner's folder holds. What
  the stem route does with a stereo file named as speech, or a mono file
  named as music, has not been checked here, so do not rely on either.
- Not checked: what happens when stems differ in length or sample rate. The
  session route refuses a source that is not 48 kHz; the stem route's
  behaviour is unknown. Export them equal and at 48 kHz.

## 5. What would help kuulas record

- The role (`kind`) and the speaker, per track, in the manifest: yes, kuulas
  already has them.
- A statement of the stems' sample rate and whether gain is applied.
- Not needed: per-track target loudness, ducking envelopes. Automixer
  decides both from the audio.
- Not needed in `tracks.json`: anything about the plug-in. The dxRevive
  state is a separate file given with `--plugin-state`.

## What is not decided

1. Whether a disk-based stem route (section 0) comes before the manifest
   (section 2). The first removes a memory risk; the second removes a
   naming risk. The first is the more important.
2. Whether kuulas pan or gain should win over automixer's.
3. What `speech-mix` means.
4. Whether to keep `-o` as the only way to name the output, or add a folder
   mode.
