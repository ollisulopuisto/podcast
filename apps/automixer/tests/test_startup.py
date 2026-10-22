"""``automixer --help`` ja lippuvirheet eivät tuo raskaita moduuleja.

kuulas ajaa ``automixer --help`` (10 s aikaraja, myös ssh:n yli toisella
Macilla) ennen jokaista miksausta nähdäkseen mitkä liput on olemassa. Ennen
tätä pelkkä ``import automixer.cli_mix`` vei 0,87 s (Linux, lämmin välimuisti,
``-X importtime``), josta 0,74 s oli ``speechmix``in kaikkien alimoduulien
ahne tuonti ja 0,55 s siitä ``scipy.signal``. Ohje ei tarvitse niistä yhtään.

Ajo omassa prosessissaan: muiden testien tuonnit eivät vuoda ``sys.modules``iin.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

#: Raskaat moduulit, joita ohje tai lippuvirhe ei saa tuoda.
HEAVY = (
    "numba",
    "numpy",
    "pedalboard",
    "scipy",
    "soundfile",
    "speechmix.chain",
    "speechmix.dsp",
    "speechmix.stems",
    "automixer.stems_mix",
)


def _run(module: str, argv: list[str]) -> tuple[int, str, list[str]]:
    """``module.main()`` argumenteilla ``argv``: (paluukoodi, tuloste, tuodut)."""
    code = (
        "import json, sys\n"
        f"sys.argv = ['prog', *{argv!r}]\n"
        f"from {module} import main\n"
        "try:\n"
        "    main()\n"
        "    status = 0\n"
        "except SystemExit as exc:\n"
        "    status = exc.code\n"
        "sys.stdout.flush()\n"
        "print('@@modules', json.dumps(sorted(sys.modules)))\n"
        "print('@@status', json.dumps(status))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    lines = done.stdout.splitlines()
    modules = json.loads(next(x for x in lines if x.startswith("@@modules "))[10:])
    status = json.loads(next(x for x in lines if x.startswith("@@status "))[9:])
    text = "\n".join(x for x in lines if not x.startswith("@@")) + done.stderr
    return status, text, modules


def _heavy(modules: list[str]) -> list[str]:
    return [m for m in modules if m.split(".")[0] in HEAVY or m in HEAVY]


@pytest.mark.parametrize(
    ("module", "argv"),
    [
        ("automixer.cli_mix", ["--help"]),
        ("automixer.cli_beds", ["--help"]),
    ],
)
def test_help_imports_nothing_heavy(module, argv):
    status, text, modules = _run(module, argv)
    assert status == 0, text
    assert "usage:" in text
    assert _heavy(modules) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--no-such-flag"],
        ["--target-lufs", "loud"],
        ["--bed-under-speech-db", "99"],
        ["--balance-speakers-max-db", "-1"],
        ["--balance-speakers-tolerance-db", "nan"],
    ],
)
def test_a_bad_flag_is_refused_without_the_heavy_modules(argv):
    """Sama virhe ja paluukoodi 2 kuin ennen, mutta ilman ketjun tuontia."""
    status, text, modules = _run("automixer.cli_mix", argv)
    assert status == 2, text
    assert "error:" in text
    assert _heavy(modules) == []


def test_a_range_error_still_names_the_range():
    """Virheteksti on sama kuin ``stems_mix``in tarkistuksen."""
    status, text, _ = _run("automixer.cli_mix", ["--bed-under-speech-db", "99"])
    assert status == 2
    assert "argument --bed-under-speech-db: 99: must be between -30 and 6 dB" in text
