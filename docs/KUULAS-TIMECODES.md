# Transcription word times: what was measured, what exists, what kuulas can use

Answers the kuulas session's five questions on the transcription timecodes. Written
2026-10-19 by the podcast-repo session; **status updated the same day after the fix was
merged** (PR [#62](https://github.com/ollisulopuisto/podcast/pull/62)). Short version: the
correction **exists and runs on Colab** (`colab-transcribe --audio ... --json ... --align`),
and the file says whether it was applied (`"timing": "ctc-v1"` or `"whisper"`). It has been
measured on **one speaker in one episode**, so treat it as a measured improvement there and not
as a guarantee elsewhere.

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
- *The Colab path:* the 15 marks above were measured with a local transcription on a Mac (CPU).
  Afterwards the same 10-minute clip was run once on a real Colab T4: Whisper's own starts showed
  the same pattern (four hand-marked words 0.7-2.4 s early), and the aligned starts (section 2)
  were within 41 ms of the 12 marks in that clip. One run, one clip; no timing or cost was recorded.
- *Other speakers, other episodes:* one speaker, one episode.
- The marks are one person's, placed by eye on the waveform at about 100 ms zoom (so about
  +-20-30 ms), and a soft-onset consonant can be audible a little before the visible rise.

## 2. Where the fix lives

On `main`:

- `packages/wordalign/` is the aligner, **one file** (`wordalign.py`, numpy; torch only when the
  aligner is made). It forces the transcript's text onto the audio with torchaudio's `MMS_FA` (CTC,
  20 ms frames, multilingual including Finnish), one group of words at a time. The transcribe app
  imports it, and `colab-transcribe` uploads the same file to the Colab VM.
- `podcast-magic`: *Correct word starts* (`Options.align`, off by default), a post-step on Whisper's
  saved JSON.
- `colab-transcribe --audio ... --json ... --align`: Whisper and the aligner both run on the VM.
  The result is `<stem>.words.json` (section 3).
- `scripts/ab/ctc_align.py` measures the same code against hand-marked starts.

The correction, on the 15 marked words (one speaker, local run):

| | Whisper | forced aligner |
|---|---|---|
| median error | +87 ms | +6 ms |
| median absolute error | 117 ms | **28 ms** |
| within 50 ms | 2 / 15 | 12 / 15 |
| within 100 ms | 7 / 15 | 14 / 15 |
| after a pause | +263 ms | -6 ms |

On the Colab run, 12 marked words in the same clip: aligned start within 6-41 ms of the mark (median
about 23 ms), Whisper's median error about 180 ms with a worst case of 2.4 s. **This second check is not
independent**: the same words and speaker are what the rules below were tuned on. It shows that the
Colab path works and gives the same quality, not that the result holds for other voices.

One word is far off in the first measurement (`Mitäs`, +173 ms). Words starting with a soft consonant
(n, j, h, s) tend to be 30-80 ms *late* in the aligner (5 of 7); the tendency is not a rule and is not
corrected for.

Safety rules, from what was measured: words are aligned in groups split at pauses over 0.5 s (a 2.9 s
pause with another microphone's sound in it once made the aligner place a word 2.7 s early); an
alignment more than 3 s later than Whisper's stamp, or more than 0.3 s earlier, is rejected and the word
keeps Whisper's time. The asymmetry is deliberate: Whisper is almost always early. The word end is the
longer of Whisper's end and the aligner's; ends are not validated.

## 3. Does the data format change?

Yes, in `colab-transcribe`'s plain-audio mode (`docs/KUULAS-COLAB.md` has the whole contract):

```json
{"version": 1, "timing": "ctc-v1", "language": "fi", "rejected": 2,
 "words": [{"w": "Niin,", "s": 8.923, "e": 9.48}]}
```

- **Unit:** seconds, floats, 3 decimals. **Origin:** the start of that audio file (Whisper's clock).
- **`words`** are in time order with `s < e`. An overlap shortens the earlier word, not the next.
- **`timing`:** `ctc-v1` when the starts were corrected, `whisper` when they are Whisper's own.
  `rejected` is the number of words the aligner could not place (they keep Whisper's time).
- **Ends are approximate** and unvalidated.
- The app's `.nhsx` path is unchanged: with the option on, corrected starts are written into the
  session instead of Whisper's.

## 4. Do existing transcripts need redoing?

They carry Whisper's raw times, so yes, to benefit; the fix does not apply on import. For a
`podcast-magic` job the correction does **not** repeat the transcription: it reads the saved Whisper
JSON (`transcripts/<stem>.<fingerprint>.json`) and keeps its own cache. For kuulas, re-run
`colab-transcribe --audio ... --align` on the media. An adapter from words stored in an `.nhsx` back to the
aligner's input has not been written. The `timing` field tells a corrected file from an old one.

For kuulas's word deletion: a cut from Whisper's start includes a little silence in the usual case,
which is harmless, but for the 1 % of words stamped 1-2.5 s early it would also cut the previous
word. That is the case a correction matters for.

## 5. How kuulas should call it

```
uvx --from "git+https://github.com/ollisulopuisto/podcast#subdirectory=colab-transcribe" \
    colab-transcribe --audio "/path/media.wav" --json ~/words --align --progress
```

The command string is a setting in kuulas; the cloud side installs torch 2.8 into its own folder, and
checks the aligner before it transcribes. `--progress` prints `PROGRESS <0-100> <message>` lines;
SIGTERM stops the Colab session; a missing result is exit 1 with the reason on stderr. First run: it
installs torch on a fresh VM and downloads about 1.2 GB of weights. Cost and wall time were not recorded;
transcription speed does not matter much when the run is in the background.

## What decides the next step

1. A second speaker and a window from another episode, with a few hand-marked starts each, before the
   numbers above are trusted beyond one voice. This is the largest open question.
2. Ends: measure a few word ends before anything uses them.
3. Drift over a long recording (the clip is 10 minutes).
4. Cost of a Colab run per hour of audio, if it matters.
