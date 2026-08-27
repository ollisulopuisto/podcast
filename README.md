# Podcast tooling workspace

A uv workspace holding the shared speech-mixing pipeline and the applications
that use it.

```
packages/speechmix/     the chain, de-bleeding, the speech grid, the programme
                        ceiling, duck/rider envelope computation -- and the
                        measurement tests that prove what each stage does
apps/automixer/         session reader, render, TUI  (see apps/automixer/README.md)
```

Room is left for the sibling apps: autoraffkat (FCPXML in, FCPXML out, picture
cuts to whoever is talking) drops in as `apps/autoraffkat/`, and the
session-based app after it as another member of `apps/`.

## Why one repository

The pipeline changed ten times in one day, and every change was driven by a
measurement that invalidated the previous behaviour. With a separately
versioned package, each of those is a release plus a bump in every consumer,
and the consumers drift in between. That drift *is* the problem: automixer was
behind on the de-clicker fix, on de-bleeding, on a compressor stage that never
fired, and on the programme ceiling. A separate repository would have
formalised the drift rather than removed it.

Each app keeps its reader, its writer, its UI and its editing logic. The
library keeps everything that turns samples into other samples, plus the tests
that prove it. Split `speechmix` into a real PyPI package when the pipeline
stops moving, or when a fourth consumer appears outside these three. Splitting
later is cheap; un-splitting is not.

## The two seams

**Samples.** `speechmix.process_track(audio, rate, settings, gain_db,
speech_flag, target_lufs, plugin, speech_mask)` takes an array and returns an
array. It has never heard of FCPXML, session files, timelines or paths.

**Decisions.** `speechmix.duck_envelopes(grid, settings, program_start)`
returns `{speaker: [(time, dB), ...]}` -- gain *decisions*. One host writes
them into an FCPXML as `<adjust-volume>` keyframes so the editor can still
change them; another bakes the same curve into samples. Same computation,
different emission:

> Level decisions that come **after** the chain can be automation.
> Level decisions that come **before** it must be baked in.

The host-shaped idea the library does carry is "a track with a placement on a
programme timeline" (`speechmix.Track` / `speechmix.Span`), because the linear
conversion between programme time and file time is the only timeline knowledge
the pipeline needs.

## Working in it

```bash
uv sync                       # installs every workspace member
uv run pytest                 # the measurement tests and the app's tests
uv run automixer --help       # the app's CLI
```

On anything that is not Apple Silicon, `mlx` has no Metal backend; install
`mlx[cpu]` to run automixer's tests. `speechmix` itself needs only numpy,
scipy and pyloudnorm, and runs anywhere.

## The findings

[`packages/speechmix/FINDINGS.md`](packages/speechmix/FINDINGS.md) carries the
measurements each stage exists for. Nearly every bug in that list was valid,
accepted, and silently wrong: correct-looking output, a clean import, no
exception, and a result nobody notices until they listen. So the working rule
is: **a feature that produced nothing must say so.** Setting on and result
empty is an error, not a silence -- and every claim about what a stage does has
a number next to it, taken from real material, in the comment where the
constant lives.
