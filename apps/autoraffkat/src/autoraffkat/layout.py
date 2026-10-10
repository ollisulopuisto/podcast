"""Pystyviennin asettelut: mitä ruudun osaa mikin kuva peittää.

Nopea kerros, ei tiedostoja. Asettelu jakaa 1080×1920-ruudun paneeleihin, ja
jokainen paneeli on suorakulmio projektin pikseleinä. Sama paneeli kertoo sekä
Final Cut -viennille (``fcp_panel``: rajaus, skaala, sijainti) että
renderöinnille (``window_of``: mikä osa lähteestä näkyy paneelissa), jotta ne
eivät voi sopia keskenään eri asioista.

``single`` on entinen: yksi kuva koko ruudulla. ``wide_top`` ja
``wide_bottom`` ovat kaksi kuvaa yhtä aikaa: laaja koko leveydeltä omassa
16:9-paneelissaan ja puhujan lähikuva loppuruudun täyttäen. Esimerkkinä
Esquiren haastattelut, joissa laaja näyttää kenen kanssa ollaan ja lähikuva
kuka puhuu.
"""

from __future__ import annotations

from dataclasses import dataclass

PROJECT_W = 1080
PROJECT_H = 1920

LAYOUT_SINGLE = "single"
LAYOUT_WIDE_TOP = "wide_top"
LAYOUT_WIDE_BOTTOM = "wide_bottom"
# Asettelu vaihtuu jakson mukana: ks. ``autolayout.py``. Ei paneeleita itsessään,
# koska jokaisella kuvalla on oma asettelunsa.
LAYOUT_AUTO = "auto"
LAYOUTS = (LAYOUT_SINGLE, LAYOUT_WIDE_TOP, LAYOUT_WIDE_BOTTOM, LAYOUT_AUTO)

# Sana jolla asettelu kirjoitetaan viennin nimeen (``project.name_tag``);
# ``single`` ei kirjoita mitään, koska se on oletus.
LAYOUT_TAGS = {LAYOUT_WIDE_TOP: "widetop", LAYOUT_WIDE_BOTTOM: "widebottom",
               LAYOUT_AUTO: "autolayout"}

# Laaja kuva on 16:9 ja täyttää leveyden. 1080 × 9/16 = 607,5; parillinen
# korkeus 608 on lähin kokonaisluku, ja sen 0,5 px:n erolla lähde rajataan
# 0,8 px sivuiltaan (ks. ``window_of``).
WIDE_ASPECT = 16 / 9


@dataclass(frozen=True)
class Panel:
    """Suorakulmio projektin pikseleinä, y ylhäältä alas."""

    x: int
    y: int
    w: int
    h: int

    @property
    def centre(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2


@dataclass(frozen=True)
class Panels:
    """Asettelun kaksi paneelia: laaja ja puhujan lähikuva."""

    wide: Panel
    close: Panel


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def panels(layout: str, project_w: int = PROJECT_W,
           project_h: int = PROJECT_H) -> Panels | None:
    """Asettelun paneelit, tai ``None`` kun asettelu on ``single`` (tai tuntematon).

    Laajan korkeus tulee leveydestä ja kuvasuhteesta, ei asetuksesta: se on
    kuvan luontainen koko, jolloin laajasta ei leikata mitään. Lähikuva saa
    jäljelle jäävän korkeuden.
    """
    if layout not in (LAYOUT_WIDE_TOP, LAYOUT_WIDE_BOTTOM):
        return None
    wide_h = _even(project_w / WIDE_ASPECT)
    close_h = project_h - wide_h
    if layout == LAYOUT_WIDE_TOP:
        return Panels(Panel(0, 0, project_w, wide_h),
                      Panel(0, wide_h, project_w, close_h))
    return Panels(Panel(0, close_h, project_w, wide_h),
                  Panel(0, 0, project_w, close_h))


def window_of(src_w: int, src_h: int, frame_w: int, frame_h: int,
              scale: float = 1.0, pos_x: float = 0.0,
              pos_y: float = 0.0) -> tuple[float, float, float, float]:
    """Lähteen näkyvä ikkuna ``(x, y, leveys, korkeus)`` lähteen pikseleinä.

    ``scale`` ja ``pos_*`` ovat kehystäjän luvut täytön päälle (ks.
    ``reframe.Reframe``): 1,0 on lähde joka täyttää kehyksen, sijainti on
    prosentteina kehyksen korkeudesta, y ylöspäin. Ikkuna pysyy lähteen
    sisällä. Sama laskenta kuin ``render._source_window``, kehyksen
    koolla eikä projektin.
    """
    fill = max(frame_w / src_w, frame_h / src_h)
    k = fill * scale
    shown_w, shown_h = src_w * k, src_h * k
    unit = frame_h / 100.0
    x = min(max(shown_w / 2 - frame_w / 2 - pos_x * unit, 0.0), max(0.0, shown_w - frame_w))
    y = min(max(shown_h / 2 - frame_h / 2 + pos_y * unit, 0.0), max(0.0, shown_h - frame_h))
    return x / k, y / k, frame_w / k, frame_h / k


@dataclass(frozen=True)
class FcpPanel:
    """Paneelin Final Cut -muoto: rajaus prosentteina, skaala ja sijainti."""

    left: float
    right: float
    top: float
    bottom: float
    scale: float
    pos_x: float
    pos_y: float


def fcp_panel(panel: Panel, window: tuple[float, float, float, float],
              src_w: int, src_h: int, project_w: int = PROJECT_W,
              project_h: int = PROJECT_H) -> FcpPanel:
    """Ikkuna → ``adjust-crop`` + ``adjust-transform`` (konformi ``none``).

    Lähde on natiivikokoinen, joten skaala on paneelin leveys jaettuna
    ikkunan leveydellä. Final Cut skaalaa klipin keskipisteen ympäri ja
    rajaus jättää jäljelle olevan osan paikalleen, joten ikkunan keskipiste
    päätyy keskipisteestä ``skaala × (ikkunan keskipiste − lähteen keskipiste)``
    päähän; sijainti on paneelin keskipisteen ja sen erotus. Prosentit ovat
    projektin korkeudesta kuten Final Cutin oma sijainti.

    **Oletus, ei vielä tuotu Final Cutiin:** rajauksen yksikkö (prosentti
    leveydestä vasemmalle ja oikealle, korkeudesta ylös ja alas) ja se, että
    skaalaus pyörii rajaamattoman klipin keskipisteen ympäri. Symmetrinen
    rajaus keskellä ei riipu jälkimmäisestä.
    """
    wx, wy, ww, wh = window
    scale = panel.w / ww
    off_x = wx + ww / 2 - src_w / 2
    off_y = wy + wh / 2 - src_h / 2
    cx, cy = panel.centre
    dest_x = cx - project_w / 2
    dest_y = project_h / 2 - cy
    unit = project_h / 100.0
    return FcpPanel(
        left=wx / src_w * 100,
        right=(src_w - wx - ww) / src_w * 100,
        top=wy / src_h * 100,
        bottom=(src_h - wy - wh) / src_h * 100,
        scale=scale,
        pos_x=(dest_x - scale * off_x) / unit,
        pos_y=(dest_y + scale * off_y) / unit,
    )
