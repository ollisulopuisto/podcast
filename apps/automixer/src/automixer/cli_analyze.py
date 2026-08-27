"""
Command-line interface for analyzing an audio file to find ad insertion spots.

This script loads an audio file, mixes it to mono if necessary, analyzes it
using SpotAnalyzer, and writes the resulting timestamps to an output text file.
"""

import os
import sys
import soundfile as sf
from automixer.analyzer import SpotAnalyzer


def main():
    """
    Main entry point for the analysis CLI.

    Parses command-line arguments to read the input audio file, runs the SpotAnalyzer
    to detect silences, and outputs the detected timestamps to the specified text file.
    """
    if len(sys.argv) < 2:
        print("Usage: python -m automixer.cli_analyze <audio_file> [output_file]")
        sys.exit(1)

    audio_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "spots.txt"

    if not os.path.exists(audio_path):
        print(f"Error: {audio_path} not found.")
        sys.exit(1)

    print(f"Analyzing {audio_path}...")

    # Load audio
    data, sr = sf.read(audio_path)

    # If stereo, mix to mono for analysis
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    analyzer = SpotAnalyzer(sr=sr)
    spots = analyzer.find_spots(data)

    print(f"Found {len(spots)} potential ad insertion spots.")

    with open(output_path, "w") as f:
        for s in spots:
            f.write(f"{s:.2f}\n")

    print(f"Spots saved to {output_path}")


if __name__ == "__main__":
    main()
