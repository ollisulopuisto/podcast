# podcast

A suite of focused audio and video tools for podcast and interview production.

Whether you need to automatically cut multicam video to the speaker, transcribe and de-bleed recordings locally on your Mac, render or preview Hindenburg sessions without the DAW, or mix and master multi-track speech to broadcast standards — there is a tool here for the job.

---

## Which tool do you need?

| If you want to... | Use | Interface | What it works with |
|---|---|---|---|
| **Cut multicam video** automatically to whoever is talking | [autoraffkat](#autoraffkat) | **Web GUI / Desktop GUI** | Final Cut Pro (`.fcpxml` / `.fcpxmld`) |
| **Transcribe & silence bleed** locally on your Mac | [podcast-magic](#podcast-magic) | **Web GUI / Desktop GUI** | Hindenburg (`.nhsx`) |
| **Mix & master** multi-track speech and music to -16 LUFS | [automixer](#automixer) | **Interactive TUI / CLI** | WAV / AIFF audio files |
| **Transcribe & silence bleed** using a cloud GPU | [colab-transcribe](#colab-transcribe) | **Interactive TUI / CLI** | Hindenburg (`.nhsx`) + Google Colab |
| **Render or inspect** a session without Hindenburg | [nhsx-render](#nhsx-render) | **CLI (headless)** | Hindenburg (`.nhsx`) → WAV |
| **Quick Look preview** sessions in macOS Finder | [NHSX Viewer](#nhsx-viewer--quick-look) | **macOS GUI / Quick Look** | Hindenburg (`.nhsx`) |

---

## Quick Start

Requirements: macOS, `ffmpeg`, and [uv](https://docs.astral.sh/uv/).

Install workspace dependencies once from the repository root:

```bash
brew install ffmpeg
uv sync --all-packages --extra mlx   # Apple Silicon (use --extra faster on Intel)
```

Then run whichever tool you need with `uv run <tool>`.

---

## The Tools

### autoraffkat

> **Automatic multicam video editing for Final Cut Pro.**  
> *Interface: Browser GUI (default) or Native Desktop GUI (`--gui`).*

* **The Problem:** You recorded a multi-camera interview or podcast. Manually switching camera angles in Final Cut Pro to follow whoever is talking takes hours of repetitive cutting.
* **The Solution:** Reads an exported FCPXML, analyzes microphone audio to detect active speakers, and outputs a new FCPXML with picture cuts already made. It opens right back into Final Cut Pro as a normal, editable multicam timeline with all angles, sync, and roles intact. Nothing is pre-rendered.
* **Interface & Features:** Offers an interactive visual patch bay, a full-episode timeline overview, and real-time sliders for turn thresholds and overlap rules. Press `⌘E` to export back to Final Cut.
* **How to run:**
  ```bash
  uv run autoraffkat                      # opens browser GUI at http://127.0.0.1:8731/
  uv run autoraffkat --gui                # opens native desktop window GUI
  uv run autoraffkat "episode.fcpxmld"    # open a specific export
  uv run autoraffkat --pick               # open Finder file dialog
  ```

📖 Details: [apps/autoraffkat/README.md](apps/autoraffkat/README.md) · [Suomeksi](apps/autoraffkat/README.fi.md)

---

### podcast-magic

> **Local transcription and auto-silencing for Hindenburg sessions.**  
> *Interface: Browser GUI (default) or Native Desktop GUI (`--gui`).*

* **The Problem:** You edit in Hindenburg and need transcription and clean tracks (muting mic bleed, coughs, and empty pauses when others speak), but uploading private recordings to cloud services is slow and risks leaks or disconnects.
* **The Solution:** Runs Whisper transcription locally on your Mac's GPU via Apple MLX (or CPU via faster-whisper). Timestamps are written directly into the `.nhsx` audio pool, and an intelligent silencer cuts and mutes non-speech gaps. Non-destructive: always writes a new session file next to the original.
* **Interface & Features:** Visual GUI showing session tracks and waveform regions, a readable script view of the generated transcription, Whisper model selection, and controls to fine-tune auto-silence tail and gap thresholds.
* **How to run:**
  ```bash
  uv run podcast-magic ~/Podcast/episode8/   # opens browser GUI at http://127.0.0.1:8741/
  uv run podcast-magic --gui                 # opens native desktop window GUI
  ```

📖 Details: [apps/podcast-magic/README.md](apps/podcast-magic/README.md) · [Suomeksi](apps/podcast-magic/README.fi.md)

---

### automixer

> **Automated DSP mixing and mastering for multi-track speech and music.**  
> *Interface: Interactive Terminal UI (TUI via `autotui`) or headless CLI.*

* **The Problem:** You have raw audio tracks (host, guest, intro music, ambience) and want a transparent, polished, broadcast-compliant mix without manual DAW mixing marathons.
* **The Solution:** An Apple Silicon-accelerated (MLX) DSP assembly pipeline. Detects speaker activity, estimates and subtracts mic cross-bleed, rides levels smoothly, applies multi-stage compression and de-essing, spectrally carves music frequencies under dialogue, ducks beds, and normalizes the master to **-16.0 LUFS** with a true-peak ceiling of **-1.5 dBTP**.
* **Interface & Features:** The interactive TUI (`autotui`) lets you navigate your project folder, tag audio files as `SPEECH` or `MUSIC`, configure mix parameters, and watch real-time DSP progress bars directly in your terminal.
* **How to run:**
  ```bash
  uv run autotui                             # launch interactive terminal UI (TUI) dashboard
  uv run automixer                           # run via headless CLI
  ```

📖 Details: [apps/automixer/README.md](apps/automixer/README.md)

---

### colab-transcribe

> **Cloud GPU batch transcription and auto-silencing for Hindenburg.**  
> *Interface: Interactive Terminal UI (TUI) or headless CLI.*

* **The Problem:** You want the transcription and auto-silencing pipeline of Podcast Magic, but your local computer lacks a fast Apple Silicon GPU, or you have large batches of episodes you prefer offloading to a cloud GPU.
* **The Solution:** A local CLI and TUI driver that connects to Google Colab. It uploads your `.nhsx` session and audio files to a Colab GPU VM (T4/L4/A100), runs Whisper transcription and auto-silence in the cloud, and downloads the finished `<episode>_processed.nhsx` back to your folder.
* **Interface & Features:** The interactive TUI allows you to select local session directories, choose presets (`remote` or `intra-mic`) and GPU tiers, and monitor live cloud VM provisioning, upload, transcription, and download progress.
* **How to run:**
  ```bash
  uv run colab-transcribe                    # launch interactive terminal UI (TUI)
  uv run colab-transcribe --input ~/jakso/ --output ~/valmis/ --preset intra-mic  # headless CLI
  ```
  *(Requires a Google Colab account and the `colab` CLI tool installed).*

📖 Details: [colab-transcribe/README.md](colab-transcribe/README.md) · [Suomeksi](colab-transcribe/README.fi.md)

---

### nhsx-render

> **Headless Hindenburg session renderer and inspector.**  
> *Interface: Headless CLI.*

* **The Problem:** You need to export a Hindenburg `.nhsx` session to a WAV file, inspect its track geometry, or verify mix plans from a script or machine without Hindenburg installed.
* **The Solution:** A standalone CLI tool built with pure Python, NumPy, and ffmpeg. Reads `.nhsx` XML and audio files to render a complete mix (respecting track volume, pan, fades, and mutes). The `--plan` and `--json` flags inspect the mix in milliseconds without decoding any audio. Perfect for automated batch jobs and headless build scripts.
* **How to run:**
  ```bash
  uv run nhsx-render "episode 8.nhsx"           # renders to episode 8.wav
  uv run nhsx-render "episode 8.nhsx" --plan    # prints playback plan instantly
  uv run nhsx-render "episode 8.nhsx" --json    # outputs JSON for scripts
  uv run nhsx-render "episode 8.nhsx" --inspect # examines session attributes
  ```

---

### NHSX Viewer & Quick Look

> **Instant Hindenburg session preview in macOS Finder.**  
> *Interface: Native macOS Desktop GUI App + Quick Look Extension.*

* **The Problem:** You want to glance at tracks and regions or listen to a `.nhsx` session on macOS without launching a full DAW or running Python scripts.
* **The Solution:** A native Swift application and Quick Look extension. Open `.nhsx` files directly in the standalone GUI window, or simply select any `.nhsx` file in Finder and hit **Spacebar** to see the timeline, track layout, and play back the mix immediately.
* **Location:** Built in [`viewer/`](viewer/README.md) with SwiftPM / XcodeGen. Runs sandboxed with zero Python dependencies.

📖 Details: [viewer/README.md](viewer/README.md)

---

## Architecture & Under the Hood

### The Shared Speech Pipeline (`packages/speechmix`)
The core DSP processing chain—cross-bleed removal, speaker activity envelopes, level riding, compressor stages, and ducking—lives in [`packages/speechmix`](packages/speechmix/). 

Instead of duplicating DSP algorithms across apps, `autoraffkat`, `podcast-magic`, and `automixer` all share this pipeline. When an audio measurement or bug fix lands, all three tools benefit simultaneously.

### Format Specifications
* [`docs/hindenburg-nhsx-format.md`](docs/hindenburg-nhsx-format.md): A detailed, standalone reference to the Hindenburg `.nhsx` XML format—documenting every element, attribute, and coordinate measurement.

### Workspace Notes (`uv`)
This repository is configured as a single `uv` workspace:
* Always run `uv sync --all-packages` from the **repository root**. Running `uv sync` inside a single app's folder will prune dependencies of the other apps from the shared virtual environment.
* `uv run <command>` works from any directory in the repository.

---

## Contributing & Rules

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for build, lint, and test commands. Project conventions, CalVer rules, and development guidelines are detailed in [`CLAUDE.md`](CLAUDE.md).
