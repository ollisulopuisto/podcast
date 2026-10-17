# Shared speech-mixing pipeline — brief for sibling projects

Context for whoever is reading this in **automixer** or in the new
session-based project: `autoraffkat` (FCPXML in, FCPXML out, picture cuts to
whoever is talking) has spent a long session measuring and correcting its
audio chain. Three projects now want the same chain. This document is the
proposal for how to share it, and — more importantly — the findings that must
travel with it.

Everything below is measured on real 77-minute two-microphone podcast
material. The numbers are the argument; please don't re-derive them.

---

> **Status, later.** Everything §1 proposes is built. The three projects are
> one uv workspace (§2), `packages/speechmix` is the chain, and the `Track`
> with spans that §1 describes is `speechmix/timeline.py` — written from this
> section, down to the formula. `mix.py` no longer leaks
> `item.placements` into the library: `track_of` converts once, and every host
> downstream of that point runs the same code. automixer builds the same
> `Track` from a wav file and a start time, which is what finally gave it
> de-bleeding, ducking and the level rider (§3.2, §3.7, §3.8). The findings
> below have not changed and still travel with the code.

## 1. Where the seam already is

`chain.py` **is already a library.** It takes `(audio ndarray, rate, settings,
gain_db, speech_flag, target_lufs, plugin, speech_mask)` and returns an array.
It has never heard of FCPXML, timelines, or files. Same for `debleed.py` and
`worker.py` (the plug-in host child process).

The impure module is `mix.py`. It knows about job dicts carrying
`item.placements`, sibling output paths, freshness stamps, and grid→file time
conversion. That is where the host format leaks in, and that is the only line
that needs drawing.

### The abstraction is "a track with a placement on a programme timeline"

Not "an FCPXML asset". Everything `mix.py` needs from the host is:

```
Track:
    path: str
    speaker: str            # who this microphone belongs to
    mono: bool              # always True for microphones, see §3.6
    bit_depth: int
    spans: [(programme_start, programme_end, file_offset)]
```

An FCPXML asset is that. An automixer session track is that. Whatever your
session format is, it is that. The conversion between programme time and file
time is linear inside each span, and that single formula is all the timeline
knowledge the pipeline needs:

```
file_time = span.file_offset + (programme_time - span.programme_start)
```

### The second seam: compute gain decisions, don't apply them

This one only became visible late and it is the more valuable of the two.

`duck_envelopes(grid, settings, program_start)` returns
`{speaker: [(time, dB), ...]}`. autoraffkat writes those into the FCPXML as
Final Cut `<adjust-volume>` keyframes, so the editor can still change them.
automixer has nothing downstream to write automation into, so it would bake
the same curve into samples. **Same computation, different emission.**

So the library should return gain *decisions* and let the host decide whether
they become samples or automation. The general rule that fell out of it:

> Level decisions that come **after** the chain can be automation.
> Level decisions that come **before** it must be baked in.

Ducking is after → it can be automation. A level rider is before → it cannot.

---

## 2. Packaging: uv workspace monorepo, not a separate repo. Not yet.

The pipeline changed ten times in one day, and every change was driven by a
measurement that invalidated the previous behaviour. With a separate
versioned package, each of those is a release plus three consumer bumps, and
consumers drift in between. **That drift is the problem we are trying to
solve**: automixer is currently behind on the de-clicker fix, on de-bleeding,
on a compressor stage that never fired, and on the programme ceiling. A
separate repo would formalise the drift rather than remove it.

```
koodi/podcast/
  packages/speechmix/     chain, debleed, envelope analysis, programme
                          ceiling, duck/rider envelope computation,
                          and the measurement tests
  apps/autoraffkat/       FCPXML reader/writer, cutting decisions, web UI
  apps/automixer/         session reader, render
  apps/<new>/             its own session reader
```

Each app keeps: its reader, its writer, its UI, and any editing logic.
The library keeps: everything that turns samples into other samples, plus the
tests that prove it.

**The measurement tests are the real asset.** They encode findings that each
cost hours to discover, and they must run against the library in one place,
atomically, on every change. If you take nothing else from this document,
take the tests.

Split into a real PyPI package when the pipeline stops moving, or when a
fourth consumer appears outside these three. Splitting later is cheap;
un-splitting is not.

### One thing that must move with the chain

`FINGERPRINT_FIELDS` and `FINGERPRINT_VERSION`. They describe *what the chain
does*, so they belong to the chain. But *where the stamp file lives* is
per-app. Get this backwards and every app invents its own idea of "up to
date", which is the bug class this project has paid for repeatedly.

---

## 3. Findings that must travel with the code

Each of these was a silent failure: valid output, clean import, no error, and
wrong. None was caught by a crash. All were caught by measuring the output.

### 3.1 The de-clicker's threshold is a rate, not a multiplier

A de-clicker calibrated by "reference × N" corrected **2 % of all samples,
550–640 corrections per second**, altering the signal −10 dB relative to
itself. It passed every test, because the tests asked whether a planted click
was removed and never how many were found.

