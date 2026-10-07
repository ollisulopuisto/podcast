"""Ristivuodon vähennys: sama ääni toisessa mikissä, viiveellä.

Kaksi mikkiä samassa huoneessa kuulevat molemmat puhujat. Kun raidat
soivat yhdessä — ja viennissä ne soivat, molemmat ovat monikameran
kulmia — toisen puhujan ääni tulee kahdesti: omalta raidaltaan ja toisen
mikin vuotona muutama millisekunti myöhemmin. Se on kampasuodin, ja se
kuulostaa metalliselta kaiulta.

**Portti ei riitä, eikä syvempi portti auta.** Mitattuna oikealla
jaksolla: vaimennus toimii ja osuu oikeaan kohtaan, mutta ääretönkin
syvyys siirsi summan aaltoilua 6,22 dB:stä 6,01 dB:hen. Syy on siinä
missä maskin aukot ovat — puheenvuorojen vaihdoissa, joissa vuoto on
kovimmillaan. Portti ei myöskään voi tehdä mitään päällekkäiselle
puheelle, jossa molempien mikkien on oltava auki.

**Vuoto on lineaarinen, joten se voidaan vähentää.** Sama lähde, sama
huone, kiinteä viive ja varhaiset heijastukset: se on FIR-suodin
lähdemikistä kohdemikkiin. Suodin estimoidaan pienimmän neliösumman
mielessä niistä jaksoista joissa **vain lähde** puhuu — muuten ratkaisu
vähentäisi kohteen omaa puhetta — ja vähennetään kaikkialta, myös
päällekkäisen puheen alta.

Mitattuna 300 sekunnin jaksolla, koherenssi 200–6000 Hz kohde- ja
lähderaidan välillä silloin kun vain lähde puhuu:

    raaka                       0,1734
    raaka + vähennys            0,0095
    ketjun jälkeen, nykyinen    0,1069
    ketjun jälkeen, vähennyksen 0,0098

ja kohteen oma puhe säilyi korrelaatiolla 0,9993.

**Tämä ajetaan raa'alla äänellä ennen liitännäistä.** Liitännäinen on
generatiivinen: se ei säilytä raitojen välistä lineaarista suhdetta, ja
sen jälkeen vuotoa ei enää voi vähentää millään suotimella.

**Tulos tarkistetaan, ei uskota.** Estimaatti voi mennä pieleen — liian
vähän aineistoa, väärin valitut jaksot, mikki joka on liikkunut kesken
jakson — ja pieleen mennyt vähennys syö kohteen omaa puhetta. Siksi
``remove`` mittaa lopputuloksen ja hylkää suotimen joka ei kelpaa. Hiljaa
väärässä oleva vähennys kuuluu vasta viennin jälkeen.
"""

from __future__ import annotations

import numpy as np

# Suotimen pituus. 8192 näytettä on 171 ms 48 kHz:llä.
#
# Tässä luki pitkään 2048 (43 ms) sillä perusteella, että suora ääni (5–7 ms
# mitattuna) ja varhaiset heijastukset mahtuvat eikä myöhäistä jälkikaikua
# tarvitse tavoittaa, koska se on hajonnut eikä muodosta kampaa. Mitattuna
# se ei pidä paikkaansa: pituudesta on hyötyä pitkälle yli 43 ms:n.
#
# Kokonainen jakso (68,7 min, kaksi mikkiä 1,8 m:n päässä toisistaan):
#
#     tapit   vuotoa pois   oma puhe   aika     muisti
#      2048      3,92 dB     0,9999    33,1 s   10,6 GB
#      8192      5,14 dB     0,9999    33,5 s   11,3 GB
#     16384      5,2  dB     0,9999     —        —
#
# Hyöty loppuu 8192:een: 16384 toi 0,14 dB lisää ja kaksinkertaistaa
# suotimen. Hintaa ei mitattu olevan: 0,4 s ja 0,7 GB koko jaksosta.
# Kuunneltuna 8192 oli parempi molemmilla puhujilla, siirtymät mukaan
# lukien, eikä raitojen summaan syntynyt uutta artefaktia — ylisovittunut
# suodin käyttäytyisi päinvastoin.
TAPS = 8192

