# Opt-in CUDA 13 experiment test

Run `python3 scripts/cuda13_test.py` on a Linux NVIDIA GPU machine, including a free Colab GPU VM or WSL2. Add an existing 5-15 second speech WAV path as the argument to test transcription too. In Colab mount Drive first through Google's UI and pass the mounted Drive path. This script does not mount or scan Drive. Audio is processed where the script runs, which means Google's VM for Colab, not solely your PC.

The script stops before any download on a failed driver/hardware gate. It clones the Kuulas experiment and required podcast path packages at pinned commits, installs pinned uv with isolated pip --target in a temporary directory (no stdlib venv or ensurepip), and creates an isolated locked Kuulas environment. It makes no driver changes, uses no secrets, does not update the normal Kuulas checkout, and refuses CPU fallback. Allow several GB of dependency/model downloads and enough local disk space. No paid Colab resources are selected by the script. Select a free GPU session yourself; resources are not guaranteed.

Each stage prints PASS or FAIL. Without a WAV it explicitly says NOT RUN transcription, never a full transcription pass. A successful Torch stage requires a CUDA 13 build, a real GPU tensor calculation and the TorchAudio MMS_FA API. The optional speech stage is faster-whisper/CTranslate2's separate GPU runtime; missing CUDA libraries count as failure. It does not prove the complete editor, a CTC model pass, native packaging or another machine's driver compatibility.

Temporary checkout/environments are removed on ordinary success/failure. uv and model download caches can remain in the user's normal cache directories; terminating the process abruptly can leave temporary files. Existing user audio is read only, never modified or uploaded by the script. Whisper weights come from the model host. No user credentials are required.

Verification for this change: 21 regression cases pass without network/GPU (old driver, old GPU, missing GPU, command error, install failure, WAV path with spaces, optional transcription and native-Windows rejection). The tests failed before implementation. Repository-wide Ruff 0.17.2 passes. The actual script rejects unavailable hardware here and exits 1 before installing. At initial implementation these hardware checks were unrun locally. The recorded owner T4 result below supersedes that initial status for its exact commits only; WSL2 and other machines remain untested.

Sources:
- https://docs.nvidia.com/deploy/cuda-compatibility/latest/minor-version-compatibility.html
- https://docs.nvidia.com/cuda/wsl-user-guide/
- https://docs.pytorch.org/audio/stable/installation.html
- https://research.google.com/colaboratory/faq.html

The runner now strips inherited uv/pip redirection settings, ignores user pip settings, and explicitly binds every uv sync/run to the temporary checkout's `.venv`. It also clears active-venv/Python-path overrides from its install/smoke children. PATH is checked for `nvidia-smi` first, with the documented WSL path as fallback.

On a mixed-GPU host, select one supported device with `CUDA_VISIBLE_DEVICES=GPU-...` (the UUID from `nvidia-smi -L`). Only that selected GPU is validated and exposed to the smoke processes. Empty/disabled selections fail; ambiguous numeric selections on multiple-GPU hosts and MIG selections are rejected before downloads. With no visibility setting, the first compatible physical GPU is selected and printed. If a UUID list is supplied, the first device is the test device.

System-wide pip settings are also disabled for bootstrap installation, and an empty or disabled first visibility-list entry fails before downloads. Four additional edge-case regressions pass.

The optional WAV check is not a CUDA-13-only transcription test. The pinned faster-whisper/CTranslate2 backend still needs CUDA 12 cuBLAS and CUDA-12-compatible cuDNN 9 available to its separate process. A successful Torch CUDA 13 stage does not supply or prove those libraries. This runner does not install system CUDA libraries or change drivers. If the WAV stage fails with missing CUDA 12/cuDNN libraries, that is a separate unmet runtime prerequisite, not proof the Torch CUDA 13 update failed. See https://github.com/SYSTRAN/faster-whisper#gpu and https://opennmt.net/CTranslate2/installation.html . The two upstream pages differ on the cuDNN major; the faster-whisper backend's current instructions specify cuDNN 9.

