"""Ajuri: suunnitelma komennoista ja niiden ajaminen `colab`-työkalulla.

`plan_commands` on puhdas — se vastaa kysymykseen mitä ajetaan eikä aja
mitään, joten koko ajon muoto on testattavissa ilman Colabia. `run` on se
joka puhuu aliprosesseille, ja sekin kerää jokaisen rivin ylös: pilvessä
ajettavan skriptin tuloste on ainoa tieto siitä mitä siellä tapahtui.
"""

from __future__ import annotations

import contextlib
import shlex
import subprocess
import tarfile
import tempfile
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from .options import RunOptions, pipeline_args

#: Ladattava ketju. Se kulkee paketin mukana, joten ajuri löytää sen myös
#: asennettuna eikä sovellushakemistosta käsin ajettuna eroa ole.
PIPELINE_SCRIPT = Path(__file__).parent / "colab" / "pipeline.py"

REMOTE_INPUT = "/content/input"
REMOTE_OUTPUT = "/content/output"

#: Paikallinen raja yhdelle `colab`-komennolle. Pilven whisper-raja on 2 h
#: (`colab/pipeline.py:WHISPER_TIMEOUT`); tätä lyhyempi wait tappaisi
#: onnistuneen litteroinnin. Asennus ja siirrot mahtuvat tunnin marginaaliin.
COMMAND_TIMEOUT = 3 * 3600