Calibrate on how often the artefact actually occurs — lip smacks are a few a
minute — and keep a ceiling that raises the threshold until the findings fit,
correcting nothing if they never do.

### 3.2 Bleed is linear: subtract it, do not gate it

The same voice in two microphones a few milliseconds apart is a comb filter.
That is what a summed pair sounds like when it sounds metallic.

Ducking cannot reach it. Measured: the masks fired correctly and closed the
microphone on 64 % of the frames where only the other person spoke, and
**infinite** attenuation still moved the ripple only 6.22 dB → 6.01, because
the gaps fall on turn-taking boundaries where the bleed is loudest — and
overlapping speech needs both microphones open anyway.

`debleed.py` estimates the leakage path as a least-squares FIR (8192 taps,
solved from the Toeplitz structure) over the passages where only the source
speaks, and subtracts it everywhere. Coherence 0.1069 → 0.0098; the target's
own speech preserved at r = 0.9993.

The filter has to reach past the room, not just the direct path. 2048 taps
at 48 kHz is 43 ms; the reflections are longer. Real two-mic material (68.7
min, microphones about 1.8 m apart, direct path +5.5 ms): 2048 taps removed
3.92 dB, 8192 (171 ms) 5.14 dB, own speech still r = 0.9999; 16384 added only
0.14 dB. Cost: 33.1 → 33.5 s and 10.6 → 11.3 GB. By ear, 8192 was better on
both speakers, turn transitions were clean, and the summed de-bled pair
showed no new artefacts. Ducking on top of it (automix) pumped audibly and
was rejected.

It must run on the **raw** audio, *before* any generative restoration
plug-in: such a plug-in does not preserve the linear relation between tracks,
and after it no filter can remove the bleed.

And it measures its own output: a filter that eats the target's own speech is
refused with a stated reason, because that mistake is only audible after the
export.

### 3.3 Compression comes in small amounts several times — and check every stage fires

Three bounded stages, each capped at 5 dB of gain reduction. The first is
multiband so a plosive cannot pull the sibilance down with it, with one ratio
and one limit across all bands (differing amounts per band move the tone with
the programme).

**One of the three never fired.** Its threshold was written
`leveler_threshold + 4.0` — four decibels *above* the second stage — and it
runs after the second, which has already pulled everything below its own
threshold. Measured on three minutes of real speech, that stage's gain moved
**0.00 dB at every target from −14 to −18 LUFS**. The chain promised three
stages and ran two.

Write a test that runs each stage in sequence and fails on any that leaves
the signal untouched. Note what the test fixture had to learn: thresholds are
absolute and applied *after* normalisation, so a signal whose every burst is
equally loud sits entirely below all of them and the test passes while
measuring nothing. The bursts must vary, because in speech it is the loud
passages that clear the threshold.

### 3.4 The peak attack must be longer than a pitch period

Two milliseconds modulates the waveform of a 110 Hz voice instead of its
level, which is harmonic distortion by definition. Measured on a sine at
110 Hz / −6 dBFS: 2 ms → THD −30.9 dB, 10 ms → −32.9 dB, 40 ms → −36.1 dB.
15 ms is longer than a pitch period for every speaking voice.

De-essing goes **before** the compressors, because a restoration plug-in adds
several dB above 3 kHz (measured +4…+5.7 dB, 3–20 kHz with dxRevive) and one
sibilant otherwise drives the gain of a whole sentence.

### 3.5 The ceiling is the programme's, not the stem's

This is the one most likely to be wrong in your project right now.

Each stem limited to −1.5 dBTP is not enough, because what plays is the
**sum**. Two stems whose peaks are both pressed to the ceiling exceed full
scale whenever those peaks coincide — in theory +4.5 dB, and measured on a
real episode **+4.51 dBFS, 49 971 samples over full scale in 4072 bursts,
200 a minute**, median 0.23 ms. That is audible as intermittent crackle on
loud syllables, and it is what a host application draws in red.

The fix is **not** harder per-stem limiting — then every stem pays six
decibels of crest for what some *other* file happens to do. Compute the
limiter's gain curve from the **summed** stems and multiply that identical
curve into each one. The sum then obeys the ceiling and the balance between
speakers cannot move, because every stem gets the same number. Measured:
+4.51 → −1.51 dBFS at a cost of 0.50 LU.

The pass is idempotent by construction — the curve is `min(1, ceiling/peak)`,
so a sum already at the ceiling gets 1 everywhere — which makes it safe to
run on every processing round.

Summing files sample-by-sample is only correct when the stems line up on the
timeline. Make that a checked fact, not an assumption, and leave mismatched
stems alone rather than summing them at the wrong offset.

Related: the ceiling must be a look-ahead limiter, never a static
attenuation. A static cut scales the whole file by what its single loudest
sample demands; measured, that turned −14.00 LUFS into −25.74, and it makes
the balance between speakers depend on whose loudest transient was loudest,
which is to say random.

