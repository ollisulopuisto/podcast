# ASR coverage audit — 2026-10-30

## Scope and evidence boundary

This is a source audit, not an inference benchmark or a model certification.
The baseline is commit `5a179e6f16024a0e1aa6fa9d01a0edcb09cdf2fc`, tagged
`podcast-magic-v2026.10.29.1`, as specified in the
[handoff](2026-10-30-asr-backend-handoff.md). Files were read from that exact
Git object through an archive in `/private/tmp/asr-coverage-audit-20261030`.
No implementation or tests were edited and nothing was committed.

The primary checkout is a different source state: branch `feat/colab-orukeet`,
HEAD `9d7f6665b52aa57d7b1cc34ee4fb0b035a375574`, with existing uncommitted
Colab/wordalign changes. At the start of this audit its local `main` ref was
`f9206ddfd566ae0ab0e8f96ae358fa94d000ddd0`; it must not be mistaken for the
handoff baseline. Those changes were preserved. Differences relevant to this
audit are listed separately below.

Evidence levels used here:

* **Code**: the app has a reachable adapter and selection path. This does not
  establish that the vendor runtime supports that model/device combination.
* **Mock tests**: tests exercise adapter arguments, conversion, or routing with
  substituted runtimes. They do not load model weights or prove inference.
* **Recorded smoke**: repository documentation reports a real runtime run,
  with its stated sample and hardware. This audit did not repeat it.
* **Unverified**: no applicable real runtime/model run was established by this
  audit. An installed SDK or an `available: true` response is insufficient.

## Execution coverage at the baseline

| App / engine | Local Apple Silicon | Local CPU | Local NVIDIA CUDA | Google Colab |
|---|---|---|---|---|
| Podcast Magic / Whisper | **Code**: `mlx` uses `mlx-whisper` on Metal; `faster-whisper` also offers CPU. Default `auto` selects MLX first when available. | **Code**: `faster-whisper` explicitly uses `device="cpu", compute_type="int8"`, including Intel Mac/Windows/Linux. | **No CUDA selection**: the adapter forces CPU even if faster-whisper itself supports other devices. | **No Colab driver** in Podcast Magic. Use Colab Transcribe for cloud execution. |
| Podcast Magic / Orukeet | **Code, runtime unverified**: native SDK receives the model, runtime, and device from an installation receipt. Metal support is claimed by its install/device description, not established by an inference run here. | **Code, runtime unverified**: same receipt-driven adapter; no separate CPU implementation or test run established. | **Code, runtime unverified**: same receipt-driven adapter; no separate CUDA implementation or test run established. | **No cloud Orukeet path**. Its adapter is local. |
| Podcast Magic / Parakeet Ultra | Adapter is present, but **no supported Apple Silicon Ultra route is established**. `info()` can advertise availability merely because `moondream` imports. README directs Mac users to MLX Whisper or Orukeet. | **No supported CPU Ultra route established**; the package comment says NVIDIA GPU is required. No CPU preflight rejects this configuration. | **Code, runtime unverified**: `md.photon("moondream/parakeet-ultra")` uses automatic device selection. The app supplies no explicit CUDA/device flag. | **No Colab driver**. The separate Colab Transcribe adapter is the cloud implementation. |
| Colab Transcribe / Whisper | **No local Whisper backend**. `--backend colab --model whisper` runs remotely, even when launched from a Mac. | **No local Whisper backend**. | **No supported local CUDA mode** through the public driver. The uploaded script has CUDA calls, but manually running that script is not a local backend contract. | **Code + mock tests**: `--backend colab --model whisper` selects Photon `openai/whisper-large-v3-turbo`, explicitly `device="cuda"`. No real Photon Whisper smoke was established. |
| Colab Transcribe / Orukeet | **Code + mock tests, runtime unverified**: `--backend orukeet` uses the native receipt-driven SDK and mandatory local CTC word alignment. Audio mode only. | **Code, runtime unverified**: receipt-driven device; no CPU preflight/model execution evidence. | **Code, runtime unverified**: receipt-driven device; no CUDA preflight/model execution evidence. | **No cloud Orukeet engine**. The public cloud model choices are Ultra and Whisper. |
| Colab Transcribe / Parakeet Ultra | **No local Ultra backend**. `--backend parakeet` is a different MLX model family, described below. | **No local Ultra backend**. | **No public local Ultra backend**. | **Code + mock tests + recorded smoke**: default cloud model is Photon `moondream/parakeet-ultra`, explicitly `device="cuda"`. The documented real run used a Colab T4 on 2026-10-27, synthetic Finnish speech, downloaded 1.26 GB of model files, and wrote seven timestamped words. |

