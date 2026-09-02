# The Hindenburg Session File (`.nhsx`) — A Field Guide

A reference to the XML session format written by Hindenburg (PRO), as it
actually is — including the parts that are undocumented, inconsistent, or
wrong in the vendor's own UI. Every claim is tagged:

* **[measured]** — verified against a session *and* a render produced by
  Hindenburg's own engine; the number is written down.
* **[observed]** — seen in real exported files; structure, not physics.
* **[unknown]** — we do not know, and guessing has been expensive. Listed
  at the end so you don't have to rediscover why.

Everything here was measured or observed in this repository's test suites
(`apps/podcast-magic/tests/test_measured_session.py`,
`packages/nhsx/tests/`) against **Hindenburg PRO 2.05.2718** on macOS,
plus real-world session files from older versions. If you use this
document with another version, treat unmeasured behavior as unknown and
re-measure — the recipe is at the end.

## 1. The file

A `.nhsx` file is **plain XML**, UTF-8 — not zipped, not a database.

**[observed]** Exports are sometimes in an XML namespace and sometimes
not — the same version does both. Parse by **local name**, never by
direct tag match, or you will read zero regions from a file that opens
fine in Hindenburg.

## 2. Document skeleton

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Session Version="Hindenburg PRO 2.05.2718" Samplerate="48000" Time="01:51.157">
  <AudioPool Path="h-test Files" Location="/Users/dst/Downloads">
    <File Id="1" Name="A1_level_m20.wav" Duration="05.000" Leq="-">
      <MetaData OriginalPath="/Users/dst/Downloads/test_signals/file_a_laws/A1_level_m20.wav"/>
    </File>
  </AudioPool>
  <Tracks>
    <Track Name="A4" Pan="-0.25">
      <Region Ref="4" Name="A4_pan_0.625" Start="30.200" Length="05.000"/>
    </Track>
  </Tracks>
  <Clipboard>
    <Group/><Group/><Group/><Group/>
  </Clipboard>
  <Markers>
    <Marker Id="1" Name="Sisään" Time="01:02.500"/>
  </Markers>
</Session>
```

| element | attributes | notes |
|---|---|---|
| `Session` | `Version`, `Samplerate`, `Time` | `Time` is the session end as a timestamp **[observed]**; `Name` also occurs **[observed]** |
| `AudioPool` | `Path`, `Location` | `Path` is the audio folder *relative to the session file* and is often **empty** — the session's own directory is then the default **[observed]**; `Location` is absolute and redundant |
| `Clipboard` | — | four empty `Group` children; purpose unknown **[unknown]** |
| `Markers` | — | optional; absent from some exports **[observed]** |

## 3. Time format

Timestamps appear in three shapes **[observed]**:

| shape | example | seconds |
|---|---|---|
| bare seconds | `05.000`, `34.6` | 5.0, 34.6 |
| `MM:SS.mmm` | `01:51.157` | 111.157 |
| `HH:MM:SS.mmm` | `01:04:00.473` | 3840.473 |

The trap: `34:46.400` is 2086.4 seconds — minutes and seconds — not
"millis ending in the seconds place". Parse by the colons, not by
decimals.

**[observed]** Three fields is the ceiling — the DTD clock is
`HH:MM:SS(.fff)`. A fourth leg (`1:2:3:4`) is malformed and must not be
read as a (wrong) longer clock; readers reject it, though they differ on
whether a malformed time is a zero or a raised error.

**[measured]** An attribute that is zero is **omitted entirely**. The
first region of a session is routinely `<Region Ref="1" Length="05.000"/>`
with no `Start` at all. A reader that requires the attribute dies on the
first real session it meets. Missing = 0, not missing = error.

## 4. `AudioPool/File`

```xml
<File Id="1" Name="A1_level_m20.wav" Duration="05.000" Leq="-">
  <MetaData OriginalPath="/Users/dst/Downloads/test_signals/file_a_laws/A1_level_m20.wav"/>
</File>
```

* `Id` — the key regions reference via `Ref`. **[observed]**
* `Name` — file name; together with `AudioPool/@Path` it locates the
  audio on disk. **[observed]**
* `Duration` — source length as a timestamp. **[observed]**
* `Leq="-"` — loudness placeholder; observed always `-` in our files.
  **[unknown]** when it carries a value.
* `<MetaData OriginalPath=…>` — where the file was imported from.
  **[observed]**
* `<Transcription>` — optional. Words as
  `<w s="1.20" l="0.31" sp="UU">sana</w>`. **`s` is time from the start
  of the *file*, not the timeline** — the single most important fact in
  this format. A word at `s` lands on the timeline at
  `Start + (s − Offset)` of the region it plays through; the same file
  can appear on the timeline several times. **[measured]** — getting
  this wrong produces a session that opens, plays, and is silently
  wrong everywhere.

## 5. `Tracks/Track`

```xml
<Track Name="A9-A10" Volume="6">
  <Track Name="A4" Pan="-0.25">
  <Track Name="A11" Volume="-6">
