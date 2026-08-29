# Signal pipeline

The order every track travels in, from import to render. Read against the
code — this file has been wrong before, and the way it was wrong is worth
knowing: it documented a de-smacker as Stage 1 of the speech chain, the CLI
exposed a sensitivity control for it, and the stage was a guaranteed no-op
that changed **0 samples** at every setting. A pipeline document that
describes a stage which never ran is worse than no document, because it makes
the missing behaviour look present.

Most of what happens below is not automixer's code. It is
`packages/speechmix`, the pipeline shared with `autoraffkat` and
`podcast-magic`, and that is deliberate: three copies of this chain drifted
apart once, and automixer was four measured fixes behind when it was merged.
Where a stage says **shared**, the numbers behind it are in
`apps/autoraffkat/SHARED-AUDIO.md` and the code is in the package.

---

## 0. Listening — before anything is processed

**Shared.** Every `type: speech` track is one person's microphone.
`domain/room.py` places each stem at its timeline offset, gives it the shape
the library asks for — a track with spans on a programme timeline — and hands
the set to `speechmix.grid.speech_grid`, which builds the **speech grid**: who
is talking, when, and how loudly, one row per microphone.

The rule is autoraffkat's, and it is one function (`grid.lane`) that both apps
call: smooth the level curve over 100 ms, read the noise floor at the 20th
percentile of that curve, and speech is what clears the floor by 12 dB. Those
numbers were measured on 77 minutes of real two-microphone material. This app
used to answer the same question with its own — a 10th-percentile floor, an
8 dB margin, and a dominance test folded into the decision — which is two
answers to one question in one package.

Dominance still decides which microphone stays *open* when two are genuinely
active. That is the ducking rule, and it belongs there: measured on the
library's own two-microphone fixture, folding it into the decision as well
changed nothing (0.4 % → 0.4 % on the other speaker's bleed), while the
measured margin took it to 0.0 %. Keeping it out also makes the "only this
speaker" masks purer, and those are what de-bleeding estimates its filter
from.

Three later stages read nothing else, and none of them existed here before the
grid did.

The grid is measured from the **raw** audio, always. A compressor lifts the
noise floor between words and flattens the difference between microphones,
and those are exactly the two things the threshold and the "loudest wins" rule
depend on.

Two things are refused rather than worked around, because both would render a
perfectly good file with everything in the wrong place: two tracks that share
a name (they would collapse into one lane) and a track at a different sample
rate from the mixer's (nothing here resamples, so every mask would land at the
wrong moment). The second is skipped per track with a message; the first is an
error.

## 1. Speech tracks — the channel strip

Each speech track is processed on its own before it reaches the bus, so what
one person's chain does cannot reach another's.

1. **Cross-bleed removal** — *shared, needs the grid*
   Two microphones in a room hear both people, so when the tracks play
   together the same voice arrives twice a few milliseconds apart. That is a
   comb filter, and it is what a summed pair sounds like when it sounds
   metallic. A gate cannot reach it: measured, infinite attenuation moved the
   ripple 6.22 → 6.01 dB, because the gaps fall on the turn-taking boundaries
   where the bleed is loudest.
   The leak is linear, so it is subtracted: an FIR path estimated over the
   passages where **only the other person** speaks — that is what the grid's
   solo masks are for — and removed everywhere, including under overlapping
   speech. Measured on real material, coherence 0.1069 → 0.0098 with own
   speech kept at r = 0.9993.
   It runs here, first, and that is not a preference: a generative plug-in
   does not preserve the linear relation between tracks, and after one no
   filter can subtract the leak. A filter that cannot be trusted is refused
   with a reason rather than applied quietly.

2. **External plug-in** — one slot
   Denoisers, restoration, mic modelling. Clean up before you amplify. It is
   flavour, not a replacement for a stage below: everything after it was
   measured, and a second limiter in front of ours would quietly undo the
   ceiling guarantee with nothing to say so.

3. **The shared speech chain** (`speechmix.chain.process`) — one call
   1. **High-pass**, 80 Hz, 4th order.
   2. **De-click**, calibrated on findings per second. Lip smacks are a few a
      minute; the threshold rises until the findings fit and corrects nothing
      if they never do.
   3. **Level rider** — *needs the grid*. A slow ride **before** the
      compressors, the stage every hand-made mix starts with. Its mask is the
      grid's, never the signal's: on two microphones half of what is loud on a
      track is the other person, and a rider driven by level dutifully lifts
      the leakage — measured, the noise floor rose 3.5 dB and the level spread
      got *worse*. Without a mask the library skips the stage rather than
      guessing.
   4. **De-esser**, 4.5 kHz, before the compressors — restoration adds several
      dB above 3 kHz and one sibilant otherwise drives a whole sentence's gain.
   5. **Three compressor stages**, each capping its own gain reduction at
      5 dB. The first is multiband with one ratio and one limit across all
      bands, so a plosive cannot pull the sibilance down with it and the tone
      cannot move with the programme. Thresholds slide with the target rather
      than being written down anywhere.
   6. **Parallel mix**, 0.4 dry / 0.6 compressed, so 40 % of every untouched
      transient survives.
   7. **Normalise** to the target, re-measured after compression and settled
      to within 0.3 LU.

4. **Microphone ducking** — *shared, needs the grid*
   Closes a microphone while its owner is silent, hidden under the other
   person's speech. Do not confuse it with the sidechain ducking on the music
   bus (§2): that one lowers a bed under the summed voices, this one closes a
   *microphone*. Both are wanted.
   It runs **after** the chain, and the split is a rule: level decisions taken
   after the chain can be automation, decisions taken before it must be baked
   in. autoraffkat writes this same curve as Final Cut volume keyframes so an
   editor can still drag it; automixer exports a finished wav and has nothing
   to write automation into, so it burns the identical curve into samples.
   Nine decibels is deliberately shallow — the leak is already ~13 dB under
   the speech, and all the benefit is in the timing.

5. **Panning**, ±10 %, and ad-spot splitting, in the bus.

## 2. Music bus

Automixer's own, and staying that way: none of it takes samples in and returns
samples out.

1. **Sum and gain-match** to a −30 LUFS bed.
2. **External plug-ins**, bus level.
3. **Spectral carving** — FFT dynamic EQ that carves the speech bus's
   frequencies out of the music.
4. **Sidechain ducking** off the summed speech.

## 3. Master

1. **Sum** speech and music.
2. **Normalise** to the target (default −16 LUFS).
3. **True-peak ceiling** — *shared*. −1.5 dBTP with 4× oversampled detection,
   centred lookahead and a one-pole release, with a static `peak_guard` behind
   it that should never fire. The old limiter worked on **sample** peaks at
   −1.0 dBFS and let the true peak out at −0.41 dBTP: the peaks that clip a
   converter and a lossy encoder fall *between* samples and cannot be seen by
   looking at them.
4. **Export**, 24-bit stereo WAV.

---

## What switches off

Every stage that needs the grid can be turned off from the CLI, and
`--minimal` turns off all of them together:
`--no-debleed`, `--no-rider`, `--no-mic-duck` (and `--mic-duck-db` for the
depth). A stage that is off is off because it was asked to be — none of them
fail into silence, and de-bleeding says why it refused when it refuses.
