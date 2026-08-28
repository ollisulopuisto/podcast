# automixer's chain against speechmix

What this is: a map of `src/automixer/domain/processor.py` against
`packages/speechmix`, so the swap can be planned rather than guessed. Which
stages exist in both, which are automixer's alone, and where a constant differs
from the measured one.

Read against the code, not the documentation. That was written when
`PIPELINE.md` documented a stage which had never run; it has since been
rewritten against the code, but the rule stands — it is how that stage
survived for as long as it did. Every number below was measured in this
repository on synthetic speech with uneven burst levels, except where it says
otherwise.

---

## 1. The De-Smacker has never done anything

`DeSmackProcessor` is a guaranteed no-op, and always has been.

```python
hp_mean = maximum_filter1d(hp_energy, size=win_size, axis=0)   # named mean, is a MAXIMUM
thresh_factor = 5.0 - (3.0 * self.sensitivity)                 # 2.0 … 5.0
potential_clicks = hp_energy > (hp_mean * thresh_factor)
```

`hp_mean` is a sliding **maximum**, so `hp_mean[i] >= hp_energy[i]` everywhere.
The test asks whether a sample exceeds at least twice its own neighbourhood
maximum, which nothing can. Measured, with five lip smacks planted in pauses:

| sensitivity | samples changed |
|---|---|
| 0.0 | 0 |
| 0.5 | 0 |
| 1.0 | 0 |

The largest `|hp| / local_max` ratio in the material was **1.000**, against a
threshold of 2.0 at the most sensitive setting.

`PIPELINE.md` documents it as Stage 1 and the CLI exposes
`--speech-desmack-sensitivity`, so there is a user-facing control over a stage
that cannot fire. `speechmix.chain.declick` is the corrected port of this same
code: it compares against a **mean**, and is then calibrated by findings per
second (`DECLICK_FACTOR_MAX/MIN`, `DECLICK_MAX_PER_SECOND`,
`DECLICK_ESCALATIONS`) with a ceiling that corrects nothing when the findings
never fit.

**Swap:** delete `DeSmackProcessor`, call `chain.declick`. Nothing can regress,
because nothing is happening now.

---

## 2. Stages in both, and how they disagree

| | automixer | speechmix | 
|---|---|---|
| plug-in slot | a **list** per track and per music bus, loaded lazily inside `process()` **on a `ThreadPoolExecutor` worker**; on failure prints and returns the input unchanged; no length check | one slot, pool built up front on the main thread, child process, length and lag both checked |
| high-pass | 80 Hz, 4th order | `settings.high_pass_hz`, default 80 | agrees |
| de-click | no-op, see above | rate-calibrated | |
| compressors | **2** stages, **no cap** on gain reduction | **3** stages, 5 dB cap each, plus a parallel dry/wet mix at 0.6 | |
| detector | centred moving **RMS** over `window_sec`; no attack, no release | one-pole **peak** follower, `min(one_pole(release), instant)` | |
| multiband | an **alternative mode**, each band auto-gained to −23 LUFS independently | stage 1 of 3, one threshold, one ratio and one cap across all bands, no per-band gain | |
| crossover | 250 / 4000 Hz, subtraction, 2nd order | 250 / 4000 Hz, subtraction, 4th order | agrees |
| de-esser | none | 4500 Hz, −30 dB, 3:1, before the compressors | |
| ceiling | `LimiterProcessor(−1.0 dBFS)` on the master, gain curve unsmoothed | −1.5 dBTP, 4× oversampled detection, centred lookahead minimum, one-pole release, `peak_guard` behind it | |
| loudness | one static makeup gain to target, never re-measured | re-measured after compression, then up to three settle rounds to land inside 0.3 LU | |

### The dead third stage is not automixer's bug

The `leveler_threshold + 4.0` finding does not transfer: automixer has no third
stage at all. What it has instead is **two uncapped stages**.

### Thresholds are closer than they look, except one

speechmix normalises to the target and slides its thresholds with it
(`THRESHOLD_REFERENCE_LUFS = -20`, `offset = target + 20`). automixer normalises
each track to a fixed −23 LUFS reference and uses absolute numbers. Expressed
relative to the level the compressor actually sees:

| stage | automixer | speechmix |
|---|---|---|
| peak | −15 against −23 → **+8 dB** | −12 against −20 → **+8 dB** |
| leveler | −26 against −23 → **−3 dB** | −18 against −20 → **+2 dB** |
| third | — | −4 dB below the leveler |

The peak threshold already agrees exactly. The leveler sits **5 dB lower** here.

**Caveat that matters more than the table:** these are not directly comparable.
automixer measures level with a centred RMS window, speechmix with a peak
follower, and for speech those differ by the crest factor. Equal numbers are
not equal compression. Measured on the same 30 s of uneven bursts:

| | stage 1 | stage 2 | stage 3 |
|---|---|---|---|
| automixer | 0.84 dB max / 0.02 mean | 3.63 / 0.60 | — |
| speechmix | 1.66 / 0.03 | 2.56 / 0.28 | 2.88 / 0.49 |

