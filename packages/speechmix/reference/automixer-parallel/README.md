# A parallel implementation, kept for reference only

**Nothing here is imported by anything. Do not wire it up.**

This is a second implementation of the speech chain, written in the automixer
session before `packages/speechmix` existed here, against the findings in
autoraffkat's `SHARED-AUDIO.md` rather than against its code. When the
canonical package turned up it was the wrong half of the work: `chain.py`,
`debleed.py`, `declick.py`, `dynamics.py` and `rider.py` in the package one
directory up are the measured originals, and these are a re-derivation of the
same findings.

It is kept because the request was that no code be stranded in the repository
that is about to be archived, and because two things in it might be worth
lifting before it is deleted:

- `tests/test_declick.py`, `tests/test_dynamics.py`, `tests/test_debleed.py`
  and the fixtures in `tests/material.py`. They are written against *this*
  API, so they will not run against the canonical modules unchanged, but the
  properties they assert are the ones the findings ask for: a correction rate
  rather than a multiplier, every compression stage reporting whether it
  fired, a de-bleed filter that measures its own output. `tests/material.py`
  encodes the fixture lesson too — bursts must vary in level, or every
  absolute threshold sits above the signal and the test passes while measuring
  nothing.
- `dynamics.py` has a linear-dB release computed as a running minimum
  (`y[i] = min(gr[i], y[i-1] + slope)` rewritten as a cumulative minimum), which
  is O(n) and does not under-charge on events shorter than its own time
  constant the way a one-pole does. The canonical `chain.compress` uses
  `min(one_pole(release), instant)`, which is the shape that made a sibilant
  duck the gain by a decibel and let go immediately instead of holding the
  sentence down.

Everything else here is duplication. The honest recommendation is to take
those two things and delete the directory; it is only still here because
deleting someone's work is not mine to do unasked.

The parts of this work that *were* additive — the programme ceiling, the
speech grid, the duck envelopes, the programme loudness target, the timeline
types, the sample-count and shift guards, and the fingerprint — are not here.
They went into the package proper, because the canonical package did not have
them.
