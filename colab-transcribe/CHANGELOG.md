# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Calendar Versioning (CalVer).

## [2026.10.23.1] - 2026-10-23

### Added
- **`--events` (with `--audio`): live, structured progress for a host such as kuulas.** Besides the text lines (unchanged, same order, same exit codes) one line per event on stdout: `@@kuulas ` and a JSON object with `schema` 1 and `event` (`session`, `stage`, `transfer`, `progress`, `warning`, `error`, `done`). The same protocol as `automixer --events`, so one reader serves both. Fields may be added, never renamed. A stage is announced when it starts. `transcribe` and `align` carry the file's `name`, `index` and `total`; `upload` carries `name`, `via` and the bytes (`total`, and `done` when it ends); files above 128 MiB report `transfer` after every 64 MiB chunk. The Colab CLI's update notices never reach `progress.message`; the first one is a `warning` with code `colab_update`. `error.message` is one short readable line (at most 200 characters), never the log. Contract: `docs/KUULAS-COLAB.md`. Written from the code and tested against a fake Colab transport; not run on a real Colab.
- **`--align` (with `--audio`): word starts corrected on the Colab VM.** Uploads `wordalign.py` next to the script, installs torch/torchaudio 2.8.0 into `/content/aligner_site`, checks the aligner before transcribing, and writes `timing: "ctc-v1"` with `rejected`. Alignment runs in its own process without the pip-nvidia library path. Fails the run if no word aligns. Not run on a real Colab.
- **Plain-audio mode: `--audio <file>` (repeatable) and `--json <folder>`.** Audio in, `<name>.words.json` out (words with start and end in seconds, in time order), no `.nhsx` and no Auto-Silence; always the direct transfer. `--model`, `--language`, `--progress` (`PROGRESS <0-100> <message>`, never falling) and exit 1 with the reason on stderr when a result is missing. SIGTERM now takes the Ctrl+C path in this mode and stops the Colab session unless `--keep-session`. Contract: `docs/KUULAS-COLAB.md`. The word starts are Whisper's own; the forced aligner is not in this mode yet.

### Changed
- **A lost Colab session is recovered inside the tool, with or without `--events`.** When the run fails and the Colab CLI says the session appears to be lost, the tool closes the session, starts a new one and runs once more (a `session` event with `state` `reset` and `reason` `lost`). A second loss, a cancel or any other failure is not retried.

## [2026.10.15.1] - 2026-10-15

### Fixed
- **A Drive upload that fails with HTTP 403 continues with direct upload.** On an account without a Drive API quota project the run used to stop at "Google Drive upload failed: 403"; it now says so and carries on with the direct transfer from where it was (session and scripts are already up).
- **Big inputs go up in parts on the direct transfer.** A 409 MB WAV failed with HTTP 500 in `colab upload`. Files over 128 MB are now sent in 64 MB parts, each retried on its own, and joined with `cat` in Colab. The sizes are a guess until a file that big has gone through; the 500 was measured, the cure is not yet.

### Added
- **`--inline-remarks` (off by default): short remarks stay inside the paragraph.** A remark of at most two words between two pieces of the same speaker ("niin", "joo") is written in the paragraph as `(Name: niin)` instead of breaking it into three lines. Without the option the script is as before. The TUI has a switch for it (and its transfer labels now say which is the default).

### Changed
- **The default Colab session is called `whisper`, not `vst-pipeline`.** The old name was a developer's own session and showed up in everyone's log and in the `colab stop -s …` hints. `--session` and `COLAB_SESSION` still set it. A session left open under the old name is not found any more; stop it with `colab stop -s vst-pipeline`.

### Fixed
- **File names with odd characters no longer fail the upload.** Colab's file API answered HTTP 400 to `audioIiris…^.wav.flac` (the `^` goes out as `%5E`). In the cache the file is now `/content/cache/<hash>/data<extension>` whatever it was called, and the real name is restored by the link into `/content/input`.
- **The run's own output folder is not uploaded as input.** An `output/` inside the input folder (earlier results) went up with the session files; it is now left out.
- **The script (`.md`) of a session that was not silenced is one turn per burst of speech, not one block per speaker.** Without Auto-Silence each track is a single region the length of the episode, so all of a speaker's words became one paragraph stamped 00:00. A region's words are now cut at pauses longer than the run's `gap` (1 s for `remote`, 0.4 s for `intra-mic` and `learned`) with the same `merge_intervals_with_gap` that Auto-Silence uses to decide what stays open, so the script and the muting cannot disagree about where speech ends, each piece is ordered by its first word and carries its own timestamp, and adjacent pieces from the same speaker merge as before. The first piece keeps the region's start when its first word is within a second of it, so silenced sessions read the same. podcast-magic's script has the same change (a test holds them equal); one of its tests changed: a long reply from the other speaker now lands in its place in time and the interviewer's last words follow it with their own timestamp, instead of the whole paragraph coming first.
- **A Whisper loop is not written into the session or the script.** Five or more of the same word in a row ("niin, niin, niin, …" dozens of times in a silent stretch) is dropped; a real "niin niin niin" is not touched.