automixer's peak tamer barely engages: its RMS detector on a −23 LUFS signal
rarely clears −15.

---

## 3. Two measured defects beyond the missing stages

**Multiband mode moves the tone with the programme.** Each band is auto-gained
to −23 LUFS independently, which is the failure `chain.multiband` explicitly
avoids. Measured band energy through `MultibandCompressorProcessor`:

| band | before | after | change |
|---|---|---|---|
| low, <250 Hz | −16.51 dB | −27.52 | **−11.02** |
| mid, 250–4k | −21.14 | −30.23 | **−9.09** |
| high, >4k | −35.74 | −33.20 | **+2.54** |

The balance across the three bands moves by **13.56 dB**, and it moves
differently depending on what is being said.

**The master ceiling is above where it thinks it is.** `LimiterProcessor` works
on sample peaks. Measured on speech normalised to −14 LUFS:

| | sample peak | true peak |
|---|---|---|
| in | +2.12 dBFS | +2.33 dBTP |
| out | **−1.00 dBFS** | **−0.41 dBTP** |

Inter-sample peaks land 0.59 dB above the intended ceiling, before any lossy
encoding lifts them further. It is the same measurement that put speechmix at
−1.5 dBTP with 4× oversampling. The gain curve is also unsmoothed: the largest
sample-to-sample gain step measured **120 dB**.

---

## 4. In speechmix, absent from automixer entirely

*Written before the grid existed. What is left of it is at the bottom.*

`debleed`, the speech grid, the level rider, the de-esser, parallel
compression, the over-compression check (`peak_to_short_term`, 6 LU floor),
lag and length assertions, the fingerprint, and per-microphone ducking.

automixer's "ducking" is a different feature and should not be confused with
it: `DuckingProcessor` sidechains the **music bed** from the summed speech bus.
speechmix's ducking closes a **microphone** while its owner is not talking.
Both are wanted; only the second is in the library.

### The grid was the whole blocker, and the premise was wrong

Four of those entries — the grid, `debleed`, the rider and per-microphone
ducking — were one entry. The last three read the grid and nothing else, so
none of them could be swapped while it was missing.

This document twice gave the reason as **"automixer has no microphones to
build one from"**. That is a true statement about FCPXML angles and a false
one about automixer: every `type: speech` track *is* one person's microphone.
What was missing was not microphones but the shape the library asks for — a
track with spans on a programme timeline — and the conversion from a wav file
with a start time to that shape is `domain/room.py`, which is thirty lines of
adapter and no arithmetic of its own.

`speechmix.grid.speech_grid` builds the grid by comparing the raw stems, and
`speechmix.timeline.Track` is the seam that was previously reachable only
through `item.placements` — which is why every one of these stages was locked
to one host. automixer is `speech_grid`'s first application consumer; it was
written for exactly this case, stems that share a time base, and had none.

Connecting it took one library change: `SpeechGrid` kept the per-frame levels
it already computed and grew a `speakers` view in the shape `masks` and
`envelopes` read. The package had two grids and nothing joined them, so
ducking could not reach the one this module builds.

**Still absent, and still wanted:** the fingerprint (automixer re-renders
every time), the lag and length assertions around the plug-in slot, and the
over-compression check.

## 5. automixer's alone, and staying that way

The whole music bus — gain-match to −30 LUFS, the spectral carver, the
sidechain duck — plus ad-spot insertion and the timeline shifting in
`Bus.process`, panning, the MLX/GPU implementations, `SpotAnalyzer`, and the
TUI. None of it belongs in a library that takes samples and returns samples.

---

## 6. Order to do the swap in — and what was done

Steps 1–3 and the de-esser are **done**: `apps/automixer/src/automixer/domain/shared.py`
imports the stages from `speechmix.chain`, and `SpeechChainProcessor` calls
`chain.process` — the same function autoraffkat and podcast-magic run. Six
hand-rolled stages came out (de-smacker, high-pass, normalising gain, two
uncapped compressors, and the multiband mode) and one call went in, which
brings four stages automixer never had: the de-esser, the third compressor,
the parallel dry/wet mix, and the settle loop onto the target.

`LimiterProcessor` and `MultibandCompressorProcessor` are deleted rather than
left reachable: a stage measured to do harm is not a fallback.

1. ~~`declick`~~ — done. Measured before the swap, on planted lip smacks:
   **0 samples changed** at sensitivity 0.0, 0.5 and 1.0.
2. ~~The ceiling~~ — done, `chain.limiter` + `peak_guard` behind it.
3. ~~The compressors~~ — done, `chain.multiband` + two `chain.compress`
   stages, each capped at `MAX_GR_DB`. Measured before the swap, one stage
   with no cap pulled **29.26 dB**.
4. ~~**De-essing**~~ — done, from `chain.process`.
5. ~~**The speech grid**~~ — done, `domain/room.py`. See §4: the reason it
   was blocked was a wrong premise, not a missing input.
