import os
import sys
import argparse
import asyncio
import wave
import subprocess
from datetime import timedelta
from faster_whisper import WhisperModel
from tqdm import tqdm

# Native MLX Whisper for Apple Silicon
try:
    import mlx_whisper
except ImportError:
    mlx_whisper = None

# Diarization
try:
    from pyannote.audio import Pipeline
    import torch
except ImportError:
    Pipeline = None

# Wyoming imports
try:
    from wyoming.audio import AudioChunk, AudioStart, AudioStop
    from wyoming.client import AsyncTcpClient
    from wyoming.transcript import Transcript
except ImportError:
    pass

def format_timestamp(seconds: float, format_type: str = "ssa") -> str:
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((td.total_seconds() - total_seconds) * 100)
    
    if format_type == "ssa":
        # H:MM:SS.cc
        millis = round((td.total_seconds() - total_seconds) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{millis:02d}"
    elif format_type == "srt":
        # HH:MM:SS,mmm
        millis_srt = round((td.total_seconds() - total_seconds) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis_srt:03d}"
    return str(seconds)

def write_ssa(segments, output_path):
    header = [
        "[Script Info]",
        "Title: FCP Generated Subtitles",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    ]
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n")
        for segment in segments:
            start = format_timestamp(segment.get('start'), "ssa")
            end = format_timestamp(segment.get('end'), "ssa")
            text = segment.get('text').strip()
            speaker = segment.get('speaker', '')
            if speaker:
                f.write(f"Dialogue: 0,{start},{end},Default,{speaker},0,0,0,,{speaker}: {text}\n")
            else:
                f.write(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

def write_srt(segments, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        for i, segment in enumerate(segments, 1):
            start = format_timestamp(segment.get('start'), "srt")
            end = format_timestamp(segment.get('end'), "srt")
            text = segment.get('text').strip()
            speaker = segment.get('speaker', '')
            display_text = f"[{speaker}] {text}" if speaker else text
            f.write(f"{i}\n{start} --> {end}\n{display_text}\n\n")

def diarize(input_path, hf_token):
    if Pipeline is None:
        print("Error: pyannote.audio not installed.")
        return []
    
    print("Loading diarization pipeline from Hugging Face...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf_token
    )
    
    # Move to GPU if available
    device = torch.device("cpu")
    if torch.backends.mps.is_available():
        device = torch.device("mps")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
    
    print(f"Using device: {device}")
    pipeline.to(device)

    print("Diarizing audio (this may take a while)...")
    diarization = pipeline(input_path)
    
    speaker_segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        speaker_segments.append({
            "start": turn.start,
            "end": turn.end,
            "speaker": speaker
        })
    return speaker_segments

def assign_speakers(transcript_segments, speaker_segments):
    for t_seg in transcript_segments:
        center_time = (t_seg["start"] + t_seg["end"]) / 2
        best_speaker = "Unknown"
        for s_seg in speaker_segments:
            if s_seg["start"] <= center_time <= s_seg["end"]:
                best_speaker = s_seg["speaker"]
                break
        t_seg["speaker"] = best_speaker
    return transcript_segments

def transcribe_mlx(input_path, model_path, language=None):
    if mlx_whisper is None:
        print("Error: mlx-whisper not installed.")
        return []
    
    print(f"Transcribing with native MLX (Turbo v3) using {model_path}...")
    result = mlx_whisper.transcribe(
        input_path,
        path_or_hf_repo=model_path,
        language=language,
        verbose=False
    )
    
    all_segments = []
    for segment in result.get("segments", []):
        all_segments.append({
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"]
        })
    return all_segments

async def transcribe_wyoming(input_path, uri, language=None):
    print("Extracting audio for Wyoming...")
    temp_wav = "temp_audio.wav"
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", "16000", "-ac", "1", "-f", "wav", temp_wav
    ]
    subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    host, port = uri.replace("tcp://", "").split(":")
    client = AsyncTcpClient(host, int(port))
    segments = []
    try:
        async with client:
            with wave.open(temp_wav, "rb") as wav_file:
                await client.write_event(AudioStart(
                    rate=wav_file.getframerate(),
                    width=wav_file.getsampwidth(),
                    channels=wav_file.getnchannels()
                ).event())
                chunk_size = 1024 * 16
                while True:
                    data = wav_file.readframes(chunk_size)
                    if not data:
                        break
                    await client.write_event(AudioChunk(audio=data).event())
                await client.write_event(AudioStop().event())
            
            while True:
                event = await client.read_event()
                if event is None: break
                if Transcript.is_type(event.type):
                    transcript = Transcript.from_event(event)
                    # Wyoming doesn't give timestamps in a simple way here, simplified
                    segments.append({"start": 0, "end": 0, "text": transcript.text})
                    break
    finally:
        if os.path.exists(temp_wav): os.remove(temp_wav)
    return segments

def transcribe_local(input_path, model_name, language, device):
    print(f"Loading faster-whisper model: {model_name}...")
    if device == "auto": device = "cpu"
    compute_type = "int8" if device == "cpu" else "float16"
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments_gen, info = model.transcribe(input_path, language=language, beam_size=5)
    all_segments = []
    with tqdm(total=round(info.duration), unit="sec") as pbar:
        for segment in segments_gen:
            all_segments.append({"start": segment.start, "end": segment.end, "text": segment.text})
            pbar.update(segment.end - pbar.n)
            if pbar.n > pbar.total: pbar.n = pbar.total
            pbar.refresh()
    return all_segments

async def main():
    parser = argparse.ArgumentParser(description="Generate subtitles for FCP using Whisper")
    parser.add_argument("input", help="Path to video or audio file")
    parser.add_argument("--method", choices=["mlx", "faster", "wyoming"], default="mlx", 
                        help="Transcription method: mlx (native Apple Silicon), faster (local CPU), wyoming (server)")
    parser.add_argument("--model", default="mlx-community/whisper-large-v3-turbo", 
                        help="Model path or name")
    parser.add_argument("--language", default=None, help="Language code (e.g. fi)")
    parser.add_argument("--diarize", action="store_true", help="Perform speaker diarization")
    parser.add_argument("--hf-token", help="Hugging Face token for diarization")
    parser.add_argument("--wyoming-uri", default="tcp://127.0.0.1:10300", help="Wyoming server URI")
    
    args = parser.parse_args()
    if not os.path.exists(args.input):
        print(f"Error: File {args.input} not found.")
        sys.exit(1)

    # Transcription
    if args.method == "mlx":
        all_segments = transcribe_mlx(args.input, args.model, args.language)
    elif args.method == "wyoming":
        all_segments = await transcribe_wyoming(args.input, args.wyoming_uri, args.language)
    else:
        model_name = "large-v3-turbo" if "turbo" in args.model else "small"
        all_segments = transcribe_local(args.input, model_name, args.language, "cpu")

    if not all_segments:
        print("No transcription generated.")
        return

    # Diarization
    if args.diarize:
        if not args.hf_token:
            args.hf_token = os.environ.get("HF_TOKEN")
        
        if not args.hf_token:
            print("\nError: --hf-token or HF_TOKEN environment variable required for diarization.")
            print("Get one at https://huggingface.co/settings/tokens")
            sys.exit(1)

        speaker_segments = diarize(args.input, args.hf_token)
        all_segments = assign_speakers(all_segments, speaker_segments)
        
        # Identify unique speakers and ask for names
        unique_speakers = sorted(list(set(s["speaker"] for s in all_segments if "speaker" in s)))
        speaker_map = {}
        print(f"\nIdentified {len(unique_speakers)} speakers.")
        for spk in unique_speakers:
            # Find a few example lines for this speaker
            examples = [s["text"].strip() for s in all_segments if s.get("speaker") == spk][:3]
            example_str = " | ".join(examples)
            print(f"\nSpeaker: {spk}")
            print(f"Examples: {example_str}")
            try:
                name = input(f"Enter name for {spk} (or press Enter to keep default): ").strip()
                speaker_map[spk] = name if name else spk
            except EOFError:
                speaker_map[spk] = spk
        
        for seg in all_segments:
            seg["speaker"] = speaker_map.get(seg.get("speaker"), seg.get("speaker"))

    base_name = os.path.splitext(args.input)[0]
    ssa_path = f"{base_name}.ssa"
    srt_path = f"{base_name}.srt"
    
    print(f"\nWriting SSA subtitles to {ssa_path}...")
    write_ssa(all_segments, ssa_path)
    print(f"Writing SRT subtitles to {srt_path}...")
    write_srt(all_segments, srt_path)
    print("Done!")

def cli():
    asyncio.run(main())

if __name__ == "__main__":
    cli()
