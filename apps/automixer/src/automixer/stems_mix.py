"""Hindenburgin istunto miksaukseksi stemeinä levyllä.

Sama putki kuin autoraffkatissa (``speechmix.stems``): jokainen puheraita
käsitellään kerrallaan omaksi stemikseen levylle, ohjelman katto ja
masterointi virtaavat stemien läpi minuutin paloissa, ja lopullinen
stereotiedosto kootaan paloittain. Koko ohjelma ei ole muistissa
missään vaiheessa.

Syy: muistissa koottu miksaus tarvitsi 47 minuutin jaksolle ~40 GB eikä
mahtunut 32 GB:n koneeseen (vst s13e03, 2026-10-06). Mitattuna synteettisellä
istunnolla 0,6 GB minuutissa; autoraffkat käsittelee 64 minuutin jaksoja
samalla koneella tällä tavalla.

Musiikki ei kulje puheketjun läpi. ``session.load`` on jo sovittanut sen
tason ja kirjoittanut häivytykset, ja se kulkee katon ja masteroinnin läpi
samana stemien joukossa kuin puhe — summa on ohjelma, ja katto on summan.
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
from dataclasses import asdict
from types import SimpleNamespace

from speechmix import blocks, chain, envelopes, masks, panning, programme, stems
from speechmix.timeline import Span, Track

from . import session as hindenburg
from .domain import shared
from .domain.processor import SpeechSettings

#: Puhestemien taso ennen masterointia: sama viite kuin muistissa
#: miksatessa (``cli_mix.SPEECH_REFERENCE_LUFS``), jotta kynnykset ja
#: musiikin sovitus (``session.MUSIC_LUFS``) pysyvät samassa suhteessa.
SPEECH_REFERENCE_LUFS = hindenburg.MUSIC_LUFS


def _log(message: str) -> None:
    print(f"[automixer] {message}", flush=True)


def _duration(path: str) -> float:
    import soundfile as sf

    info = sf.info(path)
    return info.frames / info.samplerate


#: Musiikkipohjan kovin hetki (lyhytaikainen äänekkyys, 3 s) näin paljon
#: **käsitellyn** puheen äänekkyyden **yllä**. Käyttäjä 2026-10-09,
#: korvakuulolta: «+1 for now»; hänen oma master on noin +1,2 dB. Aiemmin
#: −1,0 (2026-10-07, «music at most −16 LUFS») ja +7 dB (Hindenburgin
#: istunnosta, käsittelemätöntä puhetta vasten), joka teki valmiissa
#: miksauksessa +7…+10. Tutkimus (Sound On Sound, Transom): selvästi soiva
#: musiikki puheen tasolle, koska musiikin huiput ovat kovemmat.
BED_UNDER_SPEECH_DB = 1.0
#: Sallittu väli lipulle ``--bed-under-speech-db`` (dB käsitellyn puheen
#: suhteen). Alaraja: pohja kuuluu vielä; yläraja: selvästi puheen päällä.
BED_OFFSET_RANGE = (-30.0, 6.0)


def check_bed_offset(value) -> float:
    """Pohjan taso puheeseen nähden liukulukuna, tai ``ValueError`` jos se ei kelpaa.

    ``nan`` ja äärettömät hylätään: ``nan`` ei ole minkään välin sisällä, ja ne
    muuttaisivat pohjan vahvistuksen ``nan``iksi ilman että mikään kaatuu.
    """
    number = float(value)
    low, high = BED_OFFSET_RANGE
    if not (low <= number <= high):  # NaN ei ole välillä
        raise ValueError(f"{value}: must be between {low:g} and {high:g} dB")
    return number


def bed_change(spoken_level: float, bed_level: float, offset: float) -> float:
    """Kuinka paljon pohjia muutetaan, dB: kovin hetki ``offset`` puheen yllä."""
    return round(spoken_level + offset - bed_level, 2)

#: Sallitut välit puhujien tasauksen lipuille (dB). Ylärajat ovat selvästi
#: kaiken järkevän yli: raja 0 jättää käyttäjän tasot, suuri raja tasaa täysin.
BALANCE_MAX_RANGE = (0.0, 60.0)
BALANCE_TOLERANCE_RANGE = (0.0, 30.0)


def _checked(value, flag: str, low: float, high: float) -> float:
    number = float(value)
    if not (low <= number <= high):  # NaN ei ole välillä
        raise ValueError(f"{flag}: {value} must be between {low:g} and {high:g} dB")
    return number


def check_balance_max(value) -> float:
    """``--balance-speakers-max-db`` liukulukuna, tai ``ValueError``."""
    return _checked(value, "--balance-speakers-max-db", *BALANCE_MAX_RANGE)


def check_balance_tolerance(value) -> float:
    """``--balance-speakers-tolerance-db`` liukulukuna, tai ``ValueError``."""
    return _checked(value, "--balance-speakers-tolerance-db", *BALANCE_TOLERANCE_RANGE)


def balance_corrections(
    levels: dict[str, float], max_db: float, tolerance_db: float = 0.0
) -> tuple[dict[str, float], dict[str, float]]:
    """Puhujien tasaus rajattuna: ``(tehty korjaus, jälkivahvistus)`` dB, puhuja kohti.

    ``levels`` on kunkin puhujan tulotaso (LUFS). Ryhmän viite on mediaani, ja
    täysi tasaus veisi jokaisen siihen. Korjaus on viiteeseen päin enintään
    ``max_db``; jos puhujien välinen ero (suurin − pienin) on enintään
    ``tolerance_db``, korjausta ei tehdä lainkaan, koska hyvää käsin tehtyä
    tasapainoa ei kuulu näpertää.

    Ketju on jo nostanut jokaisen samalle tasolle (kynnykset seuraavat
    tavoitetta, joten sitä ei voi ohittaa), joten *jälkivahvistus* palauttaa
    sen osan keskinäisestä erosta jota ei haluttu tasata: ``tulotaso +
    korjaus − viite``. Täydessä tasauksessa se on nolla.
    """
    import statistics

    if len(levels) < 2:
        return dict.fromkeys(levels, 0.0), dict.fromkeys(levels, 0.0)
    reference = statistics.median(levels.values())
    within = max(levels.values()) - min(levels.values()) <= tolerance_db
    applied = {
        name: 0.0 if within else max(-max_db, min(max_db, reference - level))
        for name, level in levels.items()
    }
    after = {name: levels[name] + applied[name] - reference for name in levels}
    return applied, after


def scale_file(path: str, gain_db: float) -> None:
    """Kertoo tiedoston vahvistuksella paikallaan, paloittain, 32-bittisenä.

    Nolla desibeliä ei kirjoita mitään. Kirjoitus väliaikaiseen tiedostoon ja
    vaihto, jottei kesken jäänyt kirjoitus jätä puolikasta puhuja-stemiä.
    """
    if abs(gain_db) < 0.005:
        return
    from pedalboard.io import AudioFile

    factor = 10.0 ** (gain_db / 20.0)
    tmp = path + ".tmp.wav"
    with AudioFile(path) as src:
        rate = int(src.samplerate)
        with AudioFile(tmp, "w", rate, src.num_channels, bit_depth=32) as out:
            position, step = 0, 60 * rate
            while position < src.frames:
                piece = src.read(min(step, src.frames - position))
                out.write(piece * factor)
                position += piece.shape[-1]
    os.replace(tmp, path)


#: Musiikin keskikaistan leikkaus kun pohja on täysin (12 dB) puheen alla,
#: dB. Oletus, ei mitattu: käyttäjä halusi tilaa puheelle ja bassoon ja
#: kickiin koskematta; kuunneltava ennen kuin luku on tosi.
CARVE_DB = 3.0

#: Puheen panorointilaki: vakioteho, kuten automixerin oma väylä ennenkin.
#: Keskellä −3 dB kumpaankin, joten stereon äänekkyys on monon, ja musiikki
#: (tasattu puheen monotasoon) pysyy mitatulla etäisyydellään puheesta.
SPEECH_PAN_LAW = "power"


def stereo_layout(members, blocks):
    """Miten stemit soivat ulostulossa: sama laki kuin ``stems.sum_to_file``.

    Mittari mittaa tämän eikä stemien monosummaa, jotta masterointi osuu
    siihen mitä kirjoitetaan.
    """
    import numpy as np

    n = np.atleast_2d(blocks[0]).shape[-1]
    out = np.zeros((2, n), dtype=np.float64)
    for job, block in zip(members, blocks, strict=True):
        block = np.atleast_2d(block)
        if job.get("stereo") and block.shape[0] == 2:
            pair = block
        else:
            mono = block.mean(axis=0)
            pair = np.stack([mono, mono])
        left, right = stems.pan_gains(job.get("pan", 0.0), job.get("pan_law", "balance"))
        out[0] += pair[0] * left
        out[1] += pair[1] * right
    return out


def _loudness(jobs: list[dict], gate=None) -> tuple[float | None, float | None]:
    """``(integroitu, suurin lyhytaikainen)`` LUFS stemien summasta stereona.

    Paloittain levyltä, ``stereo_layout``in kautta: sama mittaus jolla
    masterointi mittaa. ``gate`` on ``stems.anyone_speaking``in tulos;
    sen kanssa integroitu lukema on puheen lukema.
    """
    import numpy as np
    from pedalboard.io import AudioFile

    from speechmix.meter import IntegratedMeter

    handles = [AudioFile(job["target"]) for job in jobs]
    try:
        rate = int(handles[0].samplerate)
        frames = min(h.frames for h in handles)
        spoken = None
        if gate is not None:
            spoken = envelopes.mask_samples(jobs[0]["track"], gate[0], gate[1], rate, frames)
        meter = IntegratedMeter(rate)
        position, step = 0, 60 * rate
        while position < frames:
            count = min(step, frames - position)
            blocks = [np.atleast_2d(h.read(count)) for h in handles]
            meter.add(stereo_layout(jobs, blocks),
                      None if spoken is None else spoken[position:position + count])
            position += count
    finally:
        for handle in handles:
            handle.close()
    keep = meter.speech() > 0.5 if gate is not None else None
    short = meter.short_term()
    loud = float(np.nanmax(short[np.isfinite(short)])) if np.isfinite(short).any() else None
    return meter.value(keep=keep), loud


def own_voice(lanes) -> dict:
    """Puhuja -> milloin **oma** ääni: aktiivinen ja enintään
    ``masks.DUCK_DOMINANCE_DB`` kovimman alla. Toisen puhujan vuoto on
    raidalla kovaa mutta ei omaa, ja lohkon taso mitattaisiin siitä."""
    import numpy as np

    active = np.stack([lane.on for lane in lanes])
    levels = np.stack([lane.level for lane in lanes])
    loudest = np.where(active, levels, -300.0).max(axis=0)
    keep = active & (levels >= loudest - masks.DUCK_DOMINANCE_DB)
    return {lane.name: keep[i] for i, lane in enumerate(lanes)}


def level_blocks(source: str, target: str, found: list) -> None:
    """Kirjoittaa ``source``n ``target``iin lohkojen vahvistuksella, paloittain."""
    from pedalboard.io import AudioFile

    with AudioFile(source) as src:
        rate = int(src.samplerate)
        with AudioFile(target, "w", rate, src.num_channels, bit_depth=32) as out:
            position, step = 0, 60 * rate
            while position < src.frames:
                piece = src.read(min(step, src.frames - position))
                end = position + piece.shape[-1]
                out.write(piece * blocks.gain_block(found, position, end, rate))
                position = end


def _mmss(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def review(speech: list[dict], lanes) -> tuple[dict, dict]:
    """Puhuja -> lohkot (``blocks.block_gains``) ja kovat jaksot (``loud_spans``).

    Lohkot korjataan, kovat jaksot vain merkitään: lohkon sisäinen kova
    jakso oli s13e03:ssa painotusta, ja käyttäjä jätti sen ennalleen.
    """
    found, loud = {}, {}
    if lanes is None:
        return found, loud
    own = own_voice(lanes.speakers)
    for t in speech:
        lane = next(x for x in lanes.speakers if x.name == t["name"])
        found[t["name"]] = blocks.block_gains(lane.level, own[t["name"]])
        loud[t["name"]] = blocks.loud_spans(lane.level, own[t["name"]], found[t["name"]])
    return found, loud


def write_flags(path: str, found: dict, loud: dict, block_level: bool = True) -> int:
    """Kuuntelulista: mitä muutettiin ja mitä vain merkittiin, ajassa."""
    rows = []
    for name, items in found.items():
        for b in items:
            if b.gain_db and block_level:
                rows.append((b.start, f"{_mmss(b.start)}–{_mmss(b.end)}  {name}  block "
                             f"{b.deviation_db:+.1f} dB off its level, gain {b.gain_db:+.1f} dB"))
    for name, items in loud.items():
        for x in items:
            rows.append((x.start, f"{_mmss(x.start)}–{_mmss(x.end)}  {name}  loud "
                         f"{x.excess_db:+.1f} dB over its block (not changed)"))
    rows.sort()
    with open(path, "w", encoding="utf-8") as handle:
        for _, line in rows:
            handle.write(line + "\n")
    return len(rows)


def flags(session_path: str, path: str, loader=None) -> int:
    """Pelkkä kuuntelulista ilman miksausta: lohkot ja kovat jaksot."""
    workdir = tempfile.mkdtemp(
        prefix="automixer-", dir=os.path.dirname(os.path.abspath(path)) or None
    )
    try:
        loaded = (loader or hindenburg.load)(session_path, workdir)
        speech = [t for t in loaded.tracks if t["type"] == "speech"]
        lanes = stems.grid_from_files({t["name"]: t["path"] for t in speech}) if speech else None
        count = write_flags(path, *review(speech, lanes))
        _log(f"{count} places to listen to → {path}")
        return count
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def mix(
    session_path: str,
    output: str,
    target_lufs: float = -16.0,
    plugin_path: str = "",
    plugin_params: dict | None = None,
    plugin_state: str = "",
    track_params: dict | None = None,
    high_pass: bool = True,
    declick: bool = True,
    declick_sensitivity: float = 0.5,
    rider: bool = True,
    debleed: bool = True,
    mic_duck: bool = True,
    mic_duck_db: float | None = None,
    block_level: bool = True,
    bed_under_speech_db: float | None = None,
    balance_speakers_max_db: float | None = None,
    balance_speakers_tolerance_db: float = 0.0,
    loader=None,
    progress=None,
) -> stems.StemResult:
    """Miksaa istunnon ``output``iin. Palauttaa ohjelman tason tulokset.

    ``loader(path, workdir)`` antaa raidat ``session.Loaded``ina; oletus lukee
    Hindenburgin istunnon. ``mix_folder`` antaa kuulaksen kansion.

    ``progress(prosentti, viesti)`` saa kokonaisluvun 0–100 ja lyhyen viestin;
    prosentit nousevat eivätkä laske. Keskeytys: nosta poikkeus takaisinkutsusta,
    työhakemisto siivotaan.

    ``bed_under_speech_db``: musiikkipohjan kovin hetki näin monta dB käsitellyn
    puheen **suhteen** (negatiivinen = hiljempaa); ``None`` on
    ``BED_UNDER_SPEECH_DB``. Virheellinen arvo pysäyttää ennen työtä.

    ``balance_speakers_max_db``: enintään näin monta dB automaatio saa siirtää
    puhujan tasoa ryhmän mediaaniin päin (0 = käyttäjän tasot jäävät); ``None``
    on täysi tasaus kuten ennen. ``balance_speakers_tolerance_db``: jos puhujat
    ovat enintään näin lähellä toisiaan, heitä ei koske.
    """
    bed_offset = (
        BED_UNDER_SPEECH_DB
        if bed_under_speech_db is None
        else check_bed_offset(bed_under_speech_db)
    )
    balance_max = (
        float("inf")
        if balance_speakers_max_db is None
        else check_balance_max(balance_speakers_max_db)
    )
    balance_tolerance = check_balance_tolerance(balance_speakers_tolerance_db)

    def tick(percent, message):
        if progress is not None:
            progress(int(percent), message)

    result = stems.StemResult()
    workdir = tempfile.mkdtemp(
        prefix="automixer-", dir=os.path.dirname(os.path.abspath(output)) or None
    )
    try:
        loaded = (loader or hindenburg.load)(session_path, workdir)
        for note in loaded.notes:
            _log(f"! {note}")
        tick(5, "loaded the tracks")
        speech = [t for t in loaded.tracks if t["type"] == "speech"]
        music = [t for t in loaded.tracks if t["type"] == "music"]
        if not speech and not music:
            raise stems.StemError("no audio tracks in the session")
        seconds = loaded.duration

        def placed(path: str, name: str) -> Track:
            # Kaikki stemit ovat aikajanan mittaisia ja alkavat nollasta:
            # ``session.load`` kokosi ne niin.
            return Track(path=path, speaker=name, spans=[Span(0.0, _duration(path), 0.0)])

        settings = SimpleNamespace(
            **asdict(SpeechSettings(
                high_pass_hz=shared.HIGH_PASS_HZ if high_pass else 0.0,
                declick=declick,
                declick_sensitivity=declick_sensitivity,
                rider=rider,
            )),
            debleed=debleed,
        )

        # Puheruudukko raa'oista stemeistä, verhokäyristä — ei näytteinä.
        grid = None
        lanes = stems.grid_from_files({t["name"]: t["path"] for t in speech}) if speech else None
        if len(speech) > 1:
            grid = lanes
            _log(f"speech grid: {len(grid.speakers)} microphones")

        # Lohkotaso ennen ketjua: eri otto, eri päivä, eri etäisyys —
        # vakio vahvistus koko lohkolle, kuten käyttäjä tekee Hindenburgissa.
        # Kovat jaksot lohkojen sisällä vain merkitään kuuntelulistaan.
        found_all, loud_all = review(speech, lanes)
        listing = os.path.splitext(output)[0] + " flags.txt"
        count = write_flags(listing, found_all, loud_all, block_level)
        _log(f"{count} places to listen to → {listing}")
        tick(15, "checked the levels")
        for name, items in loud_all.items():
            for x in items:
                _log(f"loud {name} {_mmss(x.start)}–{_mmss(x.end)}: "
                     f"{x.excess_db:+.1f} dB over its block (not changed)")
        if block_level and lanes is not None:
            for number, t in enumerate(speech):
                found = found_all[t["name"]]
                fixed = [b for b in found if b.gain_db]
                for b in fixed:
                    _log(f"block {t['name']} {_mmss(b.start)}–{_mmss(b.end)}: "
                         f"{b.deviation_db:+.1f} dB off, gain {b.gain_db:+.1f} dB")
                if fixed:
                    leveled = os.path.join(workdir, f"{number:02d} {t['name']} [level].wav")
                    level_blocks(t["path"], leveled, found)
                    t["path"] = leveled
        solos = masks.solo_masks(grid) if (grid is not None and debleed) else {}
        speaking = masks.speech_masks(grid) if grid is not None else None

        pans = panning.spread(len(speech))
        jobs = []
        for number, t in enumerate(speech):
            target = os.path.join(workdir, f"{number:02d} {t['name']} [mix].wav")
            jobs.append({
                "key": t["name"], "name": t["name"], "speaker": t["name"],
                "track": placed(t["path"], t["name"]),
                "source": t["path"], "target": target,
                "target_lufs": SPEECH_REFERENCE_LUFS, "gain_db": 0.0,
                "speech": True, "mono": True, "pan": pans[number],
                "pan_law": SPEECH_PAN_LAW,
            })

        pools: dict = {}

        def plugin_for(name: str):
            if not plugin_path:
                return None
            params = dict(plugin_params or {})
            for track, per_plugin in (track_params or {}).items():
                if track and track in name.lower():
                    for key, values in per_plugin.items():
                        if key in os.path.basename(plugin_path).lower():
                            params.update(values)
            key = tuple(sorted(params.items()))
            if key not in pools:
                pools[key] = chain.load_pool(
                    plugin_path, params, chain.worker_count(0), plugin_state or None
                )
            return pools[key]

        def work(job):
            _log(f"{job['name']}: processing")
            partners = [o for o in jobs if o is not job]
            return stems.process_stem(
                job, settings, plugin_for(job["name"]), 0.0,
                lambda name, _share, who=job["name"]: _log(f"  {who}: {name}"),
                0.0, solos, partners, result, speaking,
            )

        # Liitännäisvarannot luodaan pääsäikeessä ennen rinnakkaisia ajoja:
        # ``plugin_for`` täyttää sanakirjaa, eikä kahden säikeen pidä luoda
        # samaa varantoa kahdesti.
        for job in jobs:
            plugin_for(job["name"])
        workers = stems.parallel_count(
            [stems.stem_size(j["source"]) for j in jobs], report=_log
        )
        try:
            for done, (job, gain, error) in enumerate(
                stems.run_parallel(jobs, work, workers), start=1
            ):
                if error is not None:
                    raise error
                result.gains[job["key"]] = gain
                tick(15 + 60 * done / len(jobs), f"{job['name']} processed")
        finally:
            for pool in pools.values():
                if hasattr(pool, "close"):
                    pool.close()

        # Puhujien keskinäinen taso. Ketju nosti jokaisen samalle tasolle; raja
        # palauttaa osan erosta, jonka käyttäjä halusi jättää.
        levels = {
            job["name"]: SPEECH_REFERENCE_LUFS - result.gains[job["key"]]
            for job in jobs
            if result.gains.get(job["key"]) is not None
        }
        if len(levels) >= 2:
            applied, after = balance_corrections(levels, balance_max, balance_tolerance)
            for job in jobs:
                if job["name"] in after:
                    scale_file(job["target"], after[job["name"]])
            limit = "no limit" if math.isinf(balance_max) else f"limit {balance_max:.1f} dB"
            _log(
                "balance: "
                + ", ".join(
                    f"{name} {level:.1f} LUFS → {applied[name] + 0.0:+.1f} dB"
                    for name, level in levels.items()
                )
                + f" ({limit}, tolerance {balance_tolerance:.1f} dB)"
            )

        ducked_by = {t["name"]: t.get("ducked") for t in music}
        for t in music:
            # Musiikki on jo tasollaan ja häivytetty (``session.load``); se
            # kulkee katon ja masteroinnin läpi summan osana.
            jobs.append({
                "key": t["name"], "name": t["name"], "speaker": "",
                "track": placed(t["path"], t["name"]),
                "source": t["path"], "target": t["path"],
                "speech": False, "programme": True, "stereo": True,
                "bit_depth": 32,
            })

        ducks = {}
        if mic_duck and grid is not None:
            duck = SimpleNamespace(**{
                name: getattr(masks, f"DUCK_{name.upper()}")
                for name in ("db", "fade", "release", "hold", "lookahead",
                             "min_open", "min_closed", "dominance_db")
            }, duck=True)
            if mic_duck_db is not None:
                duck.db = float(mic_duck_db)
            duck.duck_db = duck.db
            for name in ("fade", "release", "hold", "lookahead", "min_open",
                         "min_closed", "dominance_db"):
                setattr(duck, f"duck_{name}", getattr(duck, name))
            ducks = envelopes.duck_envelopes(grid, duck, 0.0)

        deliver = SimpleNamespace(
            target_lufs=target_lufs,
            program_peak_db=programme.PROGRAM_PEAK_DB,
            program_limit_budget_db=programme.PROGRAM_LIMIT_BUDGET_LU,
        )
        extra = programme.shared_backoff(result.backoffs)

        # Pohjat käsitellyn puheen tasolle: kovin hetki ``BED_UNDER_SPEECH_DB``
        # puheen alla. Mitataan ketjun jälkeen, koska vain se pysyy
        # masteroinnin läpi — molemmat nostetaan samalla.
        speech_jobs = jobs[: len(speech)]
        music_jobs = jobs[len(speech):]
        if speech_jobs and music_jobs:
            spoken_level, _ = _loudness(speech_jobs, stems.anyone_speaking(grid, 0.0))
            _, bed_level = _loudness(music_jobs)
            if spoken_level is not None and bed_level is not None:
                change = bed_change(spoken_level, bed_level, bed_offset)
                for job in music_jobs:
                    extra[job["key"]] = extra.get(job["key"], 0.0) + change
                _log(f"beds: loudest {bed_level:.1f} LUFS, speech {spoken_level:.1f} "
                     f"→ beds {change:+.1f} dB "
                     f"(loudest moment {bed_offset:+.1f} dB from the speech)")
        tick(80, "mastering")
        stems.program_deliver(jobs, result, ducks, extra, deliver,
                              stems.anyone_speaking(grid, 0.0),
                              layout=stereo_layout)

        sources = [
            stems.Source(job["target"], [(0.0, seconds, 0.0)],
                         duck=ducks.get(job["speaker"]), pan=job["pan"],
                         pan_law=job["pan_law"])
            for job in jobs[: len(speech)]
        ] + [
            stems.Source(job["target"], [(0.0, seconds, 0.0)], stereo=True,
                         ducked=ducked_by.get(job["key"]), carve_db=CARVE_DB)
            for job in jobs[len(speech):]
        ]
        tick(92, "writing the mix")
        _log("writing the mix")
        stems.sum_to_file(sources, 0.0, seconds, output)
        _log(f"mastered: {result.program_lufs:.1f} LUFS, "
             f"lift {result.program_boost:+.1f} dB, "
             f"limiting {result.program_limit_cost:.1f} LU → {output}")
        tick(100, "done")
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def mix_folder(folder: str, output: str, **options) -> stems.StemResult:
    """Kuulaksen kansio (``tracks.json`` ja stemit) miksaukseksi levyltä.

    Sama putki kuin ``mix``: ``stem_folder.load`` korvaa vain istunnon luvun.
    """
    from . import stem_folder

    return mix(folder, output, loader=stem_folder.load, **options)
