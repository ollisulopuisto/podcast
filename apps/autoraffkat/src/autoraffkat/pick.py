"""Lähde-XML:n valinta ilman polun kirjoittamista.

Tavallinen työjärjestys on: vie Final Cutista hakemistoon, aja työkalu samassa
hakemistossa. Polun kirjoittaminen on siinä pelkkää kitkaa, joten se etsitään:
hakemistosta löytyvä ainoa vienti kelpaa sellaisenaan, useammasta kysytään, ja
jos hakemisto on tyhjä, avataan Finderin valintaikkuna.

Final Cut vie joko yksittäisen ``.fcpxml``-tiedoston tai ``.fcpxmld``-paketin,
jonka sisällä XML on nimellä ``Info.fcpxml``. Molemmat kelpaavat lähteeksi ja
molemmat tarkoittavat tässä samaa asiaa.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading

from .model import LONGTAKE_RULES, OVERLAP_RULES, RHYTHM_PRESETS
from .project import LEGACY_OUTPUT_SUFFIXES, OUTPUT_SUFFIX

BUNDLE_EXT = ".fcpxmld"
BUNDLE_INNER = "Info.fcpxml"
XML_EXT = ".fcpxml"


def resolve(path: str) -> str:
    """Käyttäjän antama polku varsinaiseksi XML-tiedostoksi.

    ``.fcpxmld``-paketti on hakemisto, joten sen sisältä otetaan XML. Näin
    työkalulle voi antaa sen mitä Finderissa näkyy.
    """
    path = os.path.expanduser(path)
    if not re.match(r"^[a-zA-Z]:[\\/]", path):
        path = os.path.abspath(path)
    if os.path.isdir(path):
        inner = os.path.join(path, BUNDLE_INNER)
        if os.path.exists(inner):
            return inner
    return path


# Nimeen kirjoitettavat säätimet. Lista on tarkka eikä «mitä tahansa sanoja»:
# muuten tunnus nielaisisi vieraat nimet, ja hakemistoon jätetty
# "haastattelu-cut down.fcpxml" katoaisi lähdevalikosta.
_TAG_WORDS = (
    *RHYTHM_PRESETS, *OVERLAP_RULES, *LONGTAKE_RULES,
    "audio", "move", "vertical",
)

# Oma vienti tunnuksineen: "jakso-cut.fcpxml", "jakso-cut hectic audio.fcpxml",
# numeroituna "jakso-cut v3.fcpxml". Vanha suomenkielinen tunnus tunnistetaan
# yhä: levyllä on jo `-leikattu`-viennejä, eikä tunnuksen vaihtuminen saa tehdä
# niistä kelvollisia lähteitä.
_OUTPUT_RE = re.compile(
    "("
    + "|".join(re.escape(s) for s in (OUTPUT_SUFFIX, *LEGACY_OUTPUT_SUFFIXES))
    + r")(?: (?:"
    + "|".join(re.escape(w) for w in _TAG_WORDS)
    + r"|\d+(?:\.\d+)?s))*"
    + r"( v\d+)?$"
)


def _is_output(path: str) -> bool:
    """Onko tiedosto tämän työkalun oma vienti."""
    base, _ = os.path.splitext(os.path.basename(path))
    return _OUTPUT_RE.search(base) is not None


def candidates(directory: str) -> list[str]:
    """Hakemiston lähdekelpoiset viennit, uusin ensin.

    Omat viennit jätetään pois: silmukassa palataan aina alkuperäiseen
    lähteeseen, eikä valmis leikkaus ole se.
    """
    found: list[str] = []
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return []
    for name in entries:
        full = os.path.join(directory, name)
        if name.endswith(BUNDLE_EXT) and os.path.isdir(full):
            inner = os.path.join(full, BUNDLE_INNER)
            if os.path.exists(inner) and not _is_output(full):
                found.append(inner)
        elif name.endswith(XML_EXT) and os.path.isfile(full):
            if not _is_output(full):
                found.append(full)
    found.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return found


def label(path: str) -> str:
    """Näyttönimi: paketista sen oma nimi, ei sisällön ``Info.fcpxml``."""
    if os.path.basename(path) == BUNDLE_INNER:
        return os.path.basename(os.path.dirname(path))
    return os.path.basename(path)


def interactive() -> bool:
    """Onko vastaajaa.

    Ilman päätettä ei saa kysyä mitään eikä varsinkaan avata valintaikkunaa:
    putkessa tai ajastettuna se jäisi odottamaan käyttäjää, jota ei ole.
    """
    try:
        return sys.stdin.isatty() and sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def ask(paths: list[str]) -> str | None:
    """Numeroitu valinta terminaalissa. Tyhjä rivi valitsee uusimman."""
    if not interactive():
        return paths[0]
    print("Useampi vienti tässä hakemistossa:\n", file=sys.stderr)
    for index, path in enumerate(paths, 1):
        print(f"  {index}. {label(path)}", file=sys.stderr)
    print("", file=sys.stderr)
    try:
        answer = input("Numero (Enter = 1, uusin): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("", file=sys.stderr)
        return None
    if not answer:
        return paths[0]
    if answer.isdigit() and 1 <= int(answer) <= len(paths):
        return paths[int(answer) - 1]
    print(f"Ei valintaa: {answer!r}", file=sys.stderr)
    return None


# AppleScript kelpuuttaa myös paketin, koska ``.fcpxmld`` on Finderille
# tiedosto. Jos tyyppirajaus ei löydä mitään, kysytään hakemistoa: silloin
# käyttäjällä on paketti, jota järjestelmä ei tunne paketiksi.
_CHOOSE_FILE = """
try
    set f to choose file with prompt {prompt} of type {{"fcpxml", "fcpxmld"}} {start}
    return POSIX path of f
