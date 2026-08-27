# 🎙️ Podcast Automixer

A modular, high-performance podcast assembly tool optimized for **Apple Silicon (ARM Macs)**. It uses **MLX** for GPU-accelerated signal processing and a parallelized DSP pipeline to deliver a transparent, professional sound.

## 🚀 Key Features

### 1. **Phase 1: Intelligent Spotting**
- **MLX-Accelerated Analysis**: Uses the Metal GPU to perform rapid RMS energy scans of your episode.
- **Natural Pause Detection**: Automatically identifies silences longer than 0.5s (skipping the first 50% of the episode) to suggest perfect ad insertion points.

### 2. **Phase 2: The shared speech chain**
The speech channel strip is **not automixer's own code**. It is
`packages/speechmix`, the pipeline shared with `autoraffkat` and
`podcast-magic`, so a fix measured in one of them lands in all three in the
same commit. `SPEECHMIX-INVENTORY.md` records what changed when the swap
happened, and `PIPELINE.md` is the stage-by-stage order.

- **The speech grid**: every speech track is one person's microphone, and an
  RMS envelope over all of them says who is talking when. Three stages read it
  and nothing else.
- **Cross-bleed removal**: two microphones in a room hear both people, and the
  same voice arriving twice a few milliseconds apart is a comb filter. The leak
  is linear, so it is estimated where only the other person speaks and
  subtracted everywhere — before the plug-in slot, because a generative
  plug-in destroys the linear relation that makes it possible.
- **Level rider**: a slow ride ahead of the compressors, driven by the grid
  rather than by the level — on two microphones, half of what is loud on a
  track is the other person.
- **Three bounded compressor stages** with a parallel dry/wet mix, a de-esser
  ahead of them, and a de-clicker calibrated on how often lip smacks actually
  occur.
- **Microphone ducking**: closes a microphone while its owner is silent, under
  the other person's speech. Not the same feature as the music ducking below.
- **Spectral Carving (Dynamic PEQ)**: analyzes the speech spectrum and carves
  those frequencies out of the music bus using FFT spectral subtraction.
- **Delicate Stereo Panning**: a subtle (±10%) spatial spread across speakers.
- **Sidechain Auto-Ducking**: GPU-accelerated *music* ducking triggered by the
  speech bus.

### 3. **Phase 3: Parallelized Production**
- **Multi-Core Loading**: Parallel track I/O using `ThreadPoolExecutor`.
- **Concurrent Bus Processing**: Speech and Music buses process simultaneously to saturate your CPU/GPU.
- **LUFS Normalization**: Final render is precisely normalized to **-16.0 LUFS** (ITU-R BS.1770-4) with 24-bit stereo depth.
- **True-peak ceiling**: -1.5 dBTP with oversampled detection. Sample peaks are
  not the ones that clip a converter or a lossy encoder — those fall between
  samples, and a limiter set to -1.0 dBFS measured -0.41 dBTP on the way out.

---

## 🛠️ Usage

### **The Unified TUI (Recommended)**
The easiest way to use the automixer is via the interactive dashboard:
```bash
autotui
```
*(Or `uv run python -m automixer.app` if running from source)*

**TUI Workflow:**
1.  **Audio Assets**: Select files from the current directory and mark them as `SPEECH` or `MUSIC`.
2.  **Signal Chain**: 
    - Toggle High-Pass filters (default 80Hz for speech).
    - Adjust Peak Tamer and Leveler thresholds.
    - Set the **Spectral Carve** strength (0.5 is recommended for transparency).
    - Scan for ad breaks and select your preferred spot.
3.  **Render**: Hit **"RENDER FINAL MIX"** to produce your high-fidelity stereo WAV.

### **The Automixer CLI**
The `automixer` command provides a powerful, zero-configuration way to mix your podcast. It features **Automatic Track Detection** based on filename keywords.

#### **Zero-Config Mix**
Run it in a folder containing your audio files, and it will automatically find and classify them:
```bash
automixer
```
*(Looks for all `.wav` and `.mp3` files in the current directory)*

#### **Auto-Detection Logic**
Files are classified as **MUSIC** if their filename contains any of these keywords:
`MUSIC`, `THEME`, `TUNNARI`, `MUSA`, `MUSIIKKI`, `TUNNUS`, `JINGLE`.
All other audio files are treated as **SPEECH**.

#### **Custom CLI Control**
Specify tracks and options explicitly:
```bash
automixer --speech mic1.wav mic2.wav --music theme_THEME.wav -o episode1.wav --target-lufs -14.0
```

**Available Options:**
- `tracks`: Positional arguments for audio files (auto-detected if `--speech`/--music` not used).
- `--speech`: Explicitly specify speech tracks.
- `--music`: Explicitly specify music tracks.
- `--output`, `-o`: Output filename (default: `final_mix.wav`).
- `--target-lufs`: Target loudness (default: `-16.0`).
- `--ad-spot`: Ad spot time in seconds.
- `--ad-duration`: Ad duration in seconds (default: `30.0`).

Stages that read the speech grid, all on by default and all off under
`--minimal`:
- `--no-debleed`: keep the cross-bleed between microphones.
- `--no-rider`: skip the slow level ride ahead of the compressors.
- `--no-mic-duck`: leave a microphone open while its owner is silent.
- `--mic-duck-db`: how far a closed microphone drops (default: the measured
  -9 dB, which is deliberately shallow — the benefit is in the timing).

These need two or more speech tracks at the mixer's sample rate; with one
microphone there is no grid to build, and each stage is skipped rather than
approximated.

### **Utility Commands**
- **Analyze Ad Spots**: `autoanalyze <file> <output_spots>`
- **Launch TUI**: `autotui`

### **Running the tests**
```bash
uv sync        # installs the project, so `import automixer` resolves
uv run pytest
```
The tests import `automixer`, the installed package -- not a path relative to
the checkout. A bare `pytest` from the repository root will not find it, and
that is deliberate: importing through the checkout path is what hid a broken
package layout for as long as it did.

On anything that is not Apple Silicon, `mlx` has no Metal backend; add
`uv pip install "mlx[cpu]"` after `uv sync` to run them.

---

## 🏗️ Project Architecture & Signal Flow
For a detailed breakdown of exactly when processing happens, see **[PIPELINE.md](PIPELINE.md)**.

- `src/automixer/domain/`: Core DSP logic (Processors, Buses, Tracks).
- `src/automixer/domain/shared.py`: the seam to the shared **chain** — numpy
  in, numpy out, mlx on this side of it.
- `src/automixer/domain/room.py`: the seam to the shared **decision layer** —
  wav tracks with start times become the timeline shape the library asks for,
  and the grid, ducking, de-bleeding and rider mask come back. It contains no
  DSP of its own, on purpose.
- `src/automixer/analyzer.py`: MLX-based silence detection.
- `src/automixer/cli_mix.py`: Parallelized mixing engine.
- `src/automixer/app.py`: Textual-based TUI dashboard.

### **Plugin Parameters**
You can now control your plugins directly from the TUI. In the **Plugins** tab, use the following format:
`PluginName: param1=val1, param2=val2; NextPlugin: param=val`
- Separate multiple parameters with commas.
- Separate multiple plugins with semicolons.
- The app will match the name you type against the plugin's filename.

## 💻 Optimization for Mac
This project is built from the ground up to leverage:
- **Metal Performance Shaders**: Via the `mlx` library for FFTs and convolutions.
- **Accelerate Framework**: High-efficiency math operations on Apple Silicon.
- **Parallel I/O**: Taking advantage of fast NVMe storage on modern Macs.
