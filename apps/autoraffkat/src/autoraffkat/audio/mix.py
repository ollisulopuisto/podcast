"""Äänenkäsittelyn ohjaus: mitkä tiedostot, minne ja milloin.

Itse signaalinkäsittely on ``chain.py``:ssä. Tämä moduuli päättää mitä
käsitellään, tarkistaa tuloksen ja pitää huolen kahdesta säännöstä, joista
kumpikaan ei ole neuvoteltavissa:

**Alkuperäiseen tiedostoon ei kosketa.** Käsitelty ääni menee rinnakkaiseen
``nimi [mix].wav``:iin. Päälle kirjoittaminen rikkoisi kaksi asiaa kerralla:
verhokäyrän välimuisti avainnetaan muokkausajalla, joten se laskettaisiin
uudestaan, ja uusi laskenta osuisi käsiteltyyn ääneen.

**Näytemäärä ei saa muuttua, eikä ääni saa siirtyä.** Vienti viittaa
käsiteltyyn tiedostoon samoilla ajoilla kuin alkuperäiseen. Pituus
tarkistetaan ketjussa ja uudestaan valmiista tiedostosta; siirtymä mitataan
ristikorrelaatiolla, koska ulkoinen liitännäinen voi ilmoittaa viiveensä
väärin ja tuottaa oikean mittaisen mutta väärässä kohdassa olevan raidan.

Analyysi ajetaan aina raa'asta äänestä. Kompressori nostaa pohjakohinaa
sanojen välissä ja tasoittaa mikkien keskinäisen eron — herkkyys on kynnys
pohjan yli ja päällekkäispuheen sääntö vertaa mikkejä toisiinsa, joten
käsitellystä äänestä laskettu päätös olisi huonompi.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from speechmix import chain, envelopes, programme
from speechmix.binaries import get_binary_path
from speechmix.chain import ChainError
from speechmix.envelopes import (  # noqa: F401  julkinen rajapinta säilyy
    duck_envelopes,
    envelope_at,
    program_fades,
)
from speechmix.freshness import FINGERPRINT_FIELDS, FINGERPRINT_VERSION
from speechmix.masks import (
    duck_masks,
    solo_masks,
    speech_masks,
)
from speechmix.meter import BLOCK_SEC, OVERLAP, IntegratedMeter

# Trimmin katto luetaan tämän moduulin kautta (`tests/test_mix.py` vertaa
# siihen), joten nimi on osa mix.py:n rajapintaa vaikka moduuli itse lukee sen
# `programme`n kautta.
from speechmix.programme import MAX_PROGRAM_TRIM  # noqa: F401
from speechmix.timeline import Span, Track

from ..i18n import t
from ..model import HOP, AudioSettings

# Formaatit jotka luetaan suoraan. Muut puretaan ffmpegillä: kameran ääni on
# mp4:n sisällä, eikä pedalboardin lukija avaa sitä.
READABLE = {
    ".wav",
    ".wave",
    ".aif",
    ".aiff",
    ".aifc",
    ".flac",
    ".w64",
    ".caf",
    ".ogg",
    ".mp3",
}

MIX_SUFFIX = " [mix]"
ROOM_SUFFIX = " [room]"
ROOM_ROLE = "effects.Tilaääni"

# Suurin sallittu siirtymä. Yksi millisekunti on jo kuultavissa kammalla,
# jos tilaääni ja mikki soivat päällekkäin.
MAX_LAG_MS = 1.0
TIMEOUT = 3600


class MixError(Exception):
    """Ääntä ei voitu käsitellä."""


def sibling(path: str, suffix: str) -> str:
    """``x.wav`` -> ``x [mix].wav``. Aina WAV, myös mp4-lähteestä."""
    base, _ = os.path.splitext(path)
    return f"{base}{suffix}.wav"


def is_current(source: str, target: str) -> bool:
    """Onko käsitelty tiedosto tuoreempi kuin lähde.

    Käsittely on hidas ja sama lähde tulee vastaan joka viennissä.
    Vanhentunut tunnistetaan muokkausajasta, kuten verhokäyrän välimuistissa.

    Tämä on vasta puolet: sama lähde eri asetuksilla antaa eri tuloksen,
    eikä se näy muokkausajassa mitenkään. Katso ``is_fresh``.
    """
    if not os.path.exists(target) or not os.path.exists(source):
        return False
    return os.path.getmtime(target) >= os.path.getmtime(source)




def stamp_dir() -> Path:
    """Käsittelyn jälkien hakemisto.

    Erillään lähteen vierestä, koska tämä on välimuistia eikä käyttäjän
    aineistoa: mikkikansioon ei kuulu tiedostoa jota kukaan ei ole pyytänyt.
    Turvallista tyhjentää — tyhjennys maksaa yhden uuden käsittelyn.
    """
    root = Path.home() / "Library" / "Caches" / "autoraffkat" / "mix"
    root.mkdir(parents=True, exist_ok=True)
    return root


def fingerprint(job: dict, settings: AudioSettings) -> str:
    """Mistä asetuksista tämä tiedosto syntyisi juuri nyt.

    Mukana on lähde (polku, koko, muokkausaika), työn omat arvot ja
    ``FINGERPRINT_FIELDS``. Liitännäisen muokkausaika on mukana siksi, että
    päivitetty liitännäinen kuulostaa eri tavalta samoilla säätimillä.

    Yksi asia jää ulkopuolelle tietoisesti: vaimennuksen ajoitus tulee samasta
    puheentunnistuksesta kuin kuvan leikkaus, joten raitojen herkkyys vaikuttaa
    siihen. Sitä ei ole täällä, koska ``adopt`` ajetaan latauksessa ja
    viennissä pelkillä ``stat``-kutsuilla — ruudukon rakentaminen siinä kohtaa
    rikkoisi juuri sen säännön, ettei tiedostojen lukeminen kuulu silmukkaan.
    """
    plugin_path = settings.plugin_path
    try:
        plugin_stamp = os.path.getmtime(plugin_path) if plugin_path else 0.0
    except OSError:
        plugin_stamp = 0.0
    try:
        st = os.stat(job["source"])
        source = [os.path.abspath(job["source"]), st.st_size, st.st_mtime_ns]
    except OSError:
        source = [os.path.abspath(job["source"]), 0, 0]
    raw = {
        "version": FINGERPRINT_VERSION,
        "source": source,
        "plugin_mtime": plugin_stamp,
        "job": {
            key: job.get(key)
            for key in ("target_lufs", "gain_db", "speech", "mono", "bit_depth")
        },
        "settings": {name: getattr(settings, name) for name in FINGERPRINT_FIELDS},
    }
    text = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _stamp_path(target: str) -> Path:
    key = hashlib.sha1(os.path.abspath(target).encode("utf-8")).hexdigest()
    return stamp_dir() / f"{key}.txt"


def read_stamp(target: str) -> str:
    """Millä asetuksilla levyllä oleva tiedosto tehtiin, tai ``""``."""
    try:
        return _stamp_path(target).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_stamp(job: dict, settings: AudioSettings) -> None:
    """Merkitsee millä asetuksilla juuri valmistunut tiedosto tehtiin."""
    # Merkinnän puuttuminen maksaa yhden turhan käsittelyn, ei tulosta.
    with contextlib.suppress(OSError):
        _stamp_path(job["target"]).write_text(
            fingerprint(job, settings), encoding="utf-8"
        )


def is_fresh(job: dict, settings: AudioSettings) -> bool:
    """Kelpaako levyllä oleva tulos sellaisenaan.

    Pelkkä muokkausaika ei riitä, ja ero on juuri se joka sai painikkeen
    näyttämään rikkinäiseltä: liitännäisen vaihto, sen säätimet, tavoitetaso
    tai vaimennuksen syvyys eivät koske lähdetiedostoon mitenkään, joten
    ``is_current`` piti vanhaa tulosta ajan tasalla ja käsittely palasi
    hiljaa tekemättä mitään.

    Tuntematon merkintä on vanhentunut: käsitelty tiedosto jonka
    syntyhistoriaa ei tiedetä voi olla mistä tahansa asetuksista.
    """
    if not is_current(job["source"], job["target"]):
        return False
    return read_stamp(job["target"]) == fingerprint(job, settings)


def weight_of(path: str) -> float:
    """Tiedoston osuus työstä, tiedostokokona.

    Tiedostot ovat eri mittaisia — samassa jaksossa 20 minuuttia ja 64 —
    joten «2/4» ei kerro paljonko on jäljellä eikä yhtä suuriksi oletettu
    arvio osu lähellekään. Koko on saatavissa ilman ffprobea ja on samassa
    muodossa olevilla tiedostoilla suoraan verrannollinen kestoon.
    """
    try:
        return float(max(1, os.path.getsize(path)))
    except OSError:
        return 1.0


def frame_count(path: str) -> int | None:
    """Äänen näytemäärä ffprobella, tai ``None`` jos ei selviä."""
    try:
        ffprobe_bin = get_binary_path("ffprobe")
        done = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=duration_ts,nb_samples,sample_rate,duration",
                "-of",
                "json",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        streams = json.loads(done.stdout or "{}").get("streams") or []
    except (
        OSError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        FileNotFoundError,
    ):
        return None
    if not streams:
        return None
    stream = streams[0]
    for name in ("nb_samples", "duration_ts"):
        raw = stream.get(name)
        if raw not in (None, "N/A"):
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
    try:
        return int(round(float(stream["duration"]) * int(stream["sample_rate"])))
    except (KeyError, TypeError, ValueError):
        return None


def extract_dir() -> Path:
    """Puretun äänen välimuisti. Turvallista tyhjentää milloin tahansa."""
    root = Path.home() / "Library" / "Caches" / "autoraffkat" / "extracted"
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_readable(path: str) -> str:
    """Palauttaa polun, jonka äänilukija osaa avata.

    Kameran ääni on mp4:n sisällä, joten se puretaan WAViksi välimuistiin.
    Purku ei kirjoita median viereen: se on väliaikaista eikä kuulu käyttäjän
    hakemistoon.
    """
    if os.path.splitext(path)[1].lower() in READABLE:
        return path
    stat = os.stat(path)
    target = (
        extract_dir() / f"{Path(path).stem}-{stat.st_size}-{int(stat.st_mtime)}.wav"
    )
    if target.exists():
        return str(target)
    tmp = target.with_suffix(".tmp.wav")
    try:
        ffmpeg_bin = get_binary_path("ffmpeg")
        done = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-i",
                path,
                "-vn",
                "-map",
                "a:0",
                "-c:a",
                "pcm_f32le",
                str(tmp),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        raise MixError(t("audio.extract_failed", name=exc)) from exc
    if done.returncode != 0 or not tmp.exists():
        tail = (done.stderr or "").strip().splitlines()
        raise MixError(
            t("audio.extract_failed", name=os.path.basename(path))
            + (f" — {tail[-1]}" if tail else "")
        )
    tmp.replace(target)
    return str(target)


@dataclass
class MixResult:
    """Käsittelyn tulos vientiä varten."""

    # media key -> käsitelty tiedosto. Vienti viittaa näihin alkuperäisten
    # sijaan; ajat pysyvät samoina, koska näytemäärä on sama.
    replacements: dict[str, str] = field(default_factory=dict)
    # (media key, käsitelty tiedosto) tilaäänelle, omalle lanelleen.
    room: list[tuple[str, str]] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    # Normalisoinnin nosto raidoittain. Näytetään käyttöliittymässä, koska
    # nosto nostaa myös pohjakohinaa eikä sitä saa tehdä huomaamatta.
    gains: dict[str, float] = field(default_factory=dict)
    processed: int = 0
    # Mitattu ohjelmatrimmi, näytetään käyttäjälle: se selittää miksi
    # yksittäinen stemi mittaa tavoitteen alle.
    program_trim: float = 0.0
    skipped: int = 0
    # Huomautukset raidoittain: tehtiin kyllä, mutta jokin osa jäi tekemättä
    # ja siihen on syy. Erillään virheistä, koska tiedosto on silti kelvollinen.
    notes: dict[str, list] = field(default_factory=dict)
    # Kuinka paljon rajoittimen budjetti otti tasosta stemikohtaisesti (≤ 0).
    # Tasapaino korjataan näistä yhtenä jaettuna päätöksenä, ks.
    # `programme.shared_backoff`.
    backoffs: dict[str, float] = field(default_factory=dict)
    # Jakelutason nosto, joka tehtiin summaan katon yhteydessä.
    program_boost: float = 0.0
    # Mitattu ohjelman äänekkyys jakelun jälkeen, LUFS. Nolla = ei mitattu.
    program_lufs: float = 0.0
    program_range: float = 0.0            # LRA, LU
    program_short_term_max: float = 0.0   # LUFS
    program_momentary_max: float = 0.0    # LUFS
    # Rajoittimen hinta äänekkyytenä, LU: sama summa rajoitettuna ja ilman.
    program_limit_cost: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors


# Ohjelmakaton pala ja sen marginaali. Rajoittimen muisti on ennakko (5 ms)
# ja palautus (120 ms), joten sekunnin marginaali on kertaluokkaa liikaa —
# ja liikaa on tässä oikea suunta, koska palan raja ei saa näkyä.


def track_of(item, **fields) -> Track:
    """Tämä media kirjaston ``Track``ina. **Ainoa** kohta joka tuntee molemmat.

    Aikajanan ja tiedostoajan muunnos oli laskettuna kaavana
    ``placement.start - item.asset_start - placement.offset`` kuudessa
    kohdassa tässä moduulissa ja kahdessa kirjastossa. Kaava on hiljainen
    kun se menee väärin — käännetty etumerkki tai pudonnut esiintymä
    tuottaa kelvollisen, oikean mittaisen tiedoston väärässä kohdassa — ja
    kahdeksana kappaleena se on kahdeksan tilaisuutta mennä väärin eri
    tavalla.

    ``Fraction`` muuttuu liukuluvuksi tässä ja vain tässä. Tarkka aika on
    XML:n ja aikajanan asia, koska pyöristysvirhe kertyy tuhansien ruutujen
    yli; näytepaikat pyöristetään kokonaisluvuiksi heti perään, joten
    kirjastolle liukuluku riittää.

    ``file_offset`` on tiedoston hetki joka osuu paikan alkuun, eli
    ``placement.start - item.asset_start``: tiedoston t=0 vastaa
    lähdemateriaalin hetkeä ``asset_start``.
    """
    fields.setdefault("speaker", "")
    return Track(
        path=item.path,
        spans=[
            Span(
                float(p.offset), float(p.end), float(p.start - item.asset_start)
            )
            for p in item.placements
        ],
        **fields,
    )


def closed_ranges(item, closed, program_start: float, rate: int):
    """Ruudukon kiinni-jaksot tämän tiedoston näyteväleiksi."""
    return envelopes.closed_ranges(track_of(item), closed, program_start, rate)


def speech_blocks(item, mask, program_start: float, rate: int,
                  block: int, count: int):
    """Puhujan oma puhe lohkoittain tässä tiedostossa."""
    return envelopes.speech_blocks(
        track_of(item), mask, program_start, rate, block, count
    )


def _geometry(item, frames: int) -> tuple:
    """Tiedoston sijainti aikajanalla, vertailukelpoisena avaimena."""
    return envelopes.geometry(track_of(item), frames)


#: Kuinka monta kierrosta jakelutasoa haetaan. Rajoitin vie osan noston
#: tuomasta äänekkyydestä, joten yksi kierros jää aina alle — mutta ero
#: pienenee kertaluokan kierrosta kohden, joten kolme riittää.
DELIVER_ROUNDS = 3
#: Oletustoleranssi jos asetuksissa ei ole omaa, LU.
DELIVER_TOLERANCE = 0.5


def _anyone_speaking(grid, program_start: float):
    """``(maski, ohjelman alku)`` puheportille, tai ``None``.

    Kuka tahansa käy: portin tehtävä on erottaa puhe muusta, ei puhujia
    toisistaan. Ruudukko on aikajanan aikaa, ja ``_mask_samples`` muuntaa sen
    tiedoston näytteiksi kun ryhmä on tiedossa.
    """
    if grid is None:
        return None
    lanes = [np.asarray(lane.on, dtype=bool) for lane in getattr(grid, "speakers", [])]
    if not lanes:
        return None
    anyone = lanes[0].copy()
    for lane in lanes[1:]:
        anyone |= lane
    return (anyone, float(program_start))


def program_deliver(jobs: list[dict], result: "MixResult", ducks: dict,
                    extra: dict, settings: AudioSettings,
                    speech=None) -> None:
    """Ohjelma jakelutasoon: mittaa, nosta, rajoita, mittaa uudestaan.

    Tämä on se työ jonka moni tekee erillisellä työkalulla viennin jälkeen —
    rajoitin ja äänekkyyskorjaus valmiin miksauksen päälle. Se kuuluu tänne,
    koska tässä on ainoa paikka jossa **summa** on olemassa: stemit
    kirjoitetaan erikseen ja isäntä soittaa niiden summan, joten jokainen
    muu paikka joutuisi arvaamaan sen.

    Silmukka on tarpeen eikä varovaisuutta. Nosto tuo äänekkyyttä, rajoitin
    vie osan siitä takaisin, ja yksi kierros jää siksi aina tavoitteen alle.
    Ero pienenee nopeasti, joten kolme kierrosta riittää.

    Mittaus on koko ohjelmasta eikä ikkunasta: ``IntegratedMeter`` kerää
    lukeman samasta virrasta jonka katto kirjoittaa, joten koko pituus
    maksaa yhden lisäkierroksen eikä yhtään ylimääräistä lukukertaa.
    """
    target = float(getattr(settings, "program_lufs", 0.0) or 0.0)
    if not target:
        program_ceiling(jobs, result, ducks, extra)
        return
    ceiling = float(getattr(settings, "program_peak_db", chain.CEILING_DB))
    rate = 48000
    for job in jobs:
        if os.path.exists(job.get("target", "")):
            with __import__("pedalboard").io.AudioFile(job["target"]) as handle:
                rate = int(handle.samplerate)
            break

    tolerance = float(getattr(settings, "program_tolerance", DELIVER_TOLERANCE))
    short_target = float(getattr(settings, "program_short_term_db", 0.0) or 0.0)

    # Ensimmäinen lukema tulee katon omasta ajosta, ei erillisestä
    # lukukierroksesta. Katto ajetaan joka tapauksessa, se virtaa jokaisen
    # stemin läpi ja osaa jo täyttää mittarin — erillinen mittauskierros
    # olisi gigatavu luettavaa eikä yhtään desibeliä enempää tietoa.
    #
    # Sama syy miksi lukemaa ei kerätä stemeittäin kirjoituksen yhteydessä:
    # summan äänekkyys ei ole stemien äänekkyyksien summa, ja mikkien
    # välinen vuoto on korreloitunutta, joten tehojen laskeminen yhteen
    # olisi arvio eikä mittaus. Mitataan se mikä soi.
    # Kierrokset ovat **kuivia**: ne lukevat ja mittaavat muttei kirjoita.
    # Silmukka etsii oikean noston, ja vasta valittu nosto kirjoitetaan
    # kerran. Kirjoittavat kierrokset rajoittivat jo rajoitettua, ja
    # tiivistys kertyi kierroksittain — mitattuna LRA 5,1 kun kerran ajettuna
    # se on lähes kolme yksikköä enemmän. Nosto on siksi myös absoluuttinen
    # eikä askel: jokainen kierros lähtee samasta tilanteesta.
    budget = float(getattr(settings, "program_limit_budget_db", 0.0) or 0.0)
    lift_db = float(getattr(settings, "program_lift_db", 0.0) or 0.0)
    step_sec = BLOCK_SEC / OVERLAP

    def run(gain, curve, write=False):
        """Yksi ajo. Palauttaa ``(lukema, mittari, rajoittimen hinta LU)``.

        Kaksi mittaria: sama summa rajoitettuna ja ilman. Erotus on
        rajoittimen hinta äänekkyytenä, ja se on ainoa mielekäs mitta sille
        kuinka kovaa se tekee työtä — käyrän minimi on yhden näytteen
        vaatimus, ja keskiarvo on lähes nolla koska rajoitin ei tee mitään
        suurimman osan ajasta.
        """
        played, plain = IntegratedMeter(rate), IntegratedMeter(rate)
        program_ceiling(jobs, result, ducks, extra, gain, ceiling, played,
                        curve, step_sec if curve is not None else 0.0,
                        not write, plain, speech)
        gate = played.speech() > 0.5 if speech is not None else None
        after, before = played.value(keep=gate), plain.value(keep=gate)
        cost = 0.0 if (after is None or before is None) else before - after
        return after, played, cost

    measured, meter, cost = run(0.0, None)
    step_sec = meter.step_seconds()
    boost, ride = 0.0, None
    for round_number in range(DELIVER_ROUNDS):
        if measured is None:
            break
        step = target - measured
        wanted = None
        if short_target:
            wanted = programme.short_term_ride(
                meter.short_term() + step, short_target, step_sec
            )
            wanted = wanted if wanted.any() else None
        if abs(step) <= tolerance and wanted is None:
            break
        boost = round(max(-programme.MAX_PROGRAM_BOOST,
                          min(programme.MAX_PROGRAM_BOOST, boost + step)), 2)
        ride = wanted if wanted is not None else ride
        measured, meter, cost = run(boost, ride)
        # Rajoittimella on budjetti, kuten ketjun omalla. Ala on mitattu
        # muualla eikä täällä: masteroinnissa 1–3 dB rajoitusta on tervettä,
        # 8–10 tuhoaa transientit. Ylitys otetaan pois **nostosta**, koska
        # taso on korjattavissa yhdellä liu'ulla ja litistetty ei ole.
        if budget and cost > budget:
            boost = round(boost - (cost - budget), 2)
            measured, meter, cost = run(boost, ride)
            _log(f"rajoitinbudjetti täynnä: nosto {boost:+.2f} dB, "
                 f"hinta {cost:.2f} LU -> {measured:.2f} LUFS")
            # Loppumatka pohjasta, ei katosta. Huippuja painamalla se
            # maksaisi transientteja; hiljaisia jaksoja nostamalla se ei
            # maksa rajoitusta lainkaan, koska niissä on huippuvaraa.
            short = target - measured if measured is not None else 0.0
            if lift_db > 0 and short > tolerance:
                floor = target - max(tolerance, short)
                rise = programme.short_term_lift(
                    meter.short_term(), floor, step_sec, lift_db
                )
                if rise.any():
                    ride = rise if ride is None else ride[: len(rise)] + rise
                    measured, meter, cost = run(boost, ride)
                    _log(f"pohjan nosto {rise.max():.2f} dB hiljaisiin "
                         f"jaksoihin -> {measured:.2f} LUFS "
                         f"(rajoitin {cost:.2f} LU)")
            break
        _log(f"jakelutaso kierros {round_number + 1}: nosto {boost:+.2f} dB"
             + (f", veto {ride.min():.2f} dB" if ride is not None else "")
             + f" -> {measured:.2f} LUFS (rajoitin {cost:.2f} LU)")

    # Yksi kirjoittava ajo valitulla nostolla.
    measured, meter, cost = run(boost, ride, write=True)
    result.program_limit_cost = round(cost, 2)
    result.program_boost = boost
    result.program_lufs = measured if measured is not None else 0.0
    result.program_range = meter.range()
    result.program_short_term_max = meter.short_term_max()
    result.program_momentary_max = meter.momentary_max()
    _log(f"jakelu: {result.program_lufs:.1f} LUFS · LRA {result.program_range:.1f} "
         f"· rajoitin {result.program_limit_cost:.2f} LU "
         f"· lyhyt max {result.program_short_term_max:.1f} "
         f"· hetkellinen max {result.program_momentary_max:.1f}")
    if measured is not None and abs(target - measured) > tolerance:
        for job in jobs:
            result.notes.setdefault(job["key"], []).append(
                t("audio.program_short", target=f"{target:.1f}",
                  got=f"{measured:.1f}")
            )
            break


def program_ceiling(jobs: list[dict], result: "MixResult",
                    envelopes: dict | None = None,
                    extra: dict | None = None,
                    boost_db: float = 0.0,
                    ceiling_db: float = chain.CEILING_DB,
                    meter=None,
                    ride_db=None,
                    ride_step: float = 0.0,
                    dry_run: bool = False,
                    raw_meter=None,
                    speech=None) -> None:
    """Huippukatto **ohjelmalle**, ei yhdelle stemille.

    Sama virhe kuin äänekkyydessä, jonka ``program_trim`` jo korjaa: ketju
    takaa katon jokaiselle tiedostolle erikseen, mutta Final Cut soittaa
    niiden summan. Kaksi stemiä joiden huiput on molemmat painettu
    -1,5 dBTP:hen ylittävät täyden asteikon aina kun huiput osuvat samaan
    hetkeen — teoriassa +4,5 dB, ja oikealla jaksolla mitattuna **+4,51
    dBFS, 200 ylityspursketta minuutissa**, mediaanipituus 0,23 ms. Se on
    se särö joka kuuluu, ja Final Cutin punaiset huiput ovat sama asia.

    Korjaus ei ole kovempi rajoitus stemeittäin — silloin jokainen stemi
    maksaisi kuusi desibeliä crestiä sen takia mitä *toinen* tiedosto
    sattuu tekemään — vaan **yhteinen käyrä**: vaimennus lasketaan summasta
    ja kerrotaan jokaiseen stemiin samanlaisena. Summa noudattaa kattoa, ja
    koska kerroin on sama, puhujien tasapaino ei muutu. Mitattuna summan
    huippu +4,51 -> -1,51 dBFS ja hinta 0,50 LU.

    Ajo on **idempotentti**: käyrä on ``min(1, katto/huippu)``, joten
    summalle joka jo noudattaa kattoa se on ykkönen kaikkialla eikä toinen
    ajo tee mitään. Siksi tämä voidaan ajaa aina, myös silloin kun osa
    tiedostoista ohitettiin ajan tasalla olevina.
    """
    from pedalboard.io import AudioFile

    mics = [
        job
        for job in jobs
        if job.get("speech")
        and job.get("item") is not None
        and os.path.exists(job.get("target", ""))
    ]
    if len(mics) < 2:
        # Yksi mikki *on* ohjelma: ketjun oma katto riittää.
        return

    groups: dict[tuple, list] = {}
    for job in mics:
        frames = frame_count(job["target"])
        if frames is None:
            continue
        groups.setdefault(_geometry(job["item"], frames), []).append(job)

    for key, members in groups.items():
        if len(members) < 2:
            # Yksin aikajanan palassa: ei summaa johon osua.
            continue
        frames = key[0]
        try:
            worst = _ceiling_pass(
                members, frames, AudioFile, envelopes, extra, boost_db,
                ceiling_db, meter, ride_db, ride_step, dry_run,
                raw_meter, speech,
            )
        except (OSError, ValueError) as exc:
            for job in members:
                result.notes.setdefault(job["key"], []).append(str(exc))
            _log(f"ohjelmakatto ohitettiin: {exc}")
            continue
        if worst < -0.01:
            _log(f"ohjelmakatto: {len(members)} stemiä, suurin vaimennus "
                 f"{worst:.2f} dB")


def _ceiling_pass(members: list[dict], frames: int, AudioFile,
                  envelopes: dict | None = None,
                  extra: dict | None = None,
                  boost_db: float = 0.0,
                  ceiling_db: float = chain.CEILING_DB,
                  meter=None,
                  ride_db=None,
                  ride_step: float = 0.0,
                  dry_run: bool = False,
                  raw_meter=None,
                  speech=None) -> float:
    """Yksi ryhmä: summa paloittain, sama käyrä jokaiseen stemiin.

    ``envelopes`` on vaimennus puhujittain aikajanan aikana. Se **on**
    otettava mukaan summaan, koska vaimennusta ei enää polteta tiedostoon:
    ilman sitä summa olisi ohjelma jota Final Cut ei koskaan soita — tällä
    aineistolla 8 ja 30 minuuttia vaimennettavaa — ja katto laskettaisiin
    liian kovasta signaalista. Vaimennus itse kirjoitetaan silti vientiin,
    ei tiedostoon; tässä se vain otetaan huomioon.

    ``extra`` on stemikohtainen vakiovaimennus, jolla rajoittimen budjetin
    eri syvyiset peruutukset tasataan samaan lukemaan. Se kulkee tässä
    samassa ajossa eikä omanaan, koska tämä pass lukee ja kirjoittaa jokaisen
    stemin joka tapauksessa.

    Paloittain, koska koko ohjelma muistissa olisi useita gigatavuja.
    Marginaali molemmin puolin ja siitä keskiosa talteen, jotta rajoittimen
    palautus ei ala nollasta jokaisen palan alussa — sama kuvio kuin
    ``chain.apply_plugin``in rinnakkaisilla paloilla.
    """
    handles = [AudioFile(job["target"]) for job in members]
    spoken = None
    try:
        rate = int(handles[0].samplerate)
        if any(int(h.samplerate) != rate for h in handles):
            raise ValueError("stemien näytetaajuudet eroavat")
        chunk = int(programme.CEILING_CHUNK * rate)
        margin = int(programme.CEILING_MARGIN * rate)
        if speech is not None and members[0].get("item") is not None:
            # Kerran ryhmää kohden: maski on ruudukon aikaa, mittari haluaa
            # sen näytteinä ja palan mukana.
            spoken = _mask_samples(members[0]["item"], speech[0], speech[1],
                                   rate, frames)
        # Kuiva ajo lukee ja mittaa muttei kirjoita. Silmukka etsii oikean
        # noston sillä, ja vasta valittu nosto kirjoitetaan — muuten jokainen
        # kierros rajoittaisi jo rajoitettua, ja tiivistys kertyisi
        # kierroksittain. Mitattuna kertyvänä LRA 5,1, kerran ajettuna 7,x.
        outs = [] if dry_run else [
            AudioFile(job["target"] + ".ceil.tmp.wav", "w", rate,
                      int(h.num_channels), bit_depth=job.get("bit_depth", 24))
            for job, h in zip(members, handles, strict=True)
        ]
        worst = 0.0
        try:
            position = 0
            while position < frames:
                low = max(0, position - margin)
                high = min(frames, position + chunk + margin)
                blocks = []
                for job, handle in zip(members, handles, strict=True):
                    handle.seek(low)
                    # Jakelutason nosto on jokaiselle sama, ja se tehdään
                    # **ennen** jaettua käyrää: silloin rajoitus osuu vain
                    # sinne missä huiput osuvat yhteen, eikä yksikään stemi
                    # maksa crestiä toisen puolesta.
                    # Jaettu peruutus samaan ajoon: tämä pass lukee ja
                    # kirjoittaa stemin joka tapauksessa.
                    blocks.append(
                        handle.read(high - low)
                        * _linear((extra or {}).get(job["key"], 0.0) + boost_db)
                    )
                if ride_db is not None and ride_step > 0:
                    # Hidas veto näytteille: käyrä on ohjelman aikaa, ja
                    # lineaarinen interpolointi riittää, koska se on jo
                    # pehmennetty ikkunansa pituudella.
                    when = (np.arange(low, high) / rate) / ride_step
                    curve = np.interp(when, np.arange(len(ride_db)), ride_db)
                    blocks[-1] = blocks[-1] * (10.0 ** (curve / 20.0)).astype(
                        np.float32
                    )
                heard = [
                    block * _envelope_block(job, envelopes, low, high, rate)
                    for job, block in zip(members, blocks, strict=True)
                ]
                gain = programme.shared_gain(heard, rate, ceiling_db)
                worst = min(worst, programme.reduction_db(gain))
                head = position - low
                tail = head + min(chunk, frames - position)
                if meter is not None:
                    # Mitataan **vaimennettu** summa rajoituksen jälkeen, eli
                    # juuri se ohjelma jonka isäntä soittaa. Sama ajo kirjoittaa
                    # ja mittaa: erillinen mittauskierros olisi gigatavu lisää
                    # luettavaa eikä yhtään desibeliä enempää tietoa.
                    played = sum(h * gain for h in heard)
                    mono = (played[..., head:tail].mean(axis=0)
                            if played.ndim > 1 else played[head:tail])
                    meter.add(mono, None if spoken is None
                              else spoken[low + head:low + tail])
                if raw_meter is not None:
                    # Sama summa **ilman** rajoitusta. Erotus on rajoittimen
                    # hinta äänekkyytenä, ja se on ainoa mielekäs mitta sille
                    # kuinka kovaa se tekee työtä: käyrän minimi on yhden
                    # näytteen vaatimus, ja keskiarvo on lähes nolla koska
                    # rajoitin ei tee mitään suurimman osan ajasta.
                    plain = sum(heard)
                    raw_meter.add(plain[..., head:tail].mean(axis=0)
                                  if plain.ndim > 1 else plain[head:tail])
                if not dry_run:
                    for out, block in zip(outs, blocks, strict=True):
                        out.write(np.ascontiguousarray(
                            (block * gain)[:, head:tail]))
                position += chunk
        finally:
            for out in outs:
                out.close()
    finally:
        for handle in handles:
            handle.close()

    if dry_run:
        return worst
    for job in members:
        tmp = job["target"] + ".ceil.tmp.wav"
        written = frame_count(tmp)
        if written != frames:
            # Näytemäärä on viennin ehto: mieluummin ei mitään kuin väärä
            # pituus, ja alkuperäinen käsitelty tiedosto jää paikalleen.
            for other in members:
                _drop(other["target"] + ".ceil.tmp.wav")
            raise ValueError(
                f"ohjelmakatto muutti pituutta {frames} -> {written}"
            )
    for job in members:
        os.replace(job["target"] + ".ceil.tmp.wav", job["target"])
    return worst


def _linear(db: float) -> float:
    """Desibelit kertoimeksi. Nolla on ykkönen eikä pyöristysvirhe."""
    return 1.0 if not db else float(10.0 ** (float(db) / 20.0))


def _envelope_block(job: dict, envelopes_by_speaker: dict | None, low: int,
                    high: int, rate: int) -> np.ndarray:
    """Vaimennuksen kerroin tiedoston näyteväliltä ``[low, high)``.

    Ykkösiä silloin kun puhujalle ei ole käyrää: silloin summaan menee
    tiedosto sellaisenaan.
    """
    points = (envelopes_by_speaker or {}).get(job.get("speaker"))
    item = job.get("item")
    if not points or item is None:
        return np.ones(1, dtype=np.float32)
    return envelopes.duck_gain(track_of(item), points, low, high, rate)

def _drop(path: str) -> None:
    """Poistaa tilapäistiedoston, jos se on olemassa."""
    with contextlib.suppress(OSError):
        os.remove(path)




def _jobs(timeline, roles, settings: AudioSettings) -> list[dict]:
    """Käsiteltävät tiedostot: mikit, ja tilaääni jos sellainen on valittu."""
    jobs: list[dict] = []
    for speaker, keys in roles.mics.items():
        for track_key in keys:
            for item in timeline.track_media(track_key):
                if item.path:
                    jobs.append(
                        {
                            "key": item.key,
                            "name": item.name,
                            "speaker": speaker,
                            "item": item,
                            "source": item.path,
                            "target": sibling(item.path, MIX_SUFFIX),
                            "target_lufs": settings.target_lufs,
                            "gain_db": settings.gain_db,
                            "speech": True,
                            # Mikki on aina mono ulos, myös jos lähde on
                            # stereo. Kaksikanavainen mikki rikkoo laskennan
                            # useassa kohtaa hiljaa: ristivuodon vähennys
                            # katsoo vain ensimmäistä kanavaa, ohjelmakatto
                            # summaa eri kanavamäärät levittämällä, ja
                            # panorointi on monolähteen käsite. Yhteen
                            # kanavaan pakotettuna ne kaikki pitävät.
                            "mono": True,
                            "weight": weight_of(item.path),
                        }
                    )
    if settings.room_track:
        for item in timeline.track_media(settings.room_track):
            if item.path and item.has_audio:
                # Tilaääni normalisoidaan samaan tavoitteeseen mutta asetetun
                # verran hiljemmalle, jotta taso on ennustettava eikä riipu
                # siitä miten kuuma kameran mikki sattui olemaan.
                jobs.append(
                    {
                        "key": item.key,
                        "name": item.name,
                        "source": item.path,
                        "target": sibling(item.path, ROOM_SUFFIX),
                        "target_lufs": settings.target_lufs + settings.room_db,
                        "gain_db": 0.0,
                        "speech": False,
                        # Tunnelmaraita ei tarvitse stereokuvaa eikä 24
                        # bittiä: monona ja 16 bitissä se on kuudesosa.
                        "mono": True,
                        "bit_depth": 16,
                        "weight": weight_of(item.path),
                    }
                )
    return jobs


# Ohjelmatrimmin mittausikkuna. Trimmi on tilastollinen suure — kuinka paljon
# puhujat menevät päällekkäin ja kuinka paljon mikit kuulevat toisiaan — eikä
# se muutu jakson aikana niin paljon että koko jakson lukeminen kannattaisi.
# Kaksitoista minuuttia keskeltä maksaa muutaman sekunnin.

# Trimmiä ei sallita rajattomasti kumpaankaan suuntaan: se on korjaus
# päällekkäisyyteen, ei toinen normalisointi. Kuudesta desibelistä ylöspäin
# olisi kyse mittausvirheestä, ei summasta.


def _item_span(item) -> float:
    """Median kokonaiskesto aikajanalla, ikkunan ankkurin valintaan."""
    return sum(float(p.duration) for p in item.placements)


def program_trim(jobs: list[dict], settings: AudioSettings) -> float:
    """Kuinka paljon mikkien summa on tavoitteen yli, desibeleinä (≤ 0).

    Tavoitetaso on **ohjelman** taso, ei yhden stemin. Kaksi -14 LUFS:n
    mikkiä ei summaudu -14:ään: tällä aineistolla mitattu summa oli -12,3.
    Ero ei ole 3 dB (silloin molemmat puhuisivat koko ajan) eikä 0 dB
    (silloin toinen mikki olisi täysin hiljaa toisen puhuessa), joten se
    mitataan eikä arvata.

    Mitataan raa'asta äänestä ennen käsittelyä ja rajatusta ikkunasta.
    Tarkka vastaus vaatisi koko ohjelman käsittelyn ensin ja jokaisen
    tiedoston kirjoittamisen toiseen kertaan — noin viidenneksen lisää
    aikaa — ja ero on murto-osa desibeliä. Lopullinen taso asetetaan
    Final Cutissa joka tapauksessa.

    Ikkuna on aikajanan aikaa, koska summa on aikajanalla. Tiedostoaika
    lasketaan esiintymistä samalla kaavalla kuin ``closed_ranges``:issa.
    """
    from pedalboard.io import AudioFile

    mics = [
        job
        for job in jobs
        if job.get("speech")
        and job.get("item") is not None
        and os.path.exists(job["source"])
        and os.path.splitext(job["source"])[1].lower() in READABLE
    ]
    if len(mics) < 2:
        # Yksi mikki *on* ohjelma: sen oma taso on jo oikea.
        return 0.0

    # Ikkuna ankkuroidaan pisimpään mikkitiedostoon eikä koko aikajanan
    # keskelle: monikamerassa osat ovat peräkkäin, ja aikajanan keskikohta
    # osuu yhteen osaan — toisen osan tiedostot mittautuisivat hiljaisiksi
    # ja koko mittaus kaatuisi siihen. Saman osan mikit ovat aina päällekkäin.
    anchor = max((job["item"] for job in mics), key=_item_span)
    low, high = float(anchor.timeline_start), float(anchor.timeline_end)
    span = min(programme.PROGRAM_WINDOW, high - low)
    if span <= 1.0:
        return 0.0
    middle = (low + high) / 2
    window = (middle - span / 2, middle + span / 2)

    rate = 0
    voices = 0
    total: np.ndarray | None = None
    for job in mics:
        item = job["item"]
        with AudioFile(job["source"]) as handle:
            if rate and handle.samplerate != rate:
                # Eri näytetaajuudet vaatisivat uudelleennäytteistyksen.
                # Trimmi on valinnainen tarkennus, ei syy hidastaa ajoa.
                _log("ohjelmatrimmi ohitettu: mikeillä eri näytetaajuus")
                return 0.0
            rate = handle.samplerate
            if total is None:
                total = np.zeros(int(span * rate), dtype=np.float32)
            here = np.zeros_like(total)
            for span in track_of(item).spans:
                first = max(window[0], span.programme_start)
                last = min(window[1], span.programme_end)
                if last <= first:
                    continue
                start = int(round(span.to_file_time(first) * rate))
                frames = int(round((last - first) * rate))
                if start < 0 or frames <= 0 or start >= handle.frames:
                    continue
                frames = min(frames, handle.frames - start)
                handle.seek(start)
                block = handle.read(frames).mean(axis=0)
                at = int(round((first - window[0]) * rate))
                end = min(len(here), at + len(block))
                if end > at:
                    here[at:end] = block[: end - at]
        contribution = programme.at_target(here, rate, settings.target_lufs)
        if contribution is None:
            continue
        total += contribution
        voices += 1

    if voices < 2 or total is None:
        return 0.0
    trim = programme.trim_to_target(total, rate, settings.target_lufs)
    _log(f"ohjelmatrimmi {trim:+.2f} dB")
    return trim


# Tiedoston työ vaiheittain: luku ja kirjoitus ovat gigatavun tiedostolla
# oikeaa aikaa, ketju on loput. Ketjun sisäinen jako on ``chain.STAGES_*``.
READ_SHARE = 0.07
DEBLEED_SHARE = 0.05
CHAIN_SHARE = 0.81
WRITE_SHARE = 0.07


def overlaps(one, other) -> bool:
    """Ovatko kaksi mediaa yhtään hetkeä yhtä aikaa aikajanalla.

    Monikamerassa osat ovat peräkkäin, joten toisen osan mikki ei voi
    vuotaa tämän osan tiedostoon. Ilman tätä se tarjottiin silti
    vuotolähteeksi, ``_aligned`` palautti pelkkää nollaa, ja lokiin tuli
    «vuotopolkua ei saatu ratkaistua» pariutumisesta joka ei ollut koskaan
    mahdollinen. Vienti ei mennyt siitä rikki — oikea kumppani käsiteltiin
    erikseen — mutta sama tiedosto näytti lokissa sekä onnistuvan että
    epäonnistuvan, ja se peitti alleen oikean vian pitkissä osissa.
    Virheilmoitus jota ei voi uskoa on huonompi kuin ei ilmoitusta.
    """
    for mine in one.placements:
        for theirs in other.placements:
            if (float(mine.offset) < float(theirs.end)
                    and float(theirs.offset) < float(mine.end)):
                return True
    return False


def _debleed(job, audio, rate, program_start, solos, partners, result):
    """Vähentää muiden mikkien vuodon ``audio``:sta paikan päällä.

    Yksi lähde kerrallaan ja aina tuoreimmasta tuloksesta: kun kolmas
    puhuja vuotaa kahteen muuhun, ensimmäisen vähennyksen jälkeen jäljellä
    oleva ei ole enää sama signaali kuin alussa.

    Epäonnistuminen ei ole hiljainen. Jos vähennystä ei tehty, syy menee
    lokiin ja tulokseen — asetus päällä ja lopputuloksessa ei mitään on
    juuri se vika joka tässä projektissa on jo kerran jäänyt huomaamatta.
    """
    from pedalboard.io import AudioFile

    from speechmix import debleed as db

    mine = (solos or {}).get(job.get("speaker"))
    if mine is None:
        return
    frames = audio.shape[1]
    solo_target = _mask_samples(job["item"], mine, program_start, rate, frames)
    target = audio[0].astype(np.float64)
    for partner in partners:
        theirs = (solos or {}).get(partner.get("speaker"))
        if theirs is None:
            continue
        if partner.get("item") is None or not overlaps(job["item"], partner["item"]):
            continue          # eri osa: ei yhtään yhteistä hetkeä
        try:
            with AudioFile(ensure_readable(partner["source"])) as handle:
                if handle.samplerate != rate:
                    _log(f"    vuoto {partner['speaker']}: eri näytetaajuus, ohitetaan")
                    continue
                other = handle.read(handle.frames)
        except (OSError, RuntimeError) as exc:
            _log(f"    vuoto {partner['speaker']}: {exc}")
            continue
        source = _aligned(
            job["item"], partner["item"], np.asarray(other).mean(axis=0), rate, frames
        )
        solo_source = _mask_samples(partner["item"], theirs, program_start, rate, frames)
        target, info = db.remove(target, source, rate, solo_source, solo_target)
        if info["reason"]:
            note = t(f"audio.debleed_{info['reason']}", name=partner["speaker"])
            _log(f"    vuoto {partner['speaker']}: {note}")
            if result is not None:
                result.notes.setdefault(job["key"], []).append(note)
        else:
            _log(
                f"    vuoto {partner['speaker']}: -{info['reduction_db']:.1f} dB, "
                f"oma puhe {info['kept']:.4f}"
            )
    audio[0] = target.astype(audio.dtype, copy=False)


def _run_one(
    job: dict,
    settings: AudioSettings,
    plugin,
    program_start: float = 0.0,
    stage=None,
    trim_db: float = 0.0,
    solos: dict | None = None,
    partners: list | None = None,
    result=None,
    speaking: dict | None = None,
) -> float:
    """Käsittelee yhden tiedoston. Palauttaa normalisoinnin noston.

    ``stage(nimi, osuus)`` kertoo missä kohtaa tätä tiedostoa mennään.
    Liitännäinen on kallein vaihe eikä kerro itsestään mitään kesken ajon,
    joten vaiheen tarkkuus on se mitä edistymisestä on saatavissa — ja se
    riittää siihen, ettei palkki seiso tunnin tiedoston ajan paikallaan.
    """
    from pedalboard.io import AudioFile

    def report(name: str, share: float) -> None:
        if stage is not None:
            stage(name, share)

    source = ensure_readable(job["source"])
    with AudioFile(source) as handle:
        audio = handle.read(handle.frames)
        rate = handle.samplerate
    report("read", READ_SHARE)
    if audio.shape[1] == 0:
        raise MixError(t("audio.empty_file", name=os.path.basename(job["source"])))
    if job.get("mono") and audio.shape[0] > 1:
        audio = audio.mean(axis=0, keepdims=True)

    # Ristivuoto pois ennen liitännäistä. Järjestys ei ole makuasia:
    # liitännäinen on generatiivinen eikä säilytä raitojen välistä
    # lineaarista suhdetta, ja sen jälkeen vuotoa ei enää voi vähentää
    # millään suotimella.
    if settings.debleed and job.get("speech", True) and partners:
        _debleed(job, audio, rate, program_start, solos, partners, result)
    report("debleed", READ_SHARE + DEBLEED_SHARE)

    # Ohjelmatrimmi kuuluu **tavoitteeseen**, ei vahvistukseen. Ketju
    # normalisoi lopuksi tavoitteeseen, joten vahvistukseen lisätty trimmi
    # kumoutuu siinä kokonaan — mitattuna stemit osuivat -14,1:een kun niiden
    # piti osua -15,8:aan. Tavoitteessa se säilyy, koska normalisointi ajaa
    # juuri siihen lukemaan.
    target = job.get("target_lufs")
    if target is not None and trim_db:
        target = float(target) + trim_db

    # Tasonkuljettajan maski: milloin **tämän raidan oma puhuja** on
    # äänessä. Signaalista pääteltynä puolet «puheesta» olisi toisen
    # vuotoa, ja kuljettaja nostaisi sitä — ks. ``chain.rider_gain``.
    own = None
    mine = (speaking or {}).get(job.get("speaker"))
    if mine is not None and job.get("item") is not None and job.get("speech"):
        block = max(1, int(chain.RIDER_BLOCK_S * rate))
        own = speech_blocks(job["item"], mine, program_start, rate, block,
                            audio.shape[1] // block)

    audio, info = chain.process(
        audio,
        rate,
        settings,
        job.get("gain_db", 0.0),
        job.get("speech", True),
        target,
        plugin,
        speaking=own,
        stage=lambda name, frac: report(
            name, READ_SHARE + DEBLEED_SHARE + CHAIN_SHARE * frac
        ),
    )

    # Vaimennusta **ei** polteta tiedostoon. Se kirjoitetaan vientiin Final
    # Cutin omaksi kulmakohtaiseksi äänenvoimakkuuskäyräksi, jolloin
    # leikkaaja voi muuttaa sen ilman uutta ajoa — ks. ``duck_envelopes``.
    # Tiedostoon poltettuna se oli ketjun ainoa peruuttamaton tasopäätös.
    report("duck", READ_SHARE + DEBLEED_SHARE + CHAIN_SHARE)

    # Ketjun tiivistys kirjataan muistiinpanoksi. Se on tähän asti ollut
    # ainoa vaihe jonka tulos ei näkynyt mistään: tiedosto on kelvollinen ja
    # oikean mittainen, ja se että rajoitin vei siitä viisitoista desibeliä
    # crestiä selviää vain kuuntelemalla. Ks. `chain.LIMITER_BUDGET_DB`.
    who = os.path.basename(job["source"])
    if not info.reached_target:
        result.notes.setdefault(job["key"], []).append(
            f"{who}: tavoitetaso ei osunut, rajoitin {info.limiter_db:.1f} dB"
        )
    if info.psr_lu == info.psr_lu and info.psr_lu < chain.PSR_FLOOR_LU:
        result.notes.setdefault(job["key"], []).append(
            f"{who}: ylipakattu, PSR {info.psr_lu:.1f} LU "
            f"(alle {chain.PSR_FLOOR_LU:.0f})"
        )

    limit = int(rate * MAX_LAG_MS / 1000)
    if abs(info.lag) > limit:
        raise MixError(
            t(
                "audio.plugin_shifted",
                samples=info.lag,
                ms=info.lag / rate * 1000,
                name=os.path.basename(job["source"]),
            )
        )

    # Alkuperäiseen ei kosketa. ``sibling`` takaa tämän jo, mutta tarkistus
    # on kirjoituskohdassa, koska kohteen laskeminen on muualla ja yksi
    # virhe siellä olisi peruuttamaton.
    if os.path.abspath(job["target"]) == os.path.abspath(job["source"]):
        raise MixError(t("audio.would_overwrite", name=os.path.basename(job["source"])))

    tmp = job["target"] + ".tmp.wav"
    with AudioFile(
        tmp, "w", rate, audio.shape[0], bit_depth=job.get("bit_depth", 24)
    ) as out:
        out.write(np.ascontiguousarray(audio))
    written = frame_count(tmp)
    if written is not None and written != info.frames:
        os.remove(tmp)
        raise MixError(
            t(
                "audio.written_length",
                before=info.frames,
                after=written,
                name=os.path.basename(job["source"]),
            )
        )
    os.replace(tmp, job["target"])
    write_stamp(job, settings)
    report("write", READ_SHARE + DEBLEED_SHARE + CHAIN_SHARE + WRITE_SHARE)
    if result is not None:
        result.backoffs[job["key"]] = info.backed_off_db
    return info.gain_db


def freshness(timeline, roles, settings: AudioSettings) -> tuple[int, int]:
    """(ajan tasalla, kaikkiaan) — mitä painike kertoo käyttäjälle.

    Käyttöliittymän on erotettava kolme tilaa, jotka näyttivät ennen samalta:
    ei käsitelty, käsitelty, ja käsitelty mutta asetukset ovat sen jälkeen
    muuttuneet. Ilman tätä painike palasi joka kerta tekstiin «Käsittele
    ääni», eikä valmiiseen työhön voinut luottaa katsomalla.

    Pelkkiä ``stat``-kutsuja ja pieniä merkintätiedostoja, kuten ``adopt``:
    tämä saa olla kyselyn tiellä, äänen lukeminen ei.
    """
    if timeline is None or not settings.enabled:
        return 0, 0
    jobs = _jobs(timeline, roles, settings)
    return sum(1 for job in jobs if is_fresh(job, settings)), len(jobs)


def adopt(timeline, roles, settings: AudioSettings) -> MixResult:
    """Ottaa käyttöön ne käsitellyt tiedostot jotka ovat jo levyllä.

    Käsittely tehdään kerran, mutta ``MixResult`` on istunnon tila. Ilman
    tätä jakson uusi avaus veisi raakaa ääntä pelkästään siksi että nappia
    ei painettu tällä kertaa — vaikka ajan tasalla oleva ``[mix]`` on
    lähteen vieressä. Eron kuulee vasta Final Cutissa, jolloin leikkaus on
    jo tehty eikä sille ole enää muuta lähdettä.

    Pelkkiä ``stat``-kutsuja: ei lue ääntä eikä lataa liitännäistä. Vanhaa
    ei oteta: ``is_fresh`` vertaa muokkausajan lisäksi asetuksia, samoin
    kuin ``process`` — muuten vienti käyttäisi tiedostoa jonka käsittely
    juuri totesi vanhentuneeksi.
    """
    result = MixResult()
    if not settings.enabled:
        return result
    for job in _jobs(timeline, roles, settings):
        if os.path.exists(job["source"]) and is_fresh(job, settings):
            result.skipped += 1
            _record(result, job)
    return result




def _mask_samples(item, mask, program_start: float, rate: int, frames: int):
    """Ruudukon maski tiedoston näytteiksi. Sama muunnos kuin ``closed_ranges``."""
    out = np.zeros(frames, dtype=bool)
    for first, last in closed_ranges(item, mask, program_start, rate):
        low, high = max(0, first), min(frames, last)
        if high > low:
            out[low:high] = True
    return out


def _aligned(target_item, source_item, source_audio, rate: int, frames: int):
    """Lähdemikin ääni kohdetiedoston näytepaikoille.

    Tiedostot ovat eri pituisia ja alkavat aikajanalla eri kohdista, joten
    vuotoa ei voi vähentää ennen kuin ne ovat samassa aikapohjassa. Kuvaus
    on esiintymän sisällä lineaarinen ja näytetaajuus sama, joten se on
    kokonaisluvun siirto — ei uudelleennäytteistystä, joka siirtäisi
    vaihetta ja pilaisi juuri sen mitä tässä yritetään mitata.
    """
    out = np.zeros(frames, dtype=np.float64)
    source = np.asarray(source_audio, dtype=np.float64).reshape(-1)
    for target in track_of(target_item).spans:
        for source_span in track_of(source_item).spans:
            low = max(target.programme_start, source_span.programme_start)
            high = min(target.programme_end, source_span.programme_end)
            if high <= low:
                continue
            t0 = int(round(target.to_file_time(low) * rate))
            t1 = int(round(target.to_file_time(high) * rate))
            # Kuinka kaukana lähdetiedosto on kohdetiedostosta samalla
            # ohjelman hetkellä. Molemmat kuvaukset ovat kulmakertoimeltaan
            # yksi, joten erotus on sama joka hetkellä paikan sisällä.
            shift = int(
                round(
                    (source_span.to_file_time(low) - target.to_file_time(low)) * rate
                )
            )
            t0, t1 = max(0, t0), min(frames, t1)
            s0, s1 = t0 + shift, t1 + shift
            if s1 <= 0 or s0 >= source.size or t1 <= t0:
                continue
            cut = max(0, -s0)
            s0, t0 = s0 + cut, t0 + cut
            cut = max(0, s1 - source.size)
            s1, t1 = s1 - cut, t1 - cut
            if t1 > t0:
                out[t0:t1] = source[s0:s1]
    return out


def process(
    timeline,
    roles,
    settings: AudioSettings,
    grid=None,
    program_start: float = 0.0,
    progress=None,
    force: bool = False,
) -> MixResult:
    """Käsittelee mikit ja tilaäänen. Hidas — ei kuulu säätösilmukkaan.

    Liitännäinen ladataan kerran ja sen tila nollataan tiedostojen välissä:
    lataus maksaa, mutta edellisen tiedoston häntä ei saa vuotaa seuraavaan.

    ``force`` ohittaa tuoreuden ja käsittelee kaiken uudestaan. Se on
    käyttäjän tahallinen valinta eikä oletus: ajo maksaa minuutteja, joten
    käyttöliittymä kysyy sen erikseen.
    """
    result = MixResult()
    if not settings.enabled:
        return result

    jobs = _jobs(timeline, roles, settings)
    if not jobs:
        _log("ei käsiteltäviä raitoja")
        return result

    todo = []
    for job in jobs:
        if not os.path.exists(job["source"]):
            result.errors[job["key"]] = t("audio.source_missing", path=job["source"])
        elif not force and is_fresh(job, settings):
            _log(f"ohitetaan {job['name']}: ajan tasalla")
            result.skipped += 1
            _record(result, job)
        else:
            todo.append(job)
    if not todo:
        # Ilman tätä riviä painike näyttää rikkinäiseltä: ei lokia, ei
        # palkkia, ei uusia tiedostoja — eikä mitään mikä kertoisi että ajo
        # todella tapahtui ja oli valmis ennen kuin se alkoi.
        _log(f"ei mitään tehtävää: {len(jobs)} tiedostoa on jo ajan tasalla")
        # Jakelutaso on silti tehtävä. Se ei ole tiedostojen käsittelyä vaan
        # katon yhteydessä tehtävä nosto, ja tästä palaaminen tarkoittaisi
        # että tason muuttaminen ei tee **mitään** kun stemit ovat ajan
        # tasalla: säädin liikkuu, lokiin ei tule mitään, ääni ei muutu.
        if settings.program_lufs and grid is not None:
            program_deliver(
                jobs, result, duck_envelopes(grid, settings, program_start),
                {}, settings, _anyone_speaking(grid, program_start),
            )
        return result

    try:
        workers = chain.worker_count(settings.plugin_workers)
        plugin = chain.load_pool(
            settings.plugin_path,
            settings.plugin_params,
            workers,
            settings.plugin_state,
        )
        if plugin is not None and workers > 1:
            _log(f"liitännäinen {workers} rinnakkaisena palana")
    except ChainError as exc:
        # Ohi mennään, ei pysähdytä. Liitännäinen on yksi vaihe ketjussa, ja
        # sen puuttuminen vei aiemmin mukanaan äänekkyyden, kompressorit ja
        # rajoittimen, joilla ei ole sen kanssa mitään tekemistä. Siirretty
        # tai päivittynyt liitännäinen ei ole syy jättää jakso käsittelemättä.
        #
        # Mutta **kerrotaan**. Hiljainen ohitus olisi pahempi kuin
        # pysähtyminen: tulos on kelvollinen, oikean mittainen ja siltä osin
        # käsittelemätön kuin liitännäinen olisi tehnyt, eikä sitä kuule
        # ennen kuin Final Cutissa.
        plugin = None
        for job in jobs:
            result.notes.setdefault(job["key"], []).append(
                t("audio.plugin_skipped", error=str(exc))
            )
        _log(f"liitännäinen ohitettu: {exc}")
        # Leima kertoo mitä **tehtiin**, ei mitä pyydettiin. `plugin_path` on
        # `FINGERPRINT_FIELDS`issä, joten asetetulla polulla leimattu ohitus
        # näyttäisi tuoreelta sitten kun liitännäinen taas löytyy — eikä
        # tiedostoja käsiteltäisi uudestaan koskaan.
        settings = replace(
            settings, plugin_path="", plugin_params={}, plugin_state=""
        )

    solos = solo_masks(grid) if settings.debleed else {}
    if settings.debleed and not solos:
        result.errors["debleed"] = t("audio.debleed_no_grid")
        _log(result.errors["debleed"])
    masks = duck_masks(grid, settings)
    if settings.duck:
        # Maskit avaimetaan puhujan nimellä ja työt hakevat samalla nimellä.
        # Hiljainen avainten eroaminen olisi juuri se vika joka on jo kerran
        # jäänyt huomaamatta: asetus päällä, tuloksessa ei mitään.
        wanted = {job.get("speaker") for job in jobs if job.get("speech")}
        matched = wanted & set(masks)
        if not matched:
            result.errors["duck"] = t(
                "audio.duck_none", speakers=", ".join(sorted(w for w in wanted if w))
            )
            _log(result.errors["duck"])
        else:
            covered = sum(int(masks[name].sum()) for name in matched)
            _log(
                f"vaimennus: {len(matched)}/{len(wanted)} mikkiä, "
                f"{covered * HOP / 60:.1f} min vaimennettavaa"
            )
    # Mitataan kaikista mikeistä eikä vain käsiteltävistä: summa on koko
    # ohjelma riippumatta siitä mikä tiedosto sattuu olemaan jo valmis.
    trim = program_trim(jobs, settings) if settings.program_target else 0.0
    result.program_trim = trim
    started = time.perf_counter()
    total_weight = sum(job["weight"] for job in todo) or 1.0

    try:
        out = _run_todo(
            result, todo, jobs, settings, plugin, program_start,
            progress, trim, started, total_weight, solos,
            speech_masks(grid) if grid is not None else None,
        )
    finally:
        if hasattr(plugin, "close"):
            plugin.close()
    # Katto vasta kun kaikki stemit ovat levyllä: se lasketaan niiden
    # summasta, jota ei ole olemassa ennen viimeistä tiedostoa. Vaimennus
    # mukaan, koska sitä ei enää ole tiedostoissa — ilman sitä katto
    # laskettaisiin ohjelmasta jota Final Cut ei soita.
    ducks = (duck_envelopes(grid, settings, program_start)
             if grid is not None else {})
    # Budjetin peruutukset tasataan ennen kattoa: eri syvyiset peruutukset
    # siirtäisivät puhujien tasapainoa, mitattuna 1,1 dB:n erosta 5,9 dB:iin.
    extra = programme.shared_backoff(result.backoffs)
    if any(extra.values()):
        _log(f"jaettu peruutus: {extra}")
    # Jakelutaso mitataan **vaimennetusta summasta**, koska se on ohjelma
    # jonka isäntä soittaa. Stemin oma tavoite jää siksi ennalleen: se on
    # tason lähtökohta, tämä on jakelun luku, eivätkä ne ole sama asia.
    # Puheportti: RX arvioi puheen sijainnin itse, meillä se on tiedossa.
    # Ruudukko on sama jonka päälle koko leikkaus on rakennettu, joten
    # portti on tarkempi kuin arvaus eikä maksa mitään.
    program_deliver(jobs, result, ducks, extra, settings,
                    _anyone_speaking(grid, program_start))
    return out


def _run_todo(
    result, todo, jobs, settings, plugin, program_start,
    progress, trim, started, total_weight, solos=None, speaking=None,
):
    """Tiedostot yksi kerrallaan. Erillään, jotta liitännäisvaranto suljetaan
    myös silloin kun jokin kaatuu kesken."""
    behind = 0.0
    for index, job in enumerate(todo):
        _log(f"{index + 1}/{len(todo)} {job['name']}")
        # Kello nollataan tiedostoittain: vaiheen kesto on tämän tiedoston
        # vaiheen kesto, ei kulunut aika koko ajon alusta.
        stage_at = time.perf_counter()

        def stage(name: str, share: float, job=job, behind=behind) -> None:
            """Yhden vaiheen valmistuminen: lokiin ja edistymiseen."""
            nonlocal stage_at
            now = time.perf_counter()
            _log(f"    {name} {now - stage_at:.1f}s")
            stage_at = now
            fraction = (behind + job["weight"] * share) / total_weight
            if progress is not None:
                progress(
                    {
                        "done": index,
                        "total": len(todo),
                        "current": job["name"],
                        "stage": name,
                        "fraction": round(fraction, 4),
                        "eta": _eta(started, fraction),
                    }
                )

        if progress is not None:
            progress(
                {
                    "done": index,
                    "total": len(todo),
                    "current": job["name"],
                    "stage": "read",
                    "fraction": round(behind / total_weight, 4),
                    "eta": _eta(started, behind / total_weight),
                }
            )
        try:
            # Kumppanit ovat *kaikki* mikkityöt, eivät vain tehtävälistan:
            # vuoto tulee toisesta mikistä riippumatta siitä onko se jo
            # käsitelty. Lähteeksi luetaan aina raaka tiedosto.
            partners = [
                other
                for other in jobs
                if other.get("speech")
                and other.get("speaker")
                and other["speaker"] != job.get("speaker")
                and os.path.exists(other["source"])
            ]
            result.gains[job["key"]] = _run_one(
                job, settings, plugin, program_start, stage, trim,
                solos, partners, result, speaking,
            )
        except (MixError, ChainError, OSError, RuntimeError, ValueError) as exc:
            result.errors[job["key"]] = str(exc)
            _log(f"    VIRHE: {exc}")
            behind += job["weight"]
            continue
        _log(f"    valmis {result.gains[job['key']]:+.1f} dB")
        behind += job["weight"]
        result.processed += 1
        _record(result, job)
    _log(f"valmis {time.perf_counter() - started:.0f}s")
    if progress is not None:
        progress(
            {
                "done": len(todo),
                "total": len(todo),
                "current": "",
                "stage": "",
                "fraction": 1.0,
                "eta": 0.0,
            }
        )
    return result


def _log(message: str) -> None:
    """Käsittelyn kulku terminaaliin.

    Käsittely on minuutteja pitkä ja tapahtuu taustasäikeessä, jossa mikään
    ei näy. Kun se on hidas tai kaatuu, kysymys on aina sama: minkä tiedoston
    kohdalla ja missä vaiheessa. Suomeksi kuten muukin koodi — tämä on
    ylläpitäjän loki, ei käyttäjälle näkyvä teksti.
    """
    print(f"[ääni] {message}", flush=True)


def _eta(started: float, fraction: float) -> float:
    """Arvio jäljellä olevasta ajasta sekunteina.

    Osuus painotetaan tiedostokoolla ja vaiheella, joten arvio on olemassa
    jo ensimmäisen vaiheen jälkeen eikä vasta ensimmäisen tiedoston jälkeen —
    ja 20 minuutin tiedosto ei enää lupaa samaa kuin 64 minuutin.
    """
    if fraction <= 0.001:
        return 0.0
    return (time.perf_counter() - started) / fraction * (1.0 - fraction)


def _record(result: MixResult, job: dict) -> None:
    """Merkitsee valmiin tuloksen oikeaan koriin."""
    if job.get("speech", True):
        result.replacements[job["key"]] = job["target"]
    else:
        result.room.append((job["key"], job["target"]))
