# speechmix

The speech-mixing pipeline shared by `autoraffkat`, `automixer` and
`podcast-magic`. It turns samples into other samples and knows nothing about
any session format.

## The seam

The host gives the library **tracks with spans on a programme timeline** —
not FCPXML assets, not session rows. It is `timeline.py`:

```python
Track:
    path: str
    speaker: str      # whose microphone this is
    mono: bool        # always True for microphones
    bit_depth: int
    spans: [Span(programme_start, programme_end, file_offset)]
```

Within a span the mapping is linear, and that one formula is all the timeline
knowledge the pipeline needs:

```
file_time = span.file_offset + (programme_time - span.programme_start)
```

Everything downstream — ducking, cross-bleed removal, the level rider, the
programme ceiling — is that formula applied to something. Which is why the
seam matters more than it looks: while those functions read `item.placements`
instead, they were in the library but reachable by exactly one host, and
automixer went without all four.

Building a `Track` is the host's job and the only part that cannot be shared.
autoraffkat has `mix.track_of`; a host with one file at one offset builds a
`Track` with a single `Span`, which is automixer's whole conversion.

## Who is talking

`grid.py` turns raw microphone stems into the **speech grid** — one row per
microphone, saying when its owner is speaking and how loudly. Every masking
decision in the package reads it and nothing else, so a host that can build a
grid gets ducking, solo masks and the rider mask without writing any of them.

The decision is a *comparison across microphones*, not a threshold on one: on
a two-microphone recording half of what is loud on a track is the other
person. `SpeechGrid.speakers` is the view the masks read, and it exists
because they and this module described the same thing in two shapes that
nothing joined.

`rms.py` is the other way in, for a host that has a file rather than samples
in memory: ffmpeg decodes, the envelope is cached, and the decision layer
reads only the finished table.

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

## The third seam: the plug-in's own window

`editor.py` is a child process, and both ends of it are here. A plug-in's
adjustable parameters are not its whole state: dxRevive publishes four, and
**the model selector is not one of them** — it lives in the plug-in's own
opaque state, reachable only through its own interface. `show_editor` is
main-thread-only *and* blocks until the user closes the window, so no host
with an event loop can call it in-process. The child's main thread is free,
and a plug-in UI that crashes takes only that process with it.

The parser is in the library with the child that feeds it, not in each host.
The protocol is line-delimited JSON, and it carries an intermediate
`opening` message saying whether the window came to the front — a host that
reads the first JSON line takes that for the result, and the state the user
just chose disappears without an error. One shape, one parser: `open_editor`
spawns and reads, `main` is what it spawns.

Plug-ins also print to stdout whenever they feel like it, so a line that is
not JSON is logged rather than fatal.

## Why the measurements live here

Every constant in this package came from measuring real material, and the
comment next to it says what was measured. The bugs this pipeline has had
were all silent — valid output, clean import, no exception, wrong result —
and the number is what lets the next reader tell whether a change is an
improvement. `apps/autoraffkat/SHARED-AUDIO.md` carries the full list.
