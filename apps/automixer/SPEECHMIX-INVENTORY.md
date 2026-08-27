# automixer's chain against speechmix

What this is: a map of `src/automixer/domain/processor.py` against
`packages/speechmix`, so the swap can be planned rather than guessed. Which
stages exist in both, which are automixer's alone, and where a constant differs
from the measured one.

Read against the code, not the documentation — `PIPELINE.md` describes at least
one stage that has never run. Every number below was measured in this
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

`debleed`, the speech grid, the level rider, the de-esser, parallel
compression, the over-compression check (`peak_to_short_term`, 6 LU floor),
lag and length assertions, the fingerprint, and per-microphone ducking.

automixer's "ducking" is a different feature and should not be confused with
it: `DuckingProcessor` sidechains the **music bed** from the summed speech bus.
speechmix's ducking closes a **microphone** while its owner is not talking.
Both are wanted; only the second is in the library.

## 5. automixer's alone, and staying that way

The whole music bus — gain-match to −30 LUFS, the spectral carver, the
sidechain duck — plus ad-spot insertion and the timeline shifting in
`Bus.process`, panning, the MLX/GPU implementations, `SpotAnalyzer`, and the
TUI. None of it belongs in a library that takes samples and returns samples.

---

## 6. Order to do the swap in

1. `declick` — pure win, replaces a stage that does nothing.
2. The ceiling — `chain.limiter` for the master, or `ceiling.programme_ceiling`
   if automixer ever emits stems. Fixes a real dBTP overshoot.
3. The compressors — replace the pair with `chain.multiband` + two
   `chain.compress` stages. This is the one that changes how the output sounds,
   so it wants an A/B on a real episode.
4. De-essing and the rider — new stages; the rider needs a speech grid, which
   automixer does not build yet.
5. `debleed` — needs the grid too, and needs to run before the plug-in slot.

Multiband mode is worth disabling before any of it: it is doing measurable harm
today.