The recorded Ultra T4 result is a short functionality check. It establishes
neither podcast accuracy nor long recording stability, throughput, end-time
accuracy, L4/A100 behavior, or compatibility of Photon Whisper with the same
runtime. `GPUS = ("T4", "L4", "A100")` describes selectable Colab resources;
it is not a record of three tested GPUs. Documentation says the cloud
`--align` path has not been run on real Colab.

The established local Whisper history is stronger than that of the newly
added adapters: Podcast Magic's `CLAUDE.md` records real Whisper/CTC timing
measurements on one podcast episode, one speaker, and 15 marked words. Those
measurements do not certify every Whisper model/device in this matrix or the
newly packaged DMG. This audit performed no new local Whisper inference.

### A separate local Parakeet model must not be called Ultra

Colab Transcribe also has `--backend parakeet`, implemented in `parakeet.py`
with `parakeet-mlx`. The baseline default is
`mlx-community/parakeet-tdt-0.6b-v3`, not `moondream/parakeet-ultra`.
Availability explicitly requires Darwin/arm64, an installed MLX package, and
at least 16 GiB physical RAM under a provisional policy unless
`--allow-low-memory` is passed. Its call uses 120-second chunks with
15-second overlaps. Mock tests exercise token-to-word conversion and the
chunk arguments. This establishes a local Apple Silicon TDT code path,
not local Ultra support or a real long-audio model test.

## Entry points, options, and output contracts

| Surface | Whisper | Orukeet | Parakeet Ultra |
|---|---|---|---|
| Podcast Magic backend key | `mlx` / `faster-whisper`; `auto` tries these first. | `orukeet`; later than both Whisper adapters in `auto`. | `parakeet-ultra`; last in `auto`. |
| Podcast Magic model selection | `turbo`, `large-v3`, `medium`, `small`; Python/API accepts a custom ID through `model_choice`. The current UI has a fixed select. | Receipt `model` and `runtime`; `Options.model` does not select the Orukeet model. | Fixed `moondream/parakeet-ultra`; `Options.model` is ignored by its adapter. |
| Podcast Magic word clock | Native Whisper word timestamps; optional CTC correction. | Segment text is converted to CTC inputs. `run()` requires `align=True`; every word must align before output. Segment-wide seed times are not final word times. | Requests `timestamps="word"` from Photon; optional CTC correction. |
| Podcast Magic public selection | UI or `/api/transcribe` options; `--chain` reads saved settings. | Same UI/API path; UI enables required alignment when available. | Same UI/API path. |
| Colab Transcribe public selection | `--backend colab --model whisper`. | `--backend orukeet`; only `--audio … --json …`. | `--backend colab --model parakeet-ultra`, also the default. |
| Colab input modes | Cloud audio, per-track session transcription, and downmix. | Local audio only; session/downmix rejected by `RunOptions`. | Cloud audio, per-track session transcription, and downmix. |
| Colab word clock | Photon word timestamps; optional cloud CTC in audio mode. Baseline unaligned JSON has a timing-label defect below. | Mandatory local CTC; JSON `timing="orukeet-ctc"`. | Photon word timestamps; JSON `timing="parakeet-ultra"`, or shared CTC version when aligned. |

### Concrete CLI/API gaps at `5a179e6`

1. **Whisper cloud timing is mislabeled.** `pipeline.run_audio()` calls
   `words_document(raw, language)` without selecting `timing` from `model`.
   Its default is `"parakeet-ultra"`, so `--model whisper` can write Whisper
   times labeled as Ultra times. The primary checkout already contains an
   uncommitted fix that passes `timing=model`; do not overwrite that work.

2. **Availability is not model/device readiness.** Podcast Magic Ultra only
   imports `moondream`. Orukeet checks the SDK, receipt existence, and
   torch/torchaudio module specs, but does not validate receipt content,
   runtime/model/device compatibility, supported torchaudio API version, or
   model load. Colab's local Orukeet check imports torch/torchaudio and checks
   ffmpeg, but likewise does not load the receipt/model/aligner. Failures can
   occur after these checks report success.

3. **Podcast Magic has no per-run ASR CLI flags.** `podcast-magic --chain`
   exposes no `--backend`, `--model`, `--language`, or `--align`; it relies on
   saved UI settings. The HTTP API can supply those fields. faster-whisper's
   CPU/int8 choice is hardcoded, and Ultra has no explicit device control.

4. **Cloud Whisper does not restore Whisper's prior prompt behavior.**
   Photon Whisper and Ultra both ignore `initial_prompt` in the uploaded
   script and report the omission. `--language` is an output label; both
   Photon models auto-detect language. The CLI's `--prompt` help still calls
   it Whisper filler words, while the pipeline does not apply it. Neither
   cloud model receives the MLX/faster adapter's filler or VAD switches.

