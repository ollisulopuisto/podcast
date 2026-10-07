"""Puheen kanavanauha.

Sama ketju kuin automixerin PIPELINE.md:ssä, mutta pedalboardilla ja omassa
prosessissa. Aiemmin tämä ajettiin automixerin ympäristössä `uv run`illa;
riippuvuus poistettiin, koska tarvittu osa oli pieni ja pedalboard tekee sen
suoraan — samalla lähti vaatimus Python 3.13:sta ja MLX:stä.

Järjestys on tarkoituksellinen:

1. **Ulkoinen liitännäinen** (dxRevive tms.) ensin. Kohina ja särö siivotaan
   ennen kuin mikään vahvistaa niitä.
2. **Ylipäästö** vie jyrinän.
3. **Maiskausten poisto** siivoaa huulinaksut.
4. **Normalisointi** mitataan vasta tässä, siivotusta signaalista.
5. **Kompressointi** kahdessa vaiheessa, nopea ja hidas.
6. **Trimmi ja huippukatto.**

Normalisointi on nimenomaan tässä kohtaa eikä aiemmin: kompressorin kynnykset
ovat absoluuttisia desibelejä, ja käsittelemätön podcast-mikki on helposti
-40 LUFS, jolloin -12 dB:n kynnys ei ylity kertaakaan.

Tiedostoa ei käsitellä paloissa. Liitännäisen tila jatkuisi palojen yli
(``reset=False``), mutta tulos jää liitännäisen viiveen verran lyhyemmäksi —
mitattuna 4641 näytettä — ja pituuden muuttuminen on tässä työkalussa se yksi
asia jota ei sallita.
"""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import log
from .messages import t

# Ylipäästön jyrkkyys ja kompressorien ajat. automixer ilmaisi kompressorin
# RMS-ikkunana; pedalboard puhuu hyökkäys- ja palautusajoista, joten nopea ja
# hidas vaihe on kirjoitettu tähän auki.
# Hyökkäysaika on hitaampi kuin miltä «huippukompressori» kuulostaa. Kahden
# millisekunnin hyökkäys säätää vahvistusta perusjakson **sisällä**: 110 Hz:n
# miesäänellä jakso on 9 ms, joten kompressori muokkaa aaltomuotoa eikä tasoa,
# ja se on määritelmällisesti harmonista säröä. Mitattuna sinillä 110 Hz /
# -6 dBFS: 2 ms -> THD -30,9 dB, 10 ms -> -32,9 dB, 40 ms -> -36,1 dB.
# Viisitoista millisekuntia on jaksoa pidempi kaikilla puheäänillä.
# Kompressorien kynnykset on viritetty tällä äänekkyydellä. Signaali
# normalisoidaan tavoitteeseen ennen kompressoreita, joten absoluuttinen
# kynnys tarkoittaa eri määrää tiivistystä eri tavoitteilla — ja kun oletus
# vaihtui -20:stä YouTuben -14:ään, sama kynnys söi 4,5 dB enemmän
# dynamiikkaa: crest 20,2 dB -> 15,7 dB, ja se kuuluu säröisenä.
#
# Kynnykset siirtyvät siksi tavoitteen mukana. Tavoite muuttaa tason,
# ei tiivistyksen määrää.
THRESHOLD_REFERENCE_LUFS = -20.0

# Kynnysten ja ylipäästön oletukset. Nämä ovat isännän säädettävissä, mutta
# **oletus on ketjun tietoa**: se on viritetty yhdessä kynnysviitteen,
# suhteiden ja aikojen kanssa yllä, ja irrallaan niistä se on vain numero.
# Ne olivat autoraffkatin `model.py`:ssä, jolloin toinen kuluttaja saattoi
# vain kirjoittaa toiset numerot eikä mikään kertoisi eroa. Vertaa
# `freshness.FINGERPRINT_FIELDS`, joka jo nimeää nämä ketjun asetuksiksi.
HIGH_PASS_HZ = 80.0
PEAK_THRESHOLD_DB = -12.0  # nopea, 30 ms
LEVELER_THRESHOLD_DB = -18.0  # hidas, 300 ms

PEAK_ATTACK_MS = 15.0
PEAK_RELEASE_MS = 80.0
PEAK_RATIO = 3.0
LEVEL_ATTACK_MS = 30.0
LEVEL_RELEASE_MS = 300.0
LEVEL_RATIO = 2.0

# Rinnakkaiskompressio: kuiva ja tiivistetty summataan. Äänekkyys nousee
# hiljaisten kohtien mukana, mutta transientit säilyvät kuivassa haarassa
# koskemattomina — se on se ero, jonka korva kuulee «puristettuna». Osuus on
# tiivistetyn paino; nolla olisi pelkkä kuiva.
PARALLEL_MIX = 0.6

# Sihinänpoisto. Restaurointiliitännäinen lisää ylätaajuuksia — dxRevivellä
# mitattuna +4…+5,7 dB välillä 3–20 kHz — ja se osuu suoraan s-äänteisiin,
# jotka sitten ohjaavat kompressoreita koko puheen yli. Kynnys on absoluuttinen
# ja tulee vasta normalisoinnin jälkeen, jolloin taso on tiedossa.
DEESS_HZ = 4500.0
DEESS_THRESHOLD_DB = -30.0
DEESS_RATIO = 3.0
DEESS_SMOOTH_MS = 3.0

# Puheen sävy. Käsin tehdyn Live-ketjun rinnalla sama tiedosto oli
# dynamiikaltaan sama mutta sävyltään eri (SHARED-AUDIO.md §3.10): meillä
# 160–250 Hz −2…−3 dB, 400 Hz +1,7 dB ja 3–10 kHz −3,5…−4,6 dB. Ero tuli
# puhebusin Neutron-EQ:sta (250 Hz +3, 400 Hz −4 / Q 1,8, 3 kHz:n hylly),
# joka on koko puheen sointi eikä yhden äänen korjaus. Ketju ajetaan
# sokkona kaikille, joten määrät ovat noin puolet mitatusta.
#
# Runko ja laatikkomaisuus kuuluvat siivoukseen ylipäästön kanssa, jotta
# kompressorit näkevät muotoillun signaalin. Hylly tulee vasta dynamiikan
# jälkeen: sihinänpoisto painaa 5–10 kHz:ä oikeasta puheesta mitattuna
# −1,8 dB, ja sen edellä ajetusta +1,5 dB:n hyllystä jäi jäljelle 0,9 dB,
# jälkeen ajetusta 1,41.
TONE_BODY_HZ = 250.0
TONE_BODY_DB = 1.5
TONE_BODY_Q = 1.0
TONE_BOX_HZ = 400.0
TONE_BOX_DB = -2.0
TONE_BOX_Q = 1.8
TONE_PRESENCE_HZ = 3000.0
TONE_PRESENCE_DB = 1.5

# Huippukatto.
#
# Tämä oli pitkään staattinen koko raidan vaimennus, ja se oli ketjun suurin
# virhe. Kompressorit ovat lempeitä, joten normalisoinnin jälkeen huiput
# olivat +8…+11 dBFS; staattinen vaimennus veti silloin **koko tiedoston**
# alas sen verran. Mitattuna: -14,00 LUFS -> -25,74 (nyman) ja -22,94
# (wancke). Kolme oiretta yhdestä rivistä: kaikki 9–12 dB tavoitteen alle,
# puhujat eri tasoilla sen mukaan mikä oli kunkin kovin yksittäinen napsahdus,
# ja ohjelmatrimmin 1,8 dB merkityksetön sen rinnalla.
#
# Nyt katto hoidetaan ennakoivalla rajoittimella, joka koskee vain huippuihin.
# `peak_guard` jää viimeiseksi varmistukseksi, jonka ei pitäisi koskaan laueta.
# Katto on **true peak**, ei näytehuippu, ja siihen jätetään varaa.
# Näytehuippujen rajaaminen -1 dBFS:ään antoi mitattuna -0,42 dBTP: väliin
# jäävät huiput ylittävät näytteet, ja lossy-koodaus nostaa niitä vielä.
# Puolentoista desibelin varaa kestää AAC-muunnoksen ilman leikkautumista.
#: Kuinka paljon rajoitin saa tehdä työtä tavoitteen eteen, dB.
#:
#: Rajoitin oli ketjun ainoa rajaton vaihe. Kompressorit ottavat kukin
#: enintään ``MAX_GR_DB``, mutta rajoittimen läpi ajettiin niin paljon
#: vahvistusta kuin tavoitetaso sattui vaatimaan. Mitattuna oikealla
#: mikillä: ketjun kevyet vaiheet veivät crestiä 37,4 -> 32,1 dB ja
#: **rajoitin yksin 32,1 -> 16,7**, jonka jälkeen hakusilmukka vielä
#: 12,8:aan. Kolme kertaa kaikki muu yhteensä.
#:
#: Kuusi desibeliä on sama raja kuin yhdellä kompressorivaiheella yksi
#: yli — rajoitin on viimeinen vaihe ja saa tehdä hieman enemmän, muttei
#: eri lajissa. Budjetin täytyttyä taso jää tavoitteesta, ja se on oikea
#: lopputulos: taso on korjattavissa yhdellä liu'ulla, tiivistetty puhe ei.
#: Kuinka paljon rajoitin saa tehdä **jatkuvaa** työtä, dB. Nolla tai
#: negatiivinen = ei rajaa, eli vanha käytös.
#:
#: Rajoitin oli ketjun ainoa rajaton vaihe: kompressorit ottavat kukin
#: enintään ``MAX_GR_DB``, mutta rajoittimen läpi ajettiin niin paljon
#: vahvistusta kuin tavoitetaso sattui vaatimaan. Mitattuna oikealla mikillä
#: ketjun kevyet vaiheet veivät crestiä 37,4 -> 32,1 dB ja **rajoitin yksin
#: 32,1 -> 16,7**, minkä jälkeen hakusilmukka vielä 12,8:aan.
#:
#: Syy on aritmeettinen eikä makuasia. Stemi jonka crest on 32 dB ei mahdu
#: -14 LUFS:iin: huiput osuisivat +18 dBFS:ään, eikä kiintopisteinen tiedosto
#: kanna sitä. Jompikumpi antaa periksi, taso tai crest — ja taso on se joka
#: on korjattavissa yhdellä liu'ulla. Summan katosta huolehtii silti
#: ``programme.shared_gain``, joten stemin ei tarvitse olla itse kattoa
#: vasten.
#: Kuusi desibeliä, ja se on **päällä**. Nolla oli pois päältä, eli ketjun
#: ainoa rajaton vaihe pysyi rajattomana kaikilla oletusasetuksilla.
#:
#: Mitattuna oikealla puheella (87 s, -26,2 LUFS, crest 25,4 dB) YouTuben
#: -14:stä johdetulla stemin tavoitteella -15,8: signaali osuu rajoittimeen
#: +8,0 dBFS:n huipuilla, rajoitin tekee -9,6 dB työtä ja crest putoaa
#: 15,4:ään. Kompressorit eivät voi auttaa, koska huiput ovat yksittäisiä
#: aallonharjoja: yli 0 dBFS:n meni 1005 tapahtumaa, mediaani 0,15 ms,
#: pisin 0,6 ms, 0,19 % näytteistä — 15 ms:n hyökkäys ei näe niitä, ja
#: rinnakkaishaaran kuiva 40 % säilyttää ne tarkoituksella. Rajoittimen
#: vahvistus liikkui 117 000 dB/s eli yli 2 dB yhden näytteen aikana, ja
#: 110 Hz:n äänellä jakso on 9 ms — vahvistusta moduloidaan siis jakson
#: sisällä, mikä on määritelmällisesti säröä.
#:
#: Kuunneltuna, äänekkyydeltään täsmätty A/B samasta pätkästä: crest 15,4
#: kuulostaa säröiseltä, 18,5 ja 19,4 eivät. Kokeiltiin myös rajoittimen
#: hyökkäyksen pehmennys (nopein muutos 15 800 -> 1 900 dB/s), kynnysten
#: lasku 4 dB, vaihekohtaisen vaimennuksen nosto 5 -> 8 dB, rinnakkaisosuus
#: 0,85 ja ylinäytteistetty pehmeä leikkuri rajoittimen edessä (rajoittimen
#: työ -9,6 -> -1,5 dB samalla äänekkyydellä). **Yksikään ei kuulostanut
#: paremmalta kuin tason antaminen periksi.** Määrä ratkaisee, ei muoto.
LIMITER_BUDGET_DB = 6.0

#: Mistä kohtaa jakaumaa «jatkuva työ» luetaan. Käyrän minimi on **yhden
#: näytteen** vaatimus, ja koko tiedoston vaimentaminen sen mukaan on juuri
#: se staattinen vaimennus jonka rajoitin korvasi (mitattuna 9–12 dB, ja se
#: teki puhujien tasapainosta sattumanvaraisen). Yksittäinen huippu *kuuluu*
#: rajoittaa; vaimennus joka jatkuu promillen ajan tiedostosta ei ole huippu
#: vaan taso. 20 minuutin tiedostossa promille on 1,2 sekuntia.
LIMITER_BUDGET_PERCENTILE = 0.1

