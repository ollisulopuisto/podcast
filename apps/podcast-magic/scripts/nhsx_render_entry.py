#!/usr/bin/env python3
"""Paketoidun `nhsx-render`in sisäänkäynti.

Tämä on olemassa yhdestä syystä. `nhsx/cli.py` käyttää paketin sisäisiä
tuonteja (`from . import mix`), ja PyInstaller ajaa sille annetun tiedoston
`__main__`ina — jolloin paketti ei ole tiedossa ja jokainen suhteellinen
tuonti kaatuu:

    ImportError: attempted relative import with no known parent package

Asennettuna samaa ei tapahdu, koska `[project.scripts]`in kuori tuo moduulin
paketin kautta. Paketoitaessa se kuori pitää kirjoittaa itse, ja tämä on se.

Vika näkyi vasta ensimmäisessä oikeassa käännöksessä: `.spec` oli
kelvollinen, käännös meni läpi, binääri syntyi — ja kaatui ensimmäiseen
ajoon. Se on tämän talon vikaluokka, tällä kertaa pakkauksessa.
"""

from podcastmagic.nhsx.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