```

| attribute | meaning | status |
|---|---|---|
| `Name` | track name | **[observed]** — load-bearing downstream: speaker identity |
| `Volume` | the track fader, **dB** | **[measured]** `Volume="6"` → rendered region at −13.98 dBFS with a −20 dBFS source; `Volume="-6"` → −26.03 |
| `Gain` | older spelling of track gain, **dB** | **[observed]** both spellings exist in the wild; treat as the same control in dB; where both appear we sum them — unmeasured, but Hindenburg writes one |
| `Pan` | track panorama, −1…+1 | **[measured]** — see the law below. **Pan is a track attribute; the region does not carry it** |
| `Muted` | track mute | **[observed]** |

**The pan law** — linear, constant-sum, **positive = left** (the
opposite of most DAWs):

```
R/L = (1 − p) / (1 + p)
```

Fitted from Hindenburg's own renders:

| `Pan` | predicted R/L | measured R/L |
|---|---|---|
| 0.625 | 0.23077 | 0.23027 |
| −0.55 | 3.44444 | 3.44347 |
| −0.25 | 1.66667 | 1.66667 |
| 0.1 | 0.81818 | 0.81818 |

Out-of-range values are clamped, not wrapped — wrapping would give a
negative gain, i.e. a phase flip. **[measured]**

A stereo export of a mono source carries per-channel gains `(1+p)` and
`(1−p)` — per-channel unity at center, so folding to mono must divide
by two or everything is +6 dB. **[measured]**

## 6. `Region`

```xml
<Region Ref="10" Name="A10_both_gain_clipgain" Start="01:42.601" Length="05.000" Gain="6.0"/>
<Region Ref="8" Name="A8_fade_short" Start="01:24.200" Length="03.000" FadeIn="01.600"/>
```

| attribute | meaning | status |
|---|---|---|
| `Ref` | `AudioPool/File/@Id` | **[observed]** |
| `Name` | region name as shown in the UI | **[observed]** |
| `Start` | timeline position | **[measured]** omitted when zero — see §3 |
| `Length` | region length | **[observed]** |
| `Offset` | where in the *source file* the region starts | **[observed]** — this is the other half of the word-time formula |
| `Muted` | region mute | **[observed]** — spelled `True`, `true`, or `1` in different files; accept all three |
| `Gain` | clip gain, **dB** — this is what the clip-gain handle writes | **[measured]** +6 → −8.06 dBFS rendered with a −20 source *and* a +6 track fader (−8.00 predicted): region gain and track fader **stack** |
| `ClipGain` | a *second* gain spelling | **[measured]** when a region carries both `Gain="-11.2"` and `ClipGain="-22.2"`, the render is 22.50 dB quieter than the unmuted region — **`ClipGain` wins and does not sum with `Gain`** (the sum would have been −33.4) |
| `FadeIn` / `FadeOut` | fades written as *attributes* | **[measured]** `FadeIn="01.600"` renders as a 1.6 s fade-in from silence. A second, different fade spelling besides `<Fade>` children — accept both |
| `IsMusic`, `UseTranscription` | flags, no level effect | **[observed]** |

`ClipGain` is written by something other than the clip-gain handle — in
our session, setting the clip gain in the UI wrote `Gain`, not
`ClipGain`. **[unknown]** what UI action writes it (normalization?
auto-gain?).

## 7. `Fade` — the ramp to a level

```xml
<Region Ref="7" Name="A7_fade_plateau" Start="01:00.000" Length="15.000">
  <Fade Start="02.500" Length="01.666" Gain="-10"/>
  <Fade Start="10.834" Length="01.666"/>
</Region>
```

Three facts, each once the cause of a silent, valid-looking, wrong
render:

1. **A fade is a ramp *to* the `Gain` level, and it stays there.**
   **[measured]** A 2.5 s ramp to −11.2 dB held for 26 s; the body of the
   region rendered 12.02 dB quieter. It is not a fade to silence.
2. **Without `Gain`, the ramp returns to unity** (gain 1.0). **[measured]**
3. **The curve is a raised-cosine S, not a straight line.** **[measured]**
   Fitting windowed RMS across ramps between two noise levels: cosine
   0.29 dB RMS error (at the measurement noise floor); a straight line
   1.04 dB, up to 2.06 dB wrong mid-ramp. Same shape up and down.

`Start`/`Length` are region-relative seconds; `Gain` is in dB. Multiple
`<Fade>` children follow one another and do not sum. A ramp longer than
the region is cut at the region end, not slowed. **[measured]**

## 8. `Markers/Marker`

`Id`, `Name`, `Time` — plain labeled points on the timeline. **[observed]**

## 9. What we don't know

Ordered by how badly not knowing bites:

1. Negative times, frame-rate timecodes, midnight wraps — the time
   parser has never seen one.
2. Stereo regions: what the two channels *were* — combined? one side? A
   session that sounds fine in Hindenburg can lose a channel silently.
3. What UI action writes `ClipGain` (and `Leq` values).
4. Buses, auxes, effects, master fader, automation — not in any session
   we have parsed.
5. More than two fade spellings / ordering guarantees.
6. Whether track `Gain` and `Volume` can coexist, and what it would mean.

## 10. Reproducing the measurements

The session `test_signals/h-test A.nhsx` in this repository was built
from generated white-noise sources (`scripts/generate_test_signals.py`)
so every rendered number is attributable, then exported from Hindenburg
PRO 2.05.2718. The measurements above are asserted by the test suites
cited at the top; if a future Hindenburg version disagrees, the test
that fails tells you which paragraph of this document to rewrite.

The measurement recipe — three sessions, one export each, and how to
decode them — lives in
[`apps/podcast-magic/docs/PARSER-NEEDS.md`](../apps/podcast-magic/docs/PARSER-NEEDS.md).
