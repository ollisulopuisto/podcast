# colab-transcribe

Transcription and Auto-Silence on a Google Colab GPU. A local driver around
a pipeline that runs in the cloud — this machine uploads, the GPU works.
(Suomeksi: [README.fi.md](README.fi.md).)

## What it does

Point it at a folder holding Hindenburg `.nhsx` sessions and their audio.
It starts a Colab VM, uploads everything, transcribes there with Whisper
(faster-whisper on a T4/L4/A100), writes the words into the session, mutes
every region where nobody speaks (Auto-Silence), and downloads the results:
`<jakso> litteroitu.nhsx` and `<jakso>_processed.nhsx`.

## Run it

The quickest way, on a Mac with [Homebrew](https://brew.sh): paste this into Terminal. It installs `uv` (and `ffmpeg` for the other tools) if missing, runs the Google sign-in the first time, and opens the app:

```
curl -fsSL https://raw.githubusercontent.com/ollisulopuisto/podcast/main/run.sh | sh
```

Or step by step:

On a Mac with [Homebrew](https://brew.sh), the only thing to install is uv:

```
brew install uv
```

Then, with nothing else installed (the `colab` tool comes along):

```
uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe --login   # first time only
uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" colab-transcribe           # the TUI
```

`--login` signs you in to Google through the `colab` tool: it prints an address to open in a browser, and you paste the code it gives back into the terminal. That one sign-in covers both Colab and the Google Drive transfer, so `gcloud` isn't needed. You need a Google account with Colab; the free tier gives a T4 GPU.

In the commands below, `colab-transcribe` stands for that `uvx --from … colab-transcribe`, or for `uv run colab-transcribe` inside the repository after `uv sync --all-packages`:

```
colab-transcribe              # the TUI (interactive folder picker + onboarding)
colab-transcribe --check      # check helper apps and environment credentials
```

Fully scripted, no interface:

```
colab-transcribe --input ~/jakso/ --output ~/valmis/ --preset intra-mic
colab-transcribe --input ~/jakso/ --dry-run     # print the plan, run nothing
colab-transcribe --input ~/jakso/ --gpu A100 --rms --thr -40
colab-transcribe --input ~/jakso/ --no-drive    # fallback to direct colab upload
colab-transcribe --session-status               # check active Colab session status
colab-transcribe --stop                         # stop active Colab session
colab-transcribe --input ~/jakso/ --reset-session # force stop and recreate Colab VM
colab-transcribe --input ~/jakso/ --keep-session  # keep Colab VM alive after completion
```

Files are transferred via Google Drive (`--transfer drive`, default) using fast
resumable uploads and mounted inside Colab at internal datacenter speeds.
Presets are the Colab script's: `remote` (tail 1.0 s, gap 1.0 s) and
`intra-mic` (RMS check on, tail 0.4 s, gap 0.4 s). `--thr`, `--tail`,
`--gap`, `--rms` and `--prompt` override after the preset.

## Requirements

* [uv](https://docs.astral.sh/uv/) (`brew install uv`). The `colab` command-line tool is a dependency and comes with `uvx`, pinned to a version with Google's own `jupyter-kernel-client`.
* A Google account with Colab, signed in once with `colab-transcribe --login`. Alternatively, Google Cloud ADC credentials (`gcloud auth application-default login`) or `GOOGLE_APPLICATION_CREDENTIALS`.
* `colab-transcribe` onboards you automatically in the TUI or via `--check` if anything is missing.
* That is all locally. No ffmpeg is needed: the heavy work runs in the cloud, and the pipeline script ships inside this package.

## Note on the pipeline

The Colab script (`src/colabtranscribe/colab/pipeline.py`) is a standalone
snapshot of the transcription + Auto-Silence chain. It runs on Colab and
installs its own dependencies there, so it cannot import the workspace's
shared `speechmix` pipeline. See `CLAUDE.md` for what that means when the
shared chain changes.
