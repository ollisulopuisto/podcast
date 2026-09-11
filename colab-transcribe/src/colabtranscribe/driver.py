"""Ajuri: suunnitelma komennoista ja niiden ajaminen `colab`-työkalulla.

`plan_commands` on puhdas — se vastaa kysymykseen mitä ajetaan eikä aja
mitään, joten koko ajon muoto on testattavissa ilman Colabia. `run` on se
joka puhuu aliprosesseille, ja sekin kerää jokaisen rivin ylös: pilvessä
ajettavan skriptin tuloste on ainoa tieto siitä mitä siellä tapahtui.
"""

from __future__ import annotations

import shlex
import subprocess
import tarfile
import tempfile
import threading
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


def plan_commands(options: RunOptions, input_files: list[str]) -> list[list[str]]:
    """Koko ajo komennoiksi, ensimmäisestä viimeiseen.

    Järjestys on sama kuin alkuperäisessä `run_pipeline.sh`:issa — uusi
    istunto, hakemistot, skripti ylös, syötteet ylös, ajo, tulokset alas,
    istunto kiinni. Istunto suljetaan aina viimeisenä; keskeytynyt ajo jää
    auki ja se on silloin Colabin omalla käytössä suljettava.
    """
    if options.transfer == "drive":
        drive_rel = f"ColabTranscribe/{options.session}/input.tar.gz"
        input_source = options.input_dir or "."
        remote_call = " ".join(["python3", "/content/pipeline.py", *map(shlex.quote, pipeline_args(options))])
        return [
            ["colab", "new", "-s", options.session, "--gpu", options.gpu],
            ["colab", "drivemount", "-s", options.session],
            ["colab", "exec", "-s", options.session, f"mkdir -p {REMOTE_INPUT} {REMOTE_OUTPUT}"],
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
            ["colab", "stop", "-s", options.session],
        ]

    commands = [
        ["colab", "new", "-s", options.session, "--gpu", options.gpu],
        ["colab", "exec", "-s", options.session, f"mkdir -p {REMOTE_INPUT} {REMOTE_OUTPUT}"],
        ["colab", "upload", "-s", options.session, str(PIPELINE_SCRIPT), "/content/pipeline.py"],
    ]

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
            log(stripped)
        code = process.wait()
    finally:
        if timer is not None:
            timer.cancel()

    if timed_out:
        log(f"Komento ylitti aikarajan ({timeout}s), lopetetaan: {shlex.join(command)}")
        return 124

    if is_colab_exec and has_kernel_error and code == 0:
        log(f"Etäkomento epäonnistui (virhe Colabin ytimessä): {shlex.join(command)}")
        return 1

    if code != 0:
        log(f"Komento palautti {code}, lopetetaan: {shlex.join(command)}")
        return code

    return 0


def upload_input_to_drive(input_dir: Path | str, session: str, log: Callable[[str], None]) -> str:
    """Pakkaa syötekansion ja lataa sen Google Driveen ColabTranscribe/<session>/input.tar.gz."""
    from . import gdrive

    source = Path(input_dir)
    log(f"Pakataan syötetiedostot ({source.name})...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        archive_path = Path(tmp_dir) / "input.tar.gz"
        gdrive.create_input_archive(source, archive_path)
        archive_size_mb = archive_path.stat().st_size / (1024 * 1024)

        log(f"Valmistellaan Google Drive -kansioita ({archive_size_mb:.1f} MB)...")
        token = gdrive.get_drive_token()
        root_folder_id = gdrive.ensure_folder("ColabTranscribe", token=token)
        session_folder_id = gdrive.ensure_folder(session, parent_id=root_folder_id, token=token)

        last_logged_mb = 0.0

        def on_progress(uploaded: int, total: int) -> None:
            nonlocal last_logged_mb
            up_mb = uploaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            if up_mb - last_logged_mb >= 10.0 or uploaded == total:
                pct = int(uploaded / total * 100) if total else 100
                log(f"  Google Drive -lataus: {up_mb:.1f} / {tot_mb:.1f} MB ({pct}%)")
                last_logged_mb = up_mb

        log(f"Ladataan paketti Google Driveen (ColabTranscribe/{session}/input.tar.gz)...")
        file_id = gdrive.upload_resumable(
            archive_path,
            folder_id=session_folder_id,
            token=token,
            progress_callback=on_progress,
        )
        log("Google Drive -siirto valmis.")
        return file_id


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