### Added
- **Uploads are cached in Colab by content hash and not repeated while the same session lives.** Files go to `/content/cache/<sha256>/<name>` and `/content/input` is rebuilt from hard links on every run (the script transcribes everything in `input`, so it is still emptied first). A run that reuses a live session lists the cache first and skips what is already there, so a run that stopped halfway resumes instead of starting over; a changed file has a new hash and goes up again. The session is stopped at the end of a successful run unless `--keep-session` is given, and the cache goes with it. A failed or interrupted run leaves the session open, so retrying finds the cache. Joining parts and unpacking FLAC write to a temp file and move it into place, so a half-written file is never taken for a finished one. A Colab read timeout while connecting is retried like a lost connection.
- **Choose one session when a folder holds several.** `--input <file>.nhsx` means that session in its own folder: only it and the audio it names go up (before, every `.nhsx` in the folder and all their audio went, so a folder with the original, the two-track copy and the finished session uploaded everything). Without a choice the run lists the sessions it found. The TUI asks which one when you pick a folder with more than one.

### Changed
- **Bleed from the other microphone is no longer written into the session.** Whisper still transcribes every file whole, but when the words go into the `.nhsx`, a word is left out if another track is clearly louder at that moment, each track measured against its own speech level so differing gains do not matter. The margin is measured on the material in Colab: a quarter of how much louder the speakers' own words are than the bleed (median over clear words), between 3 and 12 dB; the log says "Vuodon raja: …". With too few clear words it falls back to 6 dB. Overlapping speech stays on both tracks. Hindenburg no longer shows the same speech under every speaker and every file, and the script (`.md`) reads the filtered session, so it stops seeing one long interjection. Measured on a two-mic session (47 min): the level difference between the tracks has two clear groups, only 1.7 % of speech frames fall within 8 dB of a tie, and the bleed sits 27–28 dB under the speaker's own level. `--no-bleed-filter` turns it off. Tracks of music are not compared (only transcribed files are), and one track on its own is never filtered. Not yet run on Colab.
- **The same recording under two names is uploaded and transcribed once.** Same-size audio files are compared by SHA-256 (a file alone at its size is never read). Only the first goes up; Colab makes the others with `ln -f` before the run, so the session still finds every name. The Colab script does the same check itself and copies the finished transcript to the duplicates, so it also holds when the whole folder was sent (Drive mode).
- **Big PCM WAVs are compressed to FLAC before the direct transfer.** Lossless (checked sample for sample), unpacked in Colab by `ffmpeg` to the same name and bit depth, so the session and the results are untouched. 10 minutes of 24-bit mono: 86 MB -> 49 MB in 0.9 s. Files over 128 MB only; float and 32-bit WAVs go up as they are. `--no-compress` turns it off. New dependency: `soundfile` (ships libsndfile, no ffmpeg needed locally).
- **Only what the session uses is uploaded.** The `.nhsx` is read first and only the audio its pool names goes up (looked up in the pool's own folder, then beside the session). Leftovers next to it — raw takes, `.TAKE` copies, a rough mp3 — are no longer uploaded, and, because the Colab script transcribes every audio file it finds, no longer transcribed either; the run says how many files and GB it left out. Without a session, or if one cannot be read, everything goes up as before. (Drive mode still tars the whole folder; only the direct transfer and the 403 fallback use the selection.)
- **The default transfer is direct, not Drive.** Drive needs the Drive API to be usable on the account and answers 403 where it is not, which was a wall for a new user. `--transfer drive` is still there for the speed; if it fails with 403 the run continues directly.
- **A remark from another speaker breaks up a long turn in the script.** A Hindenburg region does not end where someone else speaks, so the interviewer's paragraph used to come first and the guest's "yes" after it. Now a region of another speaker that starts inside a turn and ends before it does cuts the paragraph there, and the paragraph continues with the time of its next word. Longer overlapping speech is still a change of turn. Same rule as podcast-magic's script (held by a test).

## [2026.10.12.1] - 2026-10-12

### Added
- **`--preset learned`: the silence threshold is learned from the stretches you muted by hand** (`colab/pipeline.py`, also offered in the TUI's preset list). Mute the quiet stretches at the start of the session in Hindenburg before the run; each track's threshold is the level of its muted audio. The calculation is the shared `silencelearn` library (one file, standard library only, also used by podcast-magic): threshold with leak from other tracks, the speech guard, and the cap from words you left unmuted. Hand-muted regions stay muted. The levels are measured with the same ffmpeg decode and RMS as podcast-magic, once per file. A session with no muted region stops with an explanation and writes nothing.
- **The library is uploaded, not copied.** The driver uploads `silencelearn.py` to `/content` next to `pipeline.py` (both transfer modes), so podcast-magic and this script cannot drift apart on the calculation. This is the first piece of the Colab script that is shipped instead of snapshotted; the others (script writer, downmix, reader hardening) still are.
- **Not applied:** the learned leak-gap limit (`dominance`). The library computes it, but this script has no word-by-word comparison against other tracks, so there is nothing to apply it to.
- `test_the_learned_threshold_matches_podcast_magics` now holds the two *adapters* (lxml + ffmpeg here, nhsx + `AudioCache` there) to the same numbers.

## [2026.10.9.1] - 2026-10-09

### Added
- **Speaker-turn script next to the finished session** (`colab/pipeline.py`): after the run, `<jakso>_processed.md` (or `<jakso> litteroitu.md` with `--transcribe-only`) is written next to the session and downloaded with the rest. The track name is the speaker; consecutive regions on one track are one paragraph. A snapshot of podcast-magic's `script/core.py`, held to it by `test_the_snapshot_script_matches_podcast_magics`.

## [2026.10.8.5] - 2026-10-08

### Fixed
- **Drive sign-in is now recognised.** 2026.10.8.4 stopped waiting for Enter, but it checked for success in a way Colab never confirms, so the Drive mount still timed out after 10 minutes although access was granted in the browser. It now completes the sign-in while it waits, prints a note every 30 s while it waits, and computers that already had 2026.10.8.4 are updated on their next run.

## [2026.10.8.4] - 2026-10-08

### Fixed
- **Drive mount no longer hangs after the browser sign-in.** The current Colab CLI waited for an Enter key press it never showed on screen, so runs stopped at "[2/10] Liitetään Google Drive...". The run now continues by itself once access is granted in the browser (waits up to 10 minutes).

## [2026.10.8.3] - 2026-10-08

### Added
- **Transcribe only:** `--transcribe-only` on the command line, or the new Auto-Silence switch in the TUI, skips the silencing step. The result is then only `<episode> litteroitu.nhsx`. Auto-Silence stays on by default. `COLAB_TRANSCRIBE_ONLY=1` does the same from the environment.

## [2026.10.8.2] - 2026-10-08

### Added
- **One command from a fresh Mac with Homebrew:** `curl -fsSL https://raw.githubusercontent.com/ollisulopuisto/podcast/main/run.sh | sh` installs `uv` and `ffmpeg` if missing, runs the Google sign-in the first time, and opens colab-transcribe. Naming another tool after `sh -s --` starts that one instead (autoraffkat, automixer, podcast-magic…).

## [2026.10.8.1] - 2026-10-08

### Added
- **Runs with one command and nothing installed but uv:** `uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe`. Google's `colab` tool now comes along as a dependency, pinned to the build with Google's own `jupyter-kernel-client` that works, so it no longer needs installing separately.
- **`colab-transcribe --login`:** a first-time Google sign-in through the `colab` tool (open an address in the browser, paste the code back). It covers Colab and the Drive transfer, so `gcloud` is no longer needed. The setup check points here first when credentials are missing.

### Fixed
- The setup check and the two `colab` fixes this app applies now find `colab`'s Python behind uv's `#!/bin/sh` launcher. Before, they read `/bin/sh` as the Python, reported a working `colab` as broken and silently skipped the fixes.

## [colab-transcribe-v2026.9.12.1] - 2026-09-12

### Fixed
- **Drive API Quota Project Isolation & Cache in Tests** (`gdrive.py`, `tests/conftest.py`, `tests/test_gdrive.py`):
  - Isolate test suite from host's Google Cloud ADC (`~/.config/gcloud/application_default_credentials.json`) and Colab token (`~/.config/colab-cli/token.json`) by setting isolated test paths and default test quota project in `conftest.py`.
  - Prevent unintended Cloud Resource Manager network requests from consuming mocked `urllib.request.urlopen` responses in unit tests when ADC is missing (e.g. clean CI runners).
  - Add `lru_cache` to `_fetch_quota_project_from_api` to avoid repeated remote Cloud Resource Manager calls during Google Drive requests.
  - Added unit tests for quota project resolution and fallback.
