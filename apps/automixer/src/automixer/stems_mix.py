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
#: **käsitellyn** puheen äänekkyyden alla. Käyttäjä 2026-10-07: «music at
#: most at −16 LUFS, the same as the speech». Käyttäjän oma master: pohja
#: +1,2 dB puheen yllä; aiempi +7 dB (Hindenburgin istunnosta,
#: käsittelemätöntä puhetta vasten) teki valmiissa miksauksessa +7…+10.
#: Tutkimus (Sound On Sound, Transom): selvästi soiva musiikki puheen
#: tasolle, koska musiikin huiput ovat kovemmat ja masterointi litistää ne.
BED_UNDER_SPEECH_DB = -1.0

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


def flags(session_path: str, path: str) -> int:
    """Pelkkä kuuntelulista ilman miksausta: lohkot ja kovat jaksot."""
    workdir = tempfile.mkdtemp(
        prefix="automixer-", dir=os.path.dirname(os.path.abspath(path)) or None
    )
    try:
        loaded = hindenburg.load(session_path, workdir)
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
    mic_duck: bool = False,
    mic_duck_db: float | None = None,
    block_level: bool = True,
) -> stems.StemResult:
    """Miksaa istunnon ``output``iin. Palauttaa ohjelman tason tulokset."""
    result = stems.StemResult()
    workdir = tempfile.mkdtemp(
        prefix="automixer-", dir=os.path.dirname(os.path.abspath(output)) or None
    )
    try:
        loaded = hindenburg.load(session_path, workdir)
        for note in loaded.notes:
            _log(f"! {note}")
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

        try:
            for job in jobs:
                _log(f"{job['name']}: processing")
                partners = [o for o in jobs if o is not job]
                result.gains[job["key"]] = stems.process_stem(
                    job, settings, plugin_for(job["name"]), 0.0,
                    lambda name, _share, who=job["name"]: _log(f"  {who}: {name}"),
                    0.0, solos, partners, result, speaking,
                )
        finally:
            for pool in pools.values():
                if hasattr(pool, "close"):
                    pool.close()

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
                change = round(spoken_level + BED_UNDER_SPEECH_DB - bed_level, 2)
                for job in music_jobs:
                    extra[job["key"]] = extra.get(job["key"], 0.0) + change
                _log(f"beds: loudest {bed_level:.1f} LUFS, speech {spoken_level:.1f} "
                     f"→ beds {change:+.1f} dB")
        stems.program_deliver(jobs, result, ducks, extra, deliver,
                              stems.anyone_speaking(grid, 0.0),
                              layout=stereo_layout)

        sources = [
            stems.Source(job["target"], [(0.0, seconds, 0.0)],
                         duck=ducks.get(job["speaker"]), pan=job["pan"],
                         pan_law=job["pan_law"])
            for job in jobs[: len(speech)]
        ] + [
            stems.Source(job["target"], [(0.0, seconds, 0.0)], stereo=True)
            for job in jobs[len(speech):]
        ]
        _log("writing the mix")
        stems.sum_to_file(sources, 0.0, seconds, output)
        _log(f"mastered: {result.program_lufs:.1f} LUFS, "
             f"lift {result.program_boost:+.1f} dB, "
             f"limiting {result.program_limit_cost:.1f} LU → {output}")
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
