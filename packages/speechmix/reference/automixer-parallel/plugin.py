"""The one plug-in slot, and the four ways it goes wrong.

The slot exists because a speech-restoration model is the one thing this
pipeline has no opinion about and cannot ship.  Everything after it was
measured, and those numbers are the tool.  One slot, it runs first, and it
never stands in for a stage of the chain -- letting a second plug-in in would
quietly undo the measurements: someone loads a limiter in front of ours and the
ceiling guarantee stops being true with nothing to say so.

Four practical constraints, all measured:

* ``plugin.process(..., reset=False)`` **shortens** the result by the plug-in's
  latency (4641 samples with dxRevive).  Always ``reset=True``, and never feed
  one instance a file in chunks.
* pedalboard loads a VST3 on the **main thread only**; it processes from any
  thread.  The error text talks about processing and hides that the constraint
  is on loading, so a lazy per-thread load looks reasonable and fails every
  time.  Build every instance up front, on the main thread.
* Host the plug-in in a child process.  It is 97 % of the run and uses **one**
  core (measured 0.98 cores, 7.25x realtime), so the only way to reach the
  other cores is several instances at once.  Measured on a 20-minute file:
  168.4 s -> 68.3 s with the file cut into pieces, each its own full
  ``reset=True`` run with a five-second margin processed and thrown away.  It
  is not free -- the pieces do not see each other's context, so the difference
  from the whole-file result is 25.7 dB below the signal in speech and
  -84 dBFS in the quiet parts -- and the piece count belongs in the
  fingerprint.
* Not everything that changes the result is an automatable parameter.
  dxRevive publishes four, and the **model selector is not one of them** -- it
  lives in the plug-in's own state, reachable only through its own interface.
  Save the opaque state blob with the project and put it in the fingerprint.
"""

import numpy as np

from . import dsp
from .verify import assert_same_length

#: Each piece is processed with this much extra either side, which is then
#: thrown away, so the piece boundary lands on audio the plug-in had context for.
DEFAULT_MARGIN_SEC = 5.0


def process_in_pieces(run, audio, rate, pieces=1, margin_sec=DEFAULT_MARGIN_SEC):
    """Run a plug-in over the audio in ``pieces``, each a full independent run.

    Args:
        run: ``callable(chunk) -> chunk`` -- one full ``reset=True`` pass of the
            plug-in.  Never hand one instance a file in chunks: with
            ``reset=False`` the result comes back short by the plug-in's
            latency, and with several chunks the shortfall compounds silently.
        audio: Mono input.
        rate: Sample rate.
        pieces: How many independent runs to cut the file into.  This changes
            the result and belongs in the fingerprint.
        margin_sec: Context processed either side of each piece and discarded.

    Returns:
        The processed audio, with the sample count checked against the input.
    """
    x = dsp.as_mono(audio, "plug-in input")
    pieces = max(1, int(pieces))
    if pieces == 1:
        return assert_same_length(x, np.asarray(run(x), dtype=np.float64).ravel(), "plug-in")

    margin = int(margin_sec * rate)
    bounds = np.linspace(0, x.size, pieces + 1).astype(int)
    out = np.empty_like(x)
    for start, end in zip(bounds[:-1], bounds[1:]):
        lo, hi = max(0, start - margin), min(x.size, end + margin)
        processed = np.asarray(run(x[lo:hi]), dtype=np.float64).ravel()
        assert_same_length(x[lo:hi], processed, f"plug-in piece {start}:{end}")
        out[start:end] = processed[start - lo : start - lo + (end - start)]
    return assert_same_length(x, out, "plug-in")