CEILING_DB = -1.5
LIMITER_OVERSAMPLE = 4
LIMITER_LOOKAHEAD_MS = 5.0
LIMITER_RELEASE_MS = 120.0
#: True peak lasketaan paloittain: palan pituus ja reunojen päällekkäisyys,
#: näytteinä. Sekunti 48 kHz:llä on 4× float64:nä stereona 3 MB.
_TRUE_PEAK_CHUNK = 48000
_TRUE_PEAK_PAD = 1024


# Mistä liitännäisiä etsitään. Vakiopaikat käyttöjärjestelmän mukaan.
def _standard_plugin_dirs() -> tuple[str, ...]:
    if sys.platform == "darwin":
        return (
            "/Library/Audio/Plug-Ins/VST3",
            "~/Library/Audio/Plug-Ins/VST3",
            "/Library/Audio/Plug-Ins/Components",
            "~/Library/Audio/Plug-Ins/Components",
        )
    if sys.platform.startswith("linux"):
        return (
            "/usr/lib/vst3",
            "/usr/local/lib/vst3",
            "~/.vst3",
            "~/.local/lib/vst3",
        )
    if sys.platform == "win32":
        common_files = os.environ.get(
            "COMMONPROGRAMFILES", r"C:\Program Files\Common Files"
        )
        common_files_x86 = os.environ.get(
            "COMMONPROGRAMFILES(X86)", r"C:\Program Files (x86)\Common Files"
        )
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        dirs = [
            os.path.join(common_files, "VST3"),
            os.path.join(common_files_x86, "VST3"),
        ]
        if local_app_data:
            dirs.append(os.path.join(local_app_data, "Programs", "Common", "VST3"))
        return tuple(dirs)
    return (
        "/Library/Audio/Plug-Ins/VST3",
        "~/Library/Audio/Plug-Ins/VST3",
    )


PLUGIN_DIRS = _standard_plugin_dirs()


class ChainError(Exception):
    """Ääntä ei voitu käsitellä."""


def plugins() -> list[dict]:
    """Asennetut VST3- ja AU-liitännäiset nimineen ja polkuineen."""
    found: dict[str, str] = {}
    for folder in PLUGIN_DIRS:
        root = Path(os.path.expanduser(folder))
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.suffix in (".vst3", ".component"):
                # Sama liitännäinen on usein molemmissa muodoissa; VST3 voittaa,
                # koska se on ensin listassa.
                found.setdefault(entry.stem, str(entry))
    return [{"name": name, "path": path} for name, path in sorted(found.items())]


def load_plugin(path: str, params: dict | None = None, state: str | None = None):
    """Lataa liitännäisen ja asettaa sen tilan ja säätimet.

    ``state`` on liitännäisen oma tila base64:nä, talletettuna sen omasta
    ikkunasta (``audio/editor.py``). Se tarvitaan siksi, että kaikki mikä
    vaikuttaa lopputulokseen ei ole parametri: dxRevivella mallin valinta
    — Studio 2 ja muut — ei ole yksikään sen neljästä parametrista, vaan
    elää tilassa. Ilman tilaa ajetaan aina liitännäisen oletusmallia.

    Tila asetetaan **ennen** parametreja, jotta talletettu Mix ei jyrää
    asetuksissa olevaa: parametri on se, jota käyttöliittymän liukusäädin
    liikuttaa, ja sen on voitettava.

    Kelvoton tila ei kaada mitään. Se on läpinäkymätön tavujono jonka vain
    liitännäinen osaa lukea, ja liitännäisen vaihtuessa vanha tila on
    roskaa — mutta parametrit toimivat silti, joten väärä tila sivuutetaan
    eikä siitä tehdä virhettä.
    """
    import pedalboard

    if not path:
        return None
    if not os.path.exists(path):
        raise ChainError(t("audio.plugin_missing", path=path))
    try:
        plugin = pedalboard.load_plugin(path)
    except Exception as exc:
        raise ChainError(
            t("audio.plugin_failed", name=os.path.basename(path), error=exc)
        ) from exc
    apply_state(plugin, state)
    apply_parameters(plugin, params)
    return plugin


def apply_state(plugin, state: str | None) -> bool:
    """Asettaa talletetun tilan. Palauttaa onnistuiko."""
    import base64

    if not state:
        return False
    try:
        plugin.raw_state = base64.b64decode(state)
        return True
    except Exception:
        # Tila on toisesta liitännäisestä tai eri versiosta. Parametrit
        # riittävät, joten jatketaan ilman.
        return False


def read_parameters(plugin) -> dict:
    """Liitännäisen nykyiset säädettävät arvot nimen mukaan.

    Käyttäjä on voinut kääntää säätimiä liitännäisen omassa ikkunassa, ja
    käyttöliittymän liukusäätimien on seurattava — muuten sama arvo lukee
    kahdessa paikassa eri lukemaa.
    """
    out: dict = {}
    for name in getattr(plugin, "parameters", {}):
        try:
            value = getattr(plugin, name)
        except Exception:
            continue
        if isinstance(value, bool):
            out[name] = value
        elif isinstance(value, (int, float)):
            out[name] = float(value)
        elif isinstance(value, str):
            out[name] = value
    return out


# Liitännäinen on 97 % käsittelyn ajasta ja käyttää **yhtä** ydintä: mitattu
# dxRevivella M2:lla 0,98 ydintä ja 7,25x reaaliaika. Koneen muut ytimet saa
# töihin vain ajamalla useaa kohtaa yhtä aikaa.
#
# Skaalaus ei ole lineaarinen — liitännäisen päättely on muistikaistarajoitettu
# ja tehokkuusytimet ovat hitaampia. Mitattu läpimeno M2:lla (4P+4E):
# 1 → 7,5x, 2 → 9,5x, 4 → 14,8x, 6 → 20,1x reaaliaikaa. Oikealla 20 minuutin
# tiedostolla koko ketju 168,4 s → 68,3 s, eli 2,46-kertainen.
#
# Osuus eikä vakioluku: kahdeksan ytimen kannettava ja kahdenkymmenen ytimen
# työasema ovat eri koneita, eikä kummankaan lukua voi kirjoittaa tähän.
WORKER_SHARE = 0.75


def worker_count(wanted: int = 0) -> int:
    """Montako liitännäisinstanssia ajetaan rinnakkain.

    ``0`` on automaattinen: ``WORKER_SHARE`` koneen ytimistä. Loput jäävät
    käyttöliittymälle ja muulle koneelle — käsittely on taustatyö, jonka
    aikana konetta käytetään muuhun.

    Muu luku on käyttäjän oma valinta, rajattuna ytimien määrään: kolmesta-
    kymmenestä palasta kahdeksalla ytimellä ei tule nopeampaa, vain enemmän
    muistia ja lyhyempiä paloja.
    """
    cores = os.cpu_count() or 2
    if wanted > 0:
        return max(1, min(int(wanted), cores))
    return max(1, round(cores * WORKER_SHARE))


# Palan reunoille jätetään marginaali, joka käsitellään ja heitetään pois:
# liitännäinen tarvitsee kontekstia ennen kuin sen tulos vakiintuu.
#
# Mitattu ero kokonaisena käsiteltyyn, 60 s puhetta neljänä palana:
# marginaali 0,5 s → -32,8 dBFS, 2 s → -34,8 dBFS, 5 s → -42,5 dBFS, kun
# signaali itse on -15,6 dBFS. Sauma on puhdas (-50…-70 dBFS) — jäljelle
# jäävä ero on liitännäisen oma hidas sopeutuminen, ei napsahdus.
#
# Oikealla 20 minuutin tiedostolla kuutena palana ero on puhelohkoissa
# 25,7 dB signaalin alle ja hiljaisissa kohdissa -84 dBFS absoluuttisesti.
# Se ei ole nolla, ja siksi tämä on säädettävissä:
# ``AudioSettings.plugin_workers``, jossa 1 tarkoittaa yhtenä palana.
PIECE_MARGIN = 5.0
# Tätä lyhyempää ei pilkota: marginaalit söisivät hyödyn.
PIECE_MIN = 120.0


class PluginPool:
    """Liitännäisiä säikeittäin, luotuina siinä säikeessä joka niitä käyttää.

    Jokainen rinnakkainen pala tarvitsee oman instanssin: VST3-olio on
    tilallinen eikä sitä voi ajaa kahdesta säikeestä yhtä aikaa. Se ei
    kuitenkaan riitä, että instansseja on monta — pedalboard vaatii, että
    instanssia käytetään **samassa säikeessä jossa se ladattiin**, ja
    muuten kaatuu viestiin «must be reloaded on the main thread».

    Siksi lataus tapahtuu laiskasti säiekohtaisesti ja säikeet pidetään
    hengissä koko ajon yli: lataus maksaa noin 0,2 s instanssilta, eikä sitä
    kannata maksaa jokaisesta palasta uudestaan.
    """

    def __init__(self, path: str, params: dict | None, workers: int, state=None):
        from concurrent.futures import ThreadPoolExecutor

        self.path = path
        self.params = params
        self.workers = max(1, workers)
        # **Kaikki instanssit ladataan tässä**, eli siinä säikeessä joka
        # varannon rakentaa. Laiska säiekohtainen lataus oli ensimmäinen
        # yritys ja se on juuri se mitä pedalboard kieltää: lataus onnistuu
        # vain pääsäikeessä, ja työsäikeessä se kaatuu viestiin «must be
        # reloaded on the main thread». Käsittely työsäikeestä on sallittua,
        # lataus ei — ja ero on helppo sekoittaa, koska virhe puhuu
        # `reset`istä.
        self.instances = [
            load_plugin(path, params, state) for _ in range(self.workers)
        ]
        self._pool = ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="plugin"
        )

    def plugin(self, index: int = 0):
        """Instanssi numero ``index``. Yksi pala, yksi instanssi."""
        return self.instances[index % len(self.instances)]

    def run(self, function, items) -> list:
        """Ajaa työt säikeissä ja palauttaa tulokset järjestyksessä."""
        return list(self._pool.map(function, items))

    def close(self) -> None:
        self._pool.shutdown(wait=True)


def load_pool(path: str, params: dict | None = None, count: int = 1, state=None):
    """Säiekohtainen liitännäisvaranto, tai ``None`` jos polkua ei ole.

    Tarkistaa polun heti pääsäikeessä, jotta virheellinen polku kerrotaan
    ennen kuin minuuttien ajo alkaa.
    """
    if not path:
        return None
    return PluginPool(path, params, count, state)


def _one_piece(plugin, audio: np.ndarray, rate: int) -> np.ndarray:
    """Liitännäinen kerralla koko palaan, pituus tarkistettuna.

    ``reset=True`` on osa sopimusta: ilman sitä liitännäisen tila jatkuu
    kutsusta toiseen, ja peräkkäin käsitellyt raidat kuulostaisivat eriltä
    sen mukaan mikä niitä edelsi.

    Pituuden tarkistus on tässä eikä kutsujassa. Viiveellinen liitännäinen
    palauttaa lyhyemmän tuloksen — dxRevivella mitattuna 4641 näytettä — ja
    se on hiljainen vika: kelvollista ääntä, ei poikkeusta, väärä synkka.
    """
    done = plugin.process(audio, rate, reset=True)
    if done.shape[1] != audio.shape[1]:
        raise ChainError(
            t("audio.plugin_length", before=audio.shape[1], after=done.shape[1])
        )
    return done