The existing Linux workflow now explicitly runs the runner's offline regression module. It does not run the GPU experiment in Actions.

Colab bootstrap no longer requires the distro python3-venv package. The runner executes the pinned uv wheel binary directly and does not pass PYTHONPATH to project processes. Install failures print captured stderr; a venv/ensurepip diagnostic includes the Debian/Ubuntu repair command, without running it automatically. The experiment pin now bounds PyAV below 19 for faster-whisper 1.2.1 compatibility. Real T4 inference remains a manual check.

The experiment now installs Linux CUDA 12 cuBLAS alongside Torch CUDA 13. Before the optional transcription process starts, the runner locates cuBLAS (and cuDNN if present) inside the project's own environment and prepends those library directories to that child's LD_LIBRARY_PATH only. It does not change the Torch child's path, create compatibility symlinks, or claim that CTranslate2 supports CUDA 13. A pass proves the two runtimes work side by side. cuDNN is not added by this change; a missing-cuDNN error remains a distinct reported prerequisite.

Pass --kuulas-path with the WAV to run the actual Kuulas local_whisper.local path after the Torch check. This opt-in stage uses tiny and allows low-memory operation, then requires nonempty word output and reports the first five word records, their flick timestamps and elapsed time. Kuulas local currently uses CPU int8 Whisper plus its separate CTC alignment worker; this is an end-to-end API check, not a claim that Kuulas itself transcribes on CUDA. Exceptions, invalid output and zero words fail as kuulas-align. The separate GPU faster-whisper smoke still runs afterward.

## Recorded owner Colab result, 2026-11-24 21:50 EET

Repository owner Olli Sulopuisto ran the Colab cell and supplied a successful run on Tesla T4, driver 580.82.07, compute capability 7.5, Python 3.13 environment, torch 2.13.0+cu130 (CUDA build 13.0) and torchaudio 2.11.1+cu132. The runner at podcast commit 5f3321c4ee16483f28eeaf608e97748f739c8e16 pinned Kuulas experiment 5ba4e993c1a29b0bdaf21c4d6483ffb3104d0fd7 and podcast path packages 40a7d503c2637e7c685c7ca1c56850385524600e. Locked installation, the Torch CUDA tensor operation, TorchAudio MMS_FA API availability and faster-whisper GPU transcription of the JFK sample all passed without CPU fallback.

This proves Torch CUDA13 and faster-whisper with CUDA12 cuBLAS worked side by side on that T4 session. It does not prove CT2 CUDA13 support, full Kuulas GUI operation, actual CTC alignment or another machine. The result predates the OpenTelemetry-only lock bump and podcast commit 29a8dce8ce731a9e57c7189112b5b0a4272952fa adding --kuulas-path. The current PR head and that new Kuulas-call stage have not been run on a T4 in this recorded result. Source: owner's iMessage output at 21:50:38 EET, 2026-11-24.


Selected console lines copied from the repository owner's pasted Colab output (GPU UUID omitted). These are evidence for the exact commits above, not a reviewer-run test:

```text
Selected GPU: Tesla T4; driver: 580.82.07; capability: 7.5
PASS hardware: driver-family/architecture gate; actual kernels checked below
PASS checkout: pinned experiment 5ba4e993c1a29b0bdaf21c4d6483ffb3104d0fd7
PASS install: isolated locked environment; no global packages changed
torch: 2.13.0+cu130
torchaudio: 2.11.1+cu132
Torch CUDA build: 13.0
GPU: Tesla T4
PASS: Torch CUDA 13 tensor operation and TorchAudio MMS_FA API
PASS torch: CUDA 13 tensor calculation and TorchAudio API
PASS: faster-whisper CUDA transcription completed without CPU fallback
PASS transcription: Torch CUDA 13 plus faster-whisper CUDA 12 libraries; nonempty GPU output, no CPU fallback
PASS requested stages; full Kuulas GUI, CTC model and other machines remain untested
```