on error number -128
    return ""
end try
"""

_CHOOSE_FOLDER = """
try
    set f to choose folder with prompt {prompt} {start}
    return POSIX path of f
on error number -128
    return ""
end try
"""


def _osascript(script: str) -> str | None:
    """Ajaa AppleScriptin. Palauttaa tulosteen tai ``None`` jos ei onnistu."""
    try:
        done = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def _load_appkit():
    """AppKit tuodaan tässä, jotta testi voi pakottaa tuontivirheen."""
    from AppKit import NSApplication, NSApplicationActivationPolicyRegular

    return NSApplication, NSApplicationActivationPolicyRegular


def _ensure_foreground() -> bool:
    """Tekee prosessista sellaisen, jonka valintaikkuna nousee eteen.

    Pelkkä Python-prosessi ei ole macOS:lle käyttöliittymäsovellus, joten
    ``osascript``in valintaikkuna jäi muiden ikkunoiden taakse: käyttäjä näki
    työkalun jumiutuneena 300 s, kunnes löysi ikkunan Cmd+`-näppäimellä. Sama
    vikaluokka kuin liitännäisen ikkunalla, jonka ``speechmix.editor`` mittasi
    ratkaistun: ikkuna kyllä syntyy — siellä mitattuna 536×392 kohdassa
    (0, 37), kolmastoista ylimmästä — mutta ei nouse koskaan eteen. Samat
    kaksi askeltä täälläkin: ``NSApplicationActivationPolicyRegular`` antaa
    Dock-kuvakkeen ja oikeuden nousta eteen, ja aktivointi nostaa prosessin
    ylimmäksi.

    AppKit ei ole tämän sovelluksen oma riippuvuus, joten puuttuminen ei ole
    virhe: ikkuna aukeaa silloinkin, se on vain etsittävä itse. Ei-macOSissa
    tai ikkunapalvelinttömässä ympäristössä (pytest CI:ssä) apuri palauttaa
    kohteliaasti ``False``-arvon, ei koskaan poikkeusta.
    """
    if sys.platform != "darwin":
        return False
    try:
        NSApplication, regular = _load_appkit()
    except Exception:
        return False
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(regular)
    app.activateIgnoringOtherApps_(True)

    def nostetaan_uudelleen() -> None:
        # Toinen aktivointi kun ikkuna on oikeasti olemassa: ensimmäinen
        # tapahtuu ennen kuin valintaikkuna on piirtynyt. Aikaväli 1,0 s on
        # kopioitu ``speechmix.editor``istä, jossa se on mitattu riittäväksi.
        import time

        time.sleep(1.0)
        with contextlib.suppress(Exception):
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    threading.Thread(target=nostetaan_uudelleen, daemon=True).start()
    return True


def _pick_macos(mode: str, directory: str = "") -> str | None:
    """Finderin valintaikkuna AppleScriptillä."""
    prompt = (
        '"Valitse Final Cutista viety FCPXML"'
        if mode == "file"
        else '"Valitse mediatiedostojen kansio"'
    )
    start = f'default location POSIX file "{directory}"' if directory else ""
    templates = (_CHOOSE_FILE, _CHOOSE_FOLDER) if mode == "file" else (_CHOOSE_FOLDER,)
    for template in templates:
        _ensure_foreground()
        result = _osascript(template.format(prompt=prompt, start=start))
        if result:
            return result.rstrip("/")
        if result == "":
            return None
    return None


def _pick_windows(mode: str, directory: str = "") -> str | None:
    """Windowsin valintaikkuna PowerShellin (tai tkinterin) kautta."""
    escaped_dir = directory.replace("'", "''") if directory and os.path.exists(directory) else ""
    if mode == "file":
        init_part = f"$f.InitialDirectory = '{escaped_dir}';" if escaped_dir else ""
        script = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;"
            "$f = New-Object System.Windows.Forms.OpenFileDialog;"
            "$f.Title = 'Valitse FCPXML';"
            "$f.Filter = 'FCPXML (*.fcpxml;*.fcpxmld)|*.fcpxml;*.fcpxmld|Kaikki tiedostot (*.*)|*.*';"
            f"{init_part}"
            "$f.RestoreDirectory = $true;"
            "$top = New-Object System.Windows.Forms.Form;"
            "$top.TopMost = $true;"
            "if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.FileName }"
        )
    else:
        init_part = f"$f.SelectedPath = '{escaped_dir}';" if escaped_dir else ""
        script = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;"
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$f.Description = 'Valitse mediatiedostojen kansio';"
            f"{init_part}"
            "$top = New-Object System.Windows.Forms.Form;"
            "$top.TopMost = $true;"
            "if ($f.ShowDialog($top) -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $f.SelectedPath }"
        )
    if shutil.which("powershell"):
        try:
            done = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
            if done.returncode == 0 and not done.stdout.strip():
                return None  # Käyttäjä perui
        except (OSError, subprocess.TimeoutExpired):
            pass
    return _pick_tk(mode, directory)


def _pick_linux(mode: str, directory: str = "") -> str | None:
    """Linuxin valintaikkuna (zenity, kdialog tai tkinter)."""
    if shutil.which("zenity"):
        if mode == "file":
            cmd = [
                "zenity",
                "--file-selection",
                "--title=Valitse FCPXML",
                "--file-filter=FCPXML (*.fcpxml, *.fcpxmld) | *.fcpxml *.fcpxmld",
                "--file-filter=Kaikki tiedostot | *",
            ]
        else:
            cmd = [
                "zenity",
                "--file-selection",
                "--directory",
                "--title=Valitse mediatiedostojen kansio",
            ]
        if directory and os.path.exists(directory):
            cmd.append(f"--filename={os.path.abspath(directory)}/")
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
            if done.returncode == 1:
                return None  # Käyttäjä perui
        except (OSError, subprocess.TimeoutExpired):
            pass

    if shutil.which("kdialog"):
        if mode == "file":
            cmd = ["kdialog", "--getopenfilename", directory or ".", "*.fcpxml *.fcpxmld | FCPXML"]
        else:
            cmd = ["kdialog", "--getexistingdirectory", directory or "."]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
            if done.returncode == 1:
                return None
        except (OSError, subprocess.TimeoutExpired):
            pass

    return _pick_tk(mode, directory)


def _has_tk() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except (ImportError, OSError):
        return False


def _pick_tk(mode: str, directory: str = "") -> str | None:
    """Alustariippumaton varavalitsin tkinterillä."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        with contextlib.suppress(Exception):
            root.attributes("-topmost", True)
            root.focus_force()
        if mode == "file":
            res = filedialog.askopenfilename(
                initialdir=directory or None,
                title="Valitse FCPXML",
                filetypes=[("FCPXML files", "*.fcpxml;*.fcpxmld"), ("All files", "*.*")],
            )
        else:
            res = filedialog.askdirectory(
                initialdir=directory or None,
                title="Valitse mediatiedostojen kansio",
            )
        root.destroy()
        return res or None
    except Exception:
        return None


def has_native_picker() -> bool:
    """Tarkistaa onko järjestelmässä valintaikkunaa käytettävissä."""
    if sys.platform == "darwin":
        return bool(shutil.which("osascript"))
    if sys.platform == "win32":
        return bool(shutil.which("powershell")) or _has_tk()
    if sys.platform.startswith("linux"):
        return bool(shutil.which("zenity") or shutil.which("kdialog")) or _has_tk()
    return _has_tk()


def native(directory: str = "", force: bool = False) -> str | None:
    """Järjestelmän natiivi tiedostonvalintaikkuna. ``None`` jos peruttiin tai ei saatavilla.

    ``force`` on ``--pick`` tai palvelinkutsu: silloin ikkuna avataan vaikka pääte puuttuisi,
    koska käyttäjä nimenomaan pyysi sitä.
    """
    if not force and not interactive():
        return None
    if sys.platform == "darwin":
        path = _pick_macos("file", directory)
    elif sys.platform == "win32":
        path = _pick_windows("file", directory)
    elif sys.platform.startswith("linux"):
        path = _pick_linux("file", directory)
    else:
        path = _pick_tk("file", directory)
    if path:
        return resolve(path.rstrip("/\\"))
    return None


def native_folder(directory: str = "", force: bool = False) -> str | None:
    """Järjestelmän natiivi hakemiston valintaikkuna."""
    if not force and not interactive():
        return None
    if sys.platform == "darwin":
        path = _pick_macos("folder", directory)
    elif sys.platform == "win32":
        path = _pick_windows("folder", directory)
    elif sys.platform.startswith("linux"):
        path = _pick_linux("folder", directory)
    else:
        path = _pick_tk("folder", directory)
    if path:
        cleaned = path.rstrip("/\\")
        if re.match(r"^[a-zA-Z]:[\\/]", cleaned):
            return cleaned
        return os.path.abspath(cleaned)
    return None


def pick(directory: str) -> str | None:
    """Lähde ilman argumenttia: yksi löytyi, useampi kysytään, tyhjästä ikkuna."""
    found = candidates(directory)
    if len(found) == 1:
        return found[0]
    if found:
        return ask(found)
    return native(directory)
