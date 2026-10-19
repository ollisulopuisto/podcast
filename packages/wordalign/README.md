# wordalign

Forced alignment of Whisper word starts to the audio. One file, numpy; torch and
torchaudio 2.8 only when the aligner itself is made (`make_aligner`).

It is one file because it is also **shipped**: `colab-transcribe` uploads
`wordalign.py` next to its Colab script, where the workspace does not exist.
`podcast-magic` imports it like any other package, so the two cannot drift.

The library knows nothing about either app. Give it Whisper's raw result
(`segments[].words[]`) and 16 kHz mono audio, and it gives back rows
(`align_raw`) or refined words (`refined`). The measurements behind the four rules
(split at pauses, accept a later shift up to 3 s, an earlier one only 0.3 s, a
rejected word keeps Whisper's time) are in the module docstring and in
`docs/KUULAS-TIMECODES.md`.

`python3 wordalign.py --check` loads the aligner (weights included) and exits;
`python3 wordalign.py jobs.json` aligns `[{"audio", "raw", "out"}, ...]`. Colab runs it
in its own process so torch's libraries do not mix with CTranslate2's.

Measured on one speaker, one episode and 15 hand-marked word starts. Word ends,
drift over a long recording, other speakers and the Colab GPU path are not measured.