def apply_plugin(plugin, audio: np.ndarray, rate: int) -> np.ndarray:
    """Liitännäinen koko tiedostoon. ``plugin`` on yksi olio tai lista.

    Listana tiedosto pilkotaan yhtä moneen palaan ja palat ajetaan
    rinnakkain omilla instansseillaan. Jokainen pala on oma täysi
    ``reset=True``-ajonsa marginaaleineen — ei siis sama asia kuin
    tiedoston syöttäminen liitännäiselle paloissa, joka lyhentäisi tuloksen
    liitännäisen viiveen verran.

    Pituus säilyy rakenteeltaan: tulos kirjoitetaan valmiiksi oikean
    kokoiseen taulukkoon, ja jokaisen palan pituus tarkistetaan erikseen.
    Myös yhden instanssin haara tarkistetaan — vartio kuuluu tähän eikä
    kutsujaan, koska tätä kutsutaan myös ``process``in ulkopuolelta.
    """
    if plugin is None:
        return audio
    if isinstance(plugin, PluginPool):
        return _apply_pool(plugin, audio, rate)
    if not isinstance(plugin, (list, tuple)):
        return _one_piece(plugin, audio, rate)
    pool = list(plugin)
    frames = audio.shape[1]
    pieces = min(len(pool), max(1, int(frames / rate / PIECE_MIN)))
    if pieces < 2:
        return _one_piece(pool[0], audio, rate)

    margin = int(PIECE_MARGIN * rate)
    edges = [int(round(i * frames / pieces)) for i in range(pieces + 1)]
    out = np.zeros_like(audio)
    failures: list[Exception] = []

    def one(index: int) -> None:
        first, last = edges[index], edges[index + 1]
        low, high = max(0, first - margin), min(frames, last + margin)
        try:
            done = pool[index].process(audio[:, low:high], rate, reset=True)
            if done.shape[1] != high - low:
                raise ChainError(
                    t("audio.plugin_length", before=high - low, after=done.shape[1])
                )
            out[:, first:last] = done[:, first - low : first - low + (last - first)]
        except Exception as exc:  # säie ei saa kaatua hiljaa
            failures.append(exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(pieces)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if failures:
        raise failures[0]
    return out


def _apply_pool(pool: "PluginPool", audio: np.ndarray, rate: int) -> np.ndarray:
    """Palat rinnakkain, jokainen sen säikeen omalla instanssilla."""
    frames = audio.shape[1]
    pieces = min(pool.workers, max(1, int(frames / rate / PIECE_MIN)))
    if pieces < 2:
        return _one_piece(pool.plugin(0), audio, rate)

    margin = int(PIECE_MARGIN * rate)
    edges = [int(round(i * frames / pieces)) for i in range(pieces + 1)]
    out = np.zeros_like(audio)

    def one(index: int) -> None:
        first, last = edges[index], edges[index + 1]
        low, high = max(0, first - margin), min(frames, last + margin)
        with log.step(f"plugin piece {index + 1}/{pieces} "
                      f"({(high - low) / rate / 60:.1f} min)"):
            done = pool.plugin(index).process(audio[:, low:high], rate, reset=True)
        if done.shape[1] != high - low:
            raise ChainError(
                t("audio.plugin_length", before=high - low, after=done.shape[1])
            )
        out[:, first:last] = done[:, first - low : first - low + (last - first)]

    pool.run(one, range(pieces))
    return out


def apply_parameters(plugin, params: dict | None) -> list[str]:
    """Asettaa liitännäisen säätimet. Palauttaa nimet jotka ohitettiin.

    Arvo on liitännäisen omissa yksiköissä (``plugin.input_gain = 3.0``);
    pedalboard muuntaa sen liitännäisen raaka-arvoksi itse, eikä muunnos ole
    aina lineaarinen — siksi asetuksissakin on yksikköarvo eikä 0–1.

    Nimi tarkistetaan ``parameters``-sanakirjasta ennen kirjoitusta. Ilman
    tarkistusta tuntematon nimi menisi läpi hiljaa: pedalboardin
    liitännäisolio ottaa vastaan minkä tahansa attribuutin, jolloin asetus
    näyttäisi menneen perille eikä vaikuttaisi mihinkään.

    Ohitus ei ole virhe. Asetukset periytyvät jaksosta toiseen, ja edellisen
    jakson liitännäinen on voinut olla toinen — silloin oikea käytös on ajaa
    liitännäinen omilla oletuksillaan eikä kaataa koko käsittelyä.
    """
    skipped: list[str] = []
    known = getattr(plugin, "parameters", None) or {}
    for name, value in (params or {}).items():
        if name not in known:
            skipped.append(str(name))
            continue
        try:
            setattr(plugin, name, value)
        except (ValueError, TypeError):
            skipped.append(str(name))
    return skipped


# Kuinka monta säädintä käyttöliittymälle kerrotaan. Puheliitännäisessä niitä
# on muutama, syntikassa tuhansia. Katkaisu kerrotaan käyttäjälle: hiljainen
# katkaisu näyttäisi siltä ettei liitännäisessä ole enempää.
MAX_PARAMS = 64
# Valikollisen säätimen vaihtoehdot. Sama syy.
MAX_CHOICES = 64

# Säätimien kuvaukset polun mukaan. Lataus kestää sekunteja, eikä liitännäinen
# muutu ohjelman ajon aikana.
_SPECS: dict[str, tuple[list[dict], int]] = {}


def _spec(name: str, param) -> dict | None:
    """Yksi säädin käyttöliittymän ymmärtämässä muodossa, tai ``None`` jos
    sitä ei voi piirtää.

    Tyyppi ratkaisee elementin: totuusarvo on valintaruutu, merkkijono on
    valikko ja luku on liukusäädin. Rajat tulevat liitännäiseltä
    (``range``), koska ne ovat sen omissa yksiköissä — desibeleissä,
    prosenteissa tai hertseissä sen mukaan mistä säätimestä on kyse.
    """
    kind = getattr(param, "type", float)
    label = str(getattr(param, "name", None) or name)
    if kind is bool:
        return {"name": name, "label": label, "type": "bool"}
    if kind is str:
        choices = [str(v) for v in (getattr(param, "valid_values", None) or [])]
        if not choices:
            return None
        return {
            "name": name,
            "label": label,
            "type": "choice",
            "choices": choices[:MAX_CHOICES],
        }
    span = tuple(getattr(param, "range", None) or ())
    low, high, step = ((*span, None, None, None))[:3]
    if low is None or high is None or float(high) <= float(low):
        return None
    low, high = float(low), float(high)
    # Askel puuttuu portaattomalta säätimeltä. Sadasosa alueesta on se mitä
    # liitännäisen oma yleiskäyttöliittymä näyttäisi.
    step = float(step) if step else (high - low) / 100.0
    out = {
        "name": name,
        "label": label,
        "type": "float",
        "min": low,
        "max": high,
        "step": step,
    }
    units = getattr(param, "units", None)
    if units:
        out["units"] = str(units)
    return out


def _default_value(plugin, name: str, kind: str):
    """Säätimen nykyarvo omana tyyppinään, tai ``None`` jos sitä ei saa.

    Muunnos on pakollinen: pedalboard palauttaa kääritun arvon, joka ei
    mene sellaisenaan JSONiin.
    """
    cast = {"bool": bool, "choice": str}.get(kind, float)
    try:
        return cast(getattr(plugin, name))
    except (AttributeError, TypeError, ValueError):
        return None


def parameter_specs(path: str) -> tuple[list[dict], int]:
    """Liitännäisen säätimet käyttöliittymälle: ``(kuvaukset, kokonaismäärä)``.

    Kuvaukseen tulee myös liitännäisen oma oletusarvo (``value``), jotta
    säädin näyttää oikeaa lukua ennen kuin siihen on koskettu: asetuksiin
    tallennetaan vain ne säätimet joita käyttäjä on liikuttanut.
    """
    if not path:
        return [], 0
    if path in _SPECS:
        return _SPECS[path]
    plugin = load_plugin(path)
    known = getattr(plugin, "parameters", None) or {}
    specs: list[dict] = []
    for name in known:
        spec = _spec(name, known[name])
        if spec is None:
            continue
        value = _default_value(plugin, name, spec["type"])
        if value is None:
            continue
        spec["value"] = value
        specs.append(spec)
        if len(specs) >= MAX_PARAMS:
            break
    _SPECS[path] = (specs, len(known))
    return _SPECS[path]


def loudness(mono: np.ndarray, rate: int) -> float | None:
    """Integroitu äänekkyys, tai ``None`` jos ei mitattavissa.

    Sama mittari kuin masteroinnissa (``meter.IntegratedMeter``). pyloudnorm
    luki 0,042 LU alakanttiin libebur128:aan verrattuna, joten ketju ja
    masterointi mittasivat samaa ääntä eri lukemin.
    """
    from speechmix.meter import IntegratedMeter

    if mono.size < rate:  # alle sekunti: ei mitattavaa
        return None
    # Paloittain: mittari kantaa tilansa, joten lukema on bitilleen sama,
    # mutta koko raidan teho- ja maskitaulukot (2 × float64) jäävät pois.
    meter = IntegratedMeter(rate)
    for start in range(0, mono.size, _MEASURE_CHUNK):
        meter.add(mono[start:start + _MEASURE_CHUNK])
    value = meter.value()
    if value is None or not np.isfinite(value) or value < -70.0:
        return None
    return value


#: Mittausten pala näytteinä. Kymmenkunta sekuntia: silmukan hinta häviää,
#: muisti ei kasva raidan mukana.
_MEASURE_CHUNK = 1 << 19


def lag_samples(
    before: np.ndarray, after: np.ndarray, rate: int, bin_ms: float = 1.0
) -> int:
    """Signaalien välinen viive näytteinä.

    Ristikorrelaatio lasketaan verhokäyristä eikä aallonmuodosta, koska
    liitännäinen muuttaa sisältöä mutta ei puheen rytmiä. Tämä on ainoa tapa
    huomata liitännäinen joka ilmoittaa viiveensä väärin: pituus säilyy, mutta
    ääni on siirtynyt — eikä sitä huomaa ennen kuin leikkaus on koossa.

    Korrelaatio tehdään FFT:llä. ``np.correlate(..., "full")`` laskee sen
    suoraan, mikä on O(n²): millisekunnin ruudulla 20 minuutin tiedostosta
    tulee 1,2 miljoonaa ruutua ja mittaus kesti **132 sekuntia** — enemmän
    kuin dxRevive samasta tiedostosta. FFT antaa saman tuloksen 0,05
    sekunnissa. Ero kasvaa neliössä, joten tunnin tiedostolla suora tapa oli
    varttitunti pelkkää tarkistusta.
    """
    from scipy import signal as sp

    step = max(1, int(rate * bin_ms / 1000))
    count = min(before.size, after.size) // step * step
    if count < step * 8:
        return 0
    a = np.abs(before[:count]).reshape(-1, step).max(axis=1)
    b = np.abs(after[:count]).reshape(-1, step).max(axis=1)
    a = a - a.mean()
    b = b - b.mean()
    if not a.any() or not b.any():
        return 0
    correlation = sp.fftconvolve(b, a[::-1], mode="full")
    return (int(np.argmax(correlation)) - (a.size - 1)) * step


def _together(*calls):
    """Ajaa riippumattomat kutsut säikeissä ja palauttaa tulokset järjestyksessä.

    Hyödyllinen vain kutsuille jotka vapauttavat GIL:n (scipy:n suotimet,
    numpy:n isot operaatiot). Säikeitä on yhtä monta kuin kutsuja — kaksi
    tai muutama — koska dxRevive käyttää samoja ytimiä.
    """
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls]
        return [future.result() for future in futures]


# Naksunpoiston kynnys, kerroin paikalliseen keskiarvoon. Kalibroitu
# oikeasta materiaalista: kertoimella 3,5 löydöksiä oli 316–666 sekunnissa,
# kertoimella 25 noin yksi. Huulinaksuja on muutama minuutissa.
DECLICK_FACTOR_MAX = 40.0  # herkkyys 0.0
DECLICK_FACTOR_MIN = 10.0  # herkkyys 1.0
# Tätä tiheämpi löydös on signaalia, ei naksuja.
DECLICK_MAX_PER_SECOND = 5.0
# Montako kertaa kynnys kaksinkertaistetaan ennen kuin luovutetaan.
DECLICK_ESCALATIONS = 6
# Tätä lähempänä toisiaan olevat ylitykset ovat samaa naksua. Ilman tätä
# yksi 2 ms:n naksu on kolmisenkymmentä erillistä löydöstä — sen puolijaksot
# — jolloin katto laukeaa yhdestä naksusta ja interpolointi korjaa vain
# aallon huiput ja jättää loput paikalleen.
DECLICK_MERGE_MS = 2.0


