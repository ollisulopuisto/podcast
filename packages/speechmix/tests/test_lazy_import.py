"""``import speechmix`` ei tuo alimoduuleja ennen kuin niitä pyydetään.

Paketin ``__init__`` toi kaikki alimoduulit heti, joten pelkkä
``import speechmix`` (tai ``from speechmix.stems import StemError``) maksoi
0,74 s, josta ``scipy.signal`` 0,55 s (Linux, lämmin välimuisti,
``-X importtime``). ``automixer --help`` ei tarvitse niistä yhtään.

Omassa prosessissaan: muiden testien tuonnit eivät vuoda ``sys.modules``iin.
"""

from __future__ import annotations

import json
import subprocess
import sys


def _modules_after(code: str) -> list[str]:
    done = subprocess.run(
        [sys.executable, "-c", code + "\nimport json, sys; print(json.dumps(sorted(sys.modules)))"],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(done.stdout.splitlines()[-1])


def test_importing_the_package_imports_no_submodule_and_no_scipy():
    modules = _modules_after("import speechmix")
    assert [m for m in modules if m.split(".")[0] in ("scipy", "numpy", "numba")] == []
    assert [m for m in modules if m.startswith("speechmix.")] == ["speechmix.messages"]


def test_set_translator_is_still_at_the_top():
    modules = _modules_after("from speechmix import set_translator")
    assert "scipy" not in modules


def test_a_submodule_is_imported_when_first_asked_for():
    import speechmix

    assert speechmix.timeline.Track is not None
    from speechmix import grid

    assert grid is speechmix.grid


def test_every_name_in_all_is_reachable():
    import speechmix

    for name in speechmix.__all__:
        assert getattr(speechmix, name) is not None, name
        assert name in dir(speechmix)


def test_an_unknown_name_is_still_an_attribute_error():
    import pytest

    import speechmix

    with pytest.raises(AttributeError, match="no_such_module"):
        speechmix.no_such_module  # noqa: B018
