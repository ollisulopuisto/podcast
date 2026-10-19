# kuulas calling colab-transcribe directly: what is accepted, what changes, what is open

Answer to the kuulas session's proposed plain-audio contract (`colab-transcribe --audio ... --json <folder>`).
Written 2026-10-19 by the podcast-repo session from the code on `main` plus PR #60
(the word-start aligner in the transcribe app). **Status 2026-10-19:** item (1) below, the plain-audio mode
(`--audio`/`--json`, `timing: "whisper"`, `--progress`, exit codes, SIGTERM), is built on branch
`feat/colab-audio-mode` and tested against a fake Colab transport. It has **not been run on a real Colab**.
The owner has decided: the heavy calculation runs on Colab (option B), local later. Items (2) and (3b) are built on branch `feat/colab-align` (`--align`, `timing: "ctc-v1"`): the aligner is a single-file library, `packages/wordalign`, uploaded to the VM. Still **not run on a real Colab**: install size and time, and whether it coexists with the transcriber's CUDA libraries. Where I know a number I say so; where I do not, I say that.

## What exists today (verified in the code)

- `colab-transcribe --input <folder | .nhsx | one audio file> --output <folder>`. There is no
  `--audio` or `--json`.
- The **transfer is already direct** by default (`--transfer direct`, CHANGELOG: "The default transfer is
  direct, not Drive"). `--transfer drive` is the opt-in, and `--no-drive` forces direct. Audio does
  not go through Drive unless asked.
- One Colab VM per run: every file in the input goes up and is processed in the same session; uploads are
  cached in the session by content hash.
- The cloud pipeline already has modes that skip the `.nhsx` steps: `--source downmix`
  (`run_downmix`, returns before any session handling). A plain-audio mode is the same shape.
- `run_transcription` writes Whisper's JSON per audio file (`transcripts/`) and the driver downloads those
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
   at Whisper's time, so raw output can be out of order or overlapping. The writer sorts by start and shortens the
   *preceding* word on overlap (what `nhsx/write.py` does and why: moving the next word would push the error forward).
   Zero-length words get a 20 ms floor. `words` is therefore in time order with `s < e`.
2. **`e` (word end) is not validated.** Only starts were measured against hand marks. When `timing` is `ctc-v1`, `e` is the longer
   of Whisper's end and the aligner's end. Treat `e` as approximate.
3. **`timing` values.** `whisper` (as Whisper gave it) or `ctc-v1` (starts corrected by the forced aligner, alignment
   version 1; the number changes if the rule or the model changes, so kuulas can tell an old correction from a new one).
   Add one more field: `"rejected": <n>`, the number of words the aligner could not place (they keep Whisper's time), so
   kuulas can show how much of a transcript is corrected.

Units are seconds from the start of that audio file (the same clock as the file), floats with 3 decimals.

## The decision that gates "start-correction on my side"

The aligner (torchaudio `MMS_FA`, CTC) needs torch and torchaudio **2.8.0** (`forced_align` is removed in 2.9) and
about 1.2 GB of weights. Where it runs is the owner's call, and I have not tried either:

- **A. Locally, after the download.** `colab-transcribe` downloads Whisper's JSON, then aligns on the Mac
  (CPU: a few minutes per 10 minutes of audio on my measurements; not timed carefully) using the audio it already has.
  Needs torch on the Mac, so the command becomes
  `uvx --from "git+...#subdirectory=colab-transcribe" --with torch==2.8.0 --with torchaudio==2.8.0 colab-transcribe ...`.
  Nothing new runs on the VM. This is what I would build first.
- **B. On the Colab VM.** Fast (GPU), but the VM's own torch version is not the pinned one, installing 2.8.0 over it is
  a download of hundreds of megabytes on every fresh VM, and the pipeline already carries a workaround for
  pip-installed NVIDIA libraries clashing with CTranslate2 (`LD_SO_CONF_PATH` in `pipeline.py`). Whether the two
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
  VM runs `apt-get install ffmpeg` and `pip install` (timeouts 10 minutes each), then downloads the model on first
  use (the turbo model is about 1.5 GB). The measured numbers I have are only for local runs. I will time the first
  real plain-audio run and write the numbers into this file instead of guessing.
- **Which command string?** Today, and until the plain-audio mode is merged to `main`:
  `uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe ...`
  works for the current CLI. For a branch, put `@<branch>` after the repository URL. Use a command setting in
  kuulas (as planned): the string will change when the aligner option adds `--with` arguments.

## When

I will not give dates. What I would build, in this order, each with tests and a fake Colab transport like the
existing driver tests: (1) the plain-audio mode with `--audio`/`--json`, `timing: "whisper"`, `--progress`, exit codes
and SIGTERM; (2) moving the aligner to a single-file library; (3) the correction on the Mac (option A), `timing:
"ctc-v1"`. Item (1) is useful to kuulas on its own and does not wait for the aligner. Kuulas can build against a fake
tool that returns this JSON now.

What I need from the owner: whether to start with (1) alone, and A or B for the aligner.

## What is not known about the correction

One speaker, one episode, 15 hand-marked starts; word ends, drift over a long recording, other speakers and the Colab GPU
path are unmeasured (see `docs/KUULAS-TIMECODES.md`). A transcript marked `ctc-v1` is a measured improvement on
those 15 words, not a guarantee.
