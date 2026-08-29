# pp 53 — what each render is, and how it measures

Working notes from the session of 28–29 August 2026, on *Peter & Peter* episode
53 (`peter peter 53 usa sota - 2026-08-18`). Two microphones, two speakers,
77.2 minutes of programme in two parts (`a` ≈ 20 min, `b` ≈ 32 min).

This file exists because the difference between these renders is inaudible in a
file listing and obvious in a meter. Everything below was measured, not
remembered; the method is at the end.

## What is baked into the WAVs, and what is not

The split matters more than any individual number, because it decides what you
can still change without re-rendering.

**Written into the `[mix].wav` files** — the plug-in, the high-pass, de-click,
the level rider, de-essing, the three-stage parallel compression, the per-stem
limiter, the programme ceiling, and (where used) the delivery gain. All of it is
sample-accurate or needs the summed programme, and the sum only exists at write
time.

**Left as Final Cut keyframes** — the ducking, the pans, and the programme
fades. Those you can drag afterwards without a re-run. Changing duck depth is
free; changing level is minutes.

Every render below shares the same chain settings unless stated: dxRevive at
mix 50 %, high-pass 80 Hz, peak threshold −12, leveler −18, rider on, de-click
on, de-bleed on, programme trim on. The variable is the **stem target** and
what the delivery stage was asked for.

## Audio folders — `vertailu/`

Measured on part `a`, summed with the duck envelopes applied, i.e. the
programme as Final Cut plays it. Duck at −12 dB.

| folder | stems asked for | delivery | LUFS | true peak | crest | PSR |
|---|---|---|---|---|---|---|
| `B-lufs20` | −20 | — | −20.23 | −1.50 | 18.88 | 13.33 |
| `P-lufs17` | −17 | — | −17.44 | −1.49 | 16.03 | 11.46 |
| `N-deliver14` | −20 | −14 | −14.38 | −0.96 | 13.37 | 10.05 |
| `Q-deliver17` | −17 | −14 | −14.70 | −0.95 | 13.68 | 10.16 |
| `R-deliver16` | −17 | −16 | −16.61 | −0.99 | 15.69 | 11.23 |

No file overshoots: zero inter-sample overs and zero full-scale samples in all
of them. What sounded "brickwalled" early on was never clipping — it was crest.

Three more folders are experiments kept for the record:

* **`L-rider10`** — `B-lufs20` settings with `rider_max_db` raised from 6 to 10.
  Rendered because a turn on this material typically **ends 7.2 dB quieter than
  it starts** (Nyman; Wancke 2.6 dB), so the rider was pinned at its ceiling for
  most of Nyman's speaking time. Never A/B'd by ear.
* **`O-deliver14st`** — `B` stems, delivery −14 with a −13 short-term ceiling, to
  test splitting the work between a slow ride and the fast limiter. Result was
  identical to `N-deliver14` (LRA 5.0 both). The two were doing the same job on
  the same material.
* **`U-molemmat14`** — `P` stems, delivery −14 with the quiet-passage lift on.
  The lift moved 4.0 dB into quiet passages and bought **0.13 dB** of flat
  boost. LRA unchanged. `program_lift_db` therefore defaults to 0.

## Final Cut sessions — the `.fcpxml` files

| file | audio | layout | master |
|---|---|---|---|
| `pp 53 K-compound.fcpxml` | `B-lufs20` | compound | −8 dB |
| `pp 53 S-jakelu14.fcpxml` | `Q-deliver17` | compound | 0 dB |
| `pp 53 T-jakelu16.fcpxml` | `R-deliver16` | compound | 0 dB |

**Compound layout** means the picture stays an ordinary multicam on the spine
(`srcEnable="video"`, angle switching intact) while the audio lives in a
`<media><sequence>` reached by one `<ref-clip lane="-1" useAudioSubroles="1">`.
That `ref-clip`'s volume is the only real master fader Final Cut offers, and the
subroles stay visible outside it, so per-speaker and overall control sit in the
same window. The structure was copied from what Final Cut itself wrote when the
audio was detached and compounded by hand — not from the DTD, which permits
plenty the app never writes.

`K-compound` is the render approved by ear on 28 August; it is tagged in git as
`aani/k-compound-hyvaksytty`, with its settings copied to
`vertailu/K-compound-asetukset.json`.

Earlier variants `A`–`J` and their audio folders were deleted once measured.
Their numbers survive in the table below so the ground does not have to be
covered again.

| deleted variant | what it was | LUFS | crest | PSR |
|---|---|---|---|---|
| `A-nykyinen` | stems −14, the original settings | −15.19 | 13.64 | 10.07 |
| `C-lufs24` | stems −24 | −24.25 | 22.93 | 17.21 |
| `D-budjetti6` | stems −14, per-stem limiter budget 6 dB | −16.08 | 14.60 | 10.70 |
| `E-jaettu6` | as `D`, budget shared across stems | −17.67 | 16.19 | 11.82 |
| `F-jaettu9` | shared budget 9 dB | −15.19 | 13.64 | 10.08 |

`D` is the instructive failure: a per-stem budget pushed the speakers **1.07 dB
apart to 5.90 dB**, because one microphone needed 5.9 dB of backing off and the
other none. `F` is identical to `A` because a 9 dB budget never binds on this
material. Both are why the backoff became one shared decision.

## Reference renders — `valmiit/`

* `… K-compound … .mov` — `K-compound` exported and taken through Waves L2 and
  iZotope RX Loudness Control by hand. Measured with our own meter:
  **−14.08 LUFS, LRA 6.95, short-term max −8.35, momentary max −5.17.** RX read
  the same file as −14.0 / LRA 7.8 / −7.7 / −4.7, so the meter agrees within
  0.1 LU on integrated and 0.5–0.9 on the maxima, which is windowing convention.
* `… (original audio).m4a` and `… NORMALIZED.wav` — the same export before and
  after that treatment.

This file is the benchmark the app's own delivery stage was measured against.

## The trade, priced

| | LUFS | limiter work | LRA |
|---|---|---|---|
| `T-jakelu16` | −16.21 | 0.27 LU | **6.8** |
| `S-jakelu14` | −14.35 | 2.0–2.3 LU | **5.3** |
| L2 + RX reference | −14.08 | — | 6.95 |

Two decibels of loudness costs about 1.5 LU of loudness range, and no limiter
design recovers it: the boosted material only *has* 7.33 LRA, and taking
8.4 dB off the peaks costs 3.2 of it whatever the release does — a
program-dependent dual release moved it 0.05. YouTube only turns loud uploads
down, so at −16 the programme plays roughly 2 dB quieter than its neighbours.
That is the whole decision.

## How these were measured

`IntegratedMeter` (`speechmix/meter.py`) for LUFS, LRA and the maxima —
ITU-R BS.1770-4, accumulated from the stream so the whole 77 minutes is
measured rather than a window. True peak is 4× oversampled. Crest is
peak − RMS; PSR is true peak − maximum short-term.

Everything is measured on the **ducked sum of part `a`**, because that is what
plays. Measuring the raw sum instead reports a programme that never exists: for
`A-nykyinen` it claims +2.61 dBTP and 14 696 overs, when the ducked programme
has none.