def declick(audio: np.ndarray, rate: int, sensitivity: float = 0.5) -> np.ndarray:
    """Poistaa huulinaksut ja maiskaukset.

    Portattu automixerin ``DeSmackProcessor``ista. Yli 4 kHz:n transientit,
    jotka piikkaavat paikallisen **keskiarvon** yli, tulkitaan naksuiksi —
    paitsi jos matalilla on samaan aikaan energiaa, jolloin kyse on
    plosiivista eikä naksusta. Löydetyt kohdat interpoloidaan yli.

    Alkuperäinen käytti vertailukohtana paikallista maksimia, vaikka koodin
    oma kommentti puhui keskiarvosta. Naksu on määritelmän mukaan oman
    ympäristönsä maksimi, joten ehto ``|x| > max * 3,5`` ei voi täyttyä
    koskaan: käsittely oli aina nolla-operaatio. Keskiarvo on se mitä
    tarkoitettiin — mutta **kerroin 3,5 oli maksimin kerroin**, ja
    keskiarvoon sovellettuna se laukeaa kaikesta. Mitattuna oikealla
    puheella: 1,8–2,2 % kaikista näytteistä, 550–640 korjausta sekunnissa,
    ja signaali muuttui −10…−15 dB itseensä nähden. Se ei ole naksunpoisto
    vaan säröngeneraattori, ja juuri siltä se kuulostaa.

    Huulinaksuja on muutama minuutissa. Kerroin on siksi kalibroitu siitä,
    montako löydöstä sekunnissa syntyy oikeasta materiaalista
    (``DECLICK_FACTOR_*``), ja sen päällä on **katto**: jos löydöksiä tulee
    silti enemmän kuin ``DECLICK_MAX_PER_SECOND``, kynnystä nostetaan kunnes
    ne loppuvat, ja jos ne eivät lopu, mitään ei korjata. Detektori joka
    löytää naksun joka toisesta millisekunnista ei ole löytänyt naksuja vaan
    signaalin, ja hiljaa väärässä oleva korjaus on tässä projektissa
    kalliimpi kuin tekemättä jätetty.

    Plosiivisuoja vertaa myös **paikalliseen** keskiarvoon. Koko tiedoston
    keskiarvo teki suojasta tiedoston pituuden funktion: tunnin nauhassa,
    jossa on paljon taukoja, keskiarvo painuu alas ja suoja lakkaa
    suojaamasta juuri hiljaisissa kohdissa, joissa detektori laukeaa
    herkimmin.
    """
    from functools import partial

    from scipy import signal as sp
    from scipy.ndimage import uniform_filter1d

    window = max(1, int(0.05 * rate))
    high_sos = sp.butter(4, 4000, "hp", fs=rate, output="sos")
    low_sos = sp.butter(4, 1000, "lp", fs=rate, output="sos")

    def band(sos, data):
        """Kaista, sen itseisarvo ja paikallinen keskiarvo."""
        level = np.abs(sp.sosfiltfilt(sos, data))
        return level, uniform_filter1d(level, size=window)

    out = audio.copy()
    for channel in range(audio.shape[0]):
        data = audio[channel]
        # Kaistat ovat riippumattomat ja scipy vapauttaa GIL:n: 20 minuutista
        # peräkkäin 2,56 s, rinnakkain 1,34 s, tulos bitilleen sama.
        (high, local), (low, local_low) = _together(
            partial(band, high_sos, data), partial(band, low_sos, data)
        )
        plosive = low > local_low * 3.0
        factor = DECLICK_FACTOR_MAX - (
            DECLICK_FACTOR_MAX - DECLICK_FACTOR_MIN
        ) * float(np.clip(sensitivity, 0.0, 1.0))
        seconds = max(data.size / rate, 1e-9)
        allowed = DECLICK_MAX_PER_SECOND * seconds
        gap = max(1, int(DECLICK_MERGE_MS * rate / 1000.0))
        index = np.empty(0, dtype=np.intp)
        for _ in range(DECLICK_ESCALATIONS):
            clicks = high > local * factor
            clicks &= ~plosive
            index = np.flatnonzero(clicks)
            if index.size == 0:
                break
            found = 1 + int((np.diff(index) > gap).sum())
            if found <= allowed:
                break
            factor *= 2.0
        else:
            # Kynnys ei riittänyt millään: tämä ei ole naksuinen tiedosto
            # vaan detektori väärässä. Ei kosketa.
            continue
        if index.size == 0:
            continue
        for cluster in np.split(index, np.flatnonzero(np.diff(index) > gap) + 1):
            start = max(0, int(cluster[0]) - 10)
            end = min(data.size, int(cluster[-1]) + 10)
            if end - start >= int(0.01 * rate):  # yli 10 ms ei ole naksu
                continue
            before = np.arange(max(0, start - 20), start)
            after = np.arange(end, min(data.size, end + 20))
            if before.size <= 5 or after.size <= 5:
                continue
            reference = np.concatenate([before, after])
            out[channel, start:end] = np.interp(
                np.arange(start, end), reference, data[reference]
            )
    return out


def _one_pole(x: np.ndarray, rate: int, ms: float) -> np.ndarray:
    """Yksinapainen tasoitus. Vektorisoitu, koska tiedostot ovat pitkiä.

    Näytteittäinen hyökkäys/palautus-seuraaja on sarjallinen eikä sellaista
    voi ajaa Pythonissa sadalle miljoonalle näytteelle. ``lfilter`` tekee
    saman C:ssä, symmetrisillä ajoilla — riittää sekä sihinänpoiston
    verhokäyrälle että rajoittimen pehmennykselle.
    """
    from scipy import signal as _sig

    coeff = float(np.exp(-1.0 / max(1.0, ms * rate / 1000.0)))
    b, a = [1.0 - coeff], [1.0, -coeff]
    # Alkutila ensimmäisestä näytteestä: nollasta lähtevä suodin häivyttäisi
    # tiedoston alun sisään, ja rajoittimen vahvistuskäyrällä se tarkoittaisi
    # että jokainen tiedosto alkaa vaimennettuna.
    zi = _sig.lfilter_zi(b, a) * float(np.asarray(x).reshape(-1)[0])
    out, _ = _sig.lfilter(b, a, x, zi=zi)
    return out


# Tasonkuljettaja.
#
# Ketjusta puuttui se vaihe joka käsityönä tehdyssä miksauksessa on ensin:
# hidas tason tasaus, joka poistaa puhujan **oman** vaihtelun ennen kuin
# kompressori näkee signaalin. Ilman sitä kompressori tekee kuljettajan työn
# huonosti — nopeasti ja tasosta riippuvasti sen sijaan että hitaasti ja
# tasaisesti — ja jokainen nojaus taaksepäin maksaa tiivistystä jota ei
# tarvittaisi.
#
# Ikkuna on sekunteja, ei millisekunteja: tämä ei ole kompressori eikä saa
# olla. Kolme sekuntia on lauseen mitta, ja siitä lyhyempi alkaisi tasoittaa
# painotusta, joka on puheessa merkitystä eikä vikaa.
RIDER_WINDOW_S = 3.0
# Kuinka nopeasti vahvistus saa liikkua. Hitaampi kuin ikkuna, koska
# kuljettajan pitää kuulostaa siltä ettei sitä ole.
RIDER_SPEED_S = 4.0
# Kuinka paljon saa nostaa tai laskea. Kuudesta desibelistä ylöspäin ollaan
# jo siinä että hiljainen kohta oli hiljainen syystä.
#: Kuinka paljon kuljettaja saa korjata, dB. Oletus on varovainen, ja
#: isäntä saa nostaa sitä: kaari on materiaalin ominaisuus eikä ketjun.
#:
#: Mitattuna 77 minuutin jaksolla, puheenvuoro = lauseet 1,5 s aukot umpeen:
#:
#:     puhuja  vuoroja yli 12 s  mediaanipituus  lasku alusta loppuun
#:     Nyman              61          36 s              +7,2 dB
#:     Wancke            103          25 s              +2,6 dB
#:
#: Nymanin vuoroista 75 % laskee yli 3 dB ja 59 % yli 6 dB, eli kuudella
#: kuljettaja on katossaan suurimman osan hänen puheajastaan. Katto on silti
#: tarpeen: kuljettaja nostaa vuoron loppua ja sen mukana huoneen.
RIDER_MAX_DB = 6.0
# Lohkon pituus tason mittaukseen.
RIDER_BLOCK_S = 0.1


def rider_gain(audio: np.ndarray, rate: int,
               speech: np.ndarray | None = None,
               max_db: float = RIDER_MAX_DB) -> tuple[np.ndarray, int]:
    """Tasonkuljettajan vahvistus lohkoittain, dB. ``(gain, lohkon koko)``.

    ``speech`` kertoo lohkoittain milloin **tämän raidan oma puhuja** on
    äänessä. Se ei ole valinnainen hienous vaan koko ehto sille että
    kuljettaja toimii kahden mikin nauhoituksessa, ja se on mitattava eikä
    pääteltävä signaalista.

    Mitattu syy: tasosta pääteltynä «puhetta» oli Nymanin raidalla 74 %
    lohkoista, kun hänen omaa puhettaan oli 53 %, ja päällekkäin ne osuivat
    vain 38 %:ssa. Loput on toisen puhujan vuotoa — ja kuljettaja nosti
    sitä, koska se on kovaa. Pohjakohina nousi 3,5 dB ja tason hajonta
    kasvoi 2,88:sta 3,37:ään: kuljettaja teki tarkalleen sen vahingon jota
    varten de-bleed on olemassa.

    Ilman maskia ei kuljeteta lainkaan. Heuristiikka olisi tässä huonompi
    kuin ei mitään, ja hiljainen huononnus on tämän projektin tyypillisin
    vika.

    Vain oman puheen aikana säädetään. Muulloin vahvistus **pidetään**
    edellisessä arvossaan — muuten kuljettaja nostaisi pohjakohinan
    tavoitetasolle joka tauossa.

    Tavoite on raidan **oma** mediaanitaso, ei absoluuttinen luku: tämä
    poistaa vaihtelun raidan sisältä eikä aseta tasoa, jonka asettaa
    normalisointi myöhemmin ohjelman lukemasta.
    """
    block = max(1, int(RIDER_BLOCK_S * rate))
    mono = audio.mean(axis=0)
    count = mono.shape[0] // block
    if count < 3 or speech is None:
        return np.zeros(max(count, 1), dtype=np.float32), block
    level = np.sqrt(np.mean(
        mono[: count * block].reshape(count, block) ** 2, axis=1) + 1e-12)
    db = 20.0 * np.log10(level)
    speech = np.asarray(speech, dtype=bool)
    if speech.shape[0] < count:
        speech = np.pad(speech, (0, count - speech.shape[0]))
    speech = speech[:count]
    # Vuoto pois vielä maskin sisältäkin: oma puhe voi olla hiljaa vaikka
    # maski on auki, ja hiljaisin kymmenys ei ole taso jota kuljetetaan.
    if speech.any():
        speech = speech & (db > float(np.percentile(db[speech], 5)))
    if speech.sum() < 3:
        return np.zeros(count, dtype=np.float32), block
    # Taso mitataan **vain puheesta**. Suoraan ``db``:n yli liu'utettu
    # keskiarvo ottaa mukaan taukojen pohjakohinan, jolloin puhejakson taso
    # näyttää sitä matalammalta mitä enemmän sen ympärillä on hiljaisuutta —
    # ja kuljettaja nostaisi eniten siellä missä puhetta on vähiten. Näin
    # tehtynä mitattuna hajonta **kasvoi** 2,87 dB:stä 3,16:een.
    index = np.arange(count)
    voiced = np.interp(index, index[speech], db[speech])
    window = max(1, int(RIDER_WINDOW_S / RIDER_BLOCK_S))
    kernel = np.ones(window) / window
    # Reunat toistetaan, ei nollata: nollapehmustettu konvoluutio lukee
    # tiedoston ensimmäiset ja viimeiset puolitoista sekuntia hiljaisimpina
    # kohtina riippumatta sisällöstä. Sama ansa kuin ``_compute_tempo``ssa.
    pad = window // 2
    smooth = np.convolve(np.pad(voiced, pad, mode="edge"), kernel,
                         mode="same")[pad:pad + count]
    target = float(np.median(smooth[speech]))
    want = np.clip(target - smooth, -max_db, max_db)
    # **Nollaan oman puheen ulkopuolella**, ei edelliseen arvoon.
    #
    # Pitäminen tuntuu oikealta — se on se mitä yhden mikin kuljettaja
    # tekee — mutta kahden mikin nauhoituksessa se kantaa nostot toisen
    # puhujan vuoron päälle ja nostaa vuotoa. Mitattuna erottelu oman
    # puheen ja vuodon välillä putosi 19,1 dB:stä 14,8:aan; nollaan
    # palautettuna vuoto jää koskemattomaksi. Hidas liuku hoitaa reunat,
    # ja ne osuvat kohtiin joissa toinen puhuu.
    want = np.where(speech, want, 0.0)
    # Loiva liuku: kuljettajan pitää kuulostaa siltä ettei sitä ole.
    return _one_pole(want.astype(np.float32), int(1 / RIDER_BLOCK_S),
                     RIDER_SPEED_S * 1000.0), block


def ride(audio: np.ndarray, rate: int,
         speech: np.ndarray | None = None,
         max_db: float = RIDER_MAX_DB) -> np.ndarray:
    """Ajaa tasonkuljettajan. Pituus ei muutu.

    Kerroin lasketaan lohkoittain ja levitetään näytteille lineaarisesti
    lohkon sisällä. Koko tiedoston mittaista vahvistustaulukkoa ei
    rakenneta: tunnin mikki on 184 miljoonaa näytettä, ja float-taulukko
    sen päälle olisi kolme neljäsosaa gigatavusta.
    """
    gain_db, block = rider_gain(audio, rate, speech, max_db)
    if not len(gain_db) or not np.any(gain_db):
        return audio
    gain = (10.0 ** (gain_db / 20.0)).astype(np.float32)
    previous = gain[0]
    for index, value in enumerate(gain):
        low = index * block
        high = min(low + block, audio.shape[1])
        if high <= low:
            break
        audio[:, low:high] *= np.linspace(
            previous, value, high - low, dtype=np.float32)
        previous = value
    # Viimeinen vajaa lohko jää kuljettamatta: se on alle kymmenesosasekunti
    # tiedoston lopussa, eikä sinne kannata tehdä hyppyä.
    return audio


