"""Ajuri: suunnitelma komennoista ja niiden ajaminen `colab`-työkalulla.

`plan_commands` on puhdas — se vastaa kysymykseen mitä ajetaan eikä aja
mitään, joten koko ajon muoto on testattavissa ilman Colabia. `run` on se
joka puhuu aliprosesseille, ja sekin kerää jokaisen rivin ylös: pilvessä
ajettavan skriptin tuloste on ainoa tieto siitä mitä siellä tapahtui.
"""

from __future__ import annotations

import contextlib
import functools
import re
import shlex
import subprocess
import tarfile
import tempfile
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import silencelearn
import wordalign

from .options import RunOptions, pipeline_args

#: Ladattava ketju. Se kulkee paketin mukana, joten ajuri löytää sen myös
#: asennettuna eikä sovellushakemistosta käsin ajettuna eroa ole.
PIPELINE_SCRIPT = Path(__file__).parent / "colab" / "pipeline.py"

#: Skriptin viereen ladattava kirjasto: yksi tiedosto, pelkkä standardikirjasto.
#: Skripti ei voi tuoda työtilaa, mutta se voi tuoda tämän, koska ``/content``
#: on sen ``sys.path``issa. Polku tulee asennetusta paketista, ei kopiosta —
#: jos tähän tulisi oma kopio, olisimme takaisin siinä mistä paketti pelasti.
LEARN_MODULE = Path(silencelearn.__file__)
LEARN_REMOTE = "/content/silencelearn.py"

#: Sanojen alkujen kohdistin: sama yksi tiedosto kuin sovelluksessa, ladataan
#: Colabiin skriptin viereen vain kun ``--align`` on päällä.
ALIGN_MODULE = Path(wordalign.__file__)
ALIGN_REMOTE = "/content/wordalign.py"

#: Suora siirto: tätä isommat syötteet lähetetään paloina. Mitattu: 409 667 072
#: tavun WAV kaatui `colab upload`issa HTTP 500:een (Colabin tiedostorajapinta),
#: neljän megan WAVit eivät ole kaatuneet. Rajat ovat arvauksia kunnes isompi
#: tiedosto on mennyt läpi paloina; muuta tästä, ei kutsuista.
CHUNK_ABOVE = 128 * 1024 * 1024
CHUNK_BYTES = 64 * 1024 * 1024
#: Yhden palan uudelleenyritykset (`colab upload` itse yrittää kahdesti vain
#: yhteyskatkoihin, ei 500:aan).
CHUNK_RETRIES = 3

REMOTE_INPUT = "/content/input"
#: Ladatut tiedostot elävät täällä sisällön tarkistussumman alla ja syöte on
#: linkkejä niihin: ``REMOTE_INPUT`` tyhjennetään joka ajossa (skripti litteroi
#: kaiken siinä), mutta välimuisti säilyy kunnes Colab-kone sulkeutuu.
REMOTE_CACHE = "/content/cache"
REMOTE_OUTPUT = "/content/output"

#: Paikallinen raja yhdelle `colab`-komennolle. Pilven whisper-raja on 2 h
#: (`colab/pipeline.py:WHISPER_TIMEOUT`); tätä lyhyempi wait tappaisi
#: onnistuneen litteroinnin. Asennus ja siirrot mahtuvat tunnin marginaaliin.
COMMAND_TIMEOUT = 3 * 3600


@functools.lru_cache(maxsize=256)
def _content_key(path: str, size: int, mtime_ns: int) -> str:
    """Sisällön SHA-256 (16 merkkiä). Koko ja aika ovat vain muistin avain, ettei
    sama tiedosto luettaisi uudestaan saman ajon aikana."""
    import hashlib

    del size, mtime_ns  # vain välimuistin avaimena
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()[:16]


def cache_path(source: Path) -> str:
    """Tiedoston paikka Colabin välimuistissa: ``/content/cache/<hash>/data<pääte>``.

    Nimi ei ole käyttäjän tiedoston nimi: Colabin tiedostorajapinta hylkäsi
    ``…Arjanne1142^.wav.flac``in (HTTP 400, ``%5E``), ja nimessä voi olla mitä
    tahansa. Oikea nimi tulee syötteen linkistä (``ln``), jossa se on lainattu."""
    source = Path(source)
    st = source.stat()
    suffix = source.suffix.lower()
    if not (suffix[1:].isascii() and suffix[1:].isalnum()):
        suffix = ""
    return f"{REMOTE_CACHE}/{_content_key(str(source), st.st_size, st.st_mtime_ns)}/data{suffix}"


