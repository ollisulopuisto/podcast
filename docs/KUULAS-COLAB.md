# kuulas calling colab-transcribe directly: what is accepted, what changes, what is open

Answer to the kuulas session's proposed plain-audio contract (`colab-transcribe --audio ... --json <folder>`).
Written 2026-10-19 and updated 2026-10-26. The original plain-audio contract
(`--audio`/`--json`, `--progress`, exit codes, SIGTERM) is implemented and tested against a fake
Colab transport. The default ASR backend is Orukeet via NeMo. `--model whisper` selects
Faster-Whisper (`large-v3-turbo`) for CUDA GPUs including the T4 path used previously; the
Faster-Whisper change has **not yet been run on a real Colab in this revision**.
The owner has decided: the heavy calculation runs on Colab (option B), local later. Items (2) and (3b) are built on branch `feat/colab-align` (`--align`, `timing: "ctc-v1"`): the aligner is a single-file library, `packages/wordalign`, uploaded to the VM. Still **not run on a real Colab**: install size and time, and whether it coexists with the transcriber's CUDA libraries. Where I know a number I say so; where I do not, I say that.

## What exists today (verified in the code)

- `colab-transcribe --audio <file> --json <folder>` writes Kuulas word JSON; the session mode
  also accepts `--input <folder | .nhsx | one audio file> --output <folder>`.
