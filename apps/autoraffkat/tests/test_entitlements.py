"""Allekirjoitusoikeudet, joita pakattu sovellus tarvitsee (hardened runtime)."""

import plistlib
from pathlib import Path

ENTITLEMENTS = Path(__file__).resolve().parents[1] / "autoraffkat.entitlements"


def _ents() -> dict:
    return plistlib.loads(ENTITLEMENTS.read_bytes())


def test_jit_entitlements_for_numba():
    ents = _ents()
    assert ents["com.apple.security.cs.allow-jit"] is True
    assert ents["com.apple.security.cs.allow-unsigned-executable-memory"] is True


def test_third_party_plugins_can_be_loaded():
    """Käyttäjän VST3/AU-liitännäiset on allekirjoittanut joku muu tiimi.
    Ilman tätä oikeutta hardened runtime hylkää ne («Unable to scan plugin»)."""
    assert _ents()["com.apple.security.cs.disable-library-validation"] is True