def list_input_files(input_dir: Path, exclude: Path | None = None) -> list[str]:
    """Kaikki tiedostot suhteellisina polkuina, syvyydestä riippumatta.

    Jos input_dir on yksittäinen tiedosto, palautetaan vain sen nimi.
    Ei suodateta ääneen: skripti tarvitsee myös `.nhsx`-istunnot, ja sen
    tarvitsema se itse. Piilotetut tiedostot ja hakemistot (alkavat
    pisteellä) suljetaan pois, koska ne ovat metadataa, ei käyttötietoa.
    ``exclude`` on kansio joka jätetään pois (ajon oma tulostekansio, jos se on
    syötteen sisällä: edellisen ajon tulokset eivät ole syötteitä).
    Symbolisia linkkejä kansion ulkopuolelle ei seurata: syötekansio on
    se mitä käyttäjä valitsi, ei sen takana oleva tiedostojärjestelmä.
    Järjestys on polun järjestys, jotta suunnitelma on sama joka ajolla.
    """
    root = input_dir.resolve()
    if root.is_file():
        return [root.name]
    if not root.is_dir():
        return []
    found: list[str] = []
    skip = exclude.resolve() if exclude is not None else None
    for dirpath, dirnames, filenames in root.walk(follow_symlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and (skip is None or (dirpath / d).resolve() != skip)
        ]
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


def _session_names(nhsx: Path) -> tuple[str, list[str]] | None:
    """Istunnon äänipoolin kansio ja tiedostonimet, tai None jos ei voi lukea."""
    import xml.etree.ElementTree as ET

    try:
        text = nhsx.read_text(encoding="utf-8")
        if "<!DOCTYPE" in text:  # sama kovennus kuin pilvessä: ei entiteettejä
            return None
        root = ET.fromstring(text)
    except (OSError, ValueError, ET.ParseError):
        return None
    for pool in root.iter():
        if pool.tag.rsplit("}", 1)[-1] == "AudioPool":
            names = [
                f.get("Name") or f.get("Path") or ""
                for f in pool
                if f.tag.rsplit("}", 1)[-1] == "File"
            ]
            return pool.get("Path", ""), [n for n in names if n]
    return None


def nhsx_sessions(input_dir: Path | str) -> list[str]:
    """Kansion ``.nhsx``-istunnot nimen mukaan (ei piilotiedostoja, ei alikansioita)."""
    try:
        return sorted(
            p.name
            for p in Path(input_dir).iterdir()
            if p.is_file() and p.suffix.lower() == ".nhsx" and not p.name.startswith(".")
        )
    except OSError:
        return []


def split_session(path: Path | str) -> tuple[Path, str | None]:
    """``.nhsx``-tiedosto syötteenä tarkoittaa sitä istuntoa omassa kansiossaan:
    ``(kansio, istunnon nimi)``. Muu syöte palautuu sellaisenaan ilman valintaa."""
    p = Path(path)
    if p.is_file() and p.suffix.lower() == ".nhsx":
        return p.parent, p.name
    return p, None


def session_inputs(
    input_dir: Path | str, files: list[str], only: str | None = None
) -> tuple[list[str], list[str]]:
    """Istuntojen tarvitsemat tiedostot ja ne jotka voi jättää lataamatta.

    Pilvessä skripti litteroi kaiken äänen jonka syötekansiosta löytää, joten
    istunnon viereen jäänyt raakamatsku tai ``.TAKE``-kopio maksaa sekä
    latauksen että ajan. Tähän jää ``.nhsx`` ja se äänitiedosto jonka
    äänipooli nimeää: ensin pooliin kuuluvasta kansiosta (``Path``), sitten
    istunnon vierestä, vasta sitten mistä tahansa samannimisestä (yksi).
    Ilman istuntoa, tai jos jokin istunto ei jäsenny, kaikki lähtee: arvaus
    joka pudottaa tarvittavan tiedoston on pahempi kuin liian iso lataus.
    """
    root = Path(input_dir).resolve()
    if root.is_file():
        return files, []
    sessions = [f for f in files if f.lower().endswith(".nhsx")]
    if only is not None:
        sessions = [f for f in sessions if f == only]
    if not sessions:
        return files, []
    present = set(files)
    by_name: dict[str, list[str]] = {}
    for f in files:
        by_name.setdefault(Path(f).name.casefold(), []).append(f)
    keep = set(sessions)
    for rel in sessions:
        parsed = _session_names(root / rel)
        if parsed is None:
            return files, []
        pool_path, names = parsed
        folder = Path(rel).parent
        for name in names:
            name = Path(name).name
            for cand in (
                (folder / pool_path / name).as_posix(),
                (folder / name).as_posix(),
            ):
                if cand in present:
                    keep.add(cand)
                    break
            else:
                hits = by_name.get(name.casefold())
                if hits:
                    keep.add(hits[0])
    return [f for f in files if f in keep], [f for f in files if f not in keep]


#: Pilven skriptin ``AUDIO_EXTENSIONS``: se litteroi kaiken tällä päätteellä.
_AUDIO_EXT = (".wav", ".aiff", ".flac", ".m4a", ".mp4", ".mp3")


