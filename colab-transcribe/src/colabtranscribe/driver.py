"""Ajuri: suunnitelma komennoista ja niiden ajaminen `colab`-työkalulla.

`plan_commands` on puhdas — se vastaa kysymykseen mitä ajetaan eikä aja
mitään, joten koko ajon muoto on testattavissa ilman Colabia. `run` on se
joka puhuu aliprosesseille, ja sekin kerää jokaisen rivin ylös: pilvessä
ajettavan skriptin tuloste on ainoa tieto siitä mitä siellä tapahtui.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

from .options import RunOptions, pipeline_args

#: Ladattava ketju. Se kulkee paketin mukana, joten ajuri löytää sen myös
#: asennettuna eikä sovellushakemistosta käsin ajettuna eroa ole.
PIPELINE_SCRIPT = Path(__file__).parent / "colab" / "pipeline.py"

REMOTE_INPUT = "/content/input"
REMOTE_OUTPUT = "/content/output"


def list_input_files(input_dir: Path) -> list[str]:
    """Kaikki tiedostot suhteellisina polkuina, syvyydestä riippumatta.

    Ei suodateta ääneen: skripti tarvitsee myös `.nhsx`-istunnot, ja sen
    tarvitsema se itse. Järjestys on polun järjestys, jotta suunnitelma on
    sama joka ajolla.
    """
    return sorted(
        p.relative_to(input_dir).as_posix()
        for p in input_dir.rglob("*")
        if p.is_file()
    )


def plan_commands(options: RunOptions, input_files: list[str]) -> list[list[str]]:
    """Koko ajo komennoiksi, ensimmäisestä viimeiseen.

    Järjestys on sama kuin alkuperäisessä `run_pipeline.sh`:issa — uusi
    istunto, hakemistot, skripti ylös, syötteet ylös, ajo, tulokset alas,
    istunto kiinni. Istunto suljetaan aina viimeisenä; keskeytynyt ajo jää
    auki ja se on silloin Colabin omalla käytössä suljettava.
    """
    commands = [
        ["colab", "new", "-s", options.session, "--gpu", options.gpu],
        ["colab", "exec", "-s", options.session, f"mkdir -p {REMOTE_INPUT} {REMOTE_OUTPUT}"],
        ["colab", "upload", "-s", options.session, str(PIPELINE_SCRIPT), "/content/pipeline.py"],
    ]

    # Alipolut on oltava olemassa ennen kuin mitään niihin ladataan.
    for sub in sorted({Path(f).parent for f in input_files if Path(f).parent != Path(".")}):
        commands.append(
            ["colab", "exec", "-s", options.session, f"mkdir -p {REMOTE_INPUT}/{sub.as_posix()}"]
        )
    for f in input_files:
        # Suhteellinen polku ratkaistaan syötekansiona: aliprosessi ei peri
        # kutsujan työhakemistoa, ja suunnitelman on oltava sama mistä ja
        # miten se suoritetaan.
        source = Path(f)
        if options.input_dir and not source.is_absolute():
            source = Path(options.input_dir) / source
        commands.append(
            ["colab", "upload", "-s", options.session, str(source), f"{REMOTE_INPUT}/{Path(f).as_posix()}"]
        )

    remote_call = " ".join(["python3", "/content/pipeline.py", *map(shlex.quote, pipeline_args(options))])
    commands.append(["colab", "exec", "-s", options.session, remote_call])
    commands.append(["colab", "download", "-s", options.session, f"{REMOTE_OUTPUT}/", options.output_dir])
    commands.append(["colab", "stop", "-s", options.session])
    return commands


def parse_generated(output: str) -> list[str]:
    """Skriptin tulosteesta ne .nhsx-tiedostot jotka se kirjoitti.

    Skripti kertoo tämän yhdellä rivillä per tiedosto; sen muoto on myös
    ainoa tapa tietää tuliko mitään, koska `colab exec` ei erottele
    vaiheita toisistaan.
    """
    marker = "Litteroitu .nhsx luotu:"
    return [line.split(marker, 1)[1].strip() for line in output.splitlines() if marker in line]


def run(commands: list[list[str]], log: Callable[[str], None]) -> int:
    """Aja suunnitelma peräkkäin ja syötä jokainen rivi lokiin.

    Nollasta poikkeava paluukoodi pysäyttää loput: puolet ajosta ilman
    istuntoa on huonompi kuin pysähtynyt ajo, koska seuraava komento
    kohtaisi istunnon joka ei ole siellä missä suunnitelma luuli.
    """
    collected: list[str] = []
    for command in commands:
        log(shlex.join(command))
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            log(f"Komentoa ei löydy: {command[0]}")
            return 127
        assert process.stdout is not None
        for line in process.stdout:
            collected.append(line.rstrip("\n"))
            log(line.rstrip("\n"))
        code = process.wait()
        if code != 0:
            log(f"Komento palautti {code}, lopetetaan: {shlex.join(command)}")
            return code
    return 0