# Autokorrelaation diagonaalin korotus. Ilman tätä Toeplitz-ratkaisu on
# huonosti ehdollistettu kaistoilla joilla lähteessä ei ole energiaa.
REGULARISATION = 1e-4

# Vähempää aineistoa ei kannata estimoida: suodin sovittuu kohinaan.
MIN_SOLO_SECONDS = 20.0

# Kohteen oman puheen on säilyttävä. Alle tämän korrelaation vähennys on
# osunut puheeseen eikä vuotoon, ja suodin hylätään.
MIN_SPEECH_KEPT = 0.99

# Vähennyksen on myös tehtävä jotain. Tätä pienempi muutos vuotojaksoissa
# ei ole vähennys vaan mittausvirhe, eikä siitä kannata maksaa.
MIN_REDUCTION_DB = 0.5


# Kuinka pitkissä paloissa korrelaatiot lasketaan.
#
# Sadan tuhannen näytteen palat olisivat turhan pieniä ja kymmenen miljoonan
# turhan isoja; miljoona on FFT:lle nopea ja muistille olematon.
_LAG_BLOCK = 1 << 20


def _lags(a: np.ndarray, b: np.ndarray, taps: int) -> np.ndarray:
    """``out[k] = sum_n a[n+k] * b[n]`` viiveille ``0 … taps-1``.

    Paloittain, eikä koko ``2n-1`` mittaista korrelaatiota josta leikataan
    kaksituhatta lukua. Ero ei ole hienosäätöä: tunnin mikki on 184
    miljoonaa näytettä, jolloin täysi korrelaatio on 368 miljoonaa
    liukulukua ja sen FFT pyöristyy seuraavaan nopeaan pituuteen — useita
    gigatavuja, ja siinä koossa ratkaisu ei enää tullut ulos. Oireena
    «vuotopolkua ei saatu ratkaistua» **vain pitkissä osissa**: 20 minuutin
    tiedostot menivät läpi, 64 minuutin eivät.

    Sama virhe kuin ``np.correlate(..., "full")``ssa siirtymän mittauksessa
    ja ``keyframe_times``issa videopuolella: lasketaan kaikki ja otetaan
    siitä murto-osa. Summat ovat tässä samat luku luvulta, vain kertyminen
    on eri järjestyksessä.
    """
    from scipy import signal as sig

    n = min(len(a), len(b))
    out = np.zeros(taps, dtype=np.float64)
    step = max(taps * 4, _LAG_BLOCK)
    for start in range(0, n, step):
        stop = min(start + step, n)
        piece = np.asarray(b[start:stop], dtype=np.float64)
        if not piece.size:
            break
        # Laajennettu pala kantaa viiveet palan reunan yli, joten raja ei
        # katkaise yhtään summan termiä. Lopussa signaali loppuu kesken, ja
        # silloin **nollataan**, ei lyhennetä: täysi korrelaatio tekee
        # saman implisiittisesti, ja lyhentäminen jättäisi pitkät viiveet
        # laskematta — jolloin ``out`` täyttyisi vain viiveelle nolla.
        wide = np.asarray(a[start:start + piece.size + taps - 1],
                          dtype=np.float64)
        if wide.size < piece.size + taps - 1:
            wide = np.pad(wide, (0, piece.size + taps - 1 - wide.size))
        found = sig.correlate(wide, piece, "valid", method="fft")
        out[: found.size] += found[:taps]
    return out


# Yhteisen kierroksen pala. Mitattu 10 minuutista (8192 tappia, 35 %
# soolona): 2^15 0,44 s, 2^16 0,42 s, 2^18 0,64 s, 2^20 0,98 s. Pienempi
# pala ohittaa enemmän ei-soolo-aikaa; tappien ylimeno on 2^16:lla 12 %.
_PAIR_BLOCK = 1 << 16


