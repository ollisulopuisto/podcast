# speechmix

The speech-mixing pipeline shared by `autoraffkat`, `automixer` and
`podcast-magic`. It turns samples into other samples and knows nothing about
any session format.

## The seam

The host gives the library **tracks with placements on a programme
timeline** — not FCPXML assets, not session rows:

```python
Track:
    path: str
    speaker: str      # whose microphone this is
    mono: bool        # always True for microphones
    bit_depth: int
    spans: [(programme_start, programme_end, file_offset)]
```

Within a span the mapping is linear, and that one formula is all the timeline
knowledge the pipeline needs:

```
file_time = span.file_offset + (programme_time - span.programme_start)
```

## The second seam: decisions, not samples

`duck_envelopes()` returns `{speaker: [(time, dB)]}`. autoraffkat writes
those into FCPXML as Final Cut volume keyframes so the editor can still
change them; automixer has nothing downstream to write automation into, so it
bakes the same curve into samples. Same computation, different emission.

> Level decisions that come **after** the chain can be automation.
> Level decisions that come **before** it must be baked in.

Ducking is after. A level rider is before.

## Why the measurements live here

Every constant in this package came from measuring real material, and the
comment next to it says what was measured. The bugs this pipeline has had
were all silent — valid output, clean import, no exception, wrong result —
and the number is what lets the next reader tell whether a change is an
improvement. `SHARED-AUDIO.md` at the repo root carries the full list.
