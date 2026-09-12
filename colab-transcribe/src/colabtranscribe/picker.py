"""Interaktiivinen kansion ja tiedoston valinta järjestelmän ikkunoilla.

Käyttäjän ei tarvitse kirjoittaa polkuja käsin:
macOS:lla avataan Finderin valintaikkuna (AppleScript / osascript),
Windowsilla PowerShell/dialogi, Linuxilla zenity/kdialog ja muuten tkinter.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading

_CHOOSE_FOLDER = """
try
    set f to choose folder with prompt {prompt} {start}
    return POSIX path of f
on error number -128
    return ""
end try
"""


def _load_appkit():
    """AppKit tuodaan tässä, jotta testi voi ohittaa tai korvata sen."""
    from AppKit import NSApplication, NSApplicationActivationPolicyRegular

    return NSApplication, NSApplicationActivationPolicyRegular


def _ensure_foreground() -> bool:
    """Nostaa prosessin etualalle macOS:ssa jotta valintaikkuna näkyy."""
    if sys.platform != "darwin":
        return False
    try:
        NSApplication, regular = _load_appkit()
    except Exception:
        return False
    try:
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(regular)
        app.activateIgnoringOtherApps_(True)

        def nostetaan_uudelleen() -> None:
            import time

            time.sleep(0.5)
            with contextlib.suppress(Exception):
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        threading.Thread(target=nostetaan_uudelleen, daemon=True).start()
        return True
    except Exception:
        return False


def _osascript(script: str) -> str | None:
    """Ajaa AppleScriptin ja palauttaa tulosteen."""
    try:
        done = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def _pick_macos(directory: str = "", prompt: str = "") -> str | None:
    prompt_text = f'"{prompt}"' if prompt else '"Valitse kansio"'
    start = (
        f'default location POSIX file "{directory}"'
        if directory and os.path.exists(directory)
        else ""
    )
    _ensure_foreground()
    result = _osascript(_CHOOSE_FOLDER.format(prompt=prompt_text, start=start))
    if result:
        return result.rstrip("/")
    return None


def _has_tk() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except (ImportError, OSError):
        return False


def _pick_tk(directory: str = "", prompt: str = "") -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        with contextlib.suppress(Exception):
            root.attributes("-topmost", True)
            root.focus_force()
        res = filedialog.askdirectory(
            initialdir=directory or None,
            title=prompt or "Valitse kansio",
        )
        root.destroy()
        return res or None
    except Exception:
        return None


def _pick_windows(directory: str = "", prompt: str = "") -> str | None:
    escaped_dir = (
        directory.replace("'", "''") if directory and os.path.exists(directory) else ""
    )
    init_part = f"$f.SelectedPath = '{escaped_dir}';" if escaped_dir else ""
    title = prompt or "Valitse kansio"
    script = (
        "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;"
        "$f = New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$f.Description = '{title}';"
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
                return None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return _pick_tk(directory, prompt)


def _pick_linux(directory: str = "", prompt: str = "") -> str | None:
    if shutil.which("zenity"):
        title = prompt or "Valitse kansio"
        cmd = ["zenity", "--file-selection", "--directory", f"--title={title}"]
        if directory and os.path.exists(directory):
            cmd.append(f"--filename={os.path.abspath(directory)}/")
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
            if done.returncode == 1:
                return None
        except (OSError, subprocess.TimeoutExpired):
            pass

    if shutil.which("kdialog"):
        cmd = ["kdialog", "--getexistingdirectory", directory or "."]
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if done.returncode == 0 and done.stdout.strip():
                return done.stdout.strip()
            if done.returncode == 1:
                return None
        except (OSError, subprocess.TimeoutExpired):
            pass

    return _pick_tk(directory, prompt)


def has_native_picker() -> bool:
    """Onko järjestelmässä käytettävissä natiivi valintaikkuna."""
    if sys.platform == "darwin":
        return bool(shutil.which("osascript"))
    if sys.platform == "win32":
        return bool(shutil.which("powershell")) or _has_tk()
    if sys.platform.startswith("linux"):
        return bool(shutil.which("zenity") or shutil.which("kdialog")) or _has_tk()
    return _has_tk()


def pick_folder(directory: str = "", prompt: str = "") -> str | None:
    """Avaa järjestelmän natiivin kansionvalintaikkunan.

    Palauttaa valitun kansion polun tai None jos käyttäjä peruutti.
    """
    if sys.platform == "darwin":
        path = _pick_macos(directory, prompt)
    elif sys.platform == "win32":
        path = _pick_windows(directory, prompt)
    elif sys.platform.startswith("linux"):
        path = _pick_linux(directory, prompt)
    else:
        path = _pick_tk(directory, prompt)

    if path:
        cleaned = path.rstrip("/\\")
        if re.match(r"^[a-zA-Z]:[\\/]", cleaned):
            return cleaned
        return os.path.abspath(cleaned)
    return None
