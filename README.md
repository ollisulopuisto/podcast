# 🎙️ Podcast Automixer

A modular, high-performance podcast assembly tool optimized for **Apple Silicon (ARM Macs)**. It uses **MLX** for GPU-accelerated signal processing and a parallelized DSP pipeline to deliver a transparent, professional sound.

## 🚀 Key Features

### 1. **Phase 1: Intelligent Spotting**
- **MLX-Accelerated Analysis**: Uses the Metal GPU to perform rapid RMS energy scans of your episode.
- **Natural Pause Detection**: Automatically identifies silences longer than 0.5s (skipping the first 50% of the episode) to suggest perfect ad insertion points.

### 2. **Phase 2: Transparent Signal Chain**
- **Serial Compression**: Replaces a single "heavy" compressor with a two-stage chain:
  - **Peak Tamer (Fast)**: Catches loud transients with a 30ms window.
  - **Leveler (Slow)**: Smooths overall volume with a 300ms window for a natural, uncompressed feel.
- **Spectral Carving (Dynamic PEQ)**: Analyzes the speech spectrum in real-time and carves out those specific frequencies from the music bus using FFT spectral subtraction.
- **Delicate Stereo Panning**: Automatically applies a subtle (±10%) spatial spread to multiple speakers, improving clarity through psychoacoustic separation.
- **Sidechain Auto-Ducking**: GPU-accelerated music ducking triggered by the speech bus.

### 3. **Phase 3: Parallelized Production**
- **Multi-Core Loading**: Parallel track I/O using `ThreadPoolExecutor`.
- **Concurrent Bus Processing**: Speech and Music buses process simultaneously to saturate your CPU/GPU.
- **LUFS Normalization**: Final render is precisely normalized to **-16.0 LUFS** (ITU-R BS.1770-4) with 24-bit stereo depth.

---

## 🛠️ Usage

### **The Unified TUI (Recommended)**
The easiest way to use the automixer is via the interactive dashboard:
```bash
autotui
```
*(Or `uv run python -m src.automixer.app` if running from source)*

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

### **Utility Commands**
- **Analyze Ad Spots**: `autoanalyze <file> <output_spots>`
- **Launch TUI**: `autotui`

---

## 🏗️ Project Architecture & Signal Flow
For a detailed breakdown of exactly when processing happens, see **[PIPELINE.md](PIPELINE.md)**.

- `src/automixer/domain/`: Core DSP logic (Processors, Buses, Tracks).
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
