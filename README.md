# Podcast Automixer

A modular, MLX-accelerated podcast assembly tool for ARM Macs.

## Features
- **Phase 1: Silence Detection**: Uses MLX-accelerated RMS calculation to find potential ad insertion spots (silences).
- **Phase 2: TUI Selection**: Interactive TUI to pick the best ad spot and save it to a reusable YAML config.
- **Phase 3: Automated Mix**: Modular signal chain with speech/music buses, auto-ducking, EQ, and -16 LUFS normalization.
- **MLX Powered**: Leveraging Metal acceleration on Apple Silicon for signal processing.

## Requirements
- macOS (Apple Silicon recommended)
- `uv` for Python package management

## Workflow

### 1. Find potential ad spots
```bash
uv run python -m src.automixer.cli_analyze episode1.wav spots.txt
```
This looks at the episode (skipping the first 50%) and finds silences longer than 0.5s.

### 2. Select the spot via TUI
```bash
uv run python -m src.automixer.tui_select spots.txt show_config.yaml
```
Use the arrow keys and Enter to select the spot. It will be saved to `show_config.yaml`.

### 3. Run the final mix
```bash
uv run python -m src.automixer.cli_mix show_config.yaml
```
This performs:
- Highpass filtering and compression on the speech bus.
- Auto-ducking of background music whenever speech is detected.
- LUFS normalization to -16.0.

## Configuration (`show_config.yaml`)
You can define per-show settings that are reused for every episode.
```yaml
project: "My Awesome Show"
target_lufs: -16.0
output_path: "final_mixed.wav"
buses:
  speech:
    processors:
      - type: "highpass"
        freq: 100
      - type: "compressor"
        threshold: -18
        ratio: 4
tracks:
  - name: "Host"
    path: "episode1.wav"
    type: "speech"
  - name: "Theme"
    path: "intro.wav"
    type: "music"
```

## Modularity
The signal chain is built using a modular `Processor` pattern. You can easily add more DSP effects in `src/automixer/domain/processor.py`.
