"""colab-transcribe: paikallinen ajuri Colabissa ajettavalle ketjulle.

Versio johdetaan asennuksesta eikä kirjoiteta auki: yksi numero vähemmän
joka voi jäädä jälkeen. Ks. `tests/test_workspace_agrees.py`.
"""

import importlib.metadata
from importlib.metadata import PackageNotFoundError

try:
    __version__ = importlib.metadata.version("colab-transcribe")
except PackageNotFoundError:  # pragma: no cover - ajetaan ilman asennusta
    __version__ = "0.0.0"