def deess(
    audio: np.ndarray,
    rate: int,
    threshold_db: float = DEESS_THRESHOLD_DB,
    ratio: float = DEESS_RATIO,
    freq: float = DEESS_HZ,
) -> np.ndarray:
    """Vaimentaa s-äänteet ennen kompressoreita.

    Jako tehdään vähentämällä alipäästö kokonaisuudesta, jolloin osat
    summautuvat takaisin täsmälleen alkuperäiseksi eikä jakoon jää
    vaihevirhettä. Vaimennus kohdistuu vain yläkaistaan, joten puheen runko
    ei liiku mukana.

    Ennen kompressoreita siksi, että ongelma ei ole s-äänteen kovuus vaan se,
    että s ohjaa kompressoria: ilman tätä yksi sihahdus vetää koko lauseen
    alas. Restauroitu ääni on tässä erityisen altis, koska liitännäinen
    lisää juuri sille alueelle useita desibelejä.
    """
    from scipy import signal as _sig

    if audio.size == 0:
        return audio
    sos = _sig.butter(4, min(freq, rate / 2 * 0.95) / (rate / 2), output="sos")
    # Paloittain, suotimet ja seuraajat jatkavat tilastaan: sama tulos kuin
    # kokonaisena, mutta muistissa on pala. Kokonaisena tämä piti kahdeksan
    # koko raidan float64-kopiota, 0,9 GB viiden minuutin raidalle (memray,
    # 2026-10-06).
    x2 = np.atleast_2d(audio)
    state = np.zeros((sos.shape[0], x2.shape[0], 2))
    smooth = _pole(rate, DEESS_SMOOTH_MS)
    follow = np.zeros(3)
    slope = 1.0 - 1.0 / ratio
    out = np.empty(x2.shape, dtype=np.result_type(x2.dtype, np.float64))
    total = x2.shape[-1]
    kernel = _kernels()["deess"]

    # Silmukka palalle k säikeessä, alipäästö palalle k+1 sillä aikaa.
    # Seuraaja jatkaa tilastaan, joten pala kerätään ennen seuraavaa.
    def collect(pending):
        begin, end, low, high, future = pending
        out[:, begin:end] = low + high * future.result()

    from concurrent.futures import ThreadPoolExecutor

    pending = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        for start in range(0, total, _COMPRESS_CHUNK):
            stop = min(total, start + _COMPRESS_CHUNK)
            piece = x2[:, start:stop]
            low, state = _sig.sosfilt(sos, piece, axis=-1, zi=state)
            high = piece - low
            if pending is not None:
                collect(pending)
            pending = (start, stop, low, high, pool.submit(
                kernel, np.ascontiguousarray(high, dtype=np.float64),
                float(threshold_db), slope, smooth, follow,
            ))
        if pending is not None:
            collect(pending)
    return out.reshape(audio.shape)


def limiter_gain(
    audio: np.ndarray,
    rate: int,
    ceiling_db: float = CEILING_DB,
    lookahead_ms: float = LIMITER_LOOKAHEAD_MS,
    release_ms: float = LIMITER_RELEASE_MS,
) -> np.ndarray:
    """Rajoittimen vahvistuskäyrä näytteittäin, arvot välillä (0, 1].

    Erillään ``limiter``ista, koska ohjelmakatto tarvitsee **käyrän** eikä
    rajoitettua ääntä: käyrä lasketaan stemien summasta ja kerrotaan
    jokaiseen stemiin erikseen, jolloin summa noudattaa kattoa eikä
    puhujien tasapaino muutu. Ks. ``mix.program_ceiling``.
    """
    if audio.size == 0:
        return np.ones(0, dtype=np.float64)
    return _shape_limiter(_needed_gain(audio, ceiling_db), rate, lookahead_ms, release_ms)


def limiter_curve(
    peak: np.ndarray,
    gain_db: float,
    rate: int,
    ceiling_db: float = CEILING_DB,
    lookahead_ms: float = LIMITER_LOOKAHEAD_MS,
    release_ms: float = LIMITER_RELEASE_MS,
) -> np.ndarray:
    """Rajoittimen käyrä signaalille ``audio · G`` sen huippuverhosta.

    ``peak`` on ``peak_envelope(audio)``. Ylinäytteistys on lineaarinen, joten
    ``audio · G``:n huippuverho on ``G · peak`` ja käyrä on sama kuin
    ``limiter_gain(audio · G)`` — ilman uutta ylinäytteistystä. Ketjun
    asettumiskierrokset ja PSR-vartija muuttavat vain G:tä; ennen jokainen
    niistä ylinäytteisti koko raidan uudestaan (87 min: 153 s 280:stä).
    """
    from scipy.ndimage import minimum_filter1d

    ceiling = 10.0 ** (ceiling_db / 20.0)
    lin = 10.0 ** (gain_db / 20.0)
    # Samat laskut kuin ``_shape_limiter``issa, mutta paikallaan ja vaatimus
    # vapautettuna heti kun ennakoiva minimi on laskettu: kerralla muistissa
    # on kaksi raidan mittaista taulukkoa, ei viittä. Ketju laskee tämän
    # jokaisella kierroksella koko raidalle.
    needed = lin * peak
    np.maximum(needed, 1e-9, out=needed)
    np.divide(ceiling, needed, out=needed)
    np.minimum(1.0, needed, out=needed)
    if needed.size == 0 or needed.min() >= 1.0:
        return np.ones(needed.shape[0], dtype=np.float64)
    window = max(1, int(lookahead_ms * rate / 1000.0))
    ahead = minimum_filter1d(needed, size=2 * window + 1, mode="nearest")
    del needed
    smooth = _one_pole(ahead, rate, release_ms)
    return np.minimum(smooth, ahead, out=smooth)


def _shape_limiter(needed: np.ndarray, rate: int, lookahead_ms: float,
                   release_ms: float) -> np.ndarray:
    """Vaatimuksesta käyrä: ennakoiva minimi ja pehmeä palautus."""
    from scipy.ndimage import minimum_filter1d

    if needed.size == 0 or needed.min() >= 1.0:
        return np.ones(needed.shape[0], dtype=np.float64)
    window = max(1, int(lookahead_ms * rate / 1000.0))
    ahead = minimum_filter1d(needed, size=2 * window + 1, mode="nearest")
    smooth = _one_pole(ahead, rate, release_ms)
    # Pehmennys saa nostaa vahvistusta hitaasti mutta ei koskaan yli sen mitä
    # huippu sallii, muuten katto ylittyy juuri siellä missä sitä tarvitaan.
    return np.minimum(smooth, ahead)


def true_peak(audio: np.ndarray) -> float:
    """Ylinäytteistetty (4×) huippu lineaarisena. Paloittain, ilman koko
    raidan mittaista verhoa."""
    if not np.size(audio):
        return 0.0
    return max(float(piece.max()) for _, _, piece in _envelope_chunks(np.atleast_2d(audio)))


def _gpu_peak_envelope_available() -> bool:
    """Metal (MLX) käytössä: Macilla jossa mlx on asennettu, ellei
    ``SPEECHMIX_NO_GPU`` ole asetettu."""
    if sys.platform != "darwin" or os.environ.get("SPEECHMIX_NO_GPU"):
        return False
    try:
        import mlx.core  # noqa: F401
    except ImportError:
        return False
    return True


_GPU_CHUNK = 1 << 21


def _envelope_chunks_gpu(audio: np.ndarray):
    """``peak_envelope`` Metalilla: sama suodin kuin ``resample_poly``issa
    (Kaiser, 2·10·up + 1 tappia), konvoluutiona nollilla täytetyn signaalin
    yli. Mitattu 10 min: 2,07 s CPU:lla, 0,20 s GPU:lla; ero scipyyn alle
    0,00001 dB (float32)."""
    import mlx.core as mx
    from scipy import signal as _sig

    up = LIMITER_OVERSAMPLE
    taps = _sig.firwin(2 * 10 * up + 1, 1.0 / up, window=("kaiser", 5.0)) * up
    delay = (len(taps) - 1) // 2
    kernel = mx.array(taps[::-1].astype(np.float32))[None, :, None]
    audio = np.atleast_2d(audio)
    total = audio.shape[1]
    for start in range(0, total, _GPU_CHUNK):
        stop = min(total, start + _GPU_CHUNK)
        lo = max(0, start - _TRUE_PEAK_PAD)
        hi = min(total, stop + _TRUE_PEAK_PAD)
        n = hi - lo
        piece = None
        for channel in range(audio.shape[0]):
            dense = mx.zeros((1, n * up, 1), dtype=mx.float32)
            dense[0, ::up, 0] = mx.array(audio[channel, lo:hi].astype(np.float32))
            y = mx.conv1d(dense, kernel, padding=len(taps) - 1)[0, :, 0]
            y = mx.abs(y[delay:delay + n * up]).reshape(n, up).max(axis=1)
            piece = y if piece is None else mx.maximum(piece, y)
        mx.eval(piece)
        yield start, stop, np.array(piece, dtype=np.float64)[start - lo:stop - lo]