def _lag_pair(
    target: np.ndarray, source: np.ndarray, taps: int, keep=None
) -> tuple[np.ndarray, np.ndarray]:
    """``(_lags(source, source), _lags(target, source))`` yhdellä kierroksella.

    Molemmat summat kertovat saman lähdepalan muunnoksella, joten se
    lasketaan kerran. Pala jossa lähde on kokonaan nolla ei lisää
    kumpaankaan summaan mitään ja ohitetaan — ``path`` nollaa kaiken
    soolojen ulkopuolelta, joten tällaisia on suurin osa. Pyöreä
    korrelaatio on tässä sama kuin lineaarinen, koska FFT on vähintään
    palan ja tappien mittainen: viiveet ``< taps`` eivät kierrä.

    ``keep`` (valinnainen) nollaa molemmat signaalit sen ulkopuolelta pala
    kerrallaan, float64:ssä: sama kuin maskattu kopio etukäteen, mutta
    raidan mittaisia float64-kopioita ei synny (5 min: 4 × float32-raita).
    """
    from scipy import fft

    n = min(len(target), len(source))
    if keep is not None:
        n = min(n, len(keep))

    def masked(x, a, b):
        if keep is None:
            return np.asarray(x[a:b], dtype=np.float64)
        return np.multiply(x[a:b], keep[a:b], dtype=np.float64)

    block = max(_PAIR_BLOCK, taps)
    size = fft.next_fast_len(block + taps - 1, real=True)
    auto = np.zeros(taps, dtype=np.float64)
    cross = np.zeros(taps, dtype=np.float64)
    for start in range(0, n, block):
        stop = min(start + block, n)
        piece = masked(source, start, stop)
        if not piece.any():
            continue
        conj = np.conj(fft.rfft(piece, size))
        # Laajennettu pala kantaa viiveet palan reunan yli; ``rfft``
        # täyttää lopun nollilla, kuten ``_lags``in nollaus.
        for out, x in ((auto, source), (cross, target)):
            wide = masked(x, start, min(stop + taps - 1, n))
            out += fft.irfft(fft.rfft(wide, size) * conj, size)[:taps]
    return auto, cross


def path(
    target: np.ndarray,
    source: np.ndarray,
    keep: np.ndarray,
    taps: int = TAPS,
) -> np.ndarray:
    """Pienimmän neliösumman FIR ``source`` -> ``target``, vain ``keep``-näytteillä.

    ``keep`` on totuusarvotaulukko: ne näytteet joissa vain lähde on
    äänessä. Molemmat signaalit nollataan sen ulkopuolelta ennen
    korrelaatioita, jolloin summat kertyvät vain valituista kohdista.

    Normaaliyhtälöt ratkaistaan Toeplitz-rakenteesta: matriisi olisi
    2048×2048 ja sen muodostaminen turhaa, kun autokorrelaatio määrää sen
    kokonaan.
    """
    from scipy import linalg

    n = min(len(target), len(source), len(keep))
    # Totuusarvoilla kertominen on sama kuin 1,0/0,0-maski; muu maski
    # kerrotaan float64:nä kuten ennen.
    mask = np.asarray(keep[:n])
    if mask.dtype != bool:
        mask = mask.astype(np.float64)
    auto, cross = _lag_pair(target, source, taps, mask)
    if not auto.any():                 # lähde hiljaa koko soolon ajan
        return np.zeros(taps)
    if auto[0] <= 0:
        return np.zeros(taps)
    auto[0] *= 1.0 + REGULARISATION
    try:
        return linalg.solve_toeplitz((auto, auto), cross)
    except (linalg.LinAlgError, ValueError):
        return np.zeros(taps)


def _level(x: np.ndarray, keep: np.ndarray) -> float:
    picked = np.asarray(x)[: len(keep)][np.asarray(keep, dtype=bool)]
    if picked.size == 0:
        return -np.inf
    return 10.0 * np.log10(float(np.mean(np.asarray(picked, np.float64) ** 2)) + 1e-30)


#: Vuotosuodatuksen lohko näytteinä (overlap-add). Mitattu 10 minuutista
#: 8192 tapilla: 2^15 0,54 s, 2^16 0,49 s, 2^18 0,49 s; muisti vakiona.
LEAK_CHUNK = 1 << 16


