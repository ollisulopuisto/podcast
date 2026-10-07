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

from speechmix import chain, envelopes, programme, stems
from speechmix import timeline as timeline_lib
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

# Trimmin katto luetaan tämän moduulin kautta (`tests/test_mix.py` vertaa
# siihen), joten nimi on osa mix.py:n rajapintaa vaikka moduuli itse lukee sen
# `programme`n kautta.
from speechmix.programme import MAX_PROGRAM_TRIM  # noqa: F401
from speechmix.timeline import Span, Track

from ..i18n import t
from ..model import HOP, AudioSettings

# Formaatit jotka luetaan suoraan: kirjaston lista, ks. ``stems.READABLE``.
READABLE = stems.READABLE

MIX_SUFFIX = " [mix]"
ROOM_SUFFIX = " [room]"
ROOM_ROLE = "effects.Tilaääni"

MAX_LAG_MS = stems.MAX_LAG_MS
TIMEOUT = 3600


# Ääntä ei voitu käsitellä. Kirjaston virhe: stemin käsittely on siellä.
MixError = stems.StemError


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
    """Äänen näytemäärä; kirjastossa (``speechmix.stems.frame_count``)."""
    return stems.frame_count(path)


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
                "-nostdin",
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
            stdin=subprocess.DEVNULL,
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
    # Masterointitason nosto, joka tehtiin summaan katon yhteydessä.
    program_boost: float = 0.0
    # Mitattu ohjelman äänekkyys masteroinnin jälkeen, LUFS. Nolla = ei mitattu.
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


_anyone_speaking = stems.anyone_speaking
delivery_lufs = stems.delivery_lufs


def _with_tracks(jobs: list[dict]) -> list[dict]:
    """Kirjaston työ tarvitsee ``Track``in; tämä sovellus tuntee ``item``in.

    Muunnos on ``track_of``issa ja vain siellä. Työ johon se on jo tehty
    (``_jobs``) kelpaa sellaisenaan.
    """
    out = []
    for job in jobs:
        if job.get("track") is None and job.get("item") is not None:
            job = {**job, "track": track_of(job["item"])}
        out.append(job)
    return out


def program_deliver(jobs: list[dict], result: "MixResult", ducks: dict,
                    extra: dict, settings: AudioSettings,
                    speech=None) -> None:
    """Ohjelma masterointitasoon. Kirjastossa: ``speechmix.stems.program_deliver``."""
    stems.program_deliver(_with_tracks(jobs), result, ducks, extra, settings, speech)


def program_ceiling(jobs: list[dict], result: "MixResult",
                    envelopes: dict | None = None,
                    extra: dict | None = None,
                    **kwargs) -> None:
    """Huippukatto ohjelmalle. Kirjastossa: ``speechmix.stems.program_ceiling``."""
    stems.program_ceiling(_with_tracks(jobs), result, envelopes, extra, **kwargs)


def _envelope_block(job: dict, envelopes_by_speaker: dict | None, low: int,
                    high: int, rate: int) -> np.ndarray:
    """Vaimennuksen kerroin. Kirjastossa: ``speechmix.stems.envelope_block``."""
    (job,) = _with_tracks([job])
    return stems.envelope_block(job, envelopes_by_speaker, low, high, rate)


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
                            "track": track_of(item),
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


def program_trim(jobs: list[dict], settings: AudioSettings) -> float:
    """Mikkien summan ero tavoitteeseen. Kirjastossa: ``speechmix.stems.program_trim``."""
    return stems.program_trim(_with_tracks(jobs), settings.target_lufs)


def overlaps(one, other) -> bool:
    """Ovatko kaksi mediaa yhtään hetkeä yhtä aikaa aikajanalla.

    Sääntö on kirjastossa: se on puhdasta jaksogeometriaa, ja automixerin
    vuodonvähennys tarvitsee saman. Tänne jää `track_of`, eli FCPXML.
    """
    return timeline_lib.overlaps(track_of(one), track_of(other))


