"""FCPXML:n luku autoraffkatille.

Lukija itse on `fcpxml`-paketissa, jotta kuulas ja autoraffkat lukevat viennin
samalla koodilla. Tämä lisää siihen sen minkä paketti tarkoituksella jättää
pois, koska se ei tunne sovellusta:

* **virheen kielellä**: paketin ``ReadError`` on vakaa ``code``, tässä siitä
  tulee käännetty teksti, jonka käyttöliittymä näyttää,
* **ruutunopeuden mediasta**: media voittaa XML:n formaatin, ja sen lukee
  ffprobe (``probe``), jota paketti ei tunne,
* **puuttuvien tiedostojen uudelleenlinkityksen** (``relink``),
* **oletusnimen**, kun XML ei nimeä projektia.
"""

from __future__ import annotations

import os
from fractions import Fraction

import fcpxml as core
from fcpxml import MulticamRef, Timeline, Track  # noqa: F401  uudelleenvienti

from ..i18n import t

# Mitä näytetään, kun XML ei nimeä projektia tai synkkaklippiä.
DEFAULT_NAMES = {
    "project": "Projekti",
    "multicam": "Projekti",
    "sync-clip": "Synkkaklippi",
}


class ReadError(core.ReadError):
    """Luettava XML ei kelpaa. ``str`` on käännetty teksti, ``code`` pakettinsa."""

    def __init__(self, error: core.ReadError) -> None:
        super().__init__(error.code, error.detail)
        # ``bad_xml`` kertoo mikä meni vikaan, ``bad_root`` mikä juuri oli,
        # ``bundle_without_info`` mikä paketti: kaikki kulkevat yhdellä nimellä.
        self.message = t(
            f"read.{error.code}", error=error.detail, tag=error.detail, path=error.detail
        )

    def __str__(self) -> str:
        return self.message


def _probed_rate(item) -> Fraction | None:
    """Tiedoston oma ruutunopeus ffprobella, tai None."""
    from .. import probe
    from ..timeline import parse_fps

    fps_val = probe.info(item.path).get("video", {}).get("fps")
    return Fraction(1, parse_fps(str(fps_val))) if fps_val else None


def probed_frame_duration(items: list) -> Fraction | None:
    """Ensimmäisen löytyvän videotiedoston ruutunopeus, tai None.

    Media voittaa aina XML:n formaattien ilmoituksen: formaatti voi väittää
    1/25s, mutta tiedosto ei voi. Probedoitu nopeus kirjoitetaan myös itse
    itemiin, jotta vienti ei konformoisi tiedostoa väärään tahtiin.
    """
    for item in items:
        if not (item.has_video and item.path and os.path.exists(item.path)):
            continue
        rate = _probed_rate(item)
        if rate:
            item.frame_duration = rate
            return rate
    return None


def read_fcpxml(path: str) -> Timeline:
    """Lukee FCPXML:n aikajanaksi: paketin lukija ja sovelluksen lisät."""
    try:
        tl = core.read_fcpxml(path, probe_frame_duration=_probed_rate)
    except core.ReadError as exc:
        raise ReadError(exc) from exc
    if not tl.name:
        tl.name = DEFAULT_NAMES.get(tl.kind, "Projekti")
    if any(not m.path or not os.path.exists(m.path) for m in tl.media):
        from ..relink import relink_timeline

        relink_timeline(tl, xml_path=path)
    return tl
