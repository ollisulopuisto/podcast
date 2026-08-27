"""Äänen puoli: mitä tästä sovelluksesta jää kirjaston ulkopuolelle.

Purku ja verhokäyrä ovat ``speechmix.rms``ssa. Tänne jää se mikä on
tämän sovelluksen omaa: **mihin** säilötään. Kirjasto ei valitse polkua
käyttäjän kotihakemistosta — kolme sovellusta säilövät omiin
hakemistoihinsa, ja kutsumatta kirjoittava kirjasto on kirjasto jota ei
uskalla ottaa käyttöön.
"""

from pathlib import Path


def cache_dir() -> Path:
    """Verhokäyrien välimuisti. Turvallista tyhjentää milloin tahansa.

    Sama juuri kuin pikkukuvilla ja videomittauksilla, eri alihakemisto:
    ``~/Library/Caches/autoraffkat/envelopes``. Hinta tyhjentämisestä on
    yksi purku tiedostoa kohden.
    """
    root = Path.home() / "Library" / "Caches" / "autoraffkat" / "envelopes"
    root.mkdir(parents=True, exist_ok=True)
    return root


__all__ = ["cache_dir"]
