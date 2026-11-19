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


# Pino: kaksi 1080×960 paneelia päällekkäin. Aiempi kiinteä neliö (1080×1080,
# keskeltä) jätti ±120 px lähteestä ruudun ulkopuolelle eikä seurannut
# kasvoja: pp 57:n pystyviennissä pään yläosa ja kasvojen reuna leikkautuivat
# (2026-10-16). Paneeli kulkee saman kehystäjän läpi kuin asettelun paneelit.


def stack_panel(sign: int, project_w: int = PROJECT_W,
                project_h: int = PROJECT_H) -> Panel:
    """Pinon puolikas: ``sign`` +1 on ylempi, −1 alempi."""
    half = project_h // 2
    return Panel(0, 0 if sign > 0 else half, project_w, half)


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
    """Paneelin Final Cut -muoto: tasainen skaala ja sijainti, ei rajausta."""

    scale: float
    pos_x: float
    pos_y: float


def fcp_panel(panel: Panel, window: tuple[float, float, float, float],
              src_w: int, src_h: int, project_w: int = PROJECT_W,
              project_h: int = PROJECT_H, zoom: float = 1.0) -> FcpPanel:
    """Ikkuna → ``adjust-transform`` (konformi ``none``), EI ``adjust-crop``ia.

    Final Cut skaalaa rajatun alueen akselikohtaisesti TÄYTTÄMÄÄN
    muunnetun kehyksen (varmistettu 2026-11-19 diagnostiikkaprojektilla),
    joten ``adjust-crop`` ei käy ikkunointiin: ikkuna tulisi käytetyksi
    kahdesti. Ilman rajausta alue on koko lähde, skaala pysyy tasaiseksi
    ja sijainti keskittää ikkunan paneeliin. Kehys on lähde × skaala,
    asetettuna projektin keskelle + sijainti; projektin reunoilla
    yli menevä osa leikkautuu pois. Tämän varmisti myös käyttäjän
    manuaalinen korjaus (2026-11-19: 37 klippiä, rajaus poistettu,
    tasainen skaala 0,96, sijainti 0/±25).

    Skaala on paneelin peittävä tasainen skaala ``max(w/src_w, h/src_h)``
    kerrottuna ``zoom``illa. ``zoom`` > 1 kiristää näkyvää ikkunaa
    (traileri: käyttäjän valitsema 0,96 / 0,8889 ≈ 1,08).

    **Sijainnin yksikkö** on prosenttia projektin korkeudesta, y ylöspäin.
    """
    wx, wy, ww, wh = window
    s = max(panel.w / src_w, panel.h / src_h) * zoom
    cx, cy = panel.centre
    unit = project_h / 100.0
    return FcpPanel(
        scale=s,
        pos_x=(cx - project_w / 2 - (wx + ww / 2 - src_w / 2) * s) / unit,
        pos_y=(project_h / 2 - cy + (wy + wh / 2 - src_h / 2) * s) / unit,
    )