Also: `pedalboard.Limiter` applies makeup gain — it lifted −20 LUFS to −15.8
and peaks to zero. Use a static attenuation that never raises, or your own
look-ahead limiter.

### 3.6 The loudness target is the programme's, not one stem's

Two microphones each normalised to −14 LUFS sum above it — measured −12.2,
because the speakers overlap and the microphones hear each other. Measure the
sum of the raw microphones over a bounded window and take the difference off
every file, and put the trim into the **target**, never into the gain: the
chain normalises to the target as its last act, so a trim added to the gain
is removed again exactly (measured, stems landed on −14.1 instead of −15.8
and the reading looked correct).

Applying −14 to a mono speech stem directly leaves about 14 dB of crest and
sounds crushed; the same figure as a programme target leaves 17.5.

**A microphone is always mono out, even from a stereo source.** Two channels
break the arithmetic in three places silently: de-bleeding reads only the
first channel, the programme ceiling sums stems of differing channel counts
by broadcasting them, and panning is a mono-source idea.

### 3.7 The level rider goes first, and it cannot work from the signal alone

A slow level ride before the compressors is the stage every hand-made mix
starts with. It removes the speaker's *own* variation so the compressor only
catches what is left, instead of doing the rider's job badly — fast and
level-dependent instead of slow and even.

Two things went the wrong way before it worked:

**Deciding "speech" from the level is worse than not riding at all.** On a
two-microphone recording, half of what is loud on a track is the other
person. Measured: the level heuristic called 74 % of one track's blocks
speech when 53 % were its owner's, agreeing only 38 % of the time. The rider
dutifully lifted the leakage — noise floor **up 3.5 dB**, level spread
*worse* at 2.88 → 3.37 dB. Take the mask from the speech grid (which is
measured on raw audio), and with no mask, return the audio untouched rather
than guessing.

**The gain must return to unity outside its own speaker's speech, not hold.**
Holding is what a one-microphone rider does and it is right there; here the
pause *is the other person talking*, so a held boost lands straight on their
leakage. Measured, separation between own speech and leakage fell
19.1 → 14.8 dB. Returning to zero keeps it at 18.7.

What it is worth, measured on ten minutes of real speech: own-speech level
spread 6.72 → 6.44 dB and 6.46 → 5.67 dB, separation and noise floor
unchanged. Modest, because real speech variation is mostly sentence-scale
emphasis, which the rider deliberately leaves alone.

**Honest note on a tempting premise:** the compressor does *not* cost
separation either (19.1 → 19.0 dB). So a rider is not the answer to leakage.
De-bleeding is.

### 3.8 Ducking, and what it does and does not do

Independent per-microphone normalisation lifts bleed: two microphones
normalised to the same LUFS get different gains — measured +25.6 dB and
+22.5 dB — and the 3.1 dB difference lands on the quieter microphone's bleed
of the louder speaker.

Ducking must never fail quietly. It depends on the analysis, and pressing the
button before the analysis finished left the masks empty with nothing said:
the setting read −9 dB and the output had none. "The setting is on and no
microphone matched a mask" is an **error**, not a silence.

Measure ducking on the **raw** files. A compressor raises the noise floor
between words and flattens the difference between microphones, which are
exactly the two things the ducking decision depends on. Measure it on
processed audio and the masks fire in the wrong places — and it still looks
fine until someone listens.

Worth knowing what ducking does to demarcation, measured on real material
(gap between own speech and own non-speech):

| track | raw | after the chain | + ducking |
|---|---|---|---|
| clean-ish mic | 17.8 dB | 24.2 dB | 25.5 dB |
| leaky mic | 13.4 dB | 13.3 dB | 15.0 dB |

Note the chain does **not** erode the gap: the compressors are downward-only
with no makeup gain, and normalisation is broadband so ratios survive. The
restoration plug-in actually improves it. What limits the leaky track is
bleed, not compression — its non-speech sits 13 dB down because it contains
the other person's voice, not noise.

### 3.9 The plug-in slot is flavour, not a replacement mechanism

One slot, it runs first, and it never stands in for a stage of the chain. The
reason it exists at all is that a speech-restoration model is the one thing
we have no opinion about and cannot ship; everything after it was measured,
and those numbers are the tool. Letting a second plug-in in would quietly
undo them — someone loads a limiter in front of ours and the ceiling
guarantee stops being true with nothing to say so.

Practical constraints, both measured:

- `plugin.process(..., reset=False)` **shortens** the result by the plug-in's
  latency (4641 samples with dxRevive). Always `reset=True`, and never feed
  one instance a file in chunks.
- pedalboard loads a VST3 on the **main thread only**; it processes from any
  thread. The error text talks about processing and hides that the constraint
  is on loading, so a lazy per-thread load looks reasonable and fails every
  time. Build every instance up front.