- The **transfer is already direct** by default (`--transfer direct`, CHANGELOG: "The default transfer is
  direct, not Drive"). `--transfer drive` is the opt-in, and `--no-drive` forces direct. Audio does
  not go through Drive unless asked.
- One Colab VM per run: every file in the input goes up and is processed in the same session; uploads are
  cached in the session by content hash.
- The cloud pipeline already has modes that skip the `.nhsx` steps: `--source downmix`
  (`run_downmix`, returns before any session handling). A plain-audio mode is the same shape.
- `run_transcription` writes Orukeet's word-timestamp JSON per audio file (`transcripts/`) and the driver downloads those
  (`parse_generated_transcripts`). Steps 3-4 (inject into `.nhsx`, Auto-Silence) are what a plain mode would
  skip.
- Cancel: `KeyboardInterrupt` (SIGINT) is handled and stops the Colab session unless `--keep-session`.
  **SIGTERM is not handled** (the process dies and the session is left).
- Progress: free-text lines (`[vaihe 2/4 (1/3)] ...`), no `PROGRESS <n>` protocol.

## The contract: accepted, changed, open

| Proposed | Answer |
|---|---|
| `--audio <file>` repeated, `--json <folder>`, `--model`, `--language` | **Accepted.** Same VM for all files (that is how it works today). |
| `<folder>/<stem>.words.json = {"version":1,"timing":...,"language":...,"words":[{"w","s","e"}]}` | **Accepted with three changes below.** |
| `--progress` lines `PROGRESS <0-100> <message>` | **Accepted.** Same format as `automixer --progress`, so one reader serves both. Percentages never fall. |
| exit 0 / non-zero with reason on stderr / no traceback-only failures | **Accepted.** The same rule `automixer` now follows (exit 1 with the reason). |
| SIGTERM cancels, stops or releases the Colab session | **Accepted, and it needs a change:** SIGTERM becomes the same path as SIGINT today (stop the session unless `--keep-session`). Nothing should be left billing on Colab after a cancel. |
| No Auto-Silence, no `.nhsx`, no session folder | **Accepted.** |
| Direct, not Drive, in this mode | **Accepted:** the mode takes no `--transfer` and never uses Drive (it is the owner's rule for private audio). Say so in the notice kuulas shows ("the audio leaves the computer"): it goes to a Google Colab VM. |

### Three changes to the JSON

1. **Order and overlap are guaranteed.** Aligned starts can move a word up to 3 s later while a rejected neighbour stays
   at Orukeet's time, so raw output can be out of order or overlapping. The writer sorts by start and shortens the
   *preceding* word on overlap (what `nhsx/write.py` does and why: moving the next word would push the error forward).
   Zero-length words get a 20 ms floor. `words` is therefore in time order with `s < e`.
2. **`e` (word end) is not validated.** Orukeet provides word starts and ends; podcast accuracy has not been
   measured. When `timing` is `ctc-v1`, starts are corrected by the forced aligner. Treat `e` as approximate.
3. **`timing` values.** `orukeet` (Orukeet's NeMo word timestamps), `whisper` (Faster-Whisper word
   timestamps), or `ctc-v1` (starts corrected by the forced
   aligner, alignment version 1; the number changes if the rule or the model changes, so kuulas can tell an old
   correction from a new one). The `"rejected": <n>` field is the number of words the aligner could not place
   (they keep Orukeet's time), so
   kuulas can show how much of a transcript is corrected.

Units are seconds from the start of that audio file (the same clock as the file), floats with 3 decimals.

## The decision that gates "start-correction on my side"

The aligner (torchaudio `MMS_FA`, CTC) needs torch and torchaudio **2.8.0** (`forced_align` is removed in 2.9) and
about 1.2 GB of weights. Where it runs is the owner's call, and I have not tried either:

- **A. Locally, after the download.** `colab-transcribe` downloads Orukeet's JSON, then aligns on the Mac
  (CPU: a few minutes per 10 minutes of audio on my measurements; not timed carefully) using the audio it already has.
  Needs torch on the Mac, so the command becomes
  `uvx --from "git+...#subdirectory=colab-transcribe" --with torch==2.8.0 --with torchaudio==2.8.0 colab-transcribe ...`.
  Nothing new runs on the VM. This is what I would build first.
- **B. On the Colab VM.** Fast (GPU), but the VM's own torch version is not the pinned one, installing 2.8.0 over it is
  a download of hundreds of megabytes on every fresh VM, and the pipeline already carries a workaround for
  pip-installed NVIDIA libraries clashing with the ASR runtime (`LD_SO_CONF_PATH` in `pipeline.py`). Whether the two
  coexist is **unknown**. I would not choose B without trying it.

Either way the aligner core must be a single-file library that does not import the app, as `silencelearn` is (the
cloud script cannot import the workspace; the driver uploads the library file). Today it lives in
`podcastmagic.transcribe.align` and imports the app's `Word`. Moving it to a shared package is a prerequisite, and a
small one.

## Answers to the questions

- **Several `--audio` files in one Colab session?** Yes: that is how a run already works (one VM, every file uploaded
  and transcribed in it).
- **Does the Drive step still happen by default?** No. Direct is the default today, and in this mode it is the only
  transfer.
- **First-run cost and wall time per hour of audio?** **Not measured in this repo.** There are no recorded timings. A fresh
  VM runs `apt-get install ffmpeg` (10-minute timeout) and `pip install` (30-minute timeout), then downloads the model on first
  use (the NeMo checkpoint is about 2.5 GB). The measured numbers I have are only for local runs. I will time the first
  real plain-audio run and write the numbers into this file instead of guessing.
- **Which command string?** Today, and until the plain-audio mode is merged to `main`:
  `uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe ...`
  works for the current CLI. For a branch, put `@<branch>` after the repository URL. Use a command setting in
  kuulas (as planned): the string will change when the aligner option adds `--with` arguments.

## Backend update (2026-10-26)

The default cloud recognizer is the local multilingual Orukeet model through NeMo. Silero VAD prepares
mono 16 kHz audio and caps speech chunks at 20 seconds; NeMo word timestamps are offset back to the
source file clock. `--model whisper` selects Faster-Whisper large-v3-turbo through CTranslate2;
it consumes the requested language and prompt and returns word timestamps. The selected recognizer's
dependencies are installed for the audio run. `timing` is `orukeet`, `whisper`, or `ctc-v1` when
alignment is enabled. Fillers and repetitions are preserved by post-processing.

This change passed local unit tests but has not been run on a real Colab. The original 2026-10-19
measurements below used Whisper and are historical; they do not describe Orukeet quality or speed.

## What is not known about the correction

One speaker, one episode, 15 hand-marked starts; word ends, drift over a long recording, other speakers and the Colab GPU
path are unmeasured (see `docs/KUULAS-TIMECODES.md`). A transcript marked `ctc-v1` is a measured improvement on
those 15 words, not a guarantee.


## First real Colab runs (2026-10-19)

Run on the 10-minute clip `olli.wav` (600 s cut from the raw `Olli 1.wav`, 760 words), T4, direct transfer.

- **Plain-audio mode** (branch `feat/colab-audio-mode`): worked; the file is valid and sorted; the session was stopped afterwards. Whisper's own starts reproduce the local error pattern (four hand-marked words 0.7-2.4 s early).
- **`--align`** (branch `feat/colab-align`): worked on the first attempt: torch 2.8.0 installed into its own folder, the model loaded, 758 of 760 words aligned (rejected: `Error,` by the early-shift rule, and `20`, which has no letters). Against the 12 words hand-marked in this clip the aligned start is within 6-41 ms of the mark (median about 23 ms); Whisper's start for the same words had a median error of about 180 ms and a worst case of 2.4 s.
- **This is not an independent test.** The same 12 words by the same speaker are what the rules were tuned on. It shows that the Colab path works and gives the same quality as the local one; it does not show that the result holds for other speakers or episodes. Word ends are still unmeasured.
- **Still unmeasured:** wall time and cost for the whole run and per stage (install, weights, transcribe, align) - the log has no timestamps, and the number should be taken from a timed run, not from memory; a long recording (drift); a second speaker.


## Live events: `--events` (kuulas BUGS 107, 2026-10-23)

kuulas reads `PROGRESS` lines and finds the Colab CLI's own notices and "Session ... appears to be lost" in the text
(`src/kuulas/colab_transcribe.py`). The same protocol as `automixer --events` (see `docs/PODCAST-MAGIC.md` in kuulas,
"Live events") exists here, so one reader serves both. **Written from the code and tested against a fake Colab
transport; not run on a real Colab.** The first version was my proposal; the second (2026-10-23, below) is kuulas's own
list of wishes from `docs/PODCAST-MAGIC.md`, built as asked.

- `--events` belongs to the plain-audio mode (`--audio`/`--json`); without `--audio` it is refused, like `--align`.
  It is listed in `--help`, so kuulas can probe for it.
- With it, **in addition to** every existing text line (unchanged, in the same order, same exit codes), one line per event
  on stdout: `@@kuulas ` followed by one JSON object, flushed at once. Without the flag nothing changes. Lines that start
  with `@@kuulas ` are not meant for a human.
- Every object has `"schema": 1` and `"event"`. Fields may be added, never renamed. Events:
  - `session`: `state` is `"new"` (a Colab VM is started), `"reuse"` (an existing session is used) or `"reset"` (an
    existing one is closed and replaced). Optional `reason` on a reset: `"requested"` (`--reset-session`) or `"lost"` (see
    "Recovery" below). Once before the first `stage`, and once more if a lost session is recovered.
  - `stage`: `stage` and `state` (`"start"` or `"done"`). A stage starts when the driver starts it and is done when the next
    one starts or the run ends, so the START is the point: a slow stage no longer looks like the one before it. Stages, in
    order: `session` (starting the VM, absent when reused), `prepare` (clearing the VM's folders), `upload`, `run` (the
    cloud script has started, nothing reported yet), `install` (dependencies), `transcribe` and `align` (one per file),
    `download`, `stop` (absent with `--keep-session`).
    - **`transcribe` and `align`** carry `index`, `total` (files) and **`name`**, the audio file's file name
      (`"Take 1-Mic.wav"`), on both the start and the done event, so a toast can say the file and not only "file 1 of 2".
    - **`upload`** is one stage per file sent (the pipeline script and the aligner module are uploads too, with their own
      names). It carries `name` (the local file's name), **`via`** (`"direct"`, or `"drive"` for the Drive route, which the
      plain-audio mode never takes) and `total` (**bytes** of the original file, not of the FLAC the tool may pack it into);
      the done event also has `done`, equal to `total`: the stage ended, so everything went. A file already on the VM
      (the upload cache) is not announced at all. Note that `total` is bytes in an `upload` stage and a file count in
      `transcribe`/`align` (where there is an `index`).
  - `transfer` (new): progress **inside** an upload, `name`, `via`, `done`, `total` (bytes, `done` never falls). Only the
    chunked route reports it, once after every 64 MiB chunk, for files above 128 MiB (a smaller file goes up in one command
    that reports nothing until it is done). The bytes are the original file's even when the tool packs it as FLAC, so
    `done / total` is a progress bar. A separate event rather than another `state` of `stage`, so a reader that only knows
    `start` and `done` cannot take an update for the end of the stage.
  - `progress`: `percent` (integer 0-100, never falls, never above 100) and `message`: what `--progress` prints as
    `PROGRESS <percent> <message>`. Emitted with `--events` whether or not `--progress` is given; the text lines still need
    `--progress`. **The Colab CLI's own update notices ("A new version of Colab CLI ...", "Run 'colab update' ...", "To
    silence this check ...") are never a `progress.message`**, in either form; they stay in the text lines.
  - `warning`: `code` and `message`. Codes: `"session_lost"` (the Colab CLI says the session appears to be lost; see
    "Recovery") and `"colab_update"` (the first of the Colab CLI's update notices, once per run; kuulas can show it once and
    keep it out of the progress bar).
  - `error`: `reason`, `message`, and for the run itself `code` (the exit code) and `stage` (the stage that had started and
    not finished, or `null`). Reasons: `"environment"` (the Colab tool or its sign-in is missing; no `code`), `"failed"` (a
    command exited non-zero), `"cancelled"` (exit 130, SIGINT or SIGTERM), `"missing_words"` (the run ended but a
    `<name>.words.json` is absent; `files` lists them). **`message` is one short readable line, at most 200 characters,
    never the log** (the log is in the text lines; a long message is cut with "…"). Always the last event of a failed run;
    the exit code and the stderr text are unchanged.
  - `done`: `files`, the paths of the `<name>.words.json` written, in the order of the `--audio` arguments. The last event
    of a successful run. Unchanged by the 2026-10-23 list.

### Paikallinen Parakeet/Orukeet-tausta

`--backend parakeet` and `--backend orukeet` use the same plain-audio JSON
contract as Colab and accept `--events`. Their `words` array uses the same
`w`/`s`/`e` fields, sorted order, three-decimal seconds, overlap handling,
20 ms minimum duration, and `version: 1`. `timing` is the selected backend
(`parakeet` or `orukeet`); `rejected` is zero because no forced alignment is
performed.

The event stream keeps schema 1. A local run emits `session` with
`state: "local"` and `backend`, then one `stage` start/done pair per file
(`stage: "transcribe"`, with `index`, `total`, and `name`), `progress` events
including 100%, and finally `done`. Local failures end with an `error` event
using the same `reason`, `code`, and `stage` fields as a failed Colab run.
`state: "local"` identifies that no Colab VM is started or reused.

### Recovery from a lost session (built inside the tool, with or without `--events`)

When the run fails and the Colab CLI said the session appears to be lost (Colab reclaimed the VM), the tool no longer
just exits: it prints a text line, closes the session (`colab stop`), emits `session` with `state: "reset"` and
`reason: "lost"`, plans the run again with a **new** VM and runs it **once more**. A second loss, a cancel (130) or any
other failure is not retried. Any stage that was open when the first attempt died is abandoned (no `done` for it) and a
new run of stages follows the `session` event; `progress` percent still never falls, so the bar waits where it was until
the second attempt passes it. kuulas's own retry (which looks for the text) stays as the fallback and finds nothing to do
when the tool has already recovered; if it still sees the failure, the tool failed twice.

- What this does not give: the Colab CLI's own error text beyond `message` (it is in the text lines), a time estimate (no
  timings have been recorded; see "First real Colab runs"), the model download progress inside `run`, or bytes inside the
  small uploads.
