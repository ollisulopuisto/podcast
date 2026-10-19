# Transcription word times: what was measured, what exists, what kuulas can use

Answers the kuulas session's five questions on the transcription timecodes. Written
2026-10-19 by the podcast-repo session. Short version: **there is no fix to integrate
yet.** There is a measurement, and a candidate correction that exists only as an
experimental script on an open pull request. The owner decides whether and where it goes.

"Measured" means checked against word starts the owner placed by hand on the waveform.
"Proposed" means not built.

## 1. What was wrong

**Whisper's word start is early.** Measured on one raw microphone recording
(`vst s13e04 - 2026-10-15`, the file `Olli 1.wav`, one speaker, a 10-minute window from
10:00, 707 words) with the real pipeline's transcription settings
(`whisper-ctranslate2 --batched True --vad_filter True --model turbo --language fi
--word_timestamps True --condition_on_previous_text False`, as in
`colab-transcribe/.../pipeline.py`), on 15 hand-marked word starts:

| | Whisper, error against the owner's mark |
|---|---|
| word starts too early | 14 of 15 |
| median | +87 ms early |
| median absolute error | 117 ms |
| range | -118 ms (late) .. +557 ms (early) |
| after a pause (7 words) | median +263 ms early |
| inside a phrase (8 words) | median +63 ms early |

Plus, about 1 % of the words (8 of 707) have a start that is **1.0 to 2.5 s early**. Four of
those eight were checked by ear: in each, the true start was where the forced aligner
(section 2) said, within 34 ms, and 1.0, 1.4, 1.5 and 2.5 s after Whisper's stamp. Such a
word's Whisper interval often swallows the pause and the end of the previous word
(`suomenkielinen?` stamped at 40.24 s, heard at 41.24 s; the five words before it fit in 0.66 s
on Whisper's clock). Two words stamped 0.18 s apart (`kuin`, `tota...`) are another
symptom: Whisper collapses hesitations.

**No constant fixes it.** A global shift of +87 ms would leave errors from -205 to +470 ms.
So it is not a per-media offset.

**What was not measured.** Say plainly, since kuulas asked about each:
- *Drift over a long recording:* not tested. The marks run from 9 s to 5 min of one 10-minute
  window; no trend is visible in 15 words, but that is not a drift test.
- *Word end precision:* not measured at all. Only starts were marked.
- *Mismatch between the .nhsx and the audio:* not examined.
- *The Colab path:* the transcription was made locally on a Mac (CPU, `compute_type auto`) with
  the same flags as the Colab script, not on the Colab GPU.
- *Other speakers, other episodes:* one speaker, one episode.
- The marks are one person's, placed by eye on the waveform at about 100 ms zoom (so about
  +-20-30 ms), and a soft-onset consonant can be audible a little before the visible rise.

## 2. Where the fix lives

**Nowhere yet.** `nhsx`, `speechmix`, the transcribe app and `colab-transcribe`'s
`pipeline.py` are unchanged.

What exists: `scripts/ab/ctc_align.py` and `tests/test_ctc_align.py`, on branch
`feat/ctc-word-align`, pull request
[ollisulopuisto/podcast#59](https://github.com/ollisulopuisto/podcast/pull/59), **open, not
merged**. It forces the transcript's text onto the audio with torchaudio's `MMS_FA` (CTC,
20 ms frames, multilingual including Finnish), one group of words at a time, and writes each
word's aligned start and end. It does not change any transcript.

The candidate correction, on the same 15 words:

| | Whisper | forced aligner |
|---|---|---|
| median error | +87 ms | +6 ms |
| median absolute error | 117 ms | **28 ms** |
| within 50 ms | 2 / 15 | 12 / 15 |
| within 100 ms | 7 / 15 | 14 / 15 |
| after a pause | +263 ms | -6 ms |

One word is far off (`Mitäs`, +173 ms). Words starting with a soft consonant (n, j, h, s) tend to
be 30-80 ms *late* in the aligner (5 of 7), plosives and vowels are within about +-40 ms; the
tendency is not a rule (`Joo.` once +7 ms, once -44 ms) and is not corrected for.

Safety rules in the script, from what was measured: words are aligned in groups split at
pauses over 0.5 s (a 2.9 s pause with another microphone's sound in it once made the aligner place
a word 2.7 s early); an alignment more than 3 s later than Whisper's stamp, or more than 0.3 s
earlier, is rejected and the word keeps no aligned time (`ctc_start` empty). The
asymmetry is deliberate: Whisper is almost always early.

## 3. Does the data format change?

Not today: nothing in the repo writes or reads a changed format. The script reads Whisper's own
JSON (`segments[].words[]` with `word`, `start`, `end`, in seconds) and writes a CSV:

```
word,whisper_start,whisper_end,ctc_start,ctc_end
```

- **Unit:** seconds, floats, written with 3 decimals.
- **Origin:** the start of the audio file that was passed in, the same clock as Whisper's
  stamps. Kuulas would convert to flicks from the media's start as it does now.
- **Empty fields:** `ctc_start` / `ctc_end` are empty for a word that was not aligned (no letters in
  it, or rejected). Empty is not zero.
- **Ends are not validated.** If kuulas uses `ctc_start`, it should use `ctc_end` from the same row so
  that start < end, and treat ends as unverified.

If this is integrated, a marker is needed that tells a corrected transcript from an old one
(for example a `timing` field on the media, `whisper` or `ctc-v1`). That does not exist; it is
a decision for the integration, not yet made.

## 4. Do existing transcripts need redoing?

They carry Whisper's raw times, so yes, to benefit; the fix does not apply on import. It needs
the audio and a model run (the first run downloads about 1.2 GB of weights, and a 10-minute
window took a few minutes on a Mac CPU), but **not a new transcription**: the aligner takes
Whisper's JSON. podcast-magic keeps that JSON next to the job (`transcripts/<stem>.<fingerprint>.json`,
`transcribe/run.py`). An adapter from the words stored in an `.nhsx` back to the aligner's input has not
been written. There is no version field to tell a fixed transcript from an old one.

For kuulas's word deletion: a cut from Whisper's start includes a little silence in the usual case,
which is harmless, but for the 1 % of words stamped 1-2.5 s early it would also cut the previous
word. That is the case a correction matters for.

## 5. How kuulas should call it

Today, a command line only:

```
uv run --package speechmix --with torch==2.8.0 --with torchaudio==2.8.0 \
    python scripts/ab/ctc_align.py <whisper.json> <audio.wav> --csv <out.csv>
```

The audio must be the one the transcript was made from, with the same time zero. The pieces are
importable from the script (`align_transcript(data, audio_16k, aligner, pad, errors)`,
`make_torchaudio_aligner()`, `resample(x, rate)`), but a script is not an API and nothing promises its
shape. torch 2.8.0 is pinned because `torchaudio.functional.forced_align` is removed after it, and
torch is a heavy dependency for kuulas to take on. Do not call this from kuulas yet.

## What decides the next step

1. Whether the owner wants the aligner in the pipeline, and where (the transcribe app's post-step,
   a `speechmix` module, and the Colab script as a copy, which then drifts).
2. Ends: measure a few word ends before anything uses them.
3. A second speaker, and a window from another episode, before the numbers above are trusted
   beyond one voice.