def _envelope_chunks_cpu(audio: np.ndarray):
    from scipy import signal as _sig

    up = LIMITER_OVERSAMPLE
    audio = np.atleast_2d(audio)
    total = audio.shape[1]
    for start in range(0, total, _TRUE_PEAK_CHUNK):
        stop = min(total, start + _TRUE_PEAK_CHUNK)
        lo = max(0, start - _TRUE_PEAK_PAD)
        hi = min(total, stop + _TRUE_PEAK_PAD)
        dense = np.abs(_sig.resample_poly(audio[:, lo:hi], up, 1, axis=-1)).max(axis=0)
        usable = (dense.shape[0] // up) * up
        piece = dense[:usable].reshape(-1, up).max(axis=1)
        if piece.shape[0] < hi - lo:
            piece = np.pad(piece, (0, hi - lo - piece.shape[0]), mode="edge")
        yield start, stop, piece[start - lo: stop - lo]


def _envelope_chunks(audio: np.ndarray):
    """Huippuverho paloittain ``(alku, loppu, pala)``: Metalilla tai scipyllä."""
    if _gpu_peak_envelope_available():
        return _envelope_chunks_gpu(audio)
    return _envelope_chunks_cpu(audio)


def peak_envelope(audio: np.ndarray) -> np.ndarray:
    """Näytteittäin suurin ylinäytteistetty (4×) huippu kanavista.

    Macilla Metalilla (``_envelope_chunks_gpu``), muualla scipyllä.
    Näytteiden **väliin** jäävä huippu on se joka leikkaa D/A-muuntimessa ja
    lossy-koodauksessa. Paloittain, reunoille päällekkäisyyttä: koko jakso
    kerralla oli masteroinnin muistihuippu (47 min stereo 4× float64:nä
    ~21 GB). Suotimen vaste (2·10·up + 1 tappia = 20 näytettä) jää
    ``_TRUE_PEAK_PAD``in alle.
    """
    audio = np.atleast_2d(audio)
    peak = np.empty(audio.shape[1], dtype=np.float64)
    for start, stop, piece in _envelope_chunks(audio):
        peak[start:stop] = piece
    return peak


def _needed_gain(audio: np.ndarray, ceiling_db: float) -> np.ndarray:
    """Näytteittäin vaadittu vahvistus, jotta true peak pysyy katon alla."""
    ceiling = 10.0 ** (ceiling_db / 20.0)
    needed = peak_envelope(audio)
    # Paikallaan: yksi raidan mittainen taulukko eikä kolme.
    np.maximum(needed, 1e-9, out=needed)
    np.divide(ceiling, needed, out=needed)
    return np.minimum(needed, 1.0, out=needed)


#: Huippuvaihe: rajoittimen edessä oleva hidas käyrä, joka vie huiput katolle
#: niin että rajoittimelle jää vain jäännös. Ikkuna on vähintään äänijakson
#: mittainen (110 Hz:n ääni on 9 ms), joten vaimennus ei moduloi yhden jakson
#: sisällä — rajoittimen askel teki juuri sitä, 117 000 dB/s.
#:
#: Mitattu pp 55:n summalla tasolla -14 (kuunneltu 2026-09-22): pelkkä
#: rajoitin teki -9,2 dB ja kuulosti säröiseltä; huippuvaihe 20 ms teki
#: enintään -8,6 dB 29 %:ssa ajasta ja rajoittimelle jäi -0,5, ja se
#: «kuulosti yllättävän hyvältä». 10 ms oli samoilla luvuilla (-8,1, 22 %)
#: ja kuuntelija valitsi 20:n. Crest on molemmissa sama 12,3 dB, koska taso ja
#: katto määräävät sen; vaihe muuttaa vain sen, miten vaimennus tehdään.
PEAK_STAGE_MS = 20.0
#: Paluunopeus, dB/s. 20 dB 60 ms:ssa, prototyypin arvo.
PEAK_STAGE_RELEASE_DB_S = 333.0


def peak_stage_gain(
    audio: np.ndarray,
    rate: int,
    ceiling_db: float = CEILING_DB,
    window_ms: float = PEAK_STAGE_MS,
    release_db_s: float = PEAK_STAGE_RELEASE_DB_S,
) -> np.ndarray:
    """Huippuvaiheen vahvistuskäyrä, arvot välillä (0, 1].

    Kolme askelta desibeleinä: tuleva minimi ikkunan yli (vaimennus alkaa
    ikkunan verran ennen huippua), rajattu paluunopeus ja lopuksi keskiarvo
    saman ikkunan yli, joka tekee hyökkäyksestä rampin. Keskiarvo ei voi
    jäädä huipun vaatimuksen yläpuolelle, koska jokainen sen ikkunan arvo on
    jo huipun minimi. Vaimennus kulkee siis lineaarisesti koko ikkunan yli
    eikä hyppää.
    """
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    if audio.size == 0:
        return np.ones(0, dtype=np.float64)
    need = 20.0 * np.log10(_needed_gain(audio, ceiling_db))
    if need.min() >= 0.0:
        return np.ones(audio.shape[1], dtype=np.float64)
    width = max(1, int(window_ms * rate / 1000.0))
    # Tuleva minimi: [t, t + ikkuna).
    future = minimum_filter1d(need, width, origin=-(width // 2), mode="nearest")
    # Paluu enintään ``step`` näytettä kohden: held[i] = min_j≤i(future[j]
    # + (i - j)·step), vektorina kumulatiivisella minimillä.
    step = release_db_s / rate
    ramp = np.arange(need.shape[0]) * step
    held = ramp + np.minimum.accumulate(future - ramp)
    # Keskiarvo yli (t - ikkuna, t].
    shaped = uniform_filter1d(held, width, origin=(width - 1) // 2, mode="nearest")
    return 10.0 ** (np.minimum(shaped, 0.0) / 20.0)


def sustained_reduction_db(
    audio: np.ndarray,
    rate: int,
    percentile: float = LIMITER_BUDGET_PERCENTILE,
    ceiling_db: float = CEILING_DB,
) -> float:
    """Kuinka paljon rajoitin joutuisi vaimentamaan **jatkuvasti**, dB (≥ 0).

    Ei käyrän minimi. Minimi on yhden näytteen vaatimus, ja se on tavallisesti
    yksittäinen plosiivi tai naksahdus — mitattuna toisen puhujan kohdalla se
    heitti tuloksen kahdellatoista desibelillä ohi siitä mitä rajoitin
    todellisuudessa teki. Prosenttipiste kysyy sen sijaan: minkä verran
    vaimennusta kestää ainakin ``percentile`` prosentin ajan tiedostosta.
    """
    gain = limiter_gain(audio, rate, ceiling_db)
    if gain.size == 0:
        return 0.0
    quiet = float(np.percentile(gain, percentile))
    return max(0.0, -20.0 * np.log10(max(quiet, 1e-9)))


def limiter(
    audio: np.ndarray,
    rate: int,
    ceiling_db: float = CEILING_DB,
    lookahead_ms: float = LIMITER_LOOKAHEAD_MS,
    release_ms: float = LIMITER_RELEASE_MS,
) -> tuple[np.ndarray, float]:
    """Ennakoiva rajoitin. Palauttaa ``(ääni, suurin vaimennus dB)``.

    Vaadittu vahvistus lasketaan näytteittäin, siitä otetaan liukuva minimi
    ennakkoikkunan yli ja tulos pehmennetään. Liukuva minimi on **keskitetty**,
    joten rajoitin ehtii laskea ennen huippua eikä signaali siirry: pituus ja
    kohdistus säilyvät, mikä on koko viennin ehto.

    Tämä korvaa staattisen vaimennuksen. Ero ei ole hienosäätöä: staattinen
    veti koko tiedoston alas kovimman yksittäisen näytteen mukaan, mitattuna
    9–12 dB, ja teki puhujien tasapainosta sattumanvaraisen.
    """
    if audio.size == 0:
        return audio, 0.0
    # Havainnointi ylinäytteistettynä: näytteiden **väliin** jäävä huippu on
    # se joka leikkaa D/A-muuntimessa ja lossy-koodauksessa, eikä se näy
    # näytteitä katsomalla. Ks. ``limiter_gain``.
    gain = limiter_gain(audio, rate, ceiling_db, lookahead_ms, release_ms)
    return audio * gain, float(20.0 * np.log10(max(gain.min(), 1e-9)))


def compress(
    audio: np.ndarray,
    rate: int,
    threshold_db: float,
    ratio: float,
    max_gr_db: float,
    attack_ms: float,
    release_ms: float,
) -> np.ndarray:
    """Yksi kompressorivaihe, jonka vaimennuksella on **katto**.

    ``max_gr_db`` on koko idea. Yksi kompressori joka vetää kaksitoista
    desibeliä kuulostaa kompressorilta; kolme jotka vetävät neljä kuulostaa
    tasaiselta. Rajaton vaihe myös reagoi yksittäiseen napsahdukseen koko
    lauseen voimalla, ja juuri se kuullaan pumppauksena.

    Hyökkäys tulee tason tasoituksesta ja palautus vahvistuksen
    tasoituksesta: ``minimum`` niiden välillä antaa nopean laskun ja hitaan
    paluun ilman näytteittäistä silmukkaa, jota ei sadalle miljoonalle
    näytteelle voi Pythonissa ajaa.
    """
    if audio.size == 0:
        return audio
    # Paloittain, seuraajien tila jatkuu palasta toiseen: tulos on sama kuin
    # kokonaisena, mutta muistissa on vain pala. Kokonaisena tämä piti
    # seitsemän koko raidan float64-kopiota (memray, 2026-10-06).
    ca, cr = _pole(rate, attack_ms), _pole(rate, release_ms)
    state = np.zeros(3)
    x2 = np.atleast_2d(audio)
    # Sama tulostyyppi kuin kokonaisena: vahvistus on float64, joten tulo on.
    out = np.empty(x2.shape, dtype=np.result_type(x2.dtype, np.float64))
    total = x2.shape[-1]
    for start in range(0, total, _COMPRESS_CHUNK):
        stop = min(total, start + _COMPRESS_CHUNK)
        out[:, start:stop] = _compress_block(
            x2[:, start:stop], threshold_db, ratio, max_gr_db, ca, cr, state
        )
    return out.reshape(audio.shape)


#: Kompressorin pala näytteinä. Sekunti 48 kHz:llä.
_COMPRESS_CHUNK = 48000


class _Follower:
    """``_one_pole`` paloittain: tila jatkuu, alkutila ensimmäisestä näytteestä."""

    def __init__(self, rate: int, ms: float):
        coeff = float(np.exp(-1.0 / max(1.0, ms * rate / 1000.0)))
        self.b, self.a = [1.0 - coeff], [1.0, -coeff]
        self.z = None

    def step(self, x: np.ndarray) -> np.ndarray:
        from scipy import signal as _sig

        if self.z is None:
            self.z = _sig.lfilter_zi(self.b, self.a) * float(np.asarray(x).reshape(-1)[0])
        out, self.z = _sig.lfilter(self.b, self.a, x, zi=self.z)
        return out


def _pole(rate: int, ms: float) -> float:
    """Yksinapaisen seuraajan kerroin, sama kuin ``_Follower``issa."""
    return float(np.exp(-1.0 / max(1.0, ms * rate / 1000.0)))


_KERNELS: dict = {}


def _kernels():
    """Käännetyt silmukat (numba), kerran prosessia kohden.

    Seuraaja, vahvistuslaskin ja dB-muunnokset yhtenä silmukkana. Erikseen
    numpyllä ne olivat kymmenkunta koko taulukon kierrosta, ja monikaista
    vei 87 minuutin raidalla 20 s vaikka sen suotimet ovat 1–3 s (tutkimus
    ja mittaus 2026-10-07). Laskutoimitukset ja niiden järjestys ovat samat
    kuin ``lfilter``-seuraajissa, joten tulos on sama.
    """
    if _KERNELS:
        return _KERNELS
    import math

    from numba import njit

    @njit(cache=True, nogil=True)
    def compress_gain(block, threshold_db, slope, max_gr_db, ca, cr, state):
        n = block.shape[1]
        gain = np.empty(n)
        started = state[0] != 0.0
        level = state[1]
        rel = state[2]
        for i in range(n):
            x = 0.0
            for c in range(block.shape[0]):
                v = abs(block[c, i])
                if v > x:
                    x = v
            if not started:
                level = x
            level = (1.0 - ca) * x + ca * level
            over = 20.0 * math.log10(level + 1e-9) - threshold_db
            if over < 0.0:
                over = 0.0
            wanted = over * slope
            if wanted > max_gr_db:
                wanted = max_gr_db
            instant = 10.0 ** (-wanted / 20.0)
            if not started:
                rel = instant
                started = True
            rel = (1.0 - cr) * instant + cr * rel
            gain[i] = rel if rel < instant else instant
        state[0] = 1.0
        state[1] = level
        state[2] = rel
        return gain

    @njit(cache=True, nogil=True)
    def deess_gain(high, threshold_db, slope, c1, state):
        n = high.shape[1]
        gain = np.empty(n)
        started = state[0] != 0.0
        level = state[1]
        g = state[2]
        for i in range(n):
            x = 0.0
            for c in range(high.shape[0]):
                v = abs(high[c, i])
                if v > x:
                    x = v
            if not started:
                level = x
            level = (1.0 - c1) * x + c1 * level
            over = 20.0 * math.log10(level + 1e-9) - threshold_db
            if over < 0.0:
                over = 0.0
            target = 10.0 ** ((-over * slope) / 20.0)
            if not started:
                g = target
                started = True
            g = (1.0 - c1) * target + c1 * g
            gain[i] = g
        state[0] = 1.0
        state[1] = level
        state[2] = g
        return gain

    _KERNELS["compress"] = compress_gain
    _KERNELS["deess"] = deess_gain
    return _KERNELS


def _compress_block(audio, threshold_db, ratio, max_gr_db, ca, cr, state):
    """Yksi pala kompressoria; ``state`` kantaa seuraajat seuraavaan palaan."""
    gain = _kernels()["compress"](
        np.ascontiguousarray(audio, dtype=np.float64), float(threshold_db),
        1.0 - 1.0 / max(ratio, 1.0001), float(max_gr_db), ca, cr, state,
    )
    return audio * gain


# Kaistat. Alaraja pitää puhalluksen ja jyrinän erillään rungosta, yläraja
# sihinän erillään siitä: ilman jakoa yksi plosiivi vetää koko puheen alas ja
# yksi s-äänne tekee saman. Rajat ovat puheen omat, eivät musiikin.
BANDS_HZ = (250.0, 4000.0)

# Kuinka paljon kukin vaihe saa enintään vaimentaa.
#
# Owsinski: yhdessä laatikossa «less (usually way less) than 3dB of
# compression», ja kuuden desibelin vaimennus on jo «extreme processing»,
# joka kannattaa jakaa useaan vaiheeseen. Viisi on siis yläraja eikä
# tavoite: tyypillinen vaimennus jää selvästi sen alle, ja kolme vaihetta
# yhteensä pysyy sielläkin missä yksi rajaton olisi ollut kaukana yli.
MAX_GR_DB = 5.0


def split_bands(audio: np.ndarray, rate: int, edges=BANDS_HZ) -> list:
    """Jako kaistoihin, jotka summautuvat takaisin täsmälleen alkuperäiseksi.

    Ylempi kaista lasketaan vähentämällä alempi kokonaisuudesta, jolloin
    rekonstruktio on tarkka eikä jakoon jää vaihe-eroa — tavallinen
    kaistanpäästösuodinpankki vuotaa juuri risteyskohdissa.
    """
    from scipy import signal as _sig

    bands, rest = [], audio
    for edge in edges:
        sos = _sig.butter(4, min(edge, rate / 2 * 0.95) / (rate / 2), output="sos")
        low = _sig.sosfilt(sos, rest, axis=-1)
        bands.append(low)
        rest = rest - low
    bands.append(rest)
    return bands


def multiband(
    audio: np.ndarray,
    rate: int,
    threshold_db: float,
    ratio: float,
    max_gr_db: float = MAX_GR_DB,
    attack_ms: float = PEAK_ATTACK_MS,
    release_ms: float = PEAK_RELEASE_MS,
) -> np.ndarray:
    """Kompressio kaistoittain, jokainen omalla vaimennuskatollaan.

    Leveäkaistainen kompressori antaa matalien taajuuksien ohjata kaikkea:
    yksi p-äänne 100 hertsissä vetää sihinän ja rungon mukanaan, ja se
    kuullaan säröisenä vaikka mikään ei leikkaannu. Kaistoittain jokainen
    hoitaa oman ongelmansa eikä kuule toisten.
    """
    from scipy import signal as _sig

    # Sama suhde ja sama vaimennuskatto joka kaistalle. Ensin ne olivat
    # eri suuruisia — matalalle enemmän, ylös vähemmän — mikä on juuri se
    # mitä Owsinski varoittaa tekemästä: «Use the same compression ratio
    # across all bands, as differing ratios can create an unnatural sound.
    # Apply roughly the same amount of gain reduction to each band to avoid
    # altering the overall mix balance too much.» Eri määrä kaistoittain
    # muuttaa äänen sävyä ohjelman mukana, ja sen kuulee epäluonnollisena.
    #
    # Paloittain: kaistasuotimet ja kompressorien seuraajat jatkavat
    # tilastaan, joten tulos on sama kuin ``split_bands`` + ``compress``
    # kokonaisena. Kokonaisena tämä oli ketjun muistihuippu, 1,15 GB
    # viiden minuutin raidalle (memray, 2026-10-06).
    x2 = np.atleast_2d(audio)
    soses = [
        _sig.butter(4, min(edge, rate / 2 * 0.95) / (rate / 2), output="sos")
        for edge in BANDS_HZ
    ]
    states = [np.zeros((sos.shape[0], x2.shape[0], 2)) for sos in soses]
    ca, cr = _pole(rate, attack_ms), _pole(rate, release_ms)
    followers = [np.zeros(3) for _ in range(len(soses) + 1)]
    out = np.empty(x2.shape, dtype=np.result_type(x2.dtype, np.float64))
    total = x2.shape[-1]

    # Kaistojen kompressorit säikeissä, ja samalla jaetaan seuraava pala.
    # Kaistan seuraaja jatkaa omasta tilastaan, joten palan tulos kerätään
    # ennen kuin saman kaistan seuraava pala lähtee: järjestys ja tulos ovat
    # samat kuin peräkkäin. Mitattu 20 minuutista: jako 1,21 s, kompressio
    # 1,47 s; säikeissä yhteensä ks. muutosloki.
    def collect(pending):
        begin, end, futures = pending
        acc = np.zeros((x2.shape[0], end - begin))
        for future in futures:
            acc = acc + future.result()
        out[:, begin:end] = acc

    from concurrent.futures import ThreadPoolExecutor

    pending = None
    with ThreadPoolExecutor(max_workers=len(followers)) as pool:
        for start in range(0, total, _COMPRESS_CHUNK):
            stop = min(total, start + _COMPRESS_CHUNK)
            rest = x2[:, start:stop]
            parts = []
            for i, sos in enumerate(soses):
                low, states[i] = _sig.sosfilt(sos, rest, axis=-1, zi=states[i])
                parts.append(low)
                rest = rest - low
            parts.append(rest)
            if pending is not None:
                collect(pending)
            pending = (start, stop, [
                pool.submit(_compress_block, part, threshold_db, ratio,
                            max_gr_db, ca, cr, state)
                for part, state in zip(parts, followers, strict=True)
            ])
        if pending is not None:
            collect(pending)
    return out.reshape(audio.shape)


# Ylipakkauksen mittari. Owsinski: «If the maximum short-term loudness is
# less than about 6LU below the true peak level, that could be an indication
# that you're compressing more than you need to.» Se on kirjan ainoa
# numeerinen raja tälle, ja se on mitattavissa — joten se mitataan.
PSR_FLOOR_LU = 6.0

#: Mihin ketju **pysähtyy**: alle tämän se antaa tason periksi, LU.
#:
#: Owsinskin kuusi yllä on kirjallisuuden raja ylipakkaukselle ja jää
#: varoitukseksi. Tämä on mitattu korvalla tästä materiaalista, ja se on
#: paljon tiukempi.
#:
#: Kuunneltuna samasta pätkästä, äänekkyydeltään täsmättynä: crest 15,4 dB
#: (PSR 13,1) kuulosti säröiseltä, crest 18,5 (PSR 16,0) ja 19,4 (16,6)
#: eivät. Raja on siis niiden välissä, ja 15 on sen varovainen puoli.
#:
#: Miksi tämä eikä rajoittimen budjetti: budjetti mittaa **jatkuvaa**
#: vaimennusta, ja oikealla puhujalla se luki 0,00 dB samaan aikaan kun
#: rajoitin teki -5,54 dB piikkeinä ja crest päätyi 14,9:ään. Vartija ei
#: herännyt, koska se mittasi eri asiaa kuin korva. Tämä mittaa
#: lopputulosta.
#:
#: Periksi antaminen myös korjaa eikä vain hiljennä: mitattuna tavoitteen
#: lasku -15,8 -> -17,8 -> -19,8 nosti crestiä 14,9 -> 16,9 -> 18,9, eli
#: taso ostaa crestiä lähes yksi yhteen niin kauan kuin rajoitin tekee työtä.
PSR_GUARD_LU = 15.0


def peak_to_short_term(audio: np.ndarray, rate: int) -> float:
    """True peak miinus suurin lyhyen aikavälin äänekkyys, LU.

    Alle kuuden tarkoittaa että tiivistys on mennyt pidemmälle kuin oli
    tarpeen. Palauttaa ``nan`` jos ei ole mitattavaa.
    """
    mono = np.asarray(audio).mean(axis=0) if audio.ndim > 1 else np.asarray(audio)
    return _psr_of_mono(mono, rate)


def _psr_of_mono(mono: np.ndarray, rate: int) -> float:
    """``peak_to_short_term`` valmiista monosta."""
    if mono.size < rate * 3:
        return float("nan")
    peak = 20.0 * np.log10(true_peak(mono) + 1e-12)
    best = _short_term_max(mono, rate)
    return float(peak - best) if np.isfinite(best) else float("nan")


def _short_term_max(mono: np.ndarray, rate: int) -> float:
    """Suurin 3 s:n ikkunan taso (0,5 s välein), dB. Kumulatiivisella summalla:
    silmukka 10 000 ikkunan yli vei 87 minuutin raidalla ~15 s."""
    window = int(3 * rate)
    step = max(1, int(0.5 * rate))
    if len(mono) < window or window % step:
        return float("-inf") if len(mono) < window else _short_term_max_loop(mono, rate)
    # Askeleen mittaisten lohkojen energiat, ikkuna = kuusi peräkkäistä:
    # sama summa kuin ikkunoittain, ilman raidan mittaisia välitaulukoita.
    count = len(mono) // step
    blocks = np.asarray(mono[: count * step], dtype=np.float64).reshape(count, step)
    energy = np.einsum("ij,ij->i", blocks, blocks)
    per = window // step
    windows = np.convolve(energy, np.ones(per), mode="valid") / window
    return float(-0.691 + 10.0 * np.log10(windows.max() + 1e-20))


def _short_term_max_loop(mono: np.ndarray, rate: int) -> float:
    """Sama ikkunoittain, jos askel ei jaa ikkunaa tasan (oudot näytetaajuudet)."""
    window = int(3 * rate)
    step = max(1, int(0.5 * rate))
    best = -np.inf
    for start in range(0, len(mono) - window + 1, step):
        block = mono[start : start + window]
        best = max(best, -0.691 + 10.0 * np.log10(float(np.mean(block**2)) + 1e-20))
    return float(best)


def _limited_mono(pre: np.ndarray, gain_db: float, shaped: np.ndarray) -> np.ndarray:
    """``(pre · G · käyrä).mean(axis=0)`` paloittain, ilman rajoitettua ääntä."""
    lin = 10.0 ** (gain_db / 20.0)
    out = np.empty(pre.shape[1], dtype=np.float64)
    for start in range(0, pre.shape[1], _MEASURE_CHUNK):
        stop = start + _MEASURE_CHUNK
        out[start:stop] = (pre[:, start:stop] * (lin * shaped[start:stop])).mean(axis=0)
    return out


def _apply_limit(pre: np.ndarray, gain_db: float, shaped: np.ndarray) -> np.ndarray:
    """``pre · G · käyrä`` paloittain: sama tulos, ilman väliaikaista kopiota."""
    lin = 10.0 ** (gain_db / 20.0)
    out = np.empty(pre.shape, dtype=np.result_type(pre.dtype, np.float64))
    for start in range(0, pre.shape[1], _MEASURE_CHUNK):
        stop = start + _MEASURE_CHUNK
        out[:, start:stop] = pre[:, start:stop] * (lin * shaped[start:stop])
    return out


def peak_guard(audio: np.ndarray, ceiling_db: float = CEILING_DB) -> tuple:
    """Vaimentaa koko raidan, jos huippu ylittää katon.

    Staattinen vaimennus eikä rajoitin: dynamiikka on jo hoidettu
    kompressoreilla, ja tässä halutaan vain varmuus ettei särö. Palauttaa
    ``(ääni, vaimennus_dB)``, jotta tavoitetason ohitus näkyy kutsujalle.
    """
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if peak <= 0.0:
        return audio, 0.0
    ceiling = 10.0 ** (ceiling_db / 20.0)
    if peak <= ceiling:
        return audio, 0.0
    return audio * (ceiling / peak), 20.0 * np.log10(ceiling / peak)


def _board(*steps):
    """Pedalboard annetuista vaiheista, tyhjät pois."""
    import pedalboard

    return pedalboard.Pedalboard([s for s in steps if s is not None])


def _tone_body() -> tuple:
    """Rungon ja laatikkomaisuuden suotimet, ks. TONE_BODY_DB."""
    import pedalboard

    return tuple(
        pedalboard.PeakFilter(cutoff_frequency_hz=hz, gain_db=db, q=q)
        for hz, db, q in (
            (TONE_BODY_HZ, TONE_BODY_DB, TONE_BODY_Q),
            (TONE_BOX_HZ, TONE_BOX_DB, TONE_BOX_Q),
        )
        if db
    )


@dataclass
class ChainResult:
    """Yhden tiedoston käsittely."""

    frames: int
    channels: int
    gain_db: float  # normalisoinnin nosto
    measured_lufs: float | None
    lag: int  # liitännäisen aiheuttama siirtymä näytteinä
    limiter_db: float = 0.0  # rajoittimen suurin vaimennus (≤ 0)
    backed_off_db: float = 0.0  # budjetin tähden tasosta otettu (≤ 0)
    reached_target: bool = True  # osuiko tavoitetasoon budjetin sisällä
    psr_lu: float = float("nan")  # ylipakkauksen mittari, ks. peak_to_short_term


# Vaiheiden kumulatiiviset osuudet ketjun työstä.
#
# Mitattu 20 minuutin mikkitiedostolla dxRevivellä: liitännäinen 163 s, mittaus
# 2,0 s, dynamiikka 2,2 s, siirtymän mittaus 0,05 s, muut alle sekunnin. Ilman
# liitännäistä painot ovat aivan toiset, joten taulukoita on kaksi.
#
# Luvut eivät ole tarkkoja eivätkä voi olla: liitännäisen nopeus riippuu
# liitännäisestä. Ne ovat siksi, että palkki liikkuisi tunnin tiedoston aikana
# eikä seisoisi kymmentä minuuttia paikallaan.
STAGES_PLUGIN = {
    "plugin": 0.95,
    "cleanup": 0.96,
    "measure": 0.975,
    "dynamics": 0.995,
    "lag": 1.0,
}
STAGES_PLAIN = {
    "cleanup": 0.10,
    "measure": 0.45,
    "dynamics": 0.90,
    "lag": 1.0,
}


def process(
    audio: np.ndarray,
    rate: int,
    settings,
    gain_db: float,
    speech: bool,
    target_lufs: float | None,
    plugin=None,
    stage=None,
    speaking=None,
) -> tuple:
    """Ajaa ketjun. ``audio`` on muotoa ``(kanavat, näytteet)``.

    Palauttaa ``(käsitelty, ChainResult)``. Pituus ei muutu; jos jokin vaihe
    muuttaa sitä, se on virhe eikä tulosta käytetä.

    ``stage(nimi, osuus)`` kutsutaan vaiheen **valmistuttua**. Liitännäistä ei
    voi kysyä kesken ajon — se käsittelee tiedoston yhtenä palana, koska
    paloittain se lyhentäisi tuloksen — joten vaiheen tarkkuus on se mitä
    edistymisestä on saatavissa.
    """
    import pedalboard

    weights = STAGES_PLUGIN if plugin is not None else STAGES_PLAIN

    def done(name: str) -> None:
        if stage is not None:
            stage(name, weights[name])

    frames = audio.shape[1]
    original = audio[0].copy() if speech and plugin is not None else None
    limiter_db, reached, capped, backed_off = 0.0, True, False, 0.0

    # 1. Ulkoinen liitännäinen ensin: siivoa ennen kuin vahvistat.
    #
    # ``reset=True`` on pakollinen. ``reset=False`` jättää liitännäisen viiveen
    # verran häntää pois — mitattuna 4641 näytettä dxRevivella — eli tulos on
    # oikean kuuloinen mutta liian lyhyt. Tiedostoa ei siksi koskaan syötetä
    # liitännäiselle paloissa; ``apply_plugin``in rinnakkaiset palat ovat eri
    # asia, jokainen niistä on oma täysi ajonsa.
    if plugin is not None:
        audio = apply_plugin(plugin, audio, rate)
        if audio.shape[1] != frames:
            raise ChainError(
                t("audio.plugin_length", before=frames, after=audio.shape[1])
            )
        done("plugin")

    # 2.–3. Siivous ennen mittausta.
    cleanup = _board(
        pedalboard.HighpassFilter(cutoff_frequency_hz=settings.high_pass_hz)
        if settings.high_pass_hz > 0
        else None,
        *(_tone_body() if speech else ()),
    )
    if len(cleanup):
        audio = cleanup(audio, rate, reset=True)
    if speech and getattr(settings, "declick", False):
        with log.step("declick"):
            audio = declick(audio, rate, getattr(settings, "declick_sensitivity", 0.5))
    done("cleanup")

    # 3,5. Tasonkuljettaja **ennen** kaikkea muuta mitä me teemme.
    #
    # Käsityönä tehdyssä miksauksessa hidas tason tasaus on ensin ja
    # kompressori vasta sen jälkeen: kuljettaja poistaa puhujan oman
    # vaihtelun, ja kompressori saa käsiteltäväkseen signaalin josta se on
    # jo poissa. Väärin päin kompressori tekee kuljettajan työn huonosti,
    # nopeasti ja tasosta riippuvasti, ja jokainen nojaus taaksepäin maksaa
    # tiivistystä jota ei tarvittaisi.
    #
    # Ilman maskia ei kuljeteta: ks. ``rider_gain``.
    if speaking is not None and getattr(settings, "rider", True):
        with log.step("rider"):
            audio = ride(audio, rate, speaking,
                         float(getattr(settings, "rider_max_db", RIDER_MAX_DB)))

    # 4. Normalisointi siivotusta signaalista.
    with log.step("measure loudness"):
        measured = loudness(audio.mean(axis=0), rate) if target_lufs is not None else None
    lift = 0.0 if measured is None else float(target_lufs - measured)
    done("measure")

    # 5. Dynamiikka.
    if speech:
        if lift:
            audio = _board(pedalboard.Gain(gain_db=lift))(audio, rate, reset=True)
        # Sihinä pois ennen kompressoreita: muuten yksi s ohjaa koko lauseen.
        with log.step("deess"):
            audio = deess(audio, rate)

        # Rinnakkaiskompressio. Tiivistetty haara nostaa hiljaiset kohdat,
        # kuiva haara pitää transientit — sarjassa ajettuna sama tiivistys
        # veisi molemmat.
        # Kynnykset seuraavat tavoitetta, ks. THRESHOLD_REFERENCE_LUFS.
        offset = (
            0.0
            if target_lufs is None
            else float(target_lufs) - THRESHOLD_REFERENCE_LUFS
        )
        # Kolme rajattua vaihetta yhden rajattoman sijaan. Ensin kaistoittain,
        # jottei plosiivi ohjaa sihinää eikä toisin päin; sitten kaksi lempeää
        # leveäkaistaista, jotka tasaavat kokonaisuuden. Jokainen enintään
        # MAX_GR_DB, joten yhteensäkin vaimennus on maltillinen ja tasainen.
        with log.step("multiband"):
            compressed = multiband(
                audio,
                rate,
                settings.peak_threshold_db + offset,
                PEAK_RATIO,
                MAX_GR_DB,
                PEAK_ATTACK_MS,
                PEAK_RELEASE_MS,
            )
        with log.step("leveler"):
            compressed = compress(
                compressed,
                rate,
                settings.leveler_threshold_db + offset,
                LEVEL_RATIO,
                MAX_GR_DB,
                LEVEL_ATTACK_MS,
                LEVEL_RELEASE_MS,
            )
        # Kolmas vaihe on hidas ja sen kynnys on toista **alempana**, ei
        # ylempänä. Plusmerkki teki siitä kuolleen: se ajetaan toisen
        # jälkeen, joka on jo vetänyt kaiken oman kynnyksensä alle, joten
        # neljä desibeliä sen yläpuolella ei laukea koskaan. Mitattuna
        # kolmella minuutilla oikeaa puhetta vaiheen vahvistuksen hajonta
        # oli 0,00 dB jokaisella tavoitteella -14…-18 — ketju lupasi kolme
        # rajattua vaihetta ja ajoi kaksi. Neljä desibeliä alempana se tekee
        # saman verran kuin toinen vaihe (hajonta 0,58 dB kumpikin), mikä on
        # se «pieniä määriä useaan kertaan» joka tässä oli tarkoitus.
        with log.step("slow stage"):
            compressed = compress(
                compressed,
                rate,
                settings.leveler_threshold_db + offset - 4.0,
                LEVEL_RATIO,
                MAX_GR_DB,
                LEVEL_ATTACK_MS * 4,
                LEVEL_RELEASE_MS * 2,
            )
        audio = audio * (1.0 - PARALLEL_MIX) + compressed * PARALLEL_MIX
        # Tiivistetty haara oli muuten muistissa rajoittimen loppuun asti:
        # koko raidan float64-kopio (2 × float32-syöte) jota ei enää lueta.
        del compressed
        # Hylly vasta tässä, ks. TONE_PRESENCE_DB. Ennen tasomittausta, jotta
        # korjaus kattaa myös sen tuoman äänekkyyden.
        if TONE_PRESENCE_DB:
            audio = _board(
                pedalboard.HighShelfFilter(
                    cutoff_frequency_hz=TONE_PRESENCE_HZ, gain_db=TONE_PRESENCE_DB
                )
            )(audio, rate, reset=True)

        # 6. Taso mitataan uudestaan, koska kompressointi siirtää sitä.
        #
        # LUFS portittaa hiljaiset kohdat pois suhteessa kokonaisuuteen. Kun
        # kompressori nostaa hiljaisia kohtia, portin läpi pääsee eri joukko
        # lohkoja ja lukema nousee — mitattuna 2,2 dB tavoitteen yli. Siksi
        # korjaus tehdään vasta tässä, ja rajoitin sen jälkeen.
        with log.step("measure after compression"):
            after = loudness(audio.mean(axis=0), rate) if target_lufs is not None else None
        correction = 0.0 if after is None else float(target_lufs - after)
        lift += correction
        tail = _board(
            pedalboard.Gain(gain_db=correction) if correction else None,
            pedalboard.Gain(gain_db=gain_db) if gain_db else None,
        )
        if len(tail):
            audio = tail(audio, rate, reset=True)

        # Katto rajoittimella, ja sen jälkeen taso uudestaan: rajoitin syö
        # äänekkyyttä sen verran kuin se leikkaa, ja puhujien on osuttava
        # samaan lukemaan. Yksi kierros riittää, koska korjaus on pieni ja
        # rajoitin ajetaan sen perään uudestaan.
        #
        # Rajoittimen työstä pidetään kirjaa: se päätyy ``ChainResult``iin,
        # koska se on ainoa vaihe jolla ei ole kattoa eikä sitä nähnyt mikään.
        # Ylimenevä osa otetaan tasosta eikä tiivistyksestä. Vaimennus ennen
        # rajoitinta vähentää vaadittua rajoitusta yksi yhteen, joten siirto
        # on tarkka — ja taso on se puoli joka on jälkikäteen korjattavissa.
        # Rajoittamaton signaali talteen PSR-vartijaa varten, ks.
        # PSR_GUARD_LU. Vaimennus on tehtävä **ennen** rajoitinta: PSR on
        # true peak miinus lyhyen aikavälin taso, joten tason laskeminen
        # jälkikäteen siirtää molempia yhtä paljon eikä muuta sitä lainkaan.
        # Kopio maksaa yhden tiedoston verran muistia, ja se vapautetaan heti
        # kun vartija on tehnyt työnsä.
        # Kaikki rajoittimen kierrokset lähtevät **rajoittamattomasta**
        # signaalista ``pre`` ja muuttavat vain vakiovahvistusta G. Silloin
        # ylinäytteistetty huippuverho lasketaan kerran, ja jokaisen
        # kierroksen käyrä saadaan siitä (``limiter_curve``). Ennen jokainen
        # kierros rajoitti jo rajoitettua ja ylinäytteisti koko raidan
        # uudestaan: 87 minuutin raidalla 153 s 280:stä (pp 56, --verbose,
        # 2026-10-07). Rajoittamattomasta lähtien rajoitus ei myöskään
        # kerry kierroksittain.
        pre = audio
        pre_lift = lift
        with log.step("limiter: peak envelope"):
            peak = peak_envelope(pre)
        gain_db_now = 0.0

        # Kierros ei muodosta rajoitettua ääntä, vain käyrän: mittaukset
        # lasketaan ``pre · G · käyrä``stä paloittain (``_limited_mono``), ja
        # ääni kirjoitetaan kerran lopuksi. Ennen jokainen kierros piti
        # tuloksensa ja edellisen, mittaukset omat mononsa: 5 min oikeaa
        # puhetta, huippu 17,0 × float32-syöte. Laskut ovat samat, tulos
        # bitilleen sama.
        current: dict = {"gain": 0.0, "shaped": None}

        def limited(gain_db_total):
            current["shaped"] = None              # vanha pois ennen uutta
            shaped = limiter_curve(peak, gain_db_total, rate)
            current["gain"], current["shaped"] = gain_db_total, shaped
            return float(20.0 * np.log10(max(shaped.min(), 1e-9)))

        def mono():
            return _limited_mono(pre, current["gain"], current["shaped"])

        budget = float(getattr(settings, "limiter_budget_db", LIMITER_BUDGET_DB))
        if budget > 0:
            with log.step("limiter budget"):
                shaped = limiter_curve(peak, 0.0, rate)
                quiet = float(np.percentile(shaped, LIMITER_BUDGET_PERCENTILE,
                                            overwrite_input=True))
                del shaped
                over = max(0.0, -20.0 * np.log10(max(quiet, 1e-9))) - budget
            if over > 0:
                gain_db_now -= over
                lift -= over
                backed_off = -over
                capped = True
        with log.step("limiter"):
            limiter_db = limited(gain_db_now)
        # Rajoitin syö äänekkyyttä sen verran kuin se leikkaa, ja korjaus
        # nostaa huiput takaisin rajoittimen kynsiin — yksi kierros jää siis
        # vajaaksi. Kolme riittää: mitattuna ensimmäinen kierros jäi 1–2 dB
        # tavoitteesta, kolmannen jälkeen ero on alle 0,3 dB. Tavoite on nyt
        # jakelualustan lukema eikä makuasia, joten se on osuttava.
        reached = not capped
        for _ in range(3):
            if target_lufs is None or capped:
                break
            with log.step("settle: measure"):
                settled = loudness(mono(), rate)
            if settled is None or abs(target_lufs - settled) <= 0.3:
                break
            step = float(target_lufs - settled)
            gain_db_now += step
            with log.step("settle: limiter"):
                round_db = limited(gain_db_now)
            limiter_db = min(limiter_db, round_db)
            lift += step
        else:
            settled = loudness(mono(), rate) if target_lufs else None
            reached = not capped and (
                settled is None or abs(target_lufs - settled) <= 0.3
            )
        # Vartija lopputulokselle, ks. PSR_GUARD_LU. Raja on **pienempi**
        # rajasta ja siitä mitä signaalissa oli ennen rajoitinta: vartija saa
        # palauttaa vain sen minkä rajoitin vei. Ilman tätä tiheä lähde
        # vaimennetaan loputtomiin korjaamatta mitään — sinipurskeilla PSR on
        # luonnostaan matala, ja vartija otti tasosta 14 dB ilman että PSR
        # liikkui. Rajoittamattoman true peak on suoraan huippuverhosta.
        with log.step("psr guard: measure"):
            limit = min(PSR_GUARD_LU, 20.0 * np.log10(float(peak.max()) + 1e-12)
                        - _short_term_max(pre.mean(axis=0), rate))
        # Kolme yritystä: taso ostaa crestiä lähes yksi yhteen mutta ei
        # tarkasti, ja kahdella jäätiin testimateriaalilla 14,44:ään (raja
        # 14,5). Kolmas maksaa vain silloin kun kaksi ei riittänyt.
        for _ in range(3):
            if target_lufs is None or not np.isfinite(limit):
                break
            with log.step("psr guard: check"):
                # Rajoitetun signaalin true peak **mitataan**: verhosta
                # arvioituna se jäi jopa 0,5 dB alakanttiin, ja vartija
                # päästi crestin rajan alle.
                psr = _psr_of_mono(mono(), rate)
            if not np.isfinite(psr) or psr >= limit - 0.1:
                break
            short = float(limit - psr)
            gain_db_now = (lift - pre_lift) - short
            with log.step("psr guard: limiter"):
                limiter_db = limited(gain_db_now)
            lift = pre_lift + gain_db_now
            backed_off -= short
            capped, reached = True, False
        del peak
        audio = _apply_limit(pre, current["gain"], current["shaped"])
        del pre, current["shaped"]
        # Viimeinen varmistus. Rajoittimen jälkeen tämän ei pitäisi laueta,
        # ja jos laukeaa, se on rajoittimessa oleva vika eikä turvaverkon työ.
        audio, trimmed = peak_guard(audio)
        lift += trimmed
    else:
        # Tilaääni jätetään koskematta muuten: kompressoitu tilaääni pumppaa,
        # eikä taso siirry, joten yksi mittaus riittää.
        board = _board(
            pedalboard.Gain(gain_db=lift) if lift else None,
            pedalboard.Gain(gain_db=gain_db) if gain_db else None,
        )
        if len(board):
            audio = board(audio, rate, reset=True)
        audio, trimmed = peak_guard(audio)
        lift += trimmed

    if audio.shape[1] != frames:
        raise ChainError(t("audio.chain_length", before=frames, after=audio.shape[1]))
    done("dynamics")

    lag = lag_samples(original, audio[0], rate) if original is not None else 0
    done("lag")
    return audio, ChainResult(
        frames=frames,
        channels=audio.shape[0],
        gain_db=round(lift, 2),
        measured_lufs=measured,
        lag=lag,
        limiter_db=round(limiter_db, 2),
        backed_off_db=round(backed_off, 2),
        reached_target=reached,
        # Ylipakkauksen mittari ajetaan vihdoin. Se on ollut kirjoitettuna
        # siitä asti kun ketju sai rajoittimen, eikä sitä kutsunut mikään:
        # mittari jota ei lueta on sama kuin mittaria ei olisi.
        psr_lu=round(peak_to_short_term(audio, rate), 2) if speech else float("nan"),
    )
