"""IIR-suodatus joka ei hidastu digitaalisessa hiljaisuudessa.

scipyn ``sosfilt`` jättää tilansa denormaaleihin lukuihin kun ääni loppuu, ja
siitä lähtien jokainen laskutoimitus maksaa noin 25-kertaisesti koko
hiljaisuuden ajan: tila jää rajasykliin (1e-321 ...1e-324) eikä enää koskaan
vaimene nollaan. Puhujan stemi on suurimman osan ajasta tarkkaa nollaa
(kuulas vaimentaa sen mitä ei haluta), joten kaistajako, sihinänpoisto ja
naksujen tunnistus maksoivat tämän useimmilla näytteillään. Mitattu 2 min
stereomiksauksessa jossa 67 % stemeistä oli nollaa: ``sosfilt`` yksin 7,6 s
(0,5 s kun hiljaisuudessa oli -65 dB kohinaa), ja 8 min × 3 puhujaa 253 s
(169 s kohinalla).

Sama suodin lohkoina. Lohkojen yli kannetaan tila täsmälleen (scipyn oma
silmukka on näytteittäinen ja kulkee kaikki asteet läpi, joten lohkominen ei
muuta yhtäkään laskutoimitusta), ja lohkojen välissä jokaisen asteen tilapari
nollataan kun se on alle ``TINY``. Tulos on sama bitti bitiltä kaikkialla missä
ulostulo on yli 1e-150. Hiljaisuuden häntä leikkautuu nollaksi sen sijaan että
jäisi denormaaliksi roskaksi, ja nollauksen jälkeen laskennan pyöristys
poikkeaa scipyn omasta: mitattu 150 Hz:n alipäästöllä ero on suhteellisesti
enintään 3e-14 alueella 1e-250 … 1e-170 ja nolla sen yläpuolella, kun signaali
palaa (ero putoaa 1e-4:stä 1e-10:een ja 1e-14:ään muutamassa tuhannessa
näytteessä, ja häviää kokonaan kun uusi ääni ajaa tilan).
"""

from __future__ import annotations

import numpy as np

#: Kuinka suuri lohko kerrallaan. Nopeasti vaimenevalla suotimella tila ehtii
#: denormaaliin jo muutamassa sadassa näytteessä, ja se pysyy siellä seuraavaan
#: lohkon rajaan, joten lohko rajaa hitaan jakson pituuden. Toisaalta jokainen
#: lohko maksaa scipy-kutsun (~30 µs). Mitattu 62 s mono, 4 kHz / 1 kHz / 120 Hz
#: suotimet (scipy ilman lohkoja: 24-32 ms kohinalla, 160-560 ms kun 67 %
#: oli nollaa): lohko 4096 -> 82 / 85 ms, 16384 -> 43-56 ms kummallakin,
#: 65536 -> 38-78 ms (hitaampi nollilla). 16384 on 0,34 s.
BLOCK = 16384

#: Tilapari nollataan kun sen itseisarvojen summa on tätä pienempi. 1e-250 on
#: vielä 10^58 kertaa denormaalien (2,2e-308) yläpuolella, joten hidastusta ei
#: ehdi syntyä, ja tarpeeksi pieni ollakseen ulostulon kannalta merkityksetön:
#: ulostulo on korkeintaan satakertainen tilaan nähden, ja se putoaa ~1e-248
#: alle ulostulon pienimmänkin kuuluvan arvon (float32:n pienin positiivinen on
#: 1,4e-45) sekä kaikkien neliöiden alivuodon (alle 2,2e-162) alapuolelle.
TINY = 1e-250

#: Alle näin monta tarkkaa nollaa syötteessä suodatetaan yhdellä scipy-kutsulla.
#: Denormaalit syntyvät vain tarkasta hiljaisuudesta, ja hidastus kestää vain
#: sen aikaa (kun ääni palaa, tila ylikirjoittuu), joten alle MIN_ZEROS nollaa
#: maksaa enintään ~0,2 ms (2048 näytettä × ~100 ns). Lohkot taas maksavat joka
#: kerta: kohinalla 24-32 ms -> 38-85 ms minuutilta, ja ``declick`` meni
#: 8 min × 3 puhujan kohinalattiaisella ajolla 5,2 s -> 12,6 s.
MIN_ZEROS = 2048


def _clear_small(zi: np.ndarray) -> None:
    """Nollaa asteittain ne tilaparit (viimeinen akseli) jotka ovat alle TINYn.

    Pari kerralla eikä tila tilalta: toisen nollaaminen yksin syöttää
    toisen takaisin ja pari jää väreilemään TINYn tuntumaan ikuisesti."""
    small = np.abs(zi).sum(axis=-1) < TINY
    if small.any():
        zi[small] = 0.0


def sosfilt(sos, x, zi=None):
    """``scipy.signal.sosfilt(sos, x, axis=-1[, zi])`` hiljaisuudessa nopeana.

    Palauttaa ``y`` (ilman ``zi``tä) tai ``(y, zf)`` kuten scipy. ``zi`` on
    muotoa ``(asteet, ..., 2)`` ja se kopioidaan, ei muuteta."""
    from scipy import signal as _sig

    sos = np.asarray(sos)
    x = np.asarray(x)
    carry = zi is not None
    state = (np.array(zi, dtype=np.result_type(sos, x, np.float64), copy=True) if carry
             else np.zeros((sos.shape[0], *x.shape[:-1], 2),
                           dtype=np.result_type(sos, x, np.float64)))
    _clear_small(state)  # edellisen palan jättämä tila voi olla jo denormaali
    total = x.shape[-1]
    if total <= BLOCK or np.count_nonzero(x == 0) < MIN_ZEROS:
        y, state = _sig.sosfilt(sos, x, axis=-1, zi=state)
        _clear_small(state)
        return (y, state) if carry else y
    out = None
    for start in range(0, total, BLOCK):
        piece, state = _sig.sosfilt(sos, x[..., start:start + BLOCK], axis=-1, zi=state)
        if out is None:
            out = np.empty(x.shape, dtype=piece.dtype)
        out[..., start:start + piece.shape[-1]] = piece
        _clear_small(state)
    return (out, state) if carry else out


def sosfiltfilt(sos, x):
    """``scipy.signal.sosfiltfilt(sos, x)`` (utiloidaan paikka, oletuspehmuste)
    hiljaisuudessa nopeana. Sama laskenta kuin scipyssä: parittomalla
    jatkeella pidennetty signaali, eteen- ja taaksepäin, tasapainotilasta."""
    from scipy import signal as _sig

    sos = np.asarray(sos)
    x = np.asarray(x)
    n_sections = sos.shape[0]
    ntaps = 2 * n_sections + 1
    ntaps -= min(int((sos[:, 2] == 0).sum()), int((sos[:, 5] == 0).sum()))
    edge = ntaps * 3
    if x.shape[-1] <= edge:
        return _sig.sosfiltfilt(sos, x)  # nostaa saman virheen kuin ennen
    ext = np.concatenate(
        (2 * x[..., :1] - x[..., edge:0:-1], x, 2 * x[..., -1:] - x[..., -2:-(edge + 2):-1]),
        axis=-1,
    )
    zi = _sig.sosfilt_zi(sos).reshape(n_sections, *([1] * (x.ndim - 1)), 2)
    y, _ = sosfilt(sos, ext, zi=zi * ext[..., :1])
    y, _ = sosfilt(sos, y[..., ::-1], zi=zi * y[..., -1:])
    return y[..., ::-1][..., edge:-edge]
