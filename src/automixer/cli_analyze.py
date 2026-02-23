import os
import sys
import soundfile as sf
import yaml
from src.automixer.analyzer import SpotAnalyzer

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m src.automixer.cli_analyze <audio_file> [output_file]")
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
            f.write(f"{s:.2f}
")
            
    print(f"Spots saved to {output_path}")

if __name__ == "__main__":
    main()
