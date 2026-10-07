"""Ohjelma stemeistä levyllä: katto, masterointi ja trimmi paloittain.

Siirretty autoraffkatin ``audio/mix.py``:stä, ei kopioitu. Siellä nämä
toimivat 64 minuutin jaksoilla, koska koko ohjelma ei ole koskaan muistissa:
jokainen stemi on oma tiedostonsa, ja ohjelman tason vaiheet virtaavat
niiden läpi minuutin paloissa. automixer piti koko jakson muistissa ja
masteroi summan kokonaisena; 47 minuutin jakso tarvitsi sillä tavalla
~40 GB eikä mahtunut 32 GB:n koneeseen (vst s13e03, 2026-10-06).

Työ on sanakirja (``job``), jonka avaimet tämä moduuli lukee:

* ``key`` — tunniste muistiinpanoille ja tasapainolle
* ``track`` — ``timeline.Track``: missä tiedosto on aikajanalla. Isäntä
  muuntaa oman istuntoformaattinsa tähän (autoraffkatissa ``track_of``).
* ``target`` — käsitelty stemi levyllä; katto kirjoittaa sen paikalleen
* ``source`` — raaka tiedosto (trimmi mittaa sen)
* ``speaker``, ``speech``, ``bit_depth``
* ``programme`` — kuuluuko stemi summaan vaikka ei olisi puhetta
  (automixerin musiikki). Oletuksena vain puhe kuuluu, kuten autoraffkatissa
  jossa Final Cut soittaa tilaäänen omalla tasollaan.

Tulos (``result``) on mikä tahansa olio jolla on ``notes`` (dict) ja
``program_*``-kentät; ``StemResult`` on kirjaston oma.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from dataclasses import dataclass, field

import numpy as np

from . import chain, envelopes, log, programme
from .binaries import get_binary_path
from .messages import t
from .meter import BLOCK_SEC, OVERLAP, IntegratedMeter

#: Kuinka monta kierrosta masterointitasoa haetaan. Rajoitin vie osan noston
#: tuomasta äänekkyydestä, joten yksi kierros jää aina alle — mutta ero
#: pienenee kertaluokan kierrosta kohden, joten kolme riittää.
DELIVER_ROUNDS = 3
#: Oletustoleranssi jos asetuksissa ei ole omaa, LU.
DELIVER_TOLERANCE = 0.5
#: Kuinka kaukana tavoitteesta jakso lasketaan «hiljaiseksi», LU. Tätä
#: lähempänä olevaan ei kosketa: nosto on tarkoitettu ohjelman pohjalle eikä
#: sen tavalliselle tasolle, ja liian korkea lattia litistäisi kaiken.
LIFT_WINDOW_LU = 8.0

# Formaatit jotka luetaan suoraan. Muut puretaan ffmpegillä: kameran ääni on
# mp4:n sisällä, eikä pedalboardin lukija avaa sitä.
READABLE = {
    ".wav", ".wave", ".aif", ".aiff", ".aifc", ".flac", ".w64", ".caf",
    ".ogg", ".mp3",
}


@dataclass
class StemResult:
    """Ohjelman tason vaiheiden tulos. Isännällä voi olla omansa samoilla
    kentillä (autoraffkatin ``MixResult``)."""

    notes: dict[str, list] = field(default_factory=dict)
    gains: dict[str, float] = field(default_factory=dict)
    backoffs: dict[str, float] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    program_trim: float = 0.0
    program_boost: float = 0.0
    program_lufs: float = 0.0
    program_range: float = 0.0
    program_short_term_max: float = 0.0
    program_momentary_max: float = 0.0
    program_limit_cost: float = 0.0


def _log(message: str) -> None:
    """Käsittelyn kulku terminaaliin, kuten autoraffkatin oma loki."""
    print(f"[ääni] {message}", flush=True)


def frame_count(path: str) -> int | None:
    """Äänen näytemäärä ffprobella, tai ``None`` jos ei selviä."""
    try:
        ffprobe_bin = get_binary_path("ffprobe")
        done = subprocess.run(
            [
                ffprobe_bin, "-v", "error", "-select_streams", "a:0",
                "-show_entries",
                "stream=duration_ts,nb_samples,sample_rate,duration",
                "-of", "json", path,
            ],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
        )
        streams = json.loads(done.stdout or "{}").get("streams") or []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError,
            FileNotFoundError):
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


def _in_programme(job: dict) -> bool:
    return bool(job.get("speech") or job.get("programme"))


def anyone_speaking(grid, program_start: float):
    """``(maski, ohjelman alku)`` puheportille, tai ``None``.

    Kuka tahansa käy: portin tehtävä on erottaa puhe muusta, ei puhujia
    toisistaan. Ruudukko on aikajanan aikaa, ja ``envelopes.mask_samples``
    muuntaa sen tiedoston näytteiksi kun ryhmä on tiedossa.
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