def preview_audio(
    timeline,
    roles,
    settings: AudioSettings,
    grid=None,
    program_start: float = 0.0,
) -> dict:
    """Arvioi äänenkäsittelyn taustalla ennen varsinaista ajoa.

    Laskee nopeasti ilman raskasta VST3-liitännäistä:
    1. Ohjelmatrimmin (program_trim) tavoitetasoon
    2. Ristivuodon poiston (debleed) toteutettavuuden ja vaimennusarvion
    3. Tilaäänen (room_track) purun välimuistiin, jos se on videoraita
    """
    from pedalboard.io import AudioFile

    from speechmix import debleed as db

    out = {
        "program_trim": 0.0,
        "debleed": [],
        "room_ready": False,
        "ready": False,
        "error": "",
    }
    if timeline is None or not settings.enabled:
        out["ready"] = True
        return out

    jobs = _jobs(timeline, roles, settings)
    if not jobs:
        out["ready"] = True
        return out

    # 1. Tilaäänen purku välimuistiin etukäteen
    if settings.room_track:
        for job in jobs:
            if not job.get("speech") and os.path.exists(job.get("source", "")):
                try:
                    ensure_readable(job["source"])
                    out["room_ready"] = True
                except Exception as exc:
                    _log(f"tilaäänen esipurku epäonnistui: {exc}")

    # 2. Ohjelmatrimmi
    if settings.program_target:
        try:
            out["program_trim"] = float(program_trim(jobs, settings))
        except Exception as exc:
            _log(f"ohjelmatrimmin arviointi epäonnistui: {exc}")

    # 3. Ristivuoto (debleed)
    if settings.debleed and grid is not None:
        solos = solo_masks(grid)
        mics = [
            j
            for j in jobs
            if j.get("speech")
            and j.get("speaker")
            and j.get("item") is not None
            and os.path.exists(j.get("source", ""))
        ]
        seen_pairs = set()
        for job in mics:
            mine = (solos or {}).get(job.get("speaker"))
            if mine is None:
                continue
            partners = [
                other
                for other in mics
                if other.get("speaker") != job.get("speaker")
                and overlaps(job["item"], other["item"])
            ]
            for partner in partners:
                theirs = (solos or {}).get(partner.get("speaker"))
                if theirs is None:
                    continue
                pair_key = (job["speaker"], partner["speaker"])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                try:
                    with AudioFile(ensure_readable(job["source"])) as h_target:
                        target_rate = int(h_target.samplerate)
                        target_frames = h_target.frames
                        target_audio = h_target.read(target_frames)
                    with AudioFile(ensure_readable(partner["source"])) as h_source:
                        if int(h_source.samplerate) != target_rate:
                            continue
                        source_audio = h_source.read(h_source.frames)

                    frames = target_audio.shape[1]
                    solo_target = _mask_samples(
                        job["item"], mine, program_start, target_rate, frames
                    )
                    source_aligned = _aligned(
                        job["item"],
                        partner["item"],
                        np.asarray(source_audio).mean(axis=0),
                        target_rate,
                        frames,
                    )
                    solo_source = _mask_samples(
                        partner["item"], theirs, program_start, target_rate, frames
                    )
                    _, info = db.remove(
                        target_audio[0].astype(np.float64),
                        source_aligned,
                        target_rate,
                        solo_source,
                        solo_target,
                    )
                    item_info = {
                        "target": job["speaker"],
                        "source": partner["speaker"],
                        "reduction_db": round(float(info.get("reduction_db", 0.0)), 2),
                        "kept": round(float(info.get("kept", 1.0)), 4),
                        "reason": info.get("reason", ""),
                    }
                    out["debleed"].append(item_info)
                except Exception as exc:
                    _log(
                        f"debleed-arvio epäonnistui välillä {job['speaker']} <- {partner['speaker']}: {exc}"
                    )

    out["ready"] = True
    return out


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
    """Käsittelee yhden tiedoston. Kirjastossa: ``speechmix.stems.process_stem``.

    Sovellukselle jää kaksi asiaa: kameran äänen purku luettavaksi
    (``ensure_readable``) ja leima, josta ``is_fresh`` tunnistaa ajan tasalla
    olevan tuloksen.
    """
    (job,) = _with_tracks([job])
    gain = stems.process_stem(
        job, settings, plugin, program_start, stage, trim_db, solos,
        _with_tracks(partners or []), result, speaking, readable=ensure_readable,
    )
    write_stamp(job, settings)
    return gain


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
    return envelopes.mask_samples(track_of(item), mask, program_start, rate, frames)