def leak(source, filt: np.ndarray, frames: int) -> np.ndarray:
    """``source`` suodatettuna vuotopolulla, ``frames`` näytettä.

    Sama kuin ``fftconvolve(source, filt)[:frames]``, mutta lohkoittain ja
    summaten (overlap-add). Koko raita yhtenä FFT:nä oli de-bleedin
    muistihuippu: viiden minuutin raidalle 0,7 GB, 47 minuutin jaksolle
    gigatavuja (memray, 2026-10-06). Suotimen muunnos lasketaan kerran;
    ``fftconvolve`` palaa kohden laski sen joka lohkolle (0,80 -> 0,49 s
    10 minuutista).
    """
    from scipy import fft

    x = source
    filt = np.asarray(filt, dtype=np.float64)
    size = fft.next_fast_len(LEAK_CHUNK + filt.size - 1, real=True)
    response = fft.rfft(filt, size)
    out = np.zeros(frames, dtype=np.float64)
    for start in range(0, min(len(x), frames), LEAK_CHUNK):
        piece = np.asarray(x[start:start + LEAK_CHUNK], dtype=np.float64)
        full = fft.irfft(fft.rfft(piece, size) * response, size)
        end = min(frames, start + piece.size + filt.size - 1)
        out[start:end] += full[: end - start]
    return out

def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearsonin korrelaatio omistetuista kopioista, keskistys paikallaan.

    ``np.corrcoef`` pinoaa ja keskistää omat kopionsa: se oli de-bleedin
    muistihuippu (5 min: 6,0 × float32-raita, tämän kanssa 3,6). Sama
    kaava; lukema voi erota viimeisissä biteissä.
    """
    a -= a.mean()
    b -= b.mean()
    return float(np.dot(a, b) / np.sqrt(np.dot(a, a) * np.dot(b, b)))


def remove(
    target: np.ndarray,
    source: np.ndarray,
    rate: int,
    solo_source: np.ndarray,
    solo_target: np.ndarray,
    taps: int = TAPS,
) -> tuple[np.ndarray, dict]:
    """Vähentää ``source``:n vuodon ``target``:sta.

    ``solo_source`` ja ``solo_target`` ovat näytekohtaisia totuusarvoja:
    kohdat joissa vain lähde puhuu (estimointiin) ja joissa vain kohde
    puhuu (tarkistukseen).

    Palauttaa ``(tulos, tiedot)``. Jos suodin ei kelpaa, tulos on
    alkuperäinen ja ``tiedot["reason"]`` kertoo miksi — vähennystä ei
    tehdä puolittain eikä hiljaa.
    """

    info: dict = {"reduction_db": 0.0, "kept": 1.0, "reason": ""}
    solo_source = np.asarray(solo_source, dtype=bool)
    seconds = float(solo_source.sum()) / max(rate, 1)
    info["solo_seconds"] = seconds
    if seconds < MIN_SOLO_SECONDS:
        info["reason"] = "too_little"
        return target, info

    filt = path(target, source, solo_source, taps)
    if not np.any(filt):
        info["reason"] = "no_path"
        return target, info

    # Vähennys vuodon taulukkoon: sama lasku, yksi raidan mittainen kopio
    # vähemmän.
    cleaned = leak(source, filt, len(target))
    np.subtract(target, cleaned, out=cleaned)

    before = _level(target, solo_source)
    after = _level(cleaned, solo_source)
    info["reduction_db"] = float(before - after)

    solo_target = np.asarray(solo_target, dtype=bool)
    if solo_target.any():
        a = np.asarray(target)[: len(solo_target)][solo_target].astype(np.float64)
        b = cleaned[: len(solo_target)][solo_target]
        if a.size > 1 and np.std(a) > 0 and np.std(b) > 0:
            info["kept"] = _correlation(a, b)

    if info["kept"] < MIN_SPEECH_KEPT:
        info["reason"] = "ate_speech"
        return target, info
    if info["reduction_db"] < MIN_REDUCTION_DB:
        info["reason"] = "no_gain"
        return target, info
    return cleaned.astype(target.dtype, copy=False), info