def _checksum(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def dedupe_inputs(
    input_dir: Path | str, files: list[str]
) -> tuple[list[str], dict[str, str]]:
    """Samasisältöiset äänitiedostot kerran: ``(ladattavat, {kopio: alkuperäinen})``.

    Koko valitsee ehdokkaat ja tarkistussumma ratkaisee, joten yksin omaa
    kokoaan olevaa tiedostoa ei lueta. Alkuperäinen on polun järjestyksessä
    ensimmäinen. Kopiot tehdään Colabissa (``ln``) ennen ajoa, jotta istunto
    löytää jokaisen nimensä, ja pilven skripti litteroi saman sisällön kerran.
    """
    root = Path(input_dir).resolve()
    if root.is_file():
        return files, {}
    by_size: dict[int, list[str]] = {}
    for f in files:
        if f.lower().endswith(_AUDIO_EXT):
            try:
                by_size.setdefault((root / f).stat().st_size, []).append(f)
            except OSError:
                continue
    aliases: dict[str, str] = {}
    for group in by_size.values():
        if len(group) < 2:
            continue
        first_by_sum: dict[str, str] = {}
        for f in group:
            try:
                digest = _checksum(root / f)
            except OSError:
                continue
            if digest in first_by_sum:
                aliases[f] = first_by_sum[digest]
            else:
                first_by_sum[digest] = f
    return [f for f in files if f not in aliases], aliases


def skipped_note(input_dir: Path | str, skipped: list[str]) -> str:
    """Yksi rivi siitä mitä jätettiin lataamatta ja kuinka paljon se oli."""
    root = Path(input_dir).resolve()
    total = 0
    for rel in skipped:
        with contextlib.suppress(OSError):
            total += (root / rel).stat().st_size
    return (
        f"Istunto ei käytä {len(skipped)} tiedostoa ({total / 1e9:.1f} GB): "
        "niitä ei ladata eikä litteroida."
    )


def has_nhsx_files(path: Path | str) -> bool:
    """Tarkistaa onko polku .nhsx-tiedosto tai kansio jossa on .nhsx-tiedostoja."""
    p = Path(path).resolve()
    if not p.exists():
        return False
    if p.is_file():
        return p.suffix.lower() == ".nhsx"
    try:
        return any(
            item.suffix.lower() == ".nhsx"
            for item in p.iterdir()
            if item.is_file() and not item.name.startswith(".")
        )
    except OSError:
        return False



def plan_commands(
    options: RunOptions,
    input_files: list[str],
    reuse_session: bool = False,
    aliases: dict[str, str] | None = None,
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
        drive_rel = f"ColabTranscribe/{options.session}/input.tar"
        input_source = options.input_dir or "."
        remote_call = " ".join(
            ["python3", "/content/pipeline.py", *map(shlex.quote, pipeline_args(options))]
        )
        cmds: list[list[str]] = []
        if not reuse_session:
            cmds.append(["colab", "new", "-s", options.session, "--gpu", options.gpu])
        cmds.extend(
            [
                ["colab", "drivemount", "-s", options.session],
                ["colab", "exec", "-s", options.session, clean_and_mkdir],
                [
                    "colab",
                    "upload",
                    "-s",
                    options.session,
                    str(PIPELINE_SCRIPT),
                    "/content/pipeline.py",
                ],
                ["colab", "upload", "-s", options.session, str(LEARN_MODULE), LEARN_REMOTE],
                ["drive", "upload", str(input_source), drive_rel],
                [
                    "colab",
                    "exec",
                    "-s",
                    options.session,
                    f"tar -xf /content/drive/MyDrive/{drive_rel} -C {REMOTE_INPUT}",
                ],
                ["colab", "exec", "-s", options.session, remote_call],
                [
                    "colab",
                    "download",
                    "-s",
                    options.session,
                    f"{REMOTE_OUTPUT}/",
                    str(options.resolved_output_dir()),
                ],
                [
                    "colab",
                    "exec",
                    "-s",
                    options.session,
                    f"rm -rf /content/drive/MyDrive/ColabTranscribe/{options.session}",
                ],
            ]
        )
        if not options.keep_session:
            cmds.append(["colab", "stop", "-s", options.session])
        return cmds

    commands: list[list[str]] = []
    if not reuse_session:
        commands.append(["colab", "new", "-s", options.session, "--gpu", options.gpu])
    commands.extend(
        [
            ["colab", "exec", "-s", options.session, clean_and_mkdir],
            [
                "colab",
                "upload",
                "-s",
                options.session,
                str(PIPELINE_SCRIPT),
                "/content/pipeline.py",
            ],
            ["colab", "upload", "-s", options.session, str(LEARN_MODULE), LEARN_REMOTE],
        ]
    )

    aliases = aliases or {}
    if reuse_session:
        # Sama kone on yhä hengissä: katso mitä edellinen ajo jätti välimuistiin.
        commands.append(["cache-list", options.session])
    uploads: list[tuple[str, str, str]] = []  # (lähde, välimuistipolku, syötepolku)
    for f in input_files:
        # Suhteellinen polku ratkaistaan syötekansiona: aliprosessi ei peri
        # kutsujan työhakemistoa, ja suunnitelman on oltava sama mistä ja
        # miten se suoritetaan.
        source = Path(f)
        if options.input_dir and not source.is_absolute():
            inp = Path(options.input_dir)
            source = inp if inp.is_file() else inp / source
        remote_input = f"{REMOTE_INPUT}/{Path(f).as_posix()}"
        try:
            remote = cache_path(source)
        except OSError:
            remote = remote_input  # ei luettavissa: suunnitelma näyttää sen silti
        uploads.append((str(source), remote, remote_input))
    commands.extend(
        _upload_commands(
            options, uploads, [f"{REMOTE_INPUT}/{Path(a).parent.as_posix()}" for a in aliases]
        )
    )

    # Kopiot vasta kun alkuperäiset ovat perillä: kova linkki, ja kopio jos
    # linkki ei onnistu.
    for alias, original in aliases.items():
        dst = shlex.quote(f"{REMOTE_INPUT}/{Path(alias).as_posix()}")
        src = shlex.quote(f"{REMOTE_INPUT}/{Path(original).as_posix()}")
        commands.append(
            [
                "colab",
                "exec",
                "-s",
                options.session,
                f"ln -f {src} {dst} || cp {src} {dst}",
            ]
        )

    remote_call = " ".join(
        ["python3", "/content/pipeline.py", *map(shlex.quote, pipeline_args(options))]
    )
    commands.append(["colab", "exec", "-s", options.session, remote_call])
    commands.append(
        [
            "colab",
            "download",
            "-s",
            options.session,
            f"{REMOTE_OUTPUT}/",
            str(options.resolved_output_dir()),
        ]
    )
    if not options.keep_session:
        commands.append(["colab", "stop", "-s", options.session])
    return commands


def _upload_commands(
    options: RunOptions,
    uploads: list[tuple[str, str, str]],
    extra_dirs: list[str] = (),
) -> list[list[str]]:
    """Kansiot, lataukset ja kovat linkit: ``(lähde, välimuistipolku, syötepolku)``."""
    commands: list[list[str]] = []
    dirs = {str(Path(r).parent) for _, r, _ in uploads if r.startswith(REMOTE_CACHE)}
    dirs |= {str(Path(i).parent) for _, _, i in uploads}
    dirs |= set(extra_dirs)
    dirs = sorted(dirs)
    if dirs:
        commands.append(
            ["colab", "exec", "-s", options.session,
             "mkdir -p " + " ".join(shlex.quote(d) for d in dirs)]
        )
    for source_str, remote, _ in uploads:
        try:
            big = Path(source_str).stat().st_size > CHUNK_ABOVE
        except OSError:
            big = False
        if big and options.compress and _flac_bitdepth(Path(source_str)):
            commands.append(["flac-upload", options.session, source_str, remote])
        elif big:
            commands.append(["chunked-upload", options.session, source_str, remote])
        else:
            commands.append(["colab", "upload", "-s", options.session, source_str, remote])
    links = [
        f"ln -f {shlex.quote(r)} {shlex.quote(i)}" for _, r, i in uploads if r != i
    ]
    if links:
        commands.append(["colab", "exec", "-s", options.session, " && ".join(links)])
    return commands


def plan_audio_commands(
    options: RunOptions, audio_files: list[str], reuse_session: bool = False
) -> list[list[str]]:
    """Pelkkä ääni sisään, sanat ulos (``--source audio``).

    Aina suora siirto: ääni lähtee suoraan Colab-koneelle eikä kulje Driven
    kautta. Ei ``silencelearn``ia eikä istuntoa, koska skripti ei tee kumpaakaan.
    Jokainen tiedosto päätyy syötekansioon omalla nimellään; nimien on oltava
    yksilöllisiä (CLI tarkistaa).
    """
    commands: list[list[str]] = []
    if not reuse_session:
        commands.append(["colab", "new", "-s", options.session, "--gpu", options.gpu])
    commands.append(
        [
            "colab", "exec", "-s", options.session,
            f"rm -rf {REMOTE_INPUT}/* {REMOTE_OUTPUT}/* && mkdir -p {REMOTE_INPUT} {REMOTE_OUTPUT}",
        ]
    )
    commands.append(
        ["colab", "upload", "-s", options.session, str(PIPELINE_SCRIPT), "/content/pipeline.py"]
    )
    if options.align:
        commands.append(
            ["colab", "upload", "-s", options.session, str(ALIGN_MODULE), ALIGN_REMOTE]
        )
    if reuse_session:
        commands.append(["cache-list", options.session])
    uploads = []
    for f in audio_files:
        source = Path(f)
        remote_input = f"{REMOTE_INPUT}/{source.name}"
        try:
            remote = cache_path(source)
        except OSError:
            remote = remote_input
        uploads.append((str(source), remote, remote_input))
    commands.extend(_upload_commands(options, uploads))
    remote_call = " ".join(
        ["python3", "/content/pipeline.py", *map(shlex.quote, pipeline_args(options))]
    )
    commands.append(["colab", "exec", "-s", options.session, remote_call])
    commands.append(
        [
            "colab", "download", "-s", options.session, f"{REMOTE_OUTPUT}/",
            str(options.resolved_output_dir()),
        ]
    )
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
    return [
        line.split(marker, 1)[1].strip() for line in output.splitlines() if marker in line
    ]


def parse_generated_transcripts(output: str) -> list[str]:
    """Skriptin tulosteesta ne litterointitiedostot jotka se kirjoitti."""
    marker = "Litterointi luotu:"
    return [
        line.split(marker, 1)[1].strip() for line in output.splitlines() if marker in line
    ]


def get_transcript_files(output_dir: Path | str) -> list[Path]:
    """Palauttaa kaikki tulostehakemiston transcripts-kansion litteroinnit (.json, .txt jne.)."""
    t_dir = Path(output_dir) / "transcripts"
    if not t_dir.is_dir():
        t_dir = Path(output_dir)
        if not t_dir.is_dir():
            return []
    return sorted(
        p
        for p in t_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in (".json", ".txt", ".srt", ".vtt", ".tsv")
        and not p.name.startswith(".")
    )


def describe_command(command: list[str]) -> str:
    """Muuntaa ajettavan komennon selkeäksi suomenkieliseksi kuvaukseksi."""
    if not command:
        return "Suoritetaan komentoa..."
    cmd0 = command[0]
    if cmd0 == "flac-upload":
        return f"Pakataan ja siirretään {Path(command[2]).name} FLACina..."
    if cmd0 == "chunked-upload":
        return f"Siirretään isoa tiedostoa {Path(command[2]).name} paloina..."
    if cmd0 == "drive" and len(command) > 1 and command[1] == "upload":
        return "Ladataan syötteet Google Driveen..."
    if cmd0 == "colab" and len(command) > 1:
        sub = command[1]
        if sub == "new":
            return "Käynnistetään Colab-GPU-istuntoa..."
        if sub == "drivemount":
            return "Liitetään Google Drive..."
        if sub == "upload":
            target = command[-1] if len(command) > 2 else ""
            if "pipeline.py" in target:
                return "Siirretään pipeline.py Colabiin..."
            return f"Siirretään tiedostoa {Path(target).name}..."
        if sub == "download":
            return "Ladataan tulokset Colabista..."
        if sub == "stop":
            return "Suljetaan Colab-istunto..."
        if sub == "exec" and len(command) > 4:
            action = command[4]
            if "rm -rf" in action and "mkdir" in action:
                return "Valmistellaan etähakemistoja..."
            if "tar -xf" in action:
                return "Puretaan syötetiedostoja Colabissa..."
            if "pipeline.py" in action:
                return "Suoritetaan litterointi ja Auto-Silence..."
            if "rm -rf" in action and "ColabTranscribe" in action:
                return "Siivotaan Google Driven väliaikaistiedostoja..."
    return f"Suoritetaan: {shlex.join(command)}"



def stage_of(command: list[str]) -> str | None:
    """Mikä ``--events``-vaihe komento on, tai None (ei omaa vaihetta)."""
    if not command:
        return None
    cmd0 = command[0]
    if cmd0 in ("flac-upload", "chunked-upload", "drive"):
        return "upload"
    if cmd0 != "colab" or len(command) < 2:
        return None
    sub = command[1]
    if sub in ("new", "drivemount"):
        return "session"
    if sub == "upload":
        return "upload"
    if sub == "download":
        return "download"
    if sub == "stop":
        return "stop"
    if sub == "exec" and len(command) > 4:
        action = command[4]
        if "pipeline.py" in action:
            return "run"
        if "tar -xf" in action:
            return "upload"
        if "rm -rf" in action and "mkdir" in action:
            return "prepare"
    return None


_MARKER_INDEX = re.compile(r"\((\d+)/(\d+)\)")


def stage_of_line(line: str) -> tuple[str, int | None, int | None] | None:
    """Pilvipään rivistä ``(vaihe, indeksi, yhteensä)`` tai None.

    ``colab exec`` ei erottele skriptin vaiheita muuten kuin sen omilla
    riveillä, ja samat merkit ohjaavat jo ``on_progress``ia.
    """
    if "[vaihe 1/4]" in line:
        return "install", None, None
    found = _MARKER_INDEX.search(line)
    index, total = (int(found.group(1)), int(found.group(2))) if found else (None, None)
    if "[vaihe 2/4" in line or "[ääni (" in line:
        return "transcribe", index, total
    if "[kohdistus (" in line:
        return "align", index, total
    return None


def _execute_single(
    command: list[str],
    log: Callable[[str], None],
    timeout: float | None = None,
    opened_auth_urls: set[str] | None = None,
    max_retries: int = 2,
    on_line: Callable[[str], None] | None = None,
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

    # ``colab`` uvx:n ympäristöstä, jos se on siellä (``onboarding.colab_env``).
    from .onboarding import colab_env

    env = colab_env()
    env["COLAB_CLI_NO_BROWSER"] = "1"

    for attempt in range(max_retries + 1):
        if attempt > 0:
            log(f"Yhteys katkesi, yritetään uudelleen ({attempt}/{max_retries})...")
            time.sleep(2)

        try:
            process = subprocess.Popen(
                cmd_to_run,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
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
        has_connection_lost_error = False
        try:
            for line in process.stdout:
                stripped = line.rstrip("\n")
                if on_line is not None:
                    on_line(stripped)
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
                if (
                    "Connection was lost" in stripped
                    or "ConnectionResetError" in stripped
                    or "ReadTimeout" in stripped
                    or "Read timed out" in stripped
                ):
                    has_connection_lost_error = True
                if "accounts.google.com/o/oauth2" in stripped:
                    for token in stripped.split():
                        if "accounts.google.com/o/oauth2" in token:
                            if opened_auth_urls is None or token not in opened_auth_urls:
                                if opened_auth_urls is not None:
                                    opened_auth_urls.add(token)
                                webbrowser.open(token)
                                log(
                                    "[colab] Avattu Google Drive -valtuutuslinkki automaattisesti selaimeen."
                                )
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
            sess_name = "whisper"
            if "-s" in command:
                idx = command.index("-s")
                if idx + 1 < len(command):
                    sess_name = command[idx + 1]
            log(
                "Virhe: Colab palautti 'Precondition Failed' (liikaa aktiivisia GPU-istuntoja)."
            )
            log(
                f"Tunnuksellasi on jo aktiivinen Colab-istunto. Voit vapauttaa sen ajamalla: colab stop -s {sess_name}"
            )

        if has_connection_lost_error:
            if attempt < max_retries:
                continue
            log(
                "Virhe: Yhteys Colab-virtuaalikoneeseen katkesi (Connection was lost)."
            )
            log(
                "Tämä johtuu yleensä verkkokatkoksesta tai välityspalvelimen aikakatkaisusta."
            )
            log(
                "Colab-istunto on todennäköisesti edelleen käynnissä pilvessä. Voit jatkaa ajoa suoraan komennolla:"
            )
            log("  uv run colab-transcribe")

        if code != 0:
            log(f"Komento palautti {code}, lopetetaan: {shlex.join(command)}")
            return code

        return 0

    return code


def direct_tail(
    options: RunOptions,
    input_files: list[str],
    aliases: dict[str, str] | None = None,
) -> list[list[str]]:
    """Suoran siirron komennot skriptien latauksen jälkeen.

    Kun Drive kaatuu kesken ajon, istunto on jo luotu ja skriptit ovat ylhäällä;
    jäljellä on vain syötteiden lataus, ajo, tulokset alas ja istunnon sulku.
    """
    direct = plan_commands(
        replace(options, transfer="direct"),
        input_files,
        reuse_session=True,
        aliases=aliases,
    )
    after_scripts = next(
        i for i, c in enumerate(direct) if LEARN_REMOTE in c
    ) + 1
    return direct[after_scripts:]


#: FLAC kantaa PCM:n 16 ja 24 bittiä; WAVin liukuluku ja 32-bittinen PCM eivät
#: mahdu siihen, ja ne lähetetään sellaisinaan. Arvo on ffmpegin purkukoodekki.
_FLAC_DECODERS = {"PCM_16": "pcm_s16le", "PCM_24": "pcm_s24le"}


def _flac_bitdepth(path: Path) -> str | None:
    """Purkukoodekki jos tiedosto on FLACiksi häviöttä pakattava WAV, muuten None."""
    if path.suffix.lower() != ".wav":
        return None
    import soundfile as sf

    try:
        info = sf.info(path)
    except (OSError, RuntimeError):
        return None
    if info.format not in ("WAV", "WAVEX", "RF64"):
        return None
    return _FLAC_DECODERS.get(info.subtype)


def _upload_as_flac(
    session: str,
    source: Path,
    remote: str,
    log: Callable[[str], None],
    timeout: float | None = None,
) -> int:
    """Pakkaa WAV FLACiksi, lähetä, ja pura Colabissa samannimiseksi WAViksi.

    Istunto viittaa ``a.wav``:iin, joten tulos on täsmälleen se tiedosto (sama
    nimi, sama bittisyvyys) eikä istuntoa tai tuloksia tarvitse muokata.
    """
    import soundfile as sf

    decoder = _flac_bitdepth(source)
    if decoder is None:
        return _upload_in_chunks(session, source, remote, log, timeout)
    remote_flac = f"{remote}.flac"
    with tempfile.TemporaryDirectory() as tmp:
        flac = Path(tmp) / "a.flac"
        log(f"Pakataan {source.name} FLACiksi (häviötön)...")
        with sf.SoundFile(source) as src, sf.SoundFile(
            flac, "w", src.samplerate, src.channels, format="FLAC", subtype=src.subtype
        ) as dst:
            while len(block := src.read(1 << 20, dtype="int32")):
                dst.write(block)
        log(f"{source.stat().st_size / 1e6:.0f} MB -> {flac.stat().st_size / 1e6:.0f} MB")
        if flac.stat().st_size > CHUNK_ABOVE:
            code = _upload_in_chunks(session, flac, remote_flac, log, timeout)
        else:
            code = _execute_single(
                ["colab", "upload", "-s", session, str(flac), remote_flac],
                log,
                timeout=timeout,
            )
    if code != 0:
        return code
    q, qf = shlex.quote(remote), shlex.quote(remote_flac)
    return _execute_single(
        [
            "colab",
            "exec",
            "-s",
            session,
            f"if [ -f {qf} ]; then ffmpeg -y -loglevel error -i {qf} -c:a {decoder} "
            f"-f wav {q}.tmp && mv {q}.tmp {q} && rm {qf}; fi; test -f {q}",
        ],
        log,
        timeout=timeout,
    )


def _upload_in_chunks(
    session: str,
    source: Path,
    remote: str,
    log: Callable[[str], None],
    timeout: float | None = None,
) -> int:
    """Lähetä iso tiedosto paloina ja liitä ne Colabissa: yhden palan virhe
    maksaa yhden palan uudelleenlähetyksen, ei koko tiedostoa."""
    with tempfile.TemporaryDirectory() as tmp, open(source, "rb") as f:
        n = 0
        while chunk := f.read(CHUNK_BYTES):
            part = Path(tmp) / f"part{n:04d}"
            part.write_bytes(chunk)
            remote_part = f"{remote}.part{n:04d}"
            for attempt in range(CHUNK_RETRIES + 1):
                if attempt:
                    log(
                        f"Pala {n} epäonnistui, yritetään uudelleen "
                        f"({attempt}/{CHUNK_RETRIES})..."
                    )
                    time.sleep(5)
                code = _execute_single(
                    ["colab", "upload", "-s", session, str(part), remote_part],
                    log,
                    timeout=timeout,
                )
                if code == 0:
                    break
            else:
                return code
            part.unlink()
            n += 1
    q = shlex.quote(remote)
    return _execute_single(
        [
            "colab",
            "exec",
            "-s",
            session,
            # Toistettavissa: jos edellinen kerta ehti liittää mutta vastaus
            # katosi, paloja ei enää ole eikä ``>`` saa tyhjentää valmista tiedostoa.
            f"if ls {q}.part* >/dev/null 2>&1; then cat {q}.part* > {q}.tmp "
            f"&& mv {q}.tmp {q} && rm {q}.part*; fi; test -f {q}",
        ],
        log,
        timeout=timeout,
    )


def _upload_target(command: list[str]) -> tuple[str, str] | None:
    """``(paikallinen, Colabin polku)`` jos komento on lataus, muuten None."""
    if command[0] in ("flac-upload", "chunked-upload") and len(command) >= 4:
        return command[2], command[3]
    if command[:2] == ["colab", "upload"] and len(command) >= 6:
        return command[4], command[5]
    return None


def _list_cache(
    session: str, log: Callable[[str], None], timeout: float | None = None
) -> set[str]:
    """Tiedostot jotka edellinen ajo jätti Colabin välimuistiin. Epäonnistunut
    listaus on tyhjä lista: silloin ladataan kaikki, mikä on aina oikein."""
    found: list[str] = []

    def collect(line: str) -> None:
        log(line)
        if line.startswith(REMOTE_CACHE + "/"):
            found.append(line.strip())

    code = _execute_single(
        ["colab", "exec", "-s", session, f"find {REMOTE_CACHE} -type f 2>/dev/null; true"],
        collect,
        timeout=timeout,
    )
    return set(found) if code == 0 else set()


def upload_input_to_drive(
    input_dir: Path | str, session: str, log: Callable[[str], None]
) -> str:
    """Pakkaa syötekansion, hyödyntää Google Driven 24 h välimuistia ja lataa sen ColabTranscribe/<session>/input.tar."""
    from . import gdrive

    return gdrive.upload_archive_with_cache(input_dir, session, log=log)


def run(
    commands: list[list[str]],
    log: Callable[[str], None],
    timeout: float | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    on_drive_failure: Callable[[], list[list[str]]] | None = None,
    trail=None,
) -> int:
    """Aja suunnitelma peräkkäin ja syötä jokainen rivi lokiin.

    Nollasta poikkeava paluukoodi pysäyttää loput: puolet ajosta ilman
    istuntoa on huonompi kuin pysähtynyt ajo, koska seuraava komento
    kohtaisi istunnon joka ei ole siellä missä suunnitelma luuli.

    Args:
        commands: Suoritettavat komennot listana.
        log: Funktio joka saa jokaisen tulosterivin.
        timeout: Yksittäisen komennon aikaraja sekunteina. None = ei rajaa.
        on_progress: Valinnainen takaisinkutsu edistymiselle (prosentti, kuvaus).
        trail: Valinnainen ``events.StageTrail`` (``--events``): saa vaiheen
            alun jokaisesta komennosta ja pilvipään vaihemerkeistä, ja sulkeutuu
            onnistuneen ajon lopussa. Kaatuneessa ajossa se jää auki kohtaan
            jossa ajo päättyi.
        on_drive_failure: Jos Drive-lataus kaatuu 403:een (quota project
            puuttuu), saa tämä antaa tilalle suoran siirron loput komennot;
            ilman sitä ajo pysähtyy kuten ennen.
    """
    opened_auth_urls: set[str] = set()
    cached: set[str] = set()
    total = len(commands)
    try:
        for i, command in enumerate(commands):
            base_pct = (i / max(total, 1)) * 100.0
            step_span = (1.0 / max(total, 1)) * 100.0
            desc = describe_command(command)
            if on_progress:
                on_progress(base_pct, f"[{i + 1}/{total}] {desc}")
            if trail is not None and (stage := stage_of(command)):
                trail.enter(stage)

            def _subline(line: str) -> None:
                if trail is not None and (marked := stage_of_line(line)):
                    trail.enter(*marked)
                if not on_progress:
                    return
                line_s = line.strip()
                if "[vaihe 1/4]" in line_s:
                    on_progress(
                        base_pct + 0.1 * step_span,
                        f"[{i + 1}/{total}] Asennetaan riippuvuudet...",
                    )
                elif "[vaihe 2/4" in line_s:
                    m = re.search(r"\((\d+)/(\d+)\)", line_s)
                    if m:
                        idx, tot_items = int(m.group(1)), int(m.group(2))
                        fraction = idx / max(tot_items, 1)
                        on_progress(
                            base_pct + (0.2 + 0.5 * fraction) * step_span,
                            f"[{i + 1}/{total}] Litteroidaan ({idx}/{tot_items})...",
                        )
                    else:
                        on_progress(
                            base_pct + 0.2 * step_span,
                            f"[{i + 1}/{total}] Litteroidaan ääntä...",
                        )
                elif "[ääni (" in line_s:
                    m = re.search(r"\[ääni \((\d+)/(\d+)\)\]", line_s)
                    if m:
                        idx, tot_items = int(m.group(1)), int(m.group(2))
                        on_progress(
                            base_pct + (0.2 + 0.5 * (idx - 1) / max(tot_items, 1)) * step_span,
                            f"[{i + 1}/{total}] Litteroidaan ({idx}/{tot_items})...",
                        )
                elif "[kohdistus (" in line_s:
                    m = re.search(r"\[kohdistus \((\d+)/(\d+)\)\]", line_s)
                    if m:
                        idx, tot_items = int(m.group(1)), int(m.group(2))
                        on_progress(
                            base_pct + (0.7 + 0.2 * (idx - 1) / max(tot_items, 1)) * step_span,
                            f"[{i + 1}/{total}] Kohdistetaan ({idx}/{tot_items})...",
                        )
                elif "[vaihe 3/4]" in line_s:
                    on_progress(
                        base_pct + 0.75 * step_span,
                        f"[{i + 1}/{total}] Injektoidaan litteroinnit...",
                    )
                elif "[vaihe 4/4" in line_s:
                    on_progress(
                        base_pct + 0.85 * step_span,
                        f"[{i + 1}/{total}] Auto-Silence...",
                    )

            if command[0] == "cache-list":
                cached = _list_cache(command[1], log, timeout)
                continue

            target = _upload_target(command)
            if target is not None and target[1] in cached:
                log(f"{Path(target[0]).name}: jo Colabissa, ei ladata uudestaan.")
                continue

            if command[0] == "flac-upload":
                code = _upload_as_flac(
                    command[1], Path(command[2]), command[3], log, timeout
                )
                if code != 0:
                    return code
                continue

            if command[0] == "chunked-upload":
                code = _upload_in_chunks(
                    command[1], Path(command[2]), command[3], log, timeout
                )
                if code != 0:
                    return code
                continue

            if len(command) >= 3 and command[0] == "drive" and command[1] == "upload":
                log(shlex.join(command))
                input_dir = command[2]
                parts = command[3].split("/")
                session = parts[1] if len(parts) >= 2 else "session"
                try:
                    upload_input_to_drive(input_dir, session, log)
                except Exception as err:
                    log(f"Google Drive -lataus epäonnistui: {err}")
                    err_msg = str(err).lower()
                    if on_drive_failure is not None and (
                        "403" in err_msg or "forbidden" in err_msg
                    ):
                        log(
                            "Drive ei ole käytettävissä tällä tilillä (403, quota "
                            "project puuttuu): jatketaan suoralla siirrolla."
                        )
                        commands[i + 1 :] = on_drive_failure()
                        total = len(commands)
                        continue
                    if "403" in err_msg or "forbidden" in err_msg:
                        log(
                            "Huom: Google Drive API vaatii aktiivisen GCP-projektin (quota project)."
                        )
                        log(
                            "Suosittelemme suoraa siirtoa ilman Drivea: valitse siirtotavaksi 'direct' (tai COLAB_TRANSFER=direct)."
                        )
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
                        [
                            "colab",
                            "exec",
                            "-s",
                            session,
                            f"tar -czf {remote_tar} -C {remote_dir} .",
                        ],
                        log,
                        timeout=timeout,
                        opened_auth_urls=opened_auth_urls,
                        on_line=_subline,
                    )
                    if code != 0:
                        return code

                    code = _execute_single(
                        ["colab", "download", "-s", session, remote_tar, str(local_tar)],
                        log,
                        timeout=timeout,
                        opened_auth_urls=opened_auth_urls,
                        on_line=_subline,
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
                        opened_auth_urls=opened_auth_urls,
                        on_line=_subline,
                    )
                continue

            code = _execute_single(
                command,
                log,
                timeout=timeout,
                opened_auth_urls=opened_auth_urls,
                on_line=_subline,
            )
            if code != 0:
                return code
        if trail is not None:
            trail.finish()
        if on_progress:
            on_progress(100.0, "Ajo valmis! Kaikki vaiheet suoritettu.")
        return 0
    except KeyboardInterrupt:
        log("Ajo keskeytetty käyttäjän toimesta (Ctrl+C).")
        return 130
