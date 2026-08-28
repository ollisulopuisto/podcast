# -*- mode: python ; coding: utf-8 -*-
"""`nhsx-render` yhtenä tiedostona, ffmpeg mukana.

Tämä on se paketti, joka toimii kun muuta ei ole: ei Pythonia, ei uv:tä, ei
tätä repositoriota, ei Hindenburgia. Yksi tiedosto, joka lukee `.nhsx`:n ja
kirjoittaa WAVin.

Erillinen `.spec` eikä `podcast-magic.spec`in kohde, koska nämä ovat eri
kokoluokan tuotteita. Podcast Magic paketoi Whisperin, MLX:n Metal-varjostimet
ja koko selainkäyttöliittymän; tämä on `nhsx/`, numpy, lxml ja ffmpeg. Jos
esikatselu tai renderöinti vaatisi gigatavun latauksen, kukaan ei lataisi.

Yksitiedostoinen (`onefile`) tarkoituksella: käyttäjä saa yhden binäärin,
jonka voi pudottaa `/usr/local/bin`iin. Käynnistys purkaa paketin
väliaikaishakemistoon, mikä maksaa noin sekunnin — renderöinnissä se ei
merkitse mitään, ja `--plan` on silti selvästi nopeampi kuin istunnon
avaaminen mihinkään.

ffmpeg tulee mukaan `bin/`iin, mistä `binaries.get_binary_path` sen löytää
(`sys._MEIPASS`). Ilman sitä binääri kaatuisi ensimmäiseen renderöintiin
koneella jolla ei ole ffmpegiä — eli täsmälleen sillä koneella jota varten
tämä tehtiin. `scripts/fetch_binaries.py` hakee sen naulatusta versiosta
tarkistussummineen.
"""

from pathlib import Path

BASE_DIR = Path(SPEC).parent.resolve()  # noqa: F821 — PyInstaller antaa SPECin
SRC_DIR = BASE_DIR / "src"

binaries = []
bin_dir = BASE_DIR / "bin"
if bin_dir.exists():
    for item in bin_dir.glob("*"):
        if item.is_file() and not item.name.startswith("."):
            binaries.append((str(item), "bin"))

a = Analysis(  # noqa: F821
    # Käynnistin eikä `cli.py` suoraan: PyInstaller ajaa annetun tiedoston
    # `__main__`ina, jolloin `nhsx/cli.py`:n suhteelliset tuonnit kaatuvat.
    # Ks. `scripts/nhsx_render_entry.py`.
    [str(BASE_DIR / "scripts" / "nhsx_render_entry.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=[],
    hiddenimports=["lxml._elementpath"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Mitä tähän ei tule. Jokainen näistä on Podcast Magicissa ja jokainen
    # on kymmeniä tai satoja megatavuja; yksikään ei ole `nhsx/`:n tarpeita.
    # Ilman tätä listaa PyInstaller niputtaisi ne mukaan sen perusteella, mitä
    # samassa ympäristössä sattuu olemaan asennettuna.
    excludes=[
        "mlx", "mlx_whisper", "faster_whisper", "ctranslate2", "torch",
        "fastapi", "uvicorn", "starlette", "pywebview", "webview",
        "scipy", "pedalboard", "soundfile", "sounddevice", "textual",
        "matplotlib", "PIL", "tkinter", "IPython",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nhsx-render",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Konsolisovellus: tämä on komentorivityökalu, ja ilman tätä macOS
    # avaisi sen ikkunattomana eikä tulostusta näkyisi missään.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
