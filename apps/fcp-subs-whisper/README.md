# FCP Subs Whisper

A high-performance subtitle generator for Final Cut Pro (FCP) powered by OpenAI's Whisper model. Optimized for Apple Silicon using MLX.

## Features

- **Apple Silicon Native**: Uses `mlx-whisper` for lightning-fast transcription using the GPU and Neural Engine.
- **Multiple Formats**: Generates both `.srt` and `.ssa` (SubStation Alpha) files.
- **FCP Optimized**: SRT files are ready to be imported directly into Final Cut Pro as captions.
- **Multiple Engines**:
  - `mlx`: Native Apple Silicon (Fastest, recommended).
  - `faster`: CPU-optimized `faster-whisper`.
  - `wyoming`: Connects to an existing Wyoming Whisper server.

## Installation

Ensure you have `uv` and `ffmpeg` installed:

```bash
brew install uv ffmpeg
```

Clone the repository and you are ready to go. `uv` will handle the Python environment and dependencies automatically.

## Usage

### Recommended (Native Apple Silicon)
This uses the MLX framework to leverage your Mac's hardware and provides precise timestamps for subtitles.

```bash
uv run python main.py "video.mp4" --method mlx
```

### CPU Optimized
Uses `faster-whisper` for efficient CPU transcription.

```bash
uv run python main.py "video.mp4" --method faster
```

### Import to Final Cut Pro

1. In FCP, go to `File` > `Import` > `Captions...`.
2. Select the generated `.srt` file.
3. The subtitles will appear on a dedicated caption lane in your timeline.

## Requirements

- macOS (for MLX support)
- FFmpeg
- `uv` for dependency management

## License

MIT
