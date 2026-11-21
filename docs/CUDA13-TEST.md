# Opt-in CUDA 13 experiment test

Run `python3 scripts/cuda13_test.py` on a Linux NVIDIA GPU machine, including a free Colab GPU VM or WSL2. Add an existing 5-15 second speech WAV path as the argument to test transcription too. In Colab mount Drive first through Google's UI and pass the mounted Drive path. This script does not mount or scan Drive. Audio is processed where the script runs, which means Google's VM for Colab, not solely your PC.

The script stops before any download on a failed driver/hardware gate. It clones the Kuulas experiment and required podcast path packages at pinned commits, installs pinned uv in a temporary bootstrap venv, and creates an isolated locked Kuulas environment. It makes no driver changes, uses no secrets, does not update the normal Kuulas checkout, and refuses CPU fallback. Allow several GB of dependency/model downloads and enough local disk space. No paid Colab resources are selected by the script. Select a free GPU session yourself; resources are not guaranteed.

Each stage prints PASS or FAIL. Without a WAV it explicitly says NOT RUN transcription, never a full transcription pass. A successful Torch stage requires a CUDA 13 build, a real GPU tensor calculation and the TorchAudio MMS_FA API. The optional speech stage is faster-whisper/CTranslate2's separate GPU runtime; missing CUDA libraries count as failure. It does not prove the complete editor, a CTC model pass, native packaging or another machine's driver compatibility.

Temporary checkout/environments are removed on ordinary success/failure. uv and model download caches can remain in the user's normal cache directories; terminating the process abruptly can leave temporary files. Existing user audio is read only, never modified or uploaded by the script. Whisper weights come from the model host. No user credentials are required.

Verification for this change: eight regression cases pass without network/GPU (old driver, old GPU, missing GPU, command error, install failure, WAV path with spaces, optional transcription and native-Windows rejection). The tests failed before implementation. Repository-wide Ruff 0.17.2 passes. The actual script rejects unavailable hardware here and exits 1 before installing. Real GPU install/inference, WSL2, Colab, driver compatibility and model downloads remain UNRUN. No GPU was available in the execution environment.

Sources:
- https://docs.nvidia.com/deploy/cuda-compatibility/latest/minor-version-compatibility.html
- https://docs.nvidia.com/cuda/wsl-user-guide/
- https://docs.pytorch.org/audio/stable/installation.html
- https://research.google.com/colaboratory/faq.html
