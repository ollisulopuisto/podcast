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
uv run colab-transcribe              # the TUI
```

Fully scripted, no interface:

```
uv run colab-transcribe --input ~/jakso/ --output ~/valmis/ --preset intra-mic
uv run colab-transcribe --input ~/jakso/ --dry-run     # print the plan, run nothing
uv run colab-transcribe --input ~/jakso/ --gpu A100 --rms --thr -40
```

Presets are the Colab script's: `remote` (tail 1.0 s, gap 1.0 s) and
`intra-mic` (RMS check on, tail 0.4 s, gap 0.4 s). `--thr`, `--tail`,
`--gap`, `--rms` and `--prompt` override after the preset.

## Requirements

* The `colab` command-line tool, and a Colab account with GPU access.
* That is all locally: the heavy work runs in the cloud, and the pipeline
  script ships inside this package.

## Note on the pipeline

The Colab script (`src/colabtranscribe/colab/pipeline.py`) is a standalone
snapshot of the transcription + Auto-Silence chain. It runs on Colab and
installs its own dependencies there, so it cannot import the workspace's
shared `speechmix` pipeline. See `CLAUDE.md` for what that means when the
shared chain changes.
