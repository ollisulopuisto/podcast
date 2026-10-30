# Colab cloud timing handoff

Branch: `codex/asr-backend-sharing`, based on `5a179e6`.

## Change

Cloud `run_audio` now stores the selected engine's canonical timing model in word JSON. Whisper aliases (including `turbo`) map to `whisper`; Parakeet Ultra aliases map to `parakeet-ultra`. Asking the cloud timing mapper for Orukeet gives explicit local-backend guidance rather than silently using Ultra.

## Verification

- Red-green regressions cover Whisper timing and reject the accidental Orukeet-to-Ultra mapping.
- Colab Transcribe suite: 398 passed.
- Ruff: clean.
- Commit: `4dad4e9` (`fix(colab): preserve selected ASR timing`).
- Real Colab inference was not run.