6. ~~**The rider**~~ — done. `speaking` now comes from the grid and
   `SpeechSettings.rider` is `True`. It is still the grid's mask and never the
   signal's: measured on autoraffkat's material, a level heuristic called 74 %
   of blocks speech when 53 % were the speaker's own, and riding on it lifted
   the leakage until the level spread got worse. Without a mask the library
   still skips the stage rather than guessing, and that path is still live —
   a single microphone has no grid.
7. ~~`debleed`~~ — done, on the raw audio ahead of the plug-in slot, with
   `solo_masks` from the grid. A refused filter reports its reason; a
   de-bleeder that quietly does nothing is the failure this whole document
   was written against.

Not swapped, deliberately: the **plug-in slot**. automixer takes a list per
track and speechmix takes one, in a child process, with length and lag
checks. The child process is the part worth having and it is not a rename —
it wants its own change.

### What the grid stages measure

On synthetic two-microphone material in this container (300 s, alternating
turns, a planted linear leak path), which is where the numbers below come
from — the numbers above are autoraffkat's, on 77 minutes of real material,
and they are the ones to trust for depth:

| | |
|---|---|
| grid precision, "is this the owner speaking" | **1.000** — no false positive on leak at any sensitivity tested (6–18 dB) |
| grid recall at the 12 dB default | 0.450 here, 0.996 at 6 dB — the floor lands on the *leak* when two people alternate, so the default is conservative on this material |
| microphone closed | **41.6 %** of the programme, all of it under the other speaker |
| microphone closed during its **own** speech | **0.00 %** |
| leak level, before → after de-bleed | −17.52 → −72.57 dB, own speech kept at r = 0.9987 |

The synthetic leak is noiseless, so −55 dB is not a number to expect from a
real room; real material gave 4.12 and 3.77 dB. What these say is the
*direction*: the errors the grid makes are misses, never false positives, so
a microphone is never closed while its owner is talking.

### The A/B, measured

Two 20 s speech tracks 12 dB apart, rendered by both chains on this container:

| | automixer's own | shared chain |
|---|---|---|
| integrated loudness | −16.00 LUFS | −16.00 LUFS |
| sample peak | −1.00 dBFS | −7.02 dBFS |
| **true peak** | **−0.36 dBTP** — 0.64 dB over its own −1.0 ceiling | **−7.00 dBTP**, under −1.5 |
| crest factor | 15.3 dB | 12.6 dB |
| render time | 0.6 s | 2.0 s |

The overshoot is the measurement this whole section opened with, reproduced
end to end. The crest moving 2.7 dB is the three capped stages engaging where
automixer's fast stage barely did (0.84 dB of gain reduction, §2).

**The render is 3.3× slower**, and that is the real cost: the library is numpy
and scipy on the CPU, automixer's stages were mlx on the GPU. On Apple Silicon
the old path is faster still, so the ratio there is likely worse than this.
What was bought with it is a de-clicker that fires, a ceiling that holds where
it says it does, and a tone that does not move with the programme.


---

## 7. The grid rule, converged on autoraffkat's

§4 said the grid arrived and the three stages that needed it started running.
What it did not say is that the *rule* was still this app's own. autoraffkat
answered "who is speaking" one way and `speechmix.grid` another, so an
improvement to autoraffkat's detection would not have reached here — the exact
thing the shared pipeline is supposed to prevent.

| | automixer (was) | autoraffkat (now both) |
|---|---|---|
| level curve | unsmoothed | 100 ms moving average |
| noise floor | 10th percentile | **20th** percentile |
| margin over floor | 8 dB | **12 dB** |
| dominance | folded into the decision | in `duck_masks`, where it decides who stays open |

The margin is the number measured on 77 minutes of real material, so it wins.
Measured on the library's own two-microphone fixture, where the bleed sits
18.4 dB under the direct voice:

| rule | own speech | other's bleed |
|---|---|---|
| 10th pct + 8 dB + dominance | 100.0 % | 0.4 % |
| 10th pct + 8 dB, no dominance | 100.0 % | 0.4 % |
| autoraffkat: smoothed, 20th pct, 12 dB | 100.0 % | **0.0 %** |

The first two rows are identical, so the dominance test was deciding nothing
there — `test_grid.py` used to assert that bleed "is loud enough to fool a
level threshold", and on that fixture it is not. The rule is now `grid.lane`,
one function, called by both apps; everything around it is a host getting hold
of levels.

### A bug that fell out of copying the rule faithfully

autoraffkat smoothed with `np.convolve(..., "same")`, which zero-pads. **Zero
is silence in the linear domain and full scale in dB.** Measured on a constant
−240 dB curve with the 100 ms kernel, the first cell came back at −144 dB:
96 dB of level that is not in the material, at the programme's first and last
40 ms — enough to read as a microphone being active there, which is a cut
decision in autoraffkat and a ducking event in both.

Nothing crashed; the curve was valid and the right length. `grid.smooth`
replicates the edge value instead, and both apps get the fix because there is
now one smoother.
