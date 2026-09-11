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

From the repository root, after `uv sync --all-packages`:

```
uv run colab-transcribe              # the TUI (interactive folder picker + onboarding)
uv run colab-transcribe --check      # check helper apps and environment credentials
```

Fully scripted, no interface:

```
uv run colab-transcribe --input ~/jakso/ --output ~/valmis/ --preset intra-mic
uv run colab-transcribe --input ~/jakso/ --dry-run     # print the plan, run nothing
uv run colab-transcribe --input ~/jakso/ --gpu A100 --rms --thr -40
uv run colab-transcribe --input ~/jakso/ --no-drive    # fallback to direct colab upload
uv run colab-transcribe --session-status               # check active Colab session status
uv run colab-transcribe --stop                         # stop active Colab session
uv run colab-transcribe --input ~/jakso/ --reset-session # force stop and recreate Colab VM
uv run colab-transcribe --input ~/jakso/ --keep-session  # keep Colab VM alive after completion
```

Files are transferred via Google Drive (`--transfer drive`, default) using fast
resumable uploads and mounted inside Colab at internal datacenter speeds.
Presets are the Colab script's: `remote` (tail 1.0 s, gap 1.0 s) and
`intra-mic` (RMS check on, tail 0.4 s, gap 0.4 s). `--thr`, `--tail`,
`--gap`, `--rms` and `--prompt` override after the preset.

## Requirements

* The `colab` command-line tool (`uv tool install google-colab-cli`), and a Colab account with GPU access.
* Google Cloud ADC credentials (`gcloud auth application-default login`) or `GOOGLE_APPLICATION_CREDENTIALS`.
* `colab-transcribe` onboards you automatically in the TUI or via `--check` if any tool or credential is missing.
* That is all locally: the heavy work runs in the cloud, and the pipeline
  script ships inside this package.

## Note on the pipeline

The Colab script (`src/colabtranscribe/colab/pipeline.py`) is a standalone
snapshot of the transcription + Auto-Silence chain. It runs on Colab and
installs its own dependencies there, so it cannot import the workspace's
shared `speechmix` pipeline. See `CLAUDE.md` for what that means when the
shared chain changes.
