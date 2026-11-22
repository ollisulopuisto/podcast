# Opt-in CUDA 13 experiment test

Run `python3 scripts/cuda13_test.py` on a Linux NVIDIA GPU machine, including a free Colab GPU VM or WSL2. Add an existing 5-15 second speech WAV path as the argument to test transcription too. In Colab mount Drive first through Google's UI and pass the mounted Drive path. This script does not mount or scan Drive. Audio is processed where the script runs, which means Google's VM for Colab, not solely your PC.

The script stops before any download on a failed driver/hardware gate. It clones the Kuulas experiment and required podcast path packages at pinned commits, installs pinned uv in a temporary bootstrap venv, and creates an isolated locked Kuulas environment. It makes no driver changes, uses no secrets, does not update the normal Kuulas checkout, and refuses CPU fallback. Allow several GB of dependency/model downloads and enough local disk space. No paid Colab resources are selected by the script. Select a free GPU session yourself; resources are not guaranteed.

Each stage prints PASS or FAIL. Without a WAV it explicitly says NOT RUN transcription, never a full transcription pass. A successful Torch stage requires a CUDA 13 build, a real GPU tensor calculation and the TorchAudio MMS_FA API. The optional speech stage is faster-whisper/CTranslate2's separate GPU runtime; missing CUDA libraries count as failure. It does not prove the complete editor, a CTC model pass, native packaging or another machine's driver compatibility.

Temporary checkout/environments are removed on ordinary success/failure. uv and model download caches can remain in the user's normal cache directories; terminating the process abruptly can leave temporary files. Existing user audio is read only, never modified or uploaded by the script. Whisper weights come from the model host. No user credentials are required.

Verification for this change: 21 regression cases pass without network/GPU (old driver, old GPU, missing GPU, command error, install failure, WAV path with spaces, optional transcription and native-Windows rejection). The tests failed before implementation. Repository-wide Ruff 0.17.2 passes. The actual script rejects unavailable hardware here and exits 1 before installing. Real GPU install/inference, WSL2, Colab, driver compatibility and model downloads remain UNRUN. No GPU was available in the execution environment.

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