5. **Some accepted local options have no effect.** Local Orukeet takes its
   model from the receipt; local Parakeet takes `parakeet_model`. Cloud
   `--model` does not choose their engine. Local Parakeet does not consume
   `options.align`, so passing `--align` does not perform the promised
   optional CTC correction there. Local Orukeet always aligns irrespective
   of that flag. The primary checkout's `--orukeet-model` alias targets
   `parakeet_model`, which the native Orukeet implementation does not read.

6. **The Colab TUI does not expose the full selection surface.**
   `collect_options()` reconstructs `RunOptions` without preserving
   `backend`, `model`, `source`, `language`, or `align`. It therefore defaults
   to cloud Ultra/tracks even when the initial options named another model.
   CLI routing and TUI routing should not be described as equivalent for
   these choices.

7. **Cache identity has limits.** Podcast Magic distinguishes explicit
   Orukeet/Ultra from Whisper in the fingerprint, but MLX and faster-whisper
   share `"whisper"`; `initial_prompt` and the Orukeet receipt's model/runtime
   are absent. A backend or receipt change can therefore reuse cached output
   rather than establish that the newly selected runtime ran. Irrelevant
   Whisper model/filler/VAD fields still change Orukeet/Ultra fingerprints.

8. **Progress granularity differs.** Podcast Magic Whisper reports frame or
   segment progress. Ultra and native Orukeet mainly report before/after a
   whole SDK call and check cancellation at those boundaries. They have no
   implemented in-call SDK cancellation/progress hook in these adapters.

### Packaging limits

The baseline has Podcast Magic extras for `mlx`, `faster`, `orukeet`, and
`ultra`; the PyInstaller spec attempts to collect their installed SDKs.
Orukeet's native model/runtime is installed separately with `orukeet install`
and read through `ORUKEET_INSTALLATION` or
`~/.cache/orukeet/installation.json`. Its CTC dependencies are also a
separate concern: the app's instructions say the packaged app does not
include torch and alignment is unavailable there. An SDK in a DMG cannot
be reported as a working Orukeet word-timing route without validating the
packaged aligner and external native installation.

Ultra's Python SDK being included on macOS likewise does not establish an
Apple GPU Ultra implementation. No Apple Silicon Ultra inference result was
found. The handoff's successful Mac build/DMG recovery is packaging evidence,
not an inference check for every registered engine.

## Existing primary-checkout work

These observations refer to the existing dirty primary checkout, separately
from the release baseline:

* Cloud Photon Whisper/Ultra selection and the native Orukeet module are
  present. The Whisper `timing=model` output correction is already applied.
* Local `--orukeet-model` remains an alias of the MLX model field despite
  native Orukeet now using the installation receipt. A detected
  `~/.models/orukeet-mlx` directory can become the default MLX model, another
  reason not to infer Ultra or native Orukeet execution from a display label.
* The checkout lacks several later release changes, including the baseline
  `CLOUD_MODELS` validation, local RAM policy, and updated clean-install
  dependencies. Copying the entire dirty tree over the baseline would regress
  unrelated fixes. Port only reviewed paths/hunks with corresponding tests.

## Source index and validation

All source paths in this section mean the baseline commit unless explicitly
marked as primary-checkout work:

* Podcast Magic: `transcribe/backends/{__init__,mlx,faster,orukeet,ultra}.py`,
  `transcribe/{options,models,run,align,api}.py`,
  `server/static/mod_transcribe.js`, `__main__.py`, `chain/cli.py`,
  `pyproject.toml`, and `podcast-magic.spec` under
  `apps/podcast-magic/` (Python paths are under `src/podcastmagic/`).
* Colab Transcribe: `src/colabtranscribe/{options,__main__,tui,parakeet,orukeet}.py`,
  `src/colabtranscribe/colab/pipeline.py`, `pyproject.toml`, `README.md`,
  `README.fi.md`, and `CLAUDE.md` under `colab-transcribe/`.
* Mock coverage: Podcast Magic `tests/test_backends.py` and
  `tests/test_transcribe.py`; Colab `tests/test_{audio_mode,pipeline,orukeet_backend,parakeet_backend}.py`.
  Runtime substitutions in these tests were inspected; their presence is not
  a claim that this audit ran the full suites.

Validation for this documentation-only audit:

* `UV_CACHE_DIR=/private/tmp/asr-coverage-uv-cache uv run --no-sync ruff check .`
  passed in the primary checkout. The unmodified command could not acquire
  its lock because the sandbox denied writes to `~/.cache/uv`; the temporary
  cache avoids changing that directory.
* No member test suite was run for this read-only source audit. No production
  code or test was changed. Other agents' test results must be reported with
  their own source state.
* No model download, local model inference, packaged-app inference, NVIDIA
  inference, or live Colab run was performed. Those runtime/device cells
  remain unverified except for the explicitly attributed historical T4 smoke.
