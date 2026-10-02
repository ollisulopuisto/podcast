"""Automixer ketjun viimeisenä vaiheena.

Miksain ajetaan **komentona**, ei tuoda. Se vetäisi mukanaan mlx:n,
pedalboardin ja textualin, ja pakattu sovellus kasvaisi niiden verran
vaikka miksausvaihe jäisi käyttämättä. Raja on sama kuin työkalujen välillä
muutenkin: istuntotiedosto sisään, tiedosto ulos. Ketju antaa automixerille
vaimennetun istunnon ja saa WAVin.

Paketissa ``sys.executable`` on sovellus itse, joten ``-m`` käynnistäisi
toisen ikkunan. Paketti löytää miksaimen vain PATHista.
"""

from __future__ import annotations

import importlib.util
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from ..jobs import Cancelled
from ..nhsx.write import next_free_path

MISSING = (
    "automixer puuttuu. Asenna se tähän ympäristöön (uv sync --all-packages) "
    "tai poista miksaus ketjusta."
)
INSTALL = "uv sync --all-packages"

#: Tauko ennen kuin prosessin tila ja peruutus tarkistetaan uudestaan. Lyhyt,
#: koska peruutus on se mitä odotetaan; pitkä ajo ei kärsi kymmenesosasekunnista.
POLL_SECONDS = 0.1

#: Kuinka kauan prosessille annetaan aikaa sulkeutua ennen kuin se tapetaan.
STOP_GRACE_SECONDS = 10


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def command() -> list[str] | None:
    """Miksaimen käynnistyskomento, tai None jos sitä ei ole."""
    found = shutil.which("automixer")
    if found:
        return [found]
    if not getattr(sys, "frozen", False) and _importable("automixer"):
        return [sys.executable, "-m", "automixer.cli_mix"]
    return None


def output_path(session_path: str) -> Path:
    """Miksauksen nimi. Vanhaa ei ylikirjoiteta, sama sääntö kuin istunnoilla."""
    source = Path(session_path)
    return next_free_path(source.with_name(f"{source.stem} automixer.wav"))


def _stop(proc) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run(session_path: str, target_lufs: float, progress) -> str:
    """Miksaa istunnon ja palauttaa WAVin polun."""
    base = command()
    if base is None:
        raise RuntimeError(MISSING)
    target = output_path(session_path)
    argv = [*base, session_path, "--output", str(target), "--target-lufs", str(target_lufs)]
    progress.log(f"Miksataan: {Path(session_path).name} → {target.name}")
    progress.fraction(None)

    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        # Ilman tätä tuloste tulee vasta kun puskuri täyttyy, ja pitkä ajo
        # näyttää jumiutuneelta.
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def read() -> None:
        for line in proc.stdout:
            lines.put(line.rstrip())
        lines.put(None)

    reader = threading.Thread(target=read, name="mixer-output", daemon=True)
    reader.start()

    last = ""
    try:
        done = False
        while not done:
            try:
                while True:
                    line = lines.get(timeout=POLL_SECONDS)
                    if line is None:
                        done = True
                        break
                    if line:
                        last = line
                        progress.log(f"  {line}")
            except queue.Empty:
                pass
            progress.check()
            # Lukija sulkee jonon kun putki sulkeutuu; poll yksin ei riitä,
            # koska prosessi voi olla päättynyt ennen kuin viimeinen rivi on luettu.
            if not done and proc.poll() is not None and not reader.is_alive():
                done = True
    except Cancelled:
        _stop(proc)
        raise
    reader.join(timeout=STOP_GRACE_SECONDS)

    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"automixer päättyi koodiin {code}: {last}")
    # Automixer palaa nollalla myös silloin kun raitoja ei löytynyt: se
    # tulostaa «No tracks found» ja lopettaa siististi. Tiedosto on ainoa
    # todiste siitä että miksaus tehtiin.
    if not target.is_file():
        raise RuntimeError(
            f"automixer ei kirjoittanut tiedostoa {target.name}. Viimeinen rivi: {last}"
        )
    progress.log(f"Kirjoitettiin {target.name}")
    return str(target)
