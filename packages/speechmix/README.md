# speechmix

The speech-mixing pipeline shared by `autoraffkat`, `automixer` and
`podcast-magic`. It turns samples into other samples and knows nothing about
any session format.

## The seam

The host gives the library **tracks with spans on a programme timeline** —
not FCPXML assets, not session rows. It is `session.py`:

```python
Track:
    path: str
    speaker: str      # whose microphone this is
    mono: bool        # always True for microphones
    bit_depth: int
    spans: [Span(start, end, file_offset)]   # programme time, programme time, file time
```

Within a span the mapping is linear, and that one formula is all the timeline
knowledge the pipeline needs:

```
file_time = span.file_offset + (programme_time - span.start)
```

Everything downstream — ducking, cross-bleed removal, the level rider, the
programme ceiling — is that formula applied to something. Which is why the
seam matters more than it looks: while those functions read `item.placements`
instead, they were in the library but reachable by exactly one host, and
automixer went without all four.

Building a `Track` is the host's job and the only part that cannot be shared.
autoraffkat has `MediaItem.as_track`; a host with one file at one offset calls
`session.whole_file`, which is automixer's whole conversion.

## Who is talking

`detect.py` turns an RMS envelope into the **speech grid** — one row per
microphone, saying when its owner is speaking and how loudly. Every masking
decision in the package reads it and nothing else, so a host that can build a
grid gets ducking, solo masks and the rider mask without writing any of them.

Two layers, and they must not be mixed. `rms_db` is the slow one and runs once
per file; the host decides where the samples come from, because that is where
the hosts genuinely differ — autoraffkat decodes with ffmpeg and caches to
disk, automixer already has the wav in memory. `curve` and `lane` are the fast
layer: numpy over the grid, no file reading, because autoraffkat rebuilds the
grid on every slider move. `curve` is split from `lane` so that cache has
somewhere to sit — settings are read in `lane`, so a cached curve survives them
changing.

## The second seam: decisions, not samples

`duck_envelopes()` returns `{speaker: [(time, dB)]}`. autoraffkat writes
those into FCPXML as Final Cut volume keyframes so the editor can still
change them; automixer has nothing downstream to write automation into, so it
multiplies the same curve into samples with `envelope_gain`. Same
computation, two emissions, and the shapes are asserted to match — a duck
that depended on which host made it would be a different feature under one
name.

> Level decisions that come **after** the chain can be automation.
> Level decisions that come **before** it must be baked in.

Ducking is after. A level rider is before.

## Why the measurements live here

Every constant in this package came from measuring real material, and the
comment next to it says what was measured. The bugs this pipeline has had
were all silent — valid output, clean import, no exception, wrong result —
and the number is what lets the next reader tell whether a change is an
improvement. `apps/autoraffkat/SHARED-AUDIO.md` carries the full list.