- Host the plug-in in a child process. It is 97 % of the run and uses **one**
  core (measured 0.98 cores, 7.25× realtime), so the only way to reach the
  other cores is several instances at once. Measured on a 20-minute file:
  168.4 s → 68.3 s with the file cut into pieces, each its own full
  `reset=True` run with a five-second margin processed and thrown away. It is
  not free — the pieces do not see each other's context — so the difference
  from the whole-file result is 25.7 dB below the signal in speech and
  −84 dBFS in the quiet parts, and the piece count belongs in the
  fingerprint.
- Not everything that changes the result is an automatable parameter.
  dxRevive publishes four, and the **model selector is not one of them** — it
  lives in the plug-in's own state, reachable only through its own interface.
  Save the opaque state blob with the project and put it in the fingerprint.

### 3.10 A hand-made Live chain as reference: the dynamics already agree, the tone does not

Measured 2026-09-22 against the Ableton Live chain used by hand on the same
podcast. Material: one 87-second speech excerpt (`Valinta.wav`, 48 kHz mono,
−26.2 LUFS counted once as mono; Hindenburg reads it as about −23 because it
counts mono as dual-mono). Everything measured with the repo's own functions:
`chain.loudness`, `chain.lag_samples`, `chain.peak_to_short_term`.

**Method: a staircase, not one device at a time.** Renders from the Live
chain with the devices switched off from the end backwards, so the
difference between neighbouring steps is one device's contribution on the
input it really sees. Devices in isolation would see a different level, and
compressor thresholds are absolute decibels.

Two traps in the method, both of which produced a confident wrong answer in
the first round of renders:

- **Live's export Normalize** scales every render to 0 dBFS sample peak. It
  erases every level difference between steps and makes a compressor look
  like it *raised* crest by 2.1 dB. Render with Normalize off.
- **The bus was in every render but not in the dry file.** The track was
  soloed and exported through its group bus, so the first step (said to be
  De-reverb alone) carried the whole bus chain too: −6.8 dB of crest and
  +5.8 dB at 5–10 kHz were attributed to De-reverb and belonged to the bus.
  Make step 0 — everything off — part of the staircase and check it against
  the dry file. Here it matched `Valinta.wav` at exactly −2.000 dB (the two
  −1 dB faders) with the residual at −97 dB.

Lag was 0 samples at every step, measured per file: Live's delay
compensation changes when a device is switched off, so one check is not
enough.

The Live chain, track `olli` then group bus `talk`:

| step | device, settings | LUFS | TP dB | crest dB | PSR LU |
|---|---|---|---|---|---|
| 0 | everything off | −28.18 | −3.95 | 25.37 | 20.06 |
| 1 | RX 9 De-reverb: reduction 8, profile 6/6/6/3.3, tail 1.0 s, smoothing 9, enhance dry | −26.37 | −2.08 | 25.46 | 20.19 |
| 2 | RX 9 Breath Control: gain −10.4 dB, sensitivity 40 | −26.37 | −2.08 | 25.46 | 20.19 |
| 3 | Vocal Rider mono: target −21 dB, range 0…+3 dB | −26.01 | −1.46 | 25.66 | 20.77 |
| 4 | Live Compressor: RMS, −25.5 dB, 2:1, 1 ms / 30 ms auto, knee 6, SC HPF 80 Hz | −29.27 | −6.76 | 23.42 | 20.60 |
| 5 | EQ Eight: low cut 100 Hz, Q 0.71 | −29.35 | −5.20 | 25.09 | 22.22 |
| 6 | dxRevive Studio 2, mix 22.5 % | −29.93 | −5.55 | 25.31 | 22.41 |
| 7 | bus: Neutron 3 (EQ, two RMS 2:1 compressors at −24.5 / −21.3 dB, 20/100 ms, limiter −2.0, out +3.8 dB, width 0) | −26.48 | −3.01 | 24.38 | 21.64 |
| 8 | bus: dxRevive Studio 2, mix 9.75 % | −26.74 | −3.28 | 24.32 | 21.57 |

Renders include the −1 dB track and −1 dB bus faders; devices see the level
before them. LUFS counted as mono.

What each device does, loudness-matched third-octave difference:

- **De-reverb:** +1.8 dB of level, nothing else — spectrum and crest within
  ±0.1 dB on this material.
- **Breath Control:** nothing measurable.
- **Vocal Rider:** +0.4 LU; the 0…+3 range keeps it small.
- **Compressor:** −2.2 dB crest. It sees −24.0 LUFS, so its threshold sits
  1.5 dB *below* integrated loudness, where ours sit +2 dB (leveler) and
  +8 dB (peak) above `THRESHOLD_REFERENCE_LUFS`. Lower threshold, but a
  30 ms release on an RMS detector, and the net work is about the same.
- **EQ Eight:** −12 dB at 50 Hz, −27 dB at 20 Hz.
- **dxRevive at 22.5 %:** −3.6 dB below 60 Hz, −2.1 dB at 2 kHz, −2.9 dB at
  12.7 kHz on the long-term spectrum. The long-term spectrum hides most of
  it: frame by frame its bands move 4.1 dB (90th percentile) in both
  directions. The +4…+5.7 dB lift at 3–20 kHz measured in our chain was at
  100 % mix; here there is none.