def delivery_lufs(settings) -> float:
    """Ohjelman masterointitaso, LUFS. Nolla = ei masterointia.

    Oma luku voittaa; muuten sama kuin käyttöliittymän tavoite, koska se
    **on** ohjelman taso (YouTube -14, suoratoisto -16). Ilman tätä vartijan
    peruutus jätti ohjelman -19,4:ään ja tavoite näytti täyttyneen.
    """
    own = float(getattr(settings, "program_lufs", 0.0) or 0.0)
    if own:
        return own
    if getattr(settings, "program_target", True):
        return float(getattr(settings, "target_lufs", 0.0) or 0.0)
    return 0.0


def program_deliver(jobs: list[dict], result, ducks: dict, extra: dict,
                    settings, speech=None, layout=None) -> None:
    """Ohjelma masterointitasoon: mittaa, nosta, rajoita, mittaa uudestaan.

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
    target = delivery_lufs(settings)
    if not target:
        program_ceiling(jobs, result, ducks, extra, layout=layout)
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
        with log.step(f"mastering pass ({'write' if write else 'measure'}, "
                      f"lift {gain:+.2f} dB)"):
            program_ceiling(jobs, result, ducks, extra, gain, ceiling, played,
                            curve, step_sec if curve is not None else 0.0,
                            not write, plain, speech, layout=layout)
        gate = played.speech() > 0.5 if speech is not None else None
        after, before = played.value(keep=gate), plain.value(keep=gate)
        cost = 0.0 if (after is None or before is None) else before - after
        return after, played, cost

    measured, meter, cost = run(0.0, None)
    if measured is None:
        # Ei yhtään mitattavaa stemiä: sanotaan se. Ennen loki kirjoitti
        # «masterointi: 0.0 LUFS» ja ohjelma jäi masteroimatta hiljaa.
        _log("masterointi ohitettu: yhtään stemiä ei voitu mitata")
        for job in jobs:
            result.notes.setdefault(job["key"], []).append(t("audio.program_none"))
            break
        return
    step_sec = meter.step_seconds()
    boost, ride = 0.0, None

    # Pohja ylös **ensin**, ei viimeisenä keinona. Nosto tuo äänekkyyttä
    # koskematta huippuihin, joten jokainen desibeli joka saadaan täältä on
    # desibeli jota tasainen nosto ei tarvitse — ja siis rajoitusta joka jää
    # tekemättä. Jälkikäteen tehtynä se ei ehtisi vaikuttaa mihinkään:
    # silmukka on jo ostanut saman äänekkyyden katosta.
    if lift_db > 0 and measured is not None:
        rise = programme.short_term_lift(
            meter.short_term(), target - LIFT_WINDOW_LU, step_sec, lift_db
        )
        if rise.any():
            ride = rise
            measured, meter, cost = run(0.0, ride)
            _log(f"pohjan nosto {rise.max():.2f} dB hiljaisiin jaksoihin "
                 f"-> {measured:.2f} LUFS")
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
            break
        _log(f"masterointi kierros {round_number + 1}: nosto {boost:+.2f} dB"
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
    _log(f"masterointi: {result.program_lufs:.1f} LUFS · LRA {result.program_range:.1f} "
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


def program_ceiling(jobs: list[dict], result,
                    envelopes_by_speaker: dict | None = None,
                    extra: dict | None = None,
                    boost_db: float = 0.0,
                    ceiling_db: float = chain.CEILING_DB,
                    meter=None,
                    ride_db=None,
                    ride_step: float = 0.0,
                    dry_run: bool = False,
                    raw_meter=None,
                    speech=None,
                    layout=None) -> None:
    """Huippukatto **ohjelmalle**, ei yhdelle stemille.

    ``layout(jäsenet, palat)`` kertoo miten stemit soivat isännän ulostulossa
    (``(kanavat, n)``), jotta mittari mittaa sen eikä stemien summaa.
    autoraffkatilla sitä ei ole: Final Cut soittaa stemit, ja mittari
    mittaa summan monona kuten ennenkin. automixer kirjoittaa stereon
    itse, panoroituna ja stereomusiikin kanssa.

    Sama virhe kuin äänekkyydessä, jonka ``program_trim`` jo korjaa: ketju
    takaa katon jokaiselle tiedostolle erikseen, mutta isäntä soittaa
    niiden summan. Kaksi stemiä joiden huiput on molemmat painettu
    -1,5 dBTP:hen ylittävät täyden asteikon aina kun huiput osuvat samaan
    hetkeen — teoriassa +4,5 dB, ja oikealla jaksolla mitattuna **+4,51
    dBFS, 200 ylityspursketta minuutissa**, mediaanipituus 0,23 ms.

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

    members_all = [
        job
        for job in jobs
        if _in_programme(job)
        and job.get("track") is not None
        and os.path.exists(job.get("target", ""))
    ]
    # Yksin oleva stemi *on* ohjelma, ja ketjun oma katto riittää sille —
    # paitsi masteroinnissa: siellä se nostetaan, ja nosto tarvitsee katon
    # ja mittauksen. Ennen yksittäinen mikki jäi masteroimatta kokonaan.
    alone_ok = meter is not None
    if not members_all or (len(members_all) < 2 and not alone_ok):
        return

    from . import timeline as timeline_lib

    # Ryhmät: stemit jotka soivat aikajanalla yhtä aikaa. Ennen ryhmä oli
    # «sama sijainti ja sama pituus», ja eri tallentimien mikit (eri pituus)
    # jäivät kukin yksin: ei kattoa, ei mittausta, ja masterointi kirjoitti
    # «0.0 LUFS» sanomatta mitään (pp 56, 2026-10-07).
    parent = list(range(len(members_all)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(members_all)):
        for j in range(i + 1, len(members_all)):
            if timeline_lib.overlaps(members_all[i]["track"], members_all[j]["track"]):
                parent[root(i)] = root(j)
    components: dict[int, list] = {}
    for i, job in enumerate(members_all):
        components.setdefault(root(i), []).append(job)

    for members in components.values():
        if len(members) < 2 and not alone_ok:
            # Yksin aikajanan palassa: ei summaa johon osua.
            continue
        frames = [frame_count(job["target"]) for job in members]
        if any(f is None for f in frames):
            continue
        shapes = {envelopes.geometry(job["track"], f) for job, f in zip(members, frames, strict=True)}
        try:
            if len(shapes) == 1:
                worst = _ceiling_pass(
                    members, frames[0], AudioFile, envelopes_by_speaker, extra,
                    boost_db, ceiling_db, meter, ride_db, ride_step, dry_run,
                    raw_meter, speech, layout,
                )
            else:
                worst = _ceiling_pass_timeline(
                    members, AudioFile, envelopes_by_speaker, extra,
                    boost_db, ceiling_db, meter, ride_db, ride_step, dry_run,
                    raw_meter, speech, layout,
                )
        except (OSError, ValueError) as exc:
            for job in members:
                result.notes.setdefault(job["key"], []).append(str(exc))
            _log(f"ohjelmakatto ohitettiin: {exc}")
            continue
        if worst < -0.01:
            _log(f"ohjelmakatto: {len(members)} stemiä, suurin vaimennus "
                 f"{worst:.2f} dB")


def _programme_block(job, handle, low: int, high: int, rate: int) -> np.ndarray:
    """Stemin ääni aikajanan näyteväliltä ``[low, high)``; nollaa muualla."""
    block = np.zeros((int(handle.num_channels), high - low), dtype=np.float32)
    for span in job["track"].spans:
        p0 = max(low, int(round(span.programme_start * rate)))
        p1 = min(high, int(round(span.programme_end * rate)))
        if p1 <= p0:
            continue
        f0 = int(round(span.to_file_time(p0 / rate) * rate))
        if f0 >= handle.frames:
            continue
        count = min(p1 - p0, handle.frames - max(f0, 0))
        if f0 < 0:
            p0 -= f0
            count += f0
            f0 = 0
        if count <= 0:
            continue
        handle.seek(f0)
        piece = handle.read(count)
        block[:, p0 - low:p0 - low + piece.shape[-1]] = piece
    return block


def _ceiling_pass_timeline(members: list[dict], AudioFile,
                           envelopes_by_speaker: dict | None = None,
                           extra: dict | None = None,
                           boost_db: float = 0.0,
                           ceiling_db: float = chain.CEILING_DB,
                           meter=None,
                           ride_db=None,
                           ride_step: float = 0.0,
                           dry_run: bool = False,
                           raw_meter=None,
                           speech=None,
                           layout=None) -> float:
    """Ryhmä jonka stemit ovat eri kohdissa tai eri mittaisia: summa
    **aikajanalla**.

    Kaksi vaihetta. Ensin aikajana paloittain: jokaisen stemin osuus
    luetaan aikajanan paikalleen, käyrä lasketaan summasta ja mittari saa
    summan — kuten ``_ceiling_pass``issa. Käyrästä talletetaan vain kohdat
    joissa se on alle ykkösen. Sitten, jos kirjoitetaan, jokainen stemi
    omassa tiedostoajassaan: käyrä luetaan sen aikajanan paikoilta.
    """
    handles = [AudioFile(job["target"]) for job in members]
    stored: list[tuple[int, np.ndarray]] = []
    worst = 0.0
    try:
        rate = int(handles[0].samplerate)
        if any(int(h.samplerate) != rate for h in handles):
            raise ValueError("stemien näytetaajuudet eroavat")
        first = min(int(round(s.programme_start * rate))
                    for job in members for s in job["track"].spans)
        last = max(int(round(s.programme_end * rate))
                   for job in members for s in job["track"].spans)
        chunk = int(programme.CEILING_CHUNK * rate)
        margin = int(programme.CEILING_MARGIN * rate)
        position = first
        while position < last:
            low = max(first, position - margin)
            high = min(last, position + chunk + margin)
            blocks = [
                _programme_block(job, h, low, high, rate)
                * _linear((extra or {}).get(job["key"], 0.0) + boost_db)
                for job, h in zip(members, handles, strict=True)
            ]
            times = np.arange(low, high) / rate
            if ride_db is not None and ride_step > 0:
                curve = np.interp(times / ride_step, np.arange(len(ride_db)), ride_db)
                blocks[-1] = blocks[-1] * (10.0 ** (curve / 20.0)).astype(np.float32)
            heard = []
            for job, block in zip(members, blocks, strict=True):
                points = (envelopes_by_speaker or {}).get(job.get("speaker"))
                if points:
                    db = np.interp(times, [t for t, _ in points], [v for _, v in points])
                    block = block * (10.0 ** (db / 20.0)).astype(np.float32)
                heard.append(block)
            gain = programme.shared_gain(heard, rate, ceiling_db)
            worst = min(worst, programme.reduction_db(gain))
            head = position - low
            tail = head + min(chunk, last - position)
            spoken = None
            if speech is not None:
                mask, start = speech
                index = ((times[head:tail] - start) / grid_hop()).astype(int)
                inside = (index >= 0) & (index < len(mask))
                spoken = np.zeros(tail - head, dtype=bool)
                spoken[inside] = np.asarray(mask, dtype=bool)[index[inside]]
            if meter is not None:
                meter.add(_heard(members, [h * gain for h in heard], layout, head, tail),
                          spoken)
            if raw_meter is not None:
                raw_meter.add(_heard(members, heard, layout, head, tail))
            below = np.flatnonzero(gain[head:tail] < 1.0)
            if not dry_run and below.size:
                a, b = head + below[0], head + below[-1] + 1
                stored.append((low + a, gain[a:b].astype(np.float32)))
            position += chunk
        if dry_run:
            return worst
        for job, handle in zip(members, handles, strict=True):
            _write_with_gain(job, handle, rate, stored,
                             _linear((extra or {}).get(job["key"], 0.0) + boost_db))
    finally:
        for handle in handles:
            handle.close()
    for job in members:
        os.replace(job["target"] + ".ceil.tmp.wav", job["target"])
    return worst


def grid_hop() -> float:
    from .grid import HOP_SEC

    return HOP_SEC


def _write_with_gain(job, handle, rate: int, stored, scale: float) -> None:
    """Stemi omassa tiedostoajassaan: ``scale`` ja käyrä aikajanan paikoilta."""
    from pedalboard.io import AudioFile

    tmp = job["target"] + ".ceil.tmp.wav"
    frames = handle.frames
    step = int(programme.CEILING_CHUNK * rate)
    with AudioFile(tmp, "w", rate, int(handle.num_channels),
                   bit_depth=job.get("bit_depth", 24)) as out:
        handle.seek(0)
        position = 0
        while position < frames:
            count = min(step, frames - position)
            block = handle.read(count) * scale
            gain = np.ones(count, dtype=np.float32)
            for span in job["track"].spans:
                f0 = max(position, int(round(span.file_offset * rate)))
                f1 = min(position + count,
                         int(round(span.to_file_time(span.programme_end) * rate)))
                if f1 <= f0:
                    continue
                p0 = int(round(span.programme_start * rate)) + (
                    f0 - int(round(span.file_offset * rate)))
                p1 = p0 + (f1 - f0)
                for start, curve in stored:
                    a, b = max(p0, start), min(p1, start + len(curve))
                    if b <= a:
                        continue
                    gain[f0 - position + (a - p0):f0 - position + (b - p0)] = \
                        curve[a - start:b - start]
            out.write(np.ascontiguousarray(block * gain))
            position += count
    written = frame_count(tmp)
    if written != frames:
        _drop(tmp)
        raise ValueError(f"ohjelmakatto muutti pituutta {frames} -> {written}")


def _ceiling_pass(members: list[dict], frames: int, AudioFile,
                  envelopes_by_speaker: dict | None = None,
                  extra: dict | None = None,
                  boost_db: float = 0.0,
                  ceiling_db: float = chain.CEILING_DB,
                  meter=None,
                  ride_db=None,
                  ride_step: float = 0.0,
                  dry_run: bool = False,
                  raw_meter=None,
                  speech=None,
                  layout=None) -> float:
    """Yksi ryhmä: summa paloittain, sama käyrä jokaiseen stemiin.

    ``envelopes_by_speaker`` on vaimennus puhujittain aikajanan aikana. Se
    **on** otettava mukaan summaan, koska vaimennusta ei polteta tiedostoon:
    ilman sitä summa olisi ohjelma jota isäntä ei koskaan soita, ja katto
    laskettaisiin liian kovasta signaalista.

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
        if speech is not None:
            # Kerran ryhmää kohden: maski on ruudukon aikaa, mittari haluaa
            # sen näytteinä ja palan mukana.
            spoken = envelopes.mask_samples(members[0]["track"], speech[0],
                                            speech[1], rate, frames)
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
                    # Masterointitason nosto on jokaiselle sama, ja se tehdään
                    # **ennen** jaettua käyrää: silloin rajoitus osuu vain
                    # sinne missä huiput osuvat yhteen, eikä yksikään stemi
                    # maksa crestiä toisen puolesta.
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
                    block * envelope_block(job, envelopes_by_speaker, low, high, rate)
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
                    meter.add(_heard(members, [h * gain for h in heard], layout,
                                     head, tail),
                              None if spoken is None
                              else spoken[low + head:low + tail])
                if raw_meter is not None:
                    raw_meter.add(_heard(members, heard, layout, head, tail))
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


def _heard(members, blocks, layout, head: int, tail: int) -> np.ndarray:
    """Mitä mittari kuulee palasta: isännän ulostulo tai stemien summa monona."""
    if layout is not None:
        return np.asarray(layout(members, blocks))[..., head:tail]
    played = sum(blocks)
    return (played[..., head:tail].mean(axis=0)
            if played.ndim > 1 else played[head:tail])


def _linear(db: float) -> float:
    """Desibelit kertoimeksi. Nolla on ykkönen eikä pyöristysvirhe."""
    return 1.0 if not db else float(10.0 ** (float(db) / 20.0))


def envelope_block(job: dict, envelopes_by_speaker: dict | None, low: int,
                   high: int, rate: int) -> np.ndarray:
    """Vaimennuksen kerroin tiedoston näyteväliltä ``[low, high)``.

    Ykkösiä silloin kun puhujalle ei ole käyrää: silloin summaan menee
    tiedosto sellaisenaan.
    """
    points = (envelopes_by_speaker or {}).get(job.get("speaker"))
    track = job.get("track")
    if not points or track is None:
        return np.ones(1, dtype=np.float32)
    return envelopes.duck_gain(track, points, low, high, rate)


def _drop(path: str) -> None:
    """Poistaa tilapäistiedoston, jos se on olemassa."""
    with contextlib.suppress(OSError):
        os.remove(path)


def _track_span(track) -> float:
    """Raidan kokonaiskesto aikajanalla, ikkunan ankkurin valintaan."""
    return sum(span.duration for span in track.spans)


def program_trim(jobs: list[dict], target_lufs: float) -> float:
    """Kuinka paljon mikkien summa on tavoitteen yli, desibeleinä (≤ 0).

    Tavoitetaso on **ohjelman** taso, ei yhden stemin. Kaksi -14 LUFS:n
    mikkiä ei summaudu -14:ään: oikealla aineistolla mitattu summa oli -12,3.
    Ero ei ole 3 dB (silloin molemmat puhuisivat koko ajan) eikä 0 dB
    (silloin toinen mikki olisi täysin hiljaa toisen puhuessa), joten se
    mitataan eikä arvata.

    Mitataan raa'asta äänestä ennen käsittelyä ja rajatusta ikkunasta.
    Ikkuna on aikajanan aikaa, koska summa on aikajanalla.
    """
    from pedalboard.io import AudioFile

    mics = [
        job
        for job in jobs
        if job.get("speech")
        and job.get("track") is not None
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
    anchor = max((job["track"] for job in mics), key=_track_span)
    low = min((s.programme_start for s in anchor.spans), default=0.0)
    high = max((s.programme_end for s in anchor.spans), default=0.0)
    span = min(programme.PROGRAM_WINDOW, high - low)
    if span <= 1.0:
        return 0.0
    middle = (low + high) / 2
    window = (middle - span / 2, middle + span / 2)

    rate = 0
    voices = 0
    total: np.ndarray | None = None
    for job in mics:
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
            for placed in job["track"].spans:
                first = max(window[0], placed.programme_start)
                last = min(window[1], placed.programme_end)
                if last <= first:
                    continue
                start = int(round(placed.to_file_time(first) * rate))
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
        contribution = programme.at_target(here, rate, target_lufs)
        if contribution is None:
            continue
        total += contribution
        voices += 1

    if voices < 2 or total is None:
        return 0.0
    trim = programme.trim_to_target(total, rate, target_lufs)
    _log(f"ohjelmatrimmi {trim:+.2f} dB")
    return trim


# ------------------------------------------------------------------ yksi stemi

#: Suurin sallittu siirtymä. Yksi millisekunti on jo kuultavissa kammalla,
#: jos tilaääni ja mikki soivat päällekkäin.
MAX_LAG_MS = 1.0

# Tiedoston työ vaiheittain: luku ja kirjoitus ovat gigatavun tiedostolla
# oikeaa aikaa, ketju on loput. Ketjun sisäinen jako on ``chain.STAGES_*``.
READ_SHARE = 0.07
DEBLEED_SHARE = 0.05
CHAIN_SHARE = 0.81
WRITE_SHARE = 0.07


class StemError(Exception):
    """Stemiä ei voitu käsitellä. Viesti on valmiiksi käännetty."""


def debleed(job, audio, rate, program_start, solos, partners, result,
            readable=None) -> None:
    """Vähentää muiden mikkien vuodon ``audio``:sta paikan päällä.

    Yksi lähde kerrallaan ja aina tuoreimmasta tuloksesta: kun kolmas
    puhuja vuotaa kahteen muuhun, ensimmäisen vähennyksen jälkeen jäljellä
    oleva ei ole enää sama signaali kuin alussa.

    Epäonnistuminen ei ole hiljainen. Jos vähennystä ei tehty, syy menee
    lokiin ja tulokseen — asetus päällä ja lopputuloksessa ei mitään on
    juuri se vika joka tässä projektissa on jo kerran jäänyt huomaamatta.
    """
    from pedalboard.io import AudioFile

    from . import debleed as db
    from . import timeline as timeline_lib

    readable = readable or (lambda path: path)
    mine = (solos or {}).get(job.get("speaker"))
    if mine is None:
        return
    frames = audio.shape[1]
    solo_target = envelopes.mask_samples(job["track"], mine, program_start, rate, frames)
    target = audio[0].astype(np.float64)
    for partner in partners:
        theirs = (solos or {}).get(partner.get("speaker"))
        if theirs is None:
            continue
        if partner.get("track") is None or not timeline_lib.overlaps(
            job["track"], partner["track"]
        ):
            continue          # eri osa: ei yhtään yhteistä hetkeä
        try:
            with AudioFile(readable(partner["source"])) as handle:
                if handle.samplerate != rate:
                    _log(f"    vuoto {partner['speaker']}: eri näytetaajuus, ohitetaan")
                    continue
                other = handle.read(handle.frames)
        except (OSError, RuntimeError) as exc:
            _log(f"    vuoto {partner['speaker']}: {exc}")
            continue
        source = timeline_lib.aligned(
            job["track"], partner["track"], np.asarray(other).mean(axis=0), rate, frames
        )
        solo_source = envelopes.mask_samples(
            partner["track"], theirs, program_start, rate, frames
        )
        with log.step(f"debleed ← {partner['speaker']}: path + subtract"):
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


def process_stem(
    job: dict,
    settings,
    plugin,
    program_start: float = 0.0,
    stage=None,
    trim_db: float = 0.0,
    solos: dict | None = None,
    partners: list | None = None,
    result=None,
    speaking: dict | None = None,
    readable=None,
) -> float:
    """Käsittelee yhden tiedoston stemiksi levylle. Palauttaa normalisoinnin noston.

    Yksi tiedosto kerrallaan, ja tulos levylle: muistissa on kerralla vain
    tämän tiedoston ketju, ei koko ohjelmaa. ``readable(polku)`` on isännän
    keino muuntaa tiedosto luettavaksi (autoraffkat purkaa mp4:n äänen).

    ``stage(nimi, osuus)`` kertoo missä kohtaa tätä tiedostoa mennään.
    Liitännäinen on kallein vaihe eikä kerro itsestään mitään kesken ajon,
    joten vaiheen tarkkuus on se mitä edistymisestä on saatavissa — ja se
    riittää siihen, ettei palkki seiso tunnin tiedoston ajan paikallaan.
    """
    from pedalboard.io import AudioFile

    readable = readable or (lambda path: path)

    def report(name: str, share: float) -> None:
        if stage is not None:
            stage(name, share)

    with AudioFile(readable(job["source"])) as handle:
        audio = handle.read(handle.frames)
        rate = handle.samplerate
    report("read", READ_SHARE)
    if audio.shape[1] == 0:
        raise StemError(t("audio.empty_file", name=os.path.basename(job["source"])))
    if job.get("mono") and audio.shape[0] > 1:
        audio = audio.mean(axis=0, keepdims=True)

    # Ristivuoto pois ennen liitännäistä. Järjestys ei ole makuasia:
    # liitännäinen on generatiivinen eikä säilytä raitojen välistä
    # lineaarista suhdetta, ja sen jälkeen vuotoa ei enää voi vähentää
    # millään suotimella.
    if getattr(settings, "debleed", False) and job.get("speech", True) and partners:
        debleed(job, audio, rate, program_start, solos, partners, result, readable)
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
    if mine is not None and job.get("track") is not None and job.get("speech"):
        block = max(1, int(chain.RIDER_BLOCK_S * rate))
        own = envelopes.speech_blocks(job["track"], mine, program_start, rate,
                                      block, audio.shape[1] // block)

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
    report("duck", READ_SHARE + DEBLEED_SHARE + CHAIN_SHARE)

    # Ketjun tiivistys kirjataan muistiinpanoksi. Tiedosto on kelvollinen ja
    # oikean mittainen, ja se että rajoitin vei siitä viisitoista desibeliä
    # crestiä selviää muuten vain kuuntelemalla. Ks. `chain.LIMITER_BUDGET_DB`.
    who = os.path.basename(job["source"])
    if result is not None:
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
        raise StemError(
            t("audio.plugin_shifted", samples=info.lag, ms=info.lag / rate * 1000,
              name=who)
        )

    # Alkuperäiseen ei kosketa. Tarkistus on kirjoituskohdassa, koska kohteen
    # laskeminen on isännällä ja yksi virhe siellä olisi peruuttamaton.
    if os.path.abspath(job["target"]) == os.path.abspath(job["source"]):
        raise StemError(t("audio.would_overwrite", name=who))

    tmp = job["target"] + ".tmp.wav"
    with AudioFile(
        tmp, "w", rate, audio.shape[0], bit_depth=job.get("bit_depth", 24)
    ) as out:
        out.write(np.ascontiguousarray(audio))
    written = frame_count(tmp)
    if written is not None and written != info.frames:
        os.remove(tmp)
        raise StemError(
            t("audio.written_length", before=info.frames, after=written, name=who)
        )
    os.replace(tmp, job["target"])
    report("write", READ_SHARE + DEBLEED_SHARE + CHAIN_SHARE + WRITE_SHARE)
    if result is not None:
        result.backoffs[job["key"]] = info.backed_off_db
    return info.gain_db


# ------------------------------------------------------------------ summa


class Stopped(Exception):
    """Summaus keskeytettiin."""


@dataclass
class Source:
    """Yksi äänitiedosto ohjelmassa.

    ``placements`` on ``(aikajanan alku, aikajanan loppu, tiedoston alku)``
    sekunteina. ``duck`` on vaimennus- ja häivytyskäyrä aikajanan aikaa
    (``(t, dB)``), ``pan`` -100…100 ja ``gain_db`` kiinteä taso.
    ``stereo``: kaksikanavainen lähde soi omina kanavinaan (musiikki); muuten
    se lasketaan monoksi kuten mikki.
    """

    path: str
    placements: list
    duck: list = None  # type: ignore[assignment]
    pan: float = 0.0
    gain_db: float = 0.0
    stereo: bool = False
    #: ``"balance"`` (Final Cut) tai ``"power"`` (vakioteho, keskellä −3 dB
    #: kumpaankin). Ks. ``pan_gains``.
    pan_law: str = "balance"


def pan_gains(pan: float, law: str = "balance") -> tuple[float, float]:
    """Monoraita stereoksi.

    ``balance``: keskellä täysi taso kumpaankin, sivussa toinen kanava
    hiljenee. Final Cutin monoklippi stereoprojektissa soi niin, ja
    autoraffkatin render toistaa Final Cutia.

    ``power``: vakioteho, keskellä −3 dB kumpaankin, joten stereon äänekkyys
    (BS.1770) on sama kuin monon. automixer tasaa musiikin puheen
    **mono**tasoon; täydellä tasolla keskitetty puhe nousi stereossa 3 dB
    ja pohja jäi +3,3…+4,9 dB:iin kun piti olla +7 (vst s13e03).
    """
    amount = max(-1.0, min(1.0, pan / 100.0))
    if law == "power":
        return float(np.sqrt(0.5 * (1.0 - amount))), float(np.sqrt(0.5 * (1.0 + amount)))
    return min(1.0, 1.0 - amount), min(1.0, 1.0 + amount)


def sum_to_file(sources: list[Source], program_start: float, seconds: float,
                out_path: str, rate: int = 48000, block: float = 60.0,
                progress=None, stop=None, stopped=Stopped) -> None:
    """Äänilähteet stereoksi minuutin paloissa, ohjelman pituisena.

    Paloittain, koska tunnin jakso kahdella mikillä olisi muistissa
    gigatavuja. Vaimennuskäyrä luetaan aikajanan ajassa kuten vienti sen
    kirjoittaa; tiedostojen taso on jo käsittelyn, joten muuta tasoa ei
    tehdä. ``stopped`` on poikkeus joka nostetaan kun ``stop`` on asetettu
    (autoraffkatin renderillä on omansa).
    """
    from pedalboard.io import AudioFile

    total = int(round(seconds * rate))
    step = int(block * rate)
    opened: dict = {}
    try:
        with AudioFile(out_path, "w", samplerate=rate, num_channels=2) as out:
            for first in range(0, total, step):
                if stop is not None and stop.is_set():
                    raise stopped()
                count = min(step, total - first)
                t0 = program_start + first / rate
                mix = np.zeros((2, count), dtype=np.float32)
                for source in sources:
                    left, right = pan_gains(source.pan, source.pan_law)
                    for start, end, file_start in source.placements:
                        low, high = max(start, t0), min(end, t0 + count / rate)
                        if high <= low:
                            continue
                        a = int(round((low - t0) * rate))
                        n = min(count - a, int(round((high - low) * rate)))
                        if n <= 0:
                            continue
                        handle = opened.get(source.path)
                        if handle is None:
                            handle = AudioFile(source.path).resampled_to(rate)
                            opened[source.path] = handle
                        handle.seek(int(round((file_start + low - start) * rate)))
                        chunk = np.atleast_2d(handle.read(n))
                        if source.stereo and chunk.shape[0] == 2:
                            pair = chunk[:, :n].astype(np.float32)
                        else:
                            mono = chunk.mean(axis=0)[:n].astype(np.float32)
                            pair = np.stack([mono, mono])
                        if pair.shape[1] < n:
                            pair = np.pad(pair, ((0, 0), (0, n - pair.shape[1])))
                        gain = 10 ** (source.gain_db / 20.0)
                        if source.duck:
                            times = low + np.arange(n) / rate
                            db = np.interp(times, [p[0] for p in source.duck],
                                           [p[1] for p in source.duck])
                            pair = pair * (10 ** (db / 20.0)).astype(np.float32)
                        mix[0, a:a + n] += pair[0] * gain * left
                        mix[1, a:a + n] += pair[1] * gain * right
                out.write(mix)
                if progress is not None:
                    progress(min(1.0, (first + count) / max(1, total)))
    finally:
        for handle in opened.values():
            handle.close()


# ------------------------------------------------------------------ ruudukko


@dataclass
class Lanes:
    """Puheruudukko siinä muodossa jota ``masks`` lukee: ``speakers``-lista."""

    speakers: list


def grid_from_files(named: dict[str, str], envelope=None) -> Lanes:
    """Puheruudukko aikajanan mittaisista stemitiedostoista, verhokäyristä.

    autoraffkatin tapa eikä ``grid.speech_grid``in: tasot luetaan
    välimuistiin tallennetuista verhokäyristä (``rms.envelope_for``, 20 ms
    HOP), eikä yhtäkään raitaa pidetä muistissa näytteinä. ``speech_grid``
    halusi kaikki raidat liukulukuina kerralla, ja 5 minuutin istunnolla se
    oli 1,5 GB:n huippu — 47 minuutissa ~14 GB.

    Päätös on ``grid.lane``: aktiivinen = oman pohjan yli
    ``grid.FLOOR_MARGIN_DB``; kuka on kovin päätetään maskeissa.
    """
    from . import grid as grid_lib

    if envelope is None:
        from .rms import envelope_for

        envelope = envelope_for
    lanes = []
    for name, path in named.items():
        db = np.asarray(envelope(path), dtype=np.float32)
        floor = grid_lib.noise_floor(grid_lib.smooth(db))
        lanes.append(grid_lib.lane(name, [(db, None, floor, grid_lib.FLOOR_MARGIN_DB, 0.0)]))
    return Lanes(speakers=lanes)
