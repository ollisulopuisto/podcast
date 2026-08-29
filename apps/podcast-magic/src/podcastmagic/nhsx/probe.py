"""Mittasignaali, jolla selvitetään mitä Hindenburg tekee istunnolle.

`prospect.py` kertoo mitä istunnossa **lukee**. Tämä on sitä varten, että
selviää mitä istunto **tekee**: signaali viedään Hindenburgiin, sille
tehdään tunnetut säädöt, jakso renderöidään, ja renderöidystä tiedostosta
luetaan mitä säädöt tekivät. Erotus lähteeseen on vastaus.

Siksi tämä on sini eikä kohinaa. Sinin verhokäyrä on luettavissa näyte
näytteeltä analyyttisestä signaalista; kohinalla verhokäyrä on olemassa
vain keskiarvona, ja sen lukeminen vaatii ikkunan. 2,5 sekunnin
häivytyksellä 10 ms:n ikkuna jättää joka pisteeseen ±0,3 dB hajontaa —
juuri sen verran että suora ja loiva kaari näyttävät samalta, eli
täsmälleen se ero jota ollaan mittaamassa.

Valinnat, ja miksi:

* **1000 Hz.** 48 kHz jakautuu sillä tasan 48 näytteeseen jaksossa, joten
  aluerajalle ei jää katkaistua jaksoa. Katkaistu jakso napsahtaa, ja
  napsahdus aluerajalla on juuri se mitä häivytystä etsivä mittaus voi
  luulla häivytykseksi.
* **-20 dBFS.** Yläpuolelle jää 20 dB varaa vahvistukselle ennen
  leikkautumista, alapuolelle 24-bittisessä tiedostossa yli 100 dB, eli
  häivytyksen loppupää on mitattavissa eikä huku kvantisointiin.
* **Mono.** Monon panorointi on yksikäsitteinen. Stereolähteellä ei voi
  erottaa panorointia balanssista, koska molemmat tekevät samalle
  dual-mono-materiaalille saman asian.
* **48 kHz.** Sama kuin istunnon `Samplerate`, joten mitään ei
  uudelleennäytteistetä matkalla.

Merkit ovat 50 ms:n vaimennuksia 10 sekunnin välein. Ne eivät ole
signaalia vaan maamerkkejä: niistä näkee Hindenburgin aaltomuodosta missä
tasasekunnit ovat, ja renderöidystä tiedostosta sen ettei mikään ole
siirtynyt ajassa. Sini jatkuu merkin yli vaiheessa — merkki on kerrottu
nollalla, ei leikattu pois — jotta verhokäyrän sovitus merkin yli ei
tuota roskaa.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

RATE = 48_000
FREQ = 1000.0
LEVEL_DB = -20.0

# 10 s välein, 50 ms kerrallaan. Merkkiä ei tule nollaan: se söisi alkuun
# sijoitetun häivytyksen ensimmäiset millisekunnit.
MARK_SPACING = 10.0
MARK_LENGTH = 0.050


def probe(
    seconds: float,
    *,
    rate: int = RATE,
    freq: float = FREQ,
    level_db: float = LEVEL_DB,
    mark_spacing: float = MARK_SPACING,
    mark_length: float = MARK_LENGTH,
) -> np.ndarray:
    """Sini, jonka huippu on tasan ``level_db`` ja jossa on maamerkit."""
    n = int(seconds * rate)
    t = np.arange(n) / rate
    amplitude = 10.0 ** (level_db / 20.0)
    x = amplitude * np.sin(2 * math.pi * freq * t)

    if mark_spacing > 0:
        # Kerrotaan nollalla eikä poisteta: vaihe jatkuu merkin yli.
        for k in range(1, int(seconds / mark_spacing) + 1):
            i = int(k * mark_spacing * rate)
            x[i : i + int(mark_length * rate)] = 0.0
    return x


def write_probe(path: Path, samples: np.ndarray, rate: int = RATE) -> None:
    """Kirjoittaa 24-bittisen monon.

    `soundfile` eikä käsin pakattu `wave`: 24-bittinen pakkaus meni tässä
    talossa kerran väärin niin, että tiedosto oli kelvollinen ja 48 dB
    liian hiljainen (ks. `render.py`). Mittalaitteessa sama virhe olisi
    näkymätön, koska se siirtäisi jokaista tulosta yhtä paljon.
    """
    import soundfile as sf

    sf.write(str(path), samples, rate, subtype="PCM_24")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Mittasignaali Hindenburgin taso-, panorointi- ja häivytyskokeisiin.",
    )
    p.add_argument("-o", "--output", type=Path, default=Path("nhsx-probe.wav"))
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--rate", type=int, default=RATE)
    p.add_argument("--freq", type=float, default=FREQ)
    p.add_argument("--level-db", type=float, default=LEVEL_DB)
    p.add_argument(
        "--no-marks",
        action="store_true",
        help="ilman 10 sekunnin maamerkkejä",
    )
    a = p.parse_args(argv)

    x = probe(
        a.seconds,
        rate=a.rate,
        freq=a.freq,
        level_db=a.level_db,
        mark_spacing=0.0 if a.no_marks else MARK_SPACING,
    )
    write_probe(a.output, x, a.rate)
    peak = 20 * math.log10(float(np.max(np.abs(x))))
    print(f"{a.output}: {a.seconds:g} s, {a.rate} Hz, {a.freq:g} Hz, huippu {peak:.3f} dBFS")
    if not a.no_marks:
        print(f"Maamerkit {MARK_SPACING:g} s välein, {MARK_LENGTH * 1000:g} ms kerrallaan.")
    return 0
