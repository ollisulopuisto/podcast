# 🎙️ Podcast Automixer - Signal Pipeline

This document describes the exact order of processing for every audio track from import to final render.

## 1. SPEECH TRACKS (The "Channel Strip")
Each speech track (e.g., Host, Guest) is processed **individually** before being mixed. This ensures that processing on one person doesn't accidentally affect the other.

1.  **Stage 1: External Plugins (Per-Track)**
    - This is the first stage in the chain. 
    - **Best for**: Denoisers, De-essers, or Mic Modelers.
    - **Why**: You want to clean the noise before any compression or EQ brings it up.
2.  **Stage 2: High-Pass Filter (80Hz)**
    - Removes sub-bass "plosives" and desk rumble.
3.  **Stage 3: Intelligent Dynamics**
    - **Mode A (Single Band)**: 
        - **Peak Tamer**: Fast (30ms) 2.5:1 compression to catch sudden transients.
        - **Leveler**: Slow (300ms) 1.5:1 compression to smooth the body of the voice.
    - **Mode B (Multiband)**:
        - 3-band zero-phase subtraction crossover.
        - Independent auto-gain/compression for Low, Mid, and High frequencies.
4.  **Stage 4: Spatial Positioning**
    - **Panning**: Automatic subtle ±10% stereo spread for speaker separation.
    - **Ad Insertion**: The track is split and shifted to create space for an ad if a spot was selected.

---

## 2. MUSIC BUS (The "Bed")
All music tracks are summed and then processed as a single group.

1.  **Stage 1: SUM & Gain Match**
    - All music files are summed to stereo and gain-trimmed to a standard bed level (-30 LUFS).
2.  **Stage 2: External Plugins (Bus-Level)**
    - **Best for**: Bus compressors, Tape saturation, or Creative filters.
3.  **Stage 3: Spectral Carving (Dynamic PEQ)**
    - Analyzes the frequencies of the *entire Speech Bus* and carves matching frequencies out of the music in real-time using FFT.
4.  **Stage 4: Sidechain Ducking**
    - Reduces the music volume based on the total energy of the combined speech.

---

## 3. MASTER BUS (Finalization)
The final stage where the podcast is prepared for distribution.

1.  **Stage 1: Summing**
    - Combined Speech and Music signals.
2.  **Stage 2: Loudness Analysis**
    - Measures the Integrated LUFS of the whole mix.
3.  **Stage 3: Precision Makeup Gain**
    - Calculates the exact gain needed to hit the target (default -16.0 LUFS).
4.  **Stage 4: Lookahead Limiter**
    - A 5ms brickwall lookahead buffer catches any remaining peaks to prevent digital clipping.
5.  **Stage 5: Export**
    - Saves as a high-quality **24-bit stereo WAV**.