- **Neutron:** crest only −0.9 dB, the limiter at its ceiling. The EQ is the
  part that shows: +1.6…2 dB at 250 Hz, −2.2 dB at 400 Hz, +3 dB at
  5–12 kHz. **The brightness of the reference comes from here.**

`chain.process` on the same file, no plug-in, declick on, compared with
step 8:

- **Dynamics agree.** At Live's level (target −26.74) our chain gives crest
  24.5 dB / PSR 20.6 LU against Live's 24.3 / 21.6. At −19.9 ours falls to
  19.4 / 16.6 — that is the limiter meeting a fixed −1.5 dBTP ceiling, not
  the compressors. Nothing to port in the compressor thresholds.
- **Tone does not** (ours minus Live): +4…+7 dB at 30–60 Hz (80 Hz high-pass
  against Live's steeper 100 Hz), −2…−3 dB at 160–250 Hz, +1.7 dB at 400 Hz,
  −3.5…−4.6 dB at 3–10 kHz. Everything above 60 Hz of that is the bus EQ.

**Result: the compressors stay as they are; a tone stage was added** at
about half the bus EQ's amounts, because that curve is a house sound tuned
by ear for these speakers and the chain runs blind on everyone
(`TONE_*` in `chain.py`):

- 250 Hz +1.5 dB (Q 1) and 400 Hz −2 dB (Q 1.8) in the cleanup stage with
  the high-pass, speech only, so the compressors see the shaped signal.
- A 3 kHz high shelf +1.5 dB **after** the dynamics. Placement measured: our
  de-esser takes 1.8 dB off 5–10 kHz of real speech, and of a +1.5 dB shelf
  placed before it 0.9 dB survived the chain; placed after, 1.41.

Same comparison after the change (ours minus Live, at Live's level):
250 Hz −2.8 → −1.7 dB, 400 Hz +1.7 → +0.7 dB, 5–10 kHz −4.3…−4.6 →
−2.7…−3.1 dB. No sign flipped in the shaped bands; above 12.7 kHz ours is
now +2.2 dB, where Live's bus EQ rolls off from 14 kHz. Crest 24.5 → 24.6 dB,
PSR 20.6 → 20.8 LU: the dynamics did not move.
Listening A/B on the same excerpt, loudness-matched: with the tone stage
preferred over without, and over the Live render itself (2026-09-22) —
so the +2.2 dB above 12.7 kHz stays; no roll-off added to match Live.

**What the same listening test then found about the limiter.** Rendered at
the production stem target (−15.8 LUFS, from a −14 programme target), the
chain sounded distorted. The peaks entering the limiter are +8.0 dBFS, so it
was doing −9.6 dB and taking crest to 15.4 dB. The compressors cannot reach
those peaks: above 0 dBFS there were 1005 events, median 0.15 ms, 0.19 % of
samples, and the 40 % dry path preserves them by design. Loudness-matched
A/B: crest 15.4 dB bad, 18.5 and 19.4 dB good. Smoothing the limiter's
attack, lowering thresholds 4 dB, raising per-stage reduction to 8 dB,
a 0.85 parallel mix and an oversampled soft clipper (limiter work −9.6 →
−1.5 dB at the same loudness) all failed the ear; giving up level won.
`LIMITER_BUDGET_DB` is therefore **6.0 and on by default**, where it had been
0.0 — written, and switched off. The file lands 3 dB below target and says so
(`reached_target`).

**The budget missed a case, so the guard now reads crest.** On the same
episode one speaker's stem came out at crest 14.9 dB with the budget reading
0.00 — the limiter did −5.54 dB, but in short bursts that the 0.1-percentile
measure does not count. Level buys crest about 1:1 (−15.8 → −17.8 → −19.8
LUFS gave 14.9 → 16.9 → 18.9 dB). `PSR_GUARD_LU = 15.0`: when peak-to-short-
term loudness after the limiter falls below it, the chain backs the gain off
*before* the limiter until it holds. PSR does not move with level, so the
back-off cannot happen after. The guard only recovers what the limiter took
— its limit is the lower of 15 LU and the unlimited signal's own PSR; without
that it lowered sine bursts by 14 dB and fixed nothing. The back-off goes
into `backed_off_db`, so `shared_backoff` keeps the speakers' balance.

Ep 55 stems: one −16.02 LUFS/crest 14.91 → −19.79/18.86 (back-off −5.36),
the other −16.02/19.52 → −17.18/20.72 (−1.72). Summed programme,
loudness-matched A/B (2026-09-22): without guard −15.48 LUFS/crest 14.28/PSR
11.02; guard −18.29/17.23/13.98; guard with shared back-off −19.39/18.29/
14.84 — **the last preferred**, 5.4 dB under the −14 target. Crest was
worth more than loudness again.

The delivery stage buys the level back on the sum, where limiting only acts
where peaks coincide. It had been written and left off; it now **follows
`target_lufs`** (`mix.delivery_lufs`), so choosing YouTube or streaming in
the interface is what the programme lands on. Same minute at −16: guard
−19.39 LUFS/crest 18.29 → delivered −15.75/14.05, cost 1.3 LU. By ear the
delivered versions beat the undelivered ones, and dxRevive 25 was preferred
on the noise the lift brings up.

−14 needed a **peak stage** in front of the shared limiter
(`chain.peak_stage_gain`, `PEAK_STAGE_MS = 20`): a future-minimum over
20 ms, a release capped at 333 dB/s, then a 20 ms average, all in dB. The
gain ramps across at least a pitch period instead of stepping — steepest
change 387 dB/s against the limiter's 76 000 on the same sum. At −14 the
crest is 12.3 dB either way, because level and ceiling fix it; what
changes is how the reduction is made. Limiter alone: −9.2 dB and
distorted. Peak stage: up to −8.6 dB over 29 % of the time, −0.5 dB left
for the limiter, and it "sounds surprisingly good" (2026-09-22, 10 ms also
tried, 20 chosen). Delivery cost at −14 is 2.9 LU — just inside the 3 LU
budget, so a harder episode will land a little short and say so.

automixer masters through the same code: `programme.master` is the
in-memory form of the file-streaming `program_deliver`, and its speech bus
applies `shared_backoff`. It had a static lift into the plain limiter —
the combination that distorted.

The high-pass stays at 80 Hz. Ours is +4…+7 dB above Live below 60 Hz,
where Live cuts at 100 Hz and steeper, but that is rumble and not speech:
decided by ear, not worth a stage.

**The plug-in slot, listened to at the same loudness.** dxRevive Studio 2 at
25 % beat 50 %: at 50 % it lifts above 16 kHz by +4…+7 dB and takes 0.3–0.6 dB
of crest. Its position made little audible difference, which the numbers
support — first against last is the smallest difference measured here (the
null between them sits 19.1 LU below the signal, against 15.6 LU for 25 % vs
50 %). It stays first in the chain, where it belongs for a different reason:
de-bleeding needs the linear relation between microphones, and nothing can
recover it afterwards (§3.2). Running it last also bypasses the limiter — the
render measured +0.43 and +0.99 dBTP against a −1.5 ceiling.

Still open:
- De-reverb and Breath Control have no counterpart here. On this material
  they change neither tone nor dynamics, so the gap is smaller than assumed —
  one excerpt, one room.

### 3.11 dxRevive's Mix is a gain-preserving crossfade with a steep taper, and it does not repeat itself exactly

Measured 2026-10-17 with `scripts/ab/audition_measure.py` on the owner's Mac.
Material: one 10-second window at 600–610 s of a single unprocessed
microphone track (`recording-38`, s13e04, 2026-10-15), one speaker, speech
throughout, 8 s of speech before the window. Plug-in: Accentize-dxRevive
(VST3), model **Studio 2** (state saved with `speechmix.editor`). Everything
measured with the repo's own functions: `chain.apply_plugin` (full
`reset=True` run per render), `chain.lag_samples`, `chain.apply_parameters`.
One window, one speaker: the numbers are a first measurement, not a
calibration.

**It does not repeat itself exactly.** Two identical renders (same setting,
same window, same instance) differ by **−37.9 to −38.3 dB** (four repeats over two
runs). Every other residual below is read against that floor, and nothing
smaller than about −35 dB can be told from run-to-run variation. The first
run of the script lacked this control, called a −13 dB residual "not linear"
and, on the preroll table, "never settled"; with no control those numbers
could have been noise, and only the repeat showed they were not. A script
that compares two renders of a generative plug-in needs the repeat in the
same output.

**Why it does not repeat: the output is random, not stateful** (`scripts/ab/reset_check.py`,
2026-10-17, same window, Studio 2, Mix 100 %, preroll 0, three instances). Every
comparison lands on the same number to 0.2 dB:

| comparison | difference |
|---|---|
| three fresh instances, each rendering once (pairs 1–2, 1–3, 2–3) | −38.2, −38.2, −38.3 dB |
| the same instance, first vs second, second vs third, third vs fourth use | −38.2, −38.3, −38.4 dB |
| an instance after it processed other audio, vs its own first render | −38.4 dB |
| the same, after an explicit `reset()` | −38.2 dB |

If `reset=True` left anything behind, fresh instances would agree far better
than reused ones; they do not. The test is run at preroll 0 because a leftover
shows at the start of a call and a long preroll cuts exactly that away (the
earlier 8 s measurements could not have seen a short one). So **`reset=True`
works, nothing is carried between calls, and each render has its own noise**:
with two independent renders differing by −38.2 dB, one render's noise is about
−41 dB relative to the signal (1.3 % in amplitude, 0.9 % per render). The level
is the same for fresh and reused instances, so it is injected at a steady
level, not a chaotic effect of history.

Consequences: (1) a null deeper than about −38 dB between two dxRevive renders
cannot be reached by any setting, so the measurement scripts report the repeat
next to every residual; (2) a render is **not reproducible bit for bit**, so a
cache keyed on settings returns a different realisation than a fresh run would
(inaudible, but "same settings" does not mean "same samples"); (3) the Mix
slider built from one 100 % render (below) is **more consistent** than separate
renders at each setting: moving it reuses one realisation of the noise, where
separate renders would add −38 dB of run-to-run difference on top of the real
difference between settings.

**The other model is the same kind of noise at a higher level.** The model is
chosen in the window and lives in the saved state (`raw_state`, 524–539 bytes
base64-decoded). Opened with `state=`, `tila-studio2.b64` shows **Studio 2**,
Mix 50.0 %, and `tila-studio.b64` shows **Studio**, Mix 50.0 % (screenshots,
2026-10-18). When the second state was saved the window had shown Studio 2
again after the pick, so the display did not follow the choice, but the state
did: **a saved state restores the model**, whatever the window showed while
saving. The two states differ in 112 bytes and in length (524 against 539);
Studio at Mix 25 % (`tila-studio1.b64`) differs from Studio at 50 % in two
bytes (offsets 200–201), probably the stored Mix. Rendered through
`scripts/ab/state_compare.py` (Mix fixed to 100 %) Studio differs from Studio 2
by −8.3 dB, 17 dB above the repeat noise.

`reset_check.py` on Studio: fresh instances −25.5, −25.5, −25.3 dB; one
instance reused −25.7, −25.4, −25.7 dB; after other audio −25.4 dB; after
`reset()` −25.6 dB. Every comparison again agrees to 0.4 dB: random and not
stateful, and **13 dB noisier than Studio 2** (about −28 dB per render against
−41 dB). The Mix law table above is **Studio 2's**. **Studio's law is the same
within the rounding of the weights**, from two points (`audition_measure.py
--state tila-studio.b64 --values 25,50`): 25 % dry 0.51 / wet 0.49, 50 % dry
0.21 / wet 0.79 (Studio 2: 0.50/0.50 and 0.20/0.80; `(1 − m)^2.37` gives 0.51
and 0.19), fit residuals −25.7 and −25.0 dB against a repeat noise of −25.6 dB.
So the law looks like a property of the plug-in's Mix control and not of the
model; two points, not ten. The delay per render differs: dry 0, 25 % −2, 50 %
−3, 100 % −3 samples (Studio 2: 0 everywhere). Whether the wet path is really 3
samples early or the envelope correlation of a generative output is off by that
much is not settled; at this noise the blend cannot tell, and a 3-sample
misalignment would matter at 25–50 % (a comb notch near 8 kHz at 48 kHz) if it
is real.

**Mix is not (1−m)·dry + m·wet.** The residual against that blend is −15.0,
−13.4 and −16.9 dB at 25, 50 and 75 %, i.e. 21–25 dB above the repeat noise.
Fitting `render = a·raw + b·render(100 %)` per level (`fit_blend`) takes it
down to the repeat noise (−43.9, −39.8, −38.3 dB), so **a two-component blend
explains every level**, with weights:

| Mix | dry `a` | wet `b` | residual after fit |
|---|---|---|---|
| 10 % | 0.77 | 0.23 | −51.1 dB |
| 25 % | 0.50 | 0.50 | −43.9 dB |
| 40 % | 0.30 | 0.70 | −40.8 dB |
| 50 % | 0.20 | 0.80 | −39.8 dB |
| 60 % | 0.12 | 0.88 | −39.3 dB |
| 75 % | 0.04 | 0.96 | −38.3 dB |
| 90 % | 0.01 | 0.99 | −38.2 dB |

(25, 50 and 75 % from one run, 10 and 40 % and 60 and 90 % from two more, at
most four plug-in instances at once; the repeat noise was −38.3, −38.1 and
−37.9 dB in the three, and every fit is at or below it.) `a + b = 1.00` at
every level, so the blend is gain-preserving, and the dry weight follows
**`a(m) = (1 − m)^2.37`** (least squares over the seven points: rms error
0.005, largest 0.0095 at 40 %). 0.005 is the rounding of the weights as the
script prints them, so the curve is as good as the measurement; a
two-parameter form `(1 − m)^1.87 · (1 − 0.56 m)` brings the largest error to
0.005, not needed. The same law in dB: the dry path is −2.3 dB at 10 %, −6
dB at 25 %, −10.5 at 40 %, −14 at 50 %, −18.4 at 60 %, −28 at 75 % and −40 at
90 %. So the dial is a wet-fraction control with a steep taper: **50 % is
already 80 % wet and the dry path is 14 dB down.** That also reads the
earlier listening result (§3.10, 25 % preferred over 50 %) in a different
light: 25 % is an even 50/50 blend, 50 % is 80/20 wet.

**What it allows.** A continuous Mix slider from **one** 100 % render plus
the raw: `out(m) = a(m)·raw + (1 − a(m))·render(100 %)`, with
`a(m) = (1 − m)^2.37`. The error of the curve against the measured weights
is at most 0.0095 in a weight, which is about −40 dB of the difference
between the raw and the 100 % render: at or below the plug-in's own repeat
noise. Not yet shown: the other model (Studio), a second window or speaker,
other plug-in versions, input gain other than the default.

**A second window gives the same law.** Studio 2, window at 630–640 s of the
same recording (same speaker, 30 s from the first), `--values 25,50`: 25 % dry
0.50 / wet 0.50 and 50 % dry 0.20 / wet 0.80, the first window's weights to the
rounding. So the law does not depend on the audio, as far as two windows of
one speaker show. The fit is worse here, though: residual after fit −28.4 dB
at 25 % and −34.4 dB at 50 % against a repeat noise of −36.9 dB (the first
window reached the noise at every level), and the render delays were −1 for
25, 50 and 100 % where the first window gave 0 for all. The pattern (a larger
leftover at 25 %, where the dry and wet weights are equal, than at 50 %) is
what a one-sample offset between the plug-in's own dry and wet paths in this
window would give; a delay that changes with the audio is odd for a plug-in
and is more likely the estimate itself (an envelope correlation on generative
output, resolved to one sample) than a real delay. Not settled. Practical
reading: the slider reconstructed by the law is within about −28 dB of the
plug-in's own output in this window (3.8 % in amplitude), 8 dB above the plug-in's
own run-to-run difference; the weights are right, and the timing of the wet render
against the raw may need a per-window alignment to reach the noise floor.

**Delay.** All five renders (0, 25, 50, 75, 100 %) come back with **0 samples**
of delay against the input, measured per render at sample resolution. The
dry and wet paths are aligned; the −15 dB residual was the Mix law and not
a misalignment (the first version of the script reused the 100 % render's
delay for every render, which would have hidden a mismatch; each render is
now measured on its own).

**Preroll.** Residual against the 16 s render: 0 s −19.2 dB, 2 s −18.2 dB,
4 s −26.2 dB, **8 s −38.4 dB** (= the repeat noise, −38.1 dB). The
plug-in needs about 8 s of context before the window and 4 s is not enough
(12 dB above the noise); 6 s was not tried. Default **8 s** until a second
window says otherwise.

**Time** (10 s window, 8 s preroll, 0.5 s tail = 18.5 s of audio per render;
batch of four values: 25, 50, 75 and 100 %):

| workers | batch | per value |
|---|---|---|
| 1 | 10.4–14.2 s | 2.6–3.6 s |
| 2 | 8.0–8.4 s | 2.0–2.1 s |
| 4 | 5.2–5.7 s | 1.3–1.4 s |

Four renders in about 5 s, and one render about 2.6 s, is 7× realtime for the
audio actually processed, in line with the 7.25× of §3.9. The speed-up from
four workers is 2× not 4×: more instances do not scale linearly.

Still open:
- The same on **Studio** (the other model; the editor window would not switch
  to it, so no state for it exists yet) and on a second speaker and window.
- Whether input gain changes the answer (the plug-in publishes it).

---

## 4. Hard rules that are cheap to violate

- **Never write over the original.** Analysis is always done on the raw file.
  A compressor raises the noise floor between words and flattens the
  difference between microphones — exactly the two things sensitivity and the
  overlap rule depend on. Cache keyed on modification time makes overwriting
  doubly destructive: the curve is recomputed on already-processed audio.
- **The sample count must not change.** The export references the processed
  file with the same times as the original. Check it in more than one place
  and discard anything that deviates. Measure shift separately by
  cross-correlation, because length alone cannot detect a plug-in that
  reports its latency wrongly — and keep that correlation an FFT.
  `np.correlate(..., "full")` is O(n²) and took 132 s on a 20-minute file,
  longer than the plug-in itself.
- **"Up to date" is a fingerprint, not a modification time.** A processed
  file newer than its source proves nothing: the plug-in, its controls, the
  target level and the ducking depth never touch the source. Comparing times
  alone made the button skip every file and return before the first log line
  — indistinguishable from a broken button. Write the field list out by hand
  so a new setting cannot slip in or out unnoticed, and fail a test if it
  does. An unknown stamp counts as stale.
- **Progress is weighted by file size, and the stage is the resolution.** The
  plug-in processes a file in one piece and cannot be asked how far along it
  is. Log each file and stage: when it is slow or fails, the question is
  always which file and which stage.

---

## 5. The recurring failure, stated plainly

Nearly every bug in this list was **valid, accepted, and silently wrong**:
correct-looking output, a clean import, no exception, and a result nobody
notices until they listen — by which time the edit has been done by hand and
cannot be rebuilt.

So the working rule for this pipeline is: **a feature that produced nothing
must say so.** Setting on and result empty is an error, not a silence. And
every claim about what a stage does should have a number next to it, taken
from real material, in the comment where the constant lives.

---

*Source: autoraffkat, `CLAUDE.md` and `CHANGELOG.md` carry the same findings
with full context. Ask for the relevant section if a number here needs its
surrounding story.*