def list_input_files(input_dir: Path) -> list[str]:
    """Kaikki tiedostot suhteellisina polkuina, syvyydestä riippumatta.

    Ei suodateta ääneen: skripti tarvitsee myös `.nhsx`-istunnot, ja sen
    tarvitsema se itse. Piilotetut tiedostot ja hakemistot (alkavat
    pisteellä) suljetaan pois, koska ne ovat metadataa, ei käyttötietoa.
    Symbolisia linkkejä kansion ulkopuolelle ei seurata: syötekansio on
    se mitä käyttäjä valitsi, ei sen takana oleva tiedostojärjestelmä.
    Järjestys on polun järjestys, jotta suunnitelma on sama joka ajolla.
    """
    root = input_dir.resolve()
    found: list[str] = []
    for dirpath, dirnames, filenames in root.walk(follow_symlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            path = dirpath / name
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if not resolved.is_file() or not resolved.is_relative_to(root):
                continue
            found.append(path.relative_to(root).as_posix())
    return sorted(found)


def plan_commands(
    options: RunOptions, input_files: list[str], reuse_session: bool = False
) -> list[list[str]]:
    """Koko ajo komennoiksi, ensimmäisestä viimeiseen.

    Järjestys on sama kuin alkuperäisessä `run_pipeline.sh`:issa — uusi
    istunto, hakemistot, skripti ylös, syötteet ylös, ajo, tulokset alas,
    istunto kiinni. Istunto suljetaan aina viimeisenä (ellei keep_session);
    keskeytynyt ajo jää auki ja se on silloin Colabin omalla käytössä suljettava.
    Jos reuse_session on True, olemassa olevaa istuntoa ei luoda uudelleen vaan
    sen tilapäiskansiot puhdistetaan.
    """
    clean_and_mkdir = f"rm -rf {REMOTE_INPUT}/* {REMOTE_OUTPUT}/* && mkdir -p {REMOTE_INPUT} {REMOTE_OUTPUT}"
    if options.transfer == "drive":
        drive_rel = f"ColabTranscribe/{options.session}/input.tar.gz"
        input_source = options.input_dir or "."
        remote_call = " ".join(["python3", "/content/pipeline.py", *map(shlex.quote, pipeline_args(options))])
        cmds: list[list[str]] = []
        if not reuse_session:
            cmds.append(["colab", "new", "-s", options.session, "--gpu", options.gpu])
        cmds.extend([
            ["colab", "drivemount", "-s", options.session],
            ["colab", "exec", "-s", options.session, clean_and_mkdir],
            ["colab", "upload", "-s", options.session, str(PIPELINE_SCRIPT), "/content/pipeline.py"],
            ["drive", "upload", str(input_source), drive_rel],
            [
                "colab",
                "exec",
                "-s",
                options.session,
                f"tar -xzf /content/drive/MyDrive/{drive_rel} -C {REMOTE_INPUT}",
            ],
            ["colab", "exec", "-s", options.session, remote_call],
            ["colab", "download", "-s", options.session, f"{REMOTE_OUTPUT}/", options.output_dir],
            [
                "colab",
                "exec",
                "-s",
                options.session,
                f"rm -rf /content/drive/MyDrive/ColabTranscribe/{options.session}",
            ],
        ])
        if not options.keep_session:
            cmds.append(["colab", "stop", "-s", options.session])
        return cmds

    commands: list[list[str]] = []
    if not reuse_session:
        commands.append(["colab", "new", "-s", options.session, "--gpu", options.gpu])
    commands.extend([
        ["colab", "exec", "-s", options.session, clean_and_mkdir],
        ["colab", "upload", "-s", options.session, str(PIPELINE_SCRIPT), "/content/pipeline.py"],
    ])

    # Alipolut on oltava olemassa ennen kuin mitään niihin ladataan.
    for sub in sorted({Path(f).parent for f in input_files if Path(f).parent != Path(".")}):
        remote_dir = shlex.quote(f"{REMOTE_INPUT}/{sub.as_posix()}")
        commands.append(
            ["colab", "exec", "-s", options.session, f"mkdir -p {remote_dir}"]
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
    if not options.keep_session:
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


def _execute_single(
    command: list[str],
    log: Callable[[str], None],
    timeout: float | None = None,
) -> int:
    log(shlex.join(command))
    cmd_to_run = list(command)
    stdin_data: str | None = None
    is_colab_exec = False

    if (
        len(command) >= 5
        and command[0] == "colab"
        and command[1] == "exec"
        and command[2] == "-s"
    ):
        is_colab_exec = True
        session = command[3]
        remote_code = command[4]
        code = remote_code if remote_code.startswith("!") else f"!{remote_code}"
        stdin_data = f"{code}\nassert _exit_code == 0\n"
        cmd_timeout = timeout if timeout is not None else COMMAND_TIMEOUT
        cmd_to_run = ["colab", "exec", "-s", session, "--timeout", str(cmd_timeout)]

    try:
        process = subprocess.Popen(
            cmd_to_run,
            stdin=subprocess.PIPE if stdin_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        log(f"Komentoa ei löydy: {cmd_to_run[0]}")
        return 127

    if stdin_data is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_data)
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    assert process.stdout is not None
    timed_out = False
    timer: threading.Timer | None = None
    if timeout is not None:
        def _kill() -> None:
            nonlocal timed_out
            timed_out = True
            process.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()

    has_kernel_error = False
    has_precondition_error = False
    try:
        for line in process.stdout:
            stripped = line.rstrip("\n")
            if is_colab_exec and stripped.startswith(
                (
                    "---------------------------------------------------------------------------",
                    "AssertionError",
                    "Traceback (most recent call last)",
                )
            ):
                has_kernel_error = True
            if "Precondition Failed" in stripped or "TooManyAssignmentsError" in stripped:
                has_precondition_error = True
            if "accounts.google.com/o/oauth2" in stripped:
                for token in stripped.split():
                    if "accounts.google.com/o/oauth2" in token:
                        webbrowser.open(token)
                        log("[colab] Avattu Google Drive -valtuutuslinkki automaattisesti selaimeen.")
                        break
            log(stripped)
        code = process.wait()
    except KeyboardInterrupt:
        with contextlib.suppress(OSError):
            process.kill()
        raise
    finally:
        if timer is not None:
            timer.cancel()

    if timed_out:
        log(f"Komento ylitti aikarajan ({timeout}s), lopetetaan: {shlex.join(command)}")
        return 124

    if is_colab_exec and has_kernel_error and code == 0:
        log(f"Etäkomento epäonnistui (virhe Colabin ytimessä): {shlex.join(command)}")
        return 1

    if has_precondition_error:
        sess_name = "vst-pipeline"
        if "-s" in command:
            idx = command.index("-s")
            if idx + 1 < len(command):
                sess_name = command[idx + 1]
        log("Virhe: Colab palautti 'Precondition Failed' (liikaa aktiivisia GPU-istuntoja).")
        log(f"Tunnuksellasi on jo aktiivinen Colab-istunto. Voit vapauttaa sen ajamalla: colab stop -s {sess_name}")

    if code != 0:
        log(f"Komento palautti {code}, lopetetaan: {shlex.join(command)}")
        return code

    return 0


def upload_input_to_drive(input_dir: Path | str, session: str, log: Callable[[str], None]) -> str:
    """Pakkaa syötekansion, hyödyntää Google Driven 24 h välimuistia ja lataa sen ColabTranscribe/<session>/input.tar.gz."""
    from . import gdrive

    return gdrive.upload_archive_with_cache(input_dir, session, log=log)



def run(commands: list[list[str]], log: Callable[[str], None], timeout: float | None = None) -> int:
    """Aja suunnitelma peräkkäin ja syötä jokainen rivi lokiin.

    Nollasta poikkeava paluukoodi pysäyttää loput: puolet ajosta ilman
    istuntoa on huonompi kuin pysähtynyt ajo, koska seuraava komento
    kohtaisi istunnon joka ei ole siellä missä suunnitelma luuli.

    Args:
        commands: Suoritettavat komennot listana.
        log: Funktio joka saa jokaisen tulosterivin.
        timeout: Yksittäisen komennon aikaraja sekunteina. None = ei rajaa.
    """
    try:
        for command in commands:
            if len(command) >= 3 and command[0] == "drive" and command[1] == "upload":
                log(shlex.join(command))
                input_dir = command[2]
                parts = command[3].split("/")
                session = parts[1] if len(parts) >= 2 else "session"
                try:
                    upload_input_to_drive(input_dir, session, log)
                except Exception as err:
                    log(f"Google Drive -lataus epäonnistui: {err}")
                    return 1
                continue

            if (
                len(command) >= 6
                and command[0] == "colab"
                and command[1] == "download"
                and command[2] == "-s"
                and command[4].endswith("/")
            ):
                session = command[3]
                remote_dir = command[4].rstrip("/")
                local_dir = Path(command[5])
                log(shlex.join(command))
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tar_name = "_transfer_output.tar.gz"
                    remote_tar = f"/content/{tar_name}"
                    local_tar = Path(tmp_dir) / tar_name

                    code = _execute_single(
                        ["colab", "exec", "-s", session, f"tar -czf {remote_tar} -C {remote_dir} ."],
                        log,
                        timeout=timeout,
                    )
                    if code != 0:
                        return code

                    code = _execute_single(
                        ["colab", "download", "-s", session, remote_tar, str(local_tar)],
                        log,
                        timeout=timeout,
                    )
                    if code != 0:
                        return code

                    local_dir.mkdir(parents=True, exist_ok=True)
                    with tarfile.open(local_tar, "r:gz") as tar:
                        if hasattr(tarfile, "data_filter"):
                            tar.extractall(local_dir, filter="data")
                        else:
                            tar.extractall(local_dir)

                    _execute_single(
                        ["colab", "exec", "-s", session, f"rm -f {remote_tar}"],
                        log,
                        timeout=timeout,
                    )
                continue

            code = _execute_single(command, log, timeout=timeout)
            if code != 0:
                return code
        return 0
    except KeyboardInterrupt:
        log("Ajo keskeytetty käyttäjän toimesta (Ctrl+C).")
        return 130