def _aligned(target_item, source_item, source_audio, rate: int, frames: int):
    """Lähdemikin ääni kohdetiedoston näytepaikoille.

    Siirto on kirjastossa, koska se on jaksogeometriaa eikä FCPXML:ää — ja
    koska automixer vähentää saman vuodon omista wav-raidoistaan.
    """
    return timeline_lib.aligned(
        track_of(target_item), track_of(source_item), source_audio, rate, frames
    )


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
        # Masterointitaso on silti tehtävä. Se ei ole tiedostojen käsittelyä vaan
        # katon yhteydessä tehtävä nosto, ja tästä palaaminen tarkoittaisi
        # että tason muuttaminen ei tee **mitään** kun stemit ovat ajan
        # tasalla: säädin liikkuu, lokiin ei tule mitään, ääni ei muutu.
        if delivery_lufs(settings) and grid is not None:
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
    # Tasonkuljettaja lukee samaa ruudukkoa kolmatta kertaa itsenäisesti
    # (ks. speechmix.chain.apply: ``if speaking is not None and
    # settings.rider: ride(...)``), eikä se ollut koskaan raportoinut
    # puuttuvasta ruudukosta mitään — sama «asetus päällä, tuloksessa ei
    # mitään» kuin debleedillä ja vaimennuksella, vain hiljaisempi koska
    # kukaan ei ole aiemmin kysynyt siitä.
    if settings.rider and grid is None:
        result.errors["rider"] = t("audio.rider_no_grid")
        _log(result.errors["rider"])
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
        # Luettavana: kuka laskettiin ja miksi, ei sanakirjaa.
        lowered = ", ".join(f"{os.path.splitext(k)[0]} {v:+.2f} dB"
                            for k, v in extra.items() if v)
        _log(f"puhujien tasapaino: {lowered} (toinen mikki joutui "
             f"laskemaan tasoaan rajoittimen takia, sama lasku muille)")
    # Masterointitaso mitataan **vaimennetusta summasta**, koska se on ohjelma
    # jonka isäntä soittaa. Stemin oma tavoite jää siksi ennalleen: se on
    # tason lähtökohta, tämä on masteroinnin luku, eivätkä ne ole sama asia.
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
    """Tiedostot, yksi tai kaksi kerrallaan (``stems.parallel_count``).
    Erillään, jotta liitännäisvaranto suljetaan myös silloin kun jokin
    kaatuu kesken."""
    import threading

    # Kumppanit ovat *kaikki* mikkityöt, eivät vain tehtävälistan: vuoto
    # tulee toisesta mikistä riippumatta siitä onko se jo käsitelty.
    # Lähteeksi luetaan aina raaka tiedosto.
    def partners_of(job):
        return [
            other
            for other in jobs
            if other.get("speech")
            and other.get("speaker")
            and other["speaker"] != job.get("speaker")
            and os.path.exists(other["source"])
        ]

    workers = 1
    if len(todo) > 1:
        # Kameran ääni puretaan nyt, pääsäikeessä: rinnakkain kaksi stemiä
        # purkaisi saman kumppanin samaan väliaikaistiedostoon.
        try:
            readable = {job["source"]: ensure_readable(job["source"])
                        for job in [*todo, *jobs] if os.path.exists(job["source"])}
            workers = stems.parallel_count(
                [stems.stem_size(readable.get(job["source"], job["source"]))
                 for job in todo],
                report=_log,
            )
        except MixError as exc:
            _log(f"purku ennen käsittelyä epäonnistui, yksi kerrallaan: {exc}")

    # Palkki: valmiiden paino ja keskeneräisten osuudet yhteen. Jokaisen
    # tiedoston osuus vain kasvaa, joten summakin kasvaa — myös kun kaksi
    # tiedostoa etenee yhtä aikaa.
    lock = threading.Lock()
    shares: dict = {}
    finished = {"weight": 0.0, "count": 0}

    def report(job, name: str) -> None:
        if progress is None:
            return
        fraction = (finished["weight"] + sum(
            item["weight"] * share for item, share in shares.values()
        )) / total_weight
        progress(
            {
                "done": finished["count"],
                "total": len(todo),
                "current": job["name"],
                "stage": name,
                "fraction": round(min(fraction, 1.0), 4),
                "eta": _eta(started, fraction),
            }
        )

    def work(job):
        index = todo.index(job)
        _log(f"{index + 1}/{len(todo)} {job['name']}")
        # Kello tiedostoittain: vaiheen kesto on tämän tiedoston vaiheen
        # kesto, ei kulunut aika koko ajon alusta.
        stage_at = [time.perf_counter()]
        who = f"{job['name']}: " if workers > 1 else ""

        def stage(name: str, share: float) -> None:
            """Yhden vaiheen valmistuminen: lokiin ja edistymiseen."""
            now = time.perf_counter()
            _log(f"    {who}{name} {now - stage_at[0]:.1f}s")
            stage_at[0] = now
            with lock:
                shares[job["key"]] = (job, max(share, shares.get(job["key"], (job, 0.0))[1]))
                report(job, name)

        with lock:
            shares[job["key"]] = (job, 0.0)
            report(job, "read")
        return _run_one(
            job, settings, plugin, program_start, stage, trim,
            solos, partners_of(job), result, speaking,
        )

    expected = (MixError, ChainError, OSError, RuntimeError, ValueError)
    for job, gain, error in stems.run_parallel(todo, work, workers):
        with lock:
            shares.pop(job["key"], None)
            finished["weight"] += job["weight"]
            finished["count"] += 1
        if error is not None:
            if not isinstance(error, expected):
                raise error
            result.errors[job["key"]] = str(error)
            _log(f"    VIRHE {job['name']}: {error}")
            continue
        result.gains[job["key"]] = gain
        _log(f"    valmis {job['name']} {gain:+.1f} dB")
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
