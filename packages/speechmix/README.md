# speechmix

The shared speech-mixing pipeline. Samples in, samples out.

This package has never heard of FCPXML, session files, timelines or paths.
Everything a host knows lives on the host's side of `process_track`.

```python
import speechmix

grid = speechmix.speech_grid({"olli": mic_a, "guest": mic_b}, rate)   # on RAW audio
clean, report = speechmix.debleed(mic_a, mic_b, rate, grid.only("guest"),
                                  target_only_mask=grid.only("olli"))

target = speechmix.programme_target({"olli": mic_a, "guest": mic_b}, rate, -16.0)
out, chain_report = speechmix.process_track(
    clean, rate, settings,
    gain_db=working_gain, speech_mask=grid.mask("olli"),
    target_lufs=target.stem_target_lufs,        # the trim goes in the target
)

envelopes = speechmix.duck_envelopes(grid)      # decisions, not samples
stems, ceiling_report = speechmix.programme_ceiling(stems, rate)
```

## What is in here

| module | what it owns |
|---|---|
| `chain` | the per-track chain, in order, with a report per stage |
| `grid` | who is talking, measured on the **raw** microphones |
| `debleed` | least-squares FIR leakage estimate, subtracted, and self-checked |
| `declick` | lip smacks, budgeted by **rate** rather than by a multiplier |
| `dynamics` | three bounded compression stages, the de-esser, the attack rule |
| `rider` | the slow level ride, which does nothing without a mask |
| `envelopes` | ducking as gain *decisions* a host can emit either way |
| `ceiling` | one limiter curve computed from the **sum**, applied to every stem |
| `loudness` | the programme target, and where the trim belongs |
| `verify` | the sample-count and time-shift guards |
| `fingerprint` | what "up to date" means, written out by hand |
| `plugin` | the one plug-in slot and the four ways it goes wrong |
| `timeline` | `Track` / `Span`: a placement on a programme timeline |
| `settings` | every knob that changes the result, in one dataclass |

## The tests are the asset

`tests/` encodes findings that each cost hours to discover, and they run
against the library in one place, atomically, on every change. If you take
nothing else from this package, take the tests. `FINDINGS.md` is the same
material in prose, with the numbers.

## Dependencies

numpy, scipy, pyloudnorm. Nothing else, deliberately: this directory is meant
to lift out of the workspace unchanged the day a fourth consumer wants it.
