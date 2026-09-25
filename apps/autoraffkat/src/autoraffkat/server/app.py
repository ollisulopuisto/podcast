"""Paikallinen web-käyttöliittymä.

Analyysi jää palvelimen puolelle, koska se on jo Pythonia ja päätöskerros on
numpya. Selain hoitaa vain säätimet ja piirron. Verhokäyrät lasketaan
taustasäikeessä, jotta roolit voi nimetä heti eikä käyttöliittymä jää odottamaan
ffmpegiä.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from dataclasses import replace as dataclasses_replace

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from speechmix import chain, editor
from speechmix.chain import ChainError

from .. import i18n, pick, probe, project, reactions, reframe, staging, thumbs
from ..analysis import Analysis, AnalysisError, analyze, build_grid, resolve_roles
from ..audio import mix
from ..decide import WIDE_LABEL, decide
from ..fcpxml.read import ReadError, Timeline, read_fcpxml
from ..fcpxml.write import (
    WriteError,
    build_fcpxml,
    build_multicam_fcpxml,
    write_fcpxml,
)
from ..i18n import LANGUAGES, t
from ..model import (
    DEFAULT_PROJECT_NAME,
    LONGTAKE_RULES,
    LOUDNESS_TARGETS,
    OVERLAP_RULES,
    RHYTHM_PRESETS,
    ROLE_MIC,
    ROLES,
    AudioSettings,
    Globals,
)
from ..paths import get_resource_path
from ..preview import build as build_preview

STATIC_DIR = get_resource_path("server/static")


def _plugin_params(raw) -> dict:
    """Liitännäisen säätimet selaimesta: nimi -> arvo.

    Arvot menevät suoraan ulkopuoliselle liitännäiselle, joten tästä päästää
    läpi vain skalaarit ja korkeintaan sen verran nimiä kuin
    käyttöliittymälle ylipäätään näytetään. Nimiä ei tarkisteta täällä:
    liitännäisen lataus kestää sekunteja eikä sitä tehdä säätökierroksella —
    tuntematon nimi ohitetaan vasta ``chain.apply_parameters``issa.
    """
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for name, value in list(raw.items())[: chain.MAX_PARAMS]:
        if isinstance(value, bool):
            out[str(name)] = value
        elif isinstance(value, (int, float)):
            out[str(name)] = float(value)
        elif isinstance(value, str):
            out[str(name)] = value[:120]
    return out


# Kuinka kauan vaimennus odottaa verhokäyriä ennen kuin luovuttaa. Analyysi
# on välimuistissa ja kestää yleensä sekunteja; käsittely kestää minuutteja,
# joten odottaminen on aina halvempaa kuin väärä tulos.
ANALYSIS_WAIT_S = 180.0


def _log_mix(message: str) -> None:
    print(f"[ääni] {message}", flush=True)


@dataclass
class AppState:
    """Palvelimen tila. Yksi XML kerrallaan.

    ``lock`` suojaa asetukset ja analyysin, koska verhokäyriä lasketaan
    taustasäikeessä samaan aikaan kun käyttöliittymä lähettää säätöjä.
    """

    xml_path: str
    timeline: Timeline | None = None
    analysis: Analysis | None = None
    settings: project.ProjectSettings = field(default_factory=project.ProjectSettings)
    progress: dict = field(
        default_factory=lambda: {"done": 0, "total": 0, "current": "", "ready": False}
    )
    load_error: str = ""
    language: str = field(default_factory=i18n.detect)
    inherited_from: str = ""  # mistä roolit perittiin, "" jos ei mistään
    # Kuvan mittaukset media-avaimittain, ja mitä jäi mittaamatta. Erillään
    # äänestä, koska ne ovat eri kestoisia töitä eikä toisen ajaminen saa
    # odottaa toista.
    # Esikatselun ikkuna ohjelma-ajassa, tai None = koko ohjelma. Vain
    # katselua varten: leikkaaminen tapahtuu Final Cutissa.
    preview_window: tuple | None = None
    # Mitattujen reaktiohetkien välimuisti, ks. reaction_marks.
    _marks: object = None
    _marks_key: tuple | None = None
    video_tables: dict = field(default_factory=dict)
    # Laajojen ja ryhmäkuvien joukkotaulukot (kaikki kasvot), pystyvientiä
    # varten. Erillään, koska lähikuvan taulukko pitää vain suurimman.
    crowd_tables: dict = field(default_factory=dict)
    video_errors: dict = field(default_factory=dict)
    # Istumajärjestys kevyestä otoksesta. Erillään ``video_tables``ista,
    # koska se on eri kysymys eri hinnalla: yksi merkki puhujaa kohti
    # sekunneissa, ei tuhansia ruutuja minuuteissa.
    seating: dict = field(default_factory=dict)
    seating_running: bool = False
    video_progress: dict = field(
        default_factory=lambda: {"done": 0, "total": 0, "current": "",
                                 "fraction": 0.0, "running": False}
    )
    mix_result: mix.MixResult = field(default_factory=mix.MixResult)
    # Renderöinti (``render.py``): vienti videoksi ilman Final Cutia.
    render_progress: dict = field(
        default_factory=lambda: {"running": False, "fraction": 0.0, "path": "",
                                 "error": "", "stopped": False, "encoder": ""})
    # Pysäytyspyynnöt: renderöinnille tapahtuma, äänenkäsittelylle lapsi-
    # prosessi joka lopetetaan.
    render_stop: threading.Event = field(default_factory=threading.Event)
    _mix_child: object = None
    mix_progress: dict = field(
        default_factory=lambda: {
            "done": 0,
            "total": 0,
            "current": "",
            "stage": "",
            "fraction": 0.0,
            "eta": 0,
            "running": False,
        }
    )
    audio_preview: dict = field(default_factory=dict)
    audio_preview_running: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock)

    # ---------------------------------------------------------- lataus

    def load(self) -> None:
        """Lukee XML:n ja käynnistää verhokäyrien laskennan taustalle.

        Lukuvirhe ei kaada palvelinta vaan jää ``load_error``iin, jotta
        käyttöliittymä voi näyttää sen ja käyttäjä voi korjata viennin.
        """
        self.load_error = ""
        self.inherited_from = ""
        self.mix_result = mix.MixResult()
        self.audio_preview = {}
        self.audio_preview_running = False
        self.video_tables = {}
        self.crowd_tables = {}
        self.video_errors = {}
        self._marks_key = None
        self.video_progress.update({"done": 0, "total": 0, "current": "",
                                    "fraction": 0.0, "running": False})
        self.progress = {"done": 0, "total": 0, "current": "", "ready": False}
        try:
            timeline = read_fcpxml(self.xml_path)
        except (ReadError, OSError) as exc:
            self.load_error = str(exc)
            self.progress["ready"] = True
            return
        with self.lock:
            self.timeline = timeline
            self.analysis = Analysis(timeline=timeline)
            self.settings = project.load(self.xml_path)
            self._seed_defaults()
            # Kieli vasta perinnän jälkeen: uudella jaksolla ei ole omia
            # asetuksia, ja kieli tulee edellisestä kuten muutkin.
            if self.settings.language:
                self.language = i18n.normalise(self.settings.language)
            self.adopt_mix()
        threading.Thread(target=self._analyze, daemon=True).start()

    def _inherit(self) -> set[str]:
        """Roolit edellisestä jaksosta. Palauttaa täsmänneet raita-avaimet.

        Kamera ei kerro itsestään kumpaa puhujaa se kuvaa, eikä sitä voi
        päätellä XML:stä — mutta edellinen jakso samasta sarjasta kertoo, ja
        raita-avaimet on johdettu tiedostonimistä juuri siksi että ne kestävät
        jaksosta toiseen. Tyhjä lomake on huonompi oletus kuin viime kerran
        kokoonpano.
        """
        assert self.timeline is not None
        source = project.find_previous(self.xml_path)
        previous = project.read(source) if source else None
        if previous is None:
            return set()
        matched = {t.key for t in self.timeline.tracks if t.key in previous.tracks}
        if not matched:
            return set()
        for key in matched:
            self.settings.tracks[key] = previous.tracks[key]
        # Säätimet ovat leikkaajan makua, eivät jakson ominaisuus. Tämä
        # koskee myös ääntä: kanavanauha, liitännäinen ja vaimennus ovat
        # samat viikosta toiseen samalla kokoonpanolla.
        self.settings.globals = previous.globals
        self.settings.audio = previous.audio
        self.settings.language = previous.language
        self.inherited_from = source or ""
        return matched

    def _seed_defaults(self) -> None:
        """Ensimmäisellä avauksella täytetään roolit niin pitkälle kuin voi.

        Järjestys on paras ensin: edellisen jakson roolit, sitten nimistä
        arvaaminen. Puhujaehdotus tulee mikkitiedoston ensimmäisestä sanasta,
        koska äänitteet nimetään käytännössä aina puhujan mukaan. Kameroita ei
        arvata: monikamerassa kulmat ovat ``1``, ``2``, ``3``.

        Arvaus koskee jokaista raitaa jota asetuksissa ei vielä ole, ei vain
        ensimmäistä avausta: kun raita-avaimet muuttuvat (lukija oppi
        tahdistetut kulmat), tallennetut asetukset ovat vanhoilla avaimilla ja
        uudet raidat jäivät käyttämättömiksi ilman arvausta.
        """
        assert self.timeline is not None
        known = set(self.settings.tracks)
        inherited = set() if known else self._inherit()
        for track in self.timeline.tracks:
            cfg = self.settings.config_for(track.key)
            if track.key in known or track.key in inherited:
                continue
            lowered = track.name.lower()
            if track.has_audio and not track.has_video:
                cfg.role = ROLE_MIC
                first = track.name.split()[0] if track.name.split() else ""
                if first.isalpha():
                    cfg.speaker = first.capitalize()
            elif track.has_video and any(
                w in lowered for w in ("wide", "laaja", "master")
            ):
                cfg.role = "wide"

    def _analyze(self) -> None:
        """Taustasäie: purkaa äänet ja laskee verhokäyrät. Kerran per lataus."""
        assert self.timeline is not None
        targets = [m for m in self.timeline.media if m.has_audio]
        self.progress.update({"total": len(targets), "done": 0, "ready": False})

        def report(done: int, total: int, current: str) -> None:
            self.progress.update({"done": done, "total": total, "current": current})

        try:
            result = analyze(self.timeline, progress=report)
            with self.lock:
                self.analysis = result
        except Exception as exc:  # taustasäie ei saa kaatua hiljaa
            self.load_error = t("audio.envelope_failed", error=exc)
            traceback.print_exc()
        finally:
            self.progress["ready"] = True
        # Istumajärjestys heti perään, jos panorointi on päällä. Kytkin
        # käynnistää otoksen vain päälle vaihtaessa, joten ilman tätä
        # asetuksista peritty «panorointi päällä» ei mittaisi koskaan
        # mitään ja vienti kirjoittaisi nolla panorointia hiljaa. Vaatii
        # ruudukon, siksi vasta analyysin jälkeen. Sama koskee reaktioita
        # ja pystyvientiä: kummankin peritty «päällä» vaatisi muuten
        # käsin painetun mittausnapin ennen kuin vienti oikeasti käyttää
        # sitä, ks. ``_wants_video_measurement``.
        if self.settings.globals.panning and not self.seating:
            self.start_seating()
        elif self.video_missing():
            self.start_measure_video()
        if self.settings.audio.enabled:
            self.start_audio_preview()

    def start_seating(self) -> None:
        """Kevyt otos taustalle, jos sitä ei ole jo menossa."""
        if self.seating_running or self.timeline is None:
            return
        self.seating_running = True
        threading.Thread(target=self.measure_seating, daemon=True).start()

    def measure_seating(self) -> None:
        """Taustasäie: kevyt otos pelkkää istumajärjestystä varten.

        Panorointi tarvitsee yhden merkin puhujaa kohti, ei tuhansia
        ruutuja. Täysi mittaus on minuutteja; tämä on sekunteja, joten
        panoroinnin voi laittaa päälle ilman että se vaatii koko
        reaktiokerroksen hinnan.

        Valmiit taulukot voittavat: jos lähikuvat on jo mitattu, tästä ei
        tule uutta ffmpeg-ajoa lainkaan.
        """
        from ..video import analyse as video_analyse
        from ..video import detect

        if self.timeline is None or self.analysis is None:
            return
        try:
            roles = resolve_roles(self.timeline, self.settings.tracks)
            grid, _, _ = build_grid(self.analysis, self.settings.tracks, roles)
            detector = detect.load(self.settings.globals.reaction_detector)
            self.seating = video_analyse.seating(
                grid, roles, self.timeline, detector, self.video_tables
            )
        except (AnalysisError, ValueError, KeyError, OSError, Exception) as exc:
            self.video_errors = dict(self.video_errors)
            self.video_errors["seating"] = str(exc)
        finally:
            self.seating_running = False
            if self.video_missing():
                self.start_measure_video()

    def start_audio_preview(self) -> bool:
        """Käynnistää äänen esianalyysin taustalle, jos se ei ole jo menossa."""
        with self.lock:
            if self.audio_preview_running or self.timeline is None or self.analysis is None:
                return False
            if not self.settings.audio.enabled:
                return False
            self.audio_preview_running = True
            self.audio_preview["running"] = True
        threading.Thread(target=self.measure_audio_preview, daemon=True).start()
        return True

    def measure_audio_preview(self) -> None:
        """Taustasäie: arvioi debleedin, ohjelmatrimmin ja purkaa tilaäänen."""
        if self.timeline is None or self.analysis is None:
            with self.lock:
                self.audio_preview_running = False
            return
        try:
            roles = resolve_roles(self.timeline, self.settings.tracks)
            grid = self.analysis.grid if self.analysis else None
            program_start = float(self.timeline.start) if self.timeline else 0.0
            data = mix.preview_audio(
                self.timeline,
                roles,
                self.settings.audio,
                grid=grid,
                program_start=program_start,
            )
            with self.lock:
                self.audio_preview = data
                self.audio_preview["ready"] = True
                self.audio_preview["running"] = False
        except Exception as exc:
            with self.lock:
                self.audio_preview = {
                    "ready": True,
                    "running": False,
                    "error": str(exc),
                    "debleed": [],
                    "program_trim": 0.0,
                }
        finally:
            with self.lock:
                self.audio_preview_running = False

    def _wants_video_measurement(self) -> bool:
        """Onko jokin ominaisuus päällä joka tarvitsee ``video_tables``.

        Reaktiokuvat ja pystyvienti molemmat lukevat samaa taulukkoa, ja
        molemmat jäivät kerran erikseen tarkistamatta perinnän jälkeen —
        katso ``_analyze`` ja ``measure_seating``. Yksi paikka jonka
        molemmat kutsuvat pitää ne samassa tahdissa, sen sijaan että
        kolmas ominaisuus unohtuisi samalla tavalla vielä kerran.
        """
        return self.settings.globals.reactions or self.settings.globals.vertical

    def video_missing(self) -> bool:
        """Tarvitseeko jokin päällä oleva ominaisuus mittauksen jota ei ole.

        Lähikuvat reaktioille ja pystyviennille, ja pystyvienti lisäksi
        laajan ja ryhmäkuvien kaikki kasvot. Pelkkä «lähikuvat on mitattu»
        jätti joukon mittaamatta: automaattinen käynnistys ei käynnistynyt,
        ja laaja jäi rajaamatta hiljaa.
        """
        if not self._wants_video_measurement():
            return False
        if not self.video_tables:
            return True
        if not self.settings.globals.vertical or self.crowd_tables:
            return False
        from ..video import analyse as video_analyse

        if self.timeline is None:
            return False
        roles = resolve_roles(self.timeline, self.settings.tracks)
        return bool(video_analyse.crowd_files(roles, self.timeline))

    def start_measure_video(self) -> bool:
        """Käynnistää lähikuvien mittauksen taustalle, jos se ei ole jo menossa."""
        with self.lock:
            if self.video_progress.get("running"):
                return False
            if self.timeline is None or self.analysis is None:
                return False
            self.video_progress.update({"running": True, "fraction": 0.0, "done": 0, "current": ""})
        threading.Thread(target=self.measure_video, daemon=True).start()
        return True

    def measure_video(self) -> None:
        """Taustasäie: mittaa lähikuvien avainruudut reaktiokuvia varten.

        Säikeessä eikä lapsiprosessissa, toisin kuin äänenkäsittely: siellä
        pakko oli pedalboardin vaatimus ladata VST3 pääsäikeessä. Vision ei
        vaadi mitään sellaista, ja ffmpeg on jo oma prosessinsa.

        Tulos jää välimuistiin levylle, joten toinen ajo on ilmainen — ja
        siksi tämä saa olla painike eikä latauksen yhteydessä tehtävä työ:
        purku on minuutteja, ja useimmiten käyttäjä ei halua reaktiokuvia.
        """
        from ..video import analyse as video_analyse

        assert self.timeline is not None and self.analysis is not None
        try:
            roles = resolve_roles(self.timeline, self.settings.tracks)
            grid, _, _ = build_grid(self.analysis, self.settings.tracks, roles)
            files = video_analyse.close_up_files(grid, roles, self.timeline)
            crowd_files = (video_analyse.crowd_files(roles, self.timeline)
                           if self.settings.globals.vertical else [])
            whole = len(files) + len(crowd_files)
            with self.lock:
                self.video_progress.update({"total": whole, "done": 0,
                                            "fraction": 0.0, "running": True})
        except (AnalysisError, ValueError) as exc:
            with self.lock:
                self.video_errors = {"grid": str(exc)}
                self.video_progress["running"] = False
            return

        def report(fraction: float) -> None:
            with self.lock:
                self.video_progress.update({
                    "fraction": round(float(fraction), 4),
                    "done": int(fraction * max(1, whole)),
                })

        def part(offset: int, count: int):
            """Lähikuvat ja joukko samaan palkkiin tiedostojen määrän suhteessa."""
            return lambda fraction: report((offset + fraction * count) / max(1, whole))

        try:
            tables, errors = video_analyse.tables(
                grid, roles, self.timeline, self.settings.globals,
                progress=part(0, len(files)))
            crowd: dict = {}
            if crowd_files:
                crowd, crowd_errors = video_analyse.crowd_tables(
                    roles, self.timeline, self.settings.globals,
                    progress=part(len(files), len(crowd_files)))
                errors = {**errors, **crowd_errors}
            with self.lock:
                self.video_tables = tables
                self.crowd_tables = crowd
                self.video_errors = errors
                self._marks_key = None
        except Exception as exc:  # taustasäie ei saa kaatua hiljaa
            with self.lock:
                self.video_errors = {"video": str(exc)}
            traceback.print_exc()
        finally:
            with self.lock:
                self.video_progress.update({"running": False, "fraction": 1.0,
                                            "done": whole})

    def crowd_seats(self, grid, roles) -> tuple[dict, dict[str, list[int]]]:
        """Laajojen ja ryhmäkuvien istujat tiedostoittain.

        Palauttaa ``(median avain -> seats.FileSeats, raidan avain -> puhujat
        joita kuvassa voi olla)``. Laaja voi näyttää kenet tahansa,
        ryhmäkuva vain omansa. Käsin annettu järjestys (``TrackConfig.seats``)
        ohittaa mittauksen niissä tiedostoissa joihin se sopii.
        """
        from .. import seats as seats_mod

        names = [lane.name for lane in grid.speakers]
        index = {name: i for i, name in enumerate(names)}
        covered: dict[str, list[int]] = {}
        if roles.wide_key:
            covered[roles.wide_key] = list(range(len(names)))
        for key, people in roles.groups.items():
            covered[key] = [index[n] for n in people if n in index]
        found: dict = {}
        if not self.crowd_tables or self.timeline is None:
            return found, covered
        for key, speakers in covered.items():
            cfg = self.settings.tracks.get(key)
            order = [index[n] for n in (cfg.seats if cfg else []) if n in index] or None
            for item in self.timeline.track_media(key):
                result = seats_mod.seat_file(
                    self.crowd_tables.get(item.key), item, grid, speakers, order=order)
                if result is not None:
                    found[item.key] = result
        return found, covered

    def seats_view(self, grid, roles) -> dict:
        """Istujat käyttöliittymälle: raidan avain -> osittain vasemmalta oikealle."""
        if not self.settings.globals.vertical or not self.crowd_tables:
            return {}
        found, covered = self.crowd_seats(grid, roles)
        names = [lane.name for lane in grid.speakers]
        out: dict = {}
        for key in covered:
            rows = []
            for item in self.timeline.track_media(key):
                seated = found.get(item.key)
                if seated is None:
                    continue
                rows.append({"part": item.name,
                             "order": [names[i] for i in seated.left_to_right()],
                             "margin": round(float(seated.margin), 4),
                             "manual": seated.manual})
            if rows:
                out[key] = rows
        return out

    def reaction_marks(self, grid, roles, program_start):
        """Mitatut reaktiohetket taulukkona, välimuistitettuna.

        Laskenta maksaa mitattuna 24 ms, ja tämä ajetaan joka
        säätökierroksella. Käyttöliittymän vasteaika on tämän projektin
        tärkein vaatimus, joten tulos säilytetään ja lasketaan uudestaan
        vain kun jokin siihen vaikuttava muuttuu — mittaukset tai ne
        asetukset joista pisteytys riippuu.
        """
        globals_ = self.settings.globals
        if not globals_.reactions or not self.video_tables:
            return None
        key = (id(self.video_tables), len(self.video_tables), float(program_start),
               globals_.reaction_turn_max, globals_.reaction_threshold,
               globals_.reaction_length, globals_.reaction_lead,
               globals_.reaction_turn,
               globals_.reaction_gaze, globals_.reaction_smile,
               globals_.reaction_eyes, globals_.reaction_motion,
               globals_.reaction_size)
        if self._marks_key == key:
            return self._marks
        self._marks = reactions.marks(grid, roles, self.timeline,
                                      self.video_tables, globals_,
                                      float(program_start))
        self._marks_key = key
        return self._marks

    def reaction_lane(self, grid, roles, program_start, decision=None) -> list:
        """``(alku, loppu, puhujan indeksi)`` esikatselupalkkia varten.

        Piirretään myös kun asetus on pois: silloin palkki näyttää mitä
        päälle laittaminen toisi, mikä on ainoa tapa arvioida sitä ennen
        vientiä.
        """
        if not self.video_tables:
            return []
        names = [lane.name for lane in grid.speakers]
        wanted = dataclasses_replace(self.settings.globals, reactions=True)
        try:
            found = reactions.find(grid, roles, self.timeline, self.video_tables,
                                   wanted, float(program_start),
                                   decision=decision
                                   or decide(grid, self.settings.globals))
        except (ValueError, KeyError):
            return []
        # -2 = laaja, kuten päätösrivillä: reaktiokuva ei aina näytä sitä
        # kasvoa joka mitattiin, ks. ``reactions._vary``.
        return [(r.start, r.end,
                 -2 if r.shot and r.shot == grid.wide_key
                 else names.index(r.speaker))
                for r in found if r.speaker in names]

    def render_job(self, shots, mic_tracks, replacements, room, ducks,
                   program_start, program_end, movie: str) -> dict:
        """Renderöinnin syöte samoista päätöksistä joilla XML juuri kirjoitettiin.

        Kuvat tulevat kirjoittajalta (``shots``), ääni samoista käsitellyistä
        tiedostoista, vaimennus- ja panorointikäyristä ja tilaäänestä kuin
        viennissä — mitään ei päätetä uudestaan.
        """
        from .. import render

        assert self.timeline is not None
        by_key = self.timeline.media_by_key()
        pans = self.pans_now()
        gain = (self.settings.globals.master_db
                if self.settings.globals.compound_audio else 0.0)

        def placements(item):
            return [(float(p.offset), float(p.end),
                     float(p.source_at(p.offset) - item.asset_start))
                    for p in item.placements]

        sources = []
        for key, speaker in mic_tracks:
            for item in self.timeline.track_media(key):
                sources.append(render.AudioSource(
                    replacements.get(item.key, item.path), placements(item),
                    duck=(ducks or {}).get(speaker) or [],
                    pan=float(pans.get(speaker, 0.0)), gain_db=gain))
        for key, path in room:
            item = by_key.get(key)
            if item is not None:
                sources.append(render.AudioSource(path, placements(item), gain_db=gain))
        if self.settings.globals.vertical:
            from .. import reframe

            width, height = reframe.PROJECT_W, reframe.PROJECT_H
        else:
            video = next((m for m in self.timeline.media if m.has_video), None)
            width = video.width if video and video.width else 1920
            height = video.height if video and video.height else 1080
        frame = self.timeline.frame_duration
        return {"shots": shots, "sources": sources, "width": width, "height": height,
                "frame_duration": frame, "program_start": float(program_start),
                "frames": int(round((program_end - program_start) / frame)),
                "path": movie}

    def run_render(self, job: dict) -> None:
        """Taustasäie: renderöi MP4:n. Minuutteja; tila näkyy ``render_progress``issa."""
        from .. import render

        self.render_stop.clear()
        self.render_progress.update({"running": True, "fraction": 0.0,
                                     "path": job["path"], "error": "",
                                     "stopped": False,
                                     "encoder": render.encoder()[0]})

        def report(fraction: float) -> None:
            self.render_progress["fraction"] = round(float(fraction), 4)

        try:
            render.render_program(job["shots"], job["sources"], job["width"],
                                  job["height"], job["frame_duration"], job["frames"],
                                  job["program_start"], job["path"], progress=report,
                                  stop=self.render_stop)
        except render.Stopped:
            self.render_progress["stopped"] = True
        except Exception as exc:  # taustasäie ei saa kaatua hiljaa
            self.render_progress["error"] = str(exc)
            traceback.print_exc()
        finally:
            self.render_progress["running"] = False

    def pans_now(self) -> dict:
        """Vientiin menevä panorointi: mitattu paikka, jos kytkin on päällä.

        Määrää ei säädetä. Paikka mitataan ja leveys on vakio, koska
        «kuinka paljon panorointia» on kysymys johon käyttäjällä ei ole
        vastausta — se on juuri se numero jonka tämä työkalu on olemassa
        päättämään. Kytkin on päällä tai pois.
        """
        if not self.settings.globals.panning:
            return {}
        return self.measured_pans()

    def measured_pans(self) -> dict:
        """Istumajärjestys kuvasta, puhuja -> panorointi.

        Erillään ``pans_now``ista, koska käyttöliittymä näyttää tämän myös
        kytkimen ollessa pois: ominaisuutta ei voi arvioida ennen kuin sen
        on vienyt ja kuunnellut, ja väärin päin oleva panorointi kuulostaa
        oikealta kunnes vertaa kuvaan. Sama sääntö kuin reaktiokerroksella.

        Käyttää samoja mittauksia kuin reaktiokerros, joten mitään ei pureta
        uudestaan. Ilman mittauksia tyhjä: paikkaa jota ei tiedetä ei
        arvata, ja keskus on ainoa arvo joka ei ole koskaan väärin.
        """
        if not self.seating:
            return {}
        return staging.pans(dict(self.seating))

    def reactions_now(self, grid, roles, program_start) -> list:
        """Ehdotetut reaktiokuvat nykyisillä asetuksilla ja mittauksilla.

        Nopea: lukee valmiit taulukot eikä avaa tiedostoja. Tyhjä lista jos
        asetus on pois tai mittauksia ei ole — jälkimmäisestä kerrotaan
        viennin varoituksena, ei tässä.
        """
        if not self.settings.globals.reactions or not self.video_tables:
            return []
        return reactions.find(grid, roles, self.timeline, self.video_tables,
                              self.settings.globals, float(program_start),
                              decision=decide(grid, self.settings.globals))

    # ---------------------------------------------------------- päätös

    def apply(self, payload: dict) -> None:
        """Ottaa käyttöliittymän arvot vastaan ja tallentaa ne."""
        # Esikatselun ikkuna ei ole asetus eikä mene tiedostoon: se on
        # katselutila, joka elää vain istunnon ajan.
        if "preview_window" in payload:
            window = payload.get("preview_window")
            try:
                self.preview_window = (
                    (float(window[0]), float(window[1])) if window else None)
            except (TypeError, ValueError, IndexError):
                self.preview_window = None
        tracks = payload.get("tracks") or {}
        for key, values in tracks.items():
            cfg = self.settings.config_for(key)
            role = values.get("role")
            if role in ROLES:
                cfg.role = role
            if "speaker" in values:
                cfg.speaker = str(values["speaker"])[:60]
            for name in ("covers", "seats"):
                if isinstance(values.get(name), list):
                    setattr(cfg, name, [str(n)[:60] for n in values[name]
                                        if str(n).strip()])
            if "sensitivity_db" in values:
                cfg.sensitivity_db = float(values["sensitivity_db"])
            if "gain_db" in values:
                cfg.gain_db = float(values["gain_db"])
        raw = payload.get("globals") or {}
        g = self.settings.globals
        for name in (
            "min_shot",
            "lead",
            "hang",
            "confirm",
            "dominance_db",
            "min_overlap",
            "wide_every",
            "wide_hold",
            # Reaktiokuvien luvut. Nämä puuttuivat listalta, ja seuraus oli
            # juuri tämän projektin tyypillisin vika: säädin näkyi, liikkui
            # ja ei tehnyt mitään. Rasti ei koskaan päässyt palvelimelle,
            # joka tilan päivitys palautti sen pois, ja vienti kirjoitti
            # oikein nolla reaktiokuvaa. Testi alla estää toistumisen.
            "reaction_turn_max",
            "reaction_spacing",
            "reaction_length",
            "reaction_lead",
            "reaction_turn",
            "reaction_gaze",
            "reaction_smile",
            "reaction_eyes",
            "reaction_motion",
            "reaction_size",
        ):
            if name in raw:
                setattr(g, name, max(0.0, float(raw[name])))
        if "master_db" in raw:
            # Yleissäädin saa olla negatiivinen — ja on käytännössä aina,
            # koska se on vaimennus eikä nosto. Yllä oleva silmukka nollaisi
            # sen, kuten se olisi nollannut reaktiokynnyksenkin.
            g.master_db = float(raw["master_db"])
        if "compound_audio" in raw:
            g.compound_audio = bool(raw["compound_audio"])
        if "reaction_threshold" in raw:
            # Kynnys on z-luku ja saa olla negatiivinen: yllä oleva silmukka
            # nollaisi sen.
            g.reaction_threshold = float(raw["reaction_threshold"])
        if "reactions" in raw:
            was = g.reactions
            g.reactions = bool(raw["reactions"])
            # Sama sääntö: kytkin käynnistää mittauksen. Nappi jää, koska
            # ajo on minuutteja ja sen saa haluta uudestaan, mutta
            # ensimmäistä kertaa ei pidä joutua pyytämään erikseen.
            if g.reactions and not was and self.video_missing():
                self.start_measure_video()
        if "panning" in raw:
            was = g.panning
            g.panning = bool(raw["panning"])
            # Kytkin käynnistää otoksen. Ilman tätä panorointi olisi
            # ominaisuus joka vaatii toisen ominaisuuden mittausnapin
            # painamista ensin, eikä mikään kertoisi sitä.
            if g.panning and not was and not self.seating:
                self.start_seating()
        if "movement" in raw:
            g.movement = bool(raw["movement"])
        if raw.get("movement_style") in movement_styles():
            g.movement_style = raw["movement_style"]
        if "vertical" in raw:
            was = g.vertical
            g.vertical = bool(raw["vertical"])
            # Sama sääntö kuin panoroinnissa: kytkin käynnistää oman
            # mittauksensa. Ominaisuus joka vaatii toisen ominaisuuden
            # mittausnapin painamista ensin, on ominaisuus joka näyttää
            # rikkuneelta.
            if g.vertical and not was and self.video_missing():
                self.start_measure_video()
        if raw.get("overlap_rule") in OVERLAP_RULES:
            g.overlap_rule = raw["overlap_rule"]
        if raw.get("long_take_rule") in LONGTAKE_RULES:
            g.long_take_rule = raw["long_take_rule"]
        if raw.get("rhythm") in RHYTHM_PRESETS:
            g.rhythm = raw["rhythm"]
        if "name_tags" in raw:
            g.name_tags = bool(raw["name_tags"])
        self._apply_audio(payload.get("audio") or {})
        if (
            ("audio" in payload or "tracks" in payload)
            and self.settings.audio.enabled
            and self.analysis is not None
        ):
            self.start_audio_preview()
        if "project_name" in raw:
            g.project_name = str(raw["project_name"])[:120] or DEFAULT_PROJECT_NAME

    def _apply_audio(self, raw: dict) -> None:
        """Äänenkäsittelyn asetukset. Ei käynnistä käsittelyä — se on hidas."""
        a = self.settings.audio
        if "enabled" in raw:
            a.enabled = bool(raw["enabled"])
        if "debleed" in raw:
            a.debleed = bool(raw["debleed"])
        if "declick" in raw:
            a.declick = bool(raw["declick"])
        if "duck" in raw:
            a.duck = bool(raw["duck"])
        if "program_target" in raw:
            a.program_target = bool(raw["program_target"])
        if "plugin_workers" in raw:
            # Rajaus on ``chain.worker_count``issa; tässä riittää ettei
            # kenttään päädy roskaa eikä negatiivista.
            try:
                a.plugin_workers = max(0, int(raw["plugin_workers"]))
            except (TypeError, ValueError):
                a.plugin_workers = 0
        for name in (
            "duck_db",
            "duck_lookahead",
            "duck_hold",
            "duck_min_open",
            "duck_fade",
            "duck_release",
            "duck_min_closed",
            "duck_min_gap",
            "duck_dominance_db",
            "declick_sensitivity",
        ):
            if name in raw:
                a.__dict__[name] = float(raw[name])
        for name in (
            "high_pass_hz",
            "target_lufs",
            "peak_threshold_db",
            "leveler_threshold_db",
            "gain_db",
            "room_db",
        ):
            if name in raw:
                a.__dict__[name] = float(raw[name])
        if "plugin_path" in raw:
            wanted = str(raw["plugin_path"]).strip()
            # Tuntematon polku nollataan heti: käsittely kaatuisi siihen
            # vasta minuuttien päästä.
            wanted = wanted if (not wanted or os.path.exists(wanted)) else ""
            # Säätimet kuuluvat siihen liitännäiseen josta ne luettiin.
            # Toisen liitännäisen nimet eivät osu mihinkään, ja jos osuvat,
            # ne osuvat väärään säätimeen.
            if wanted != a.plugin_path:
                a.plugin_params = {}
                # Tila on läpinäkymätön ja liitännäiskohtainen: toisen
                # liitännäisen tavut eivät ole tälle mitään.
                a.plugin_state = ""
            a.plugin_path = wanted
        if "plugin_params" in raw:
            a.plugin_params = _plugin_params(raw["plugin_params"])
        if "room_track" in raw:
            keys = {t.key for t in self.timeline.tracks} if self.timeline else set()
            wanted = str(raw["room_track"])
            a.room_track = wanted if wanted in keys else ""

    def mix_freshness(self) -> dict:
        """Montako mikkitiedostoa vastaa nykyisiä asetuksia.

        Kesken ajon ei lasketa: luvut muuttuisivat kyselyn alla, eikä
        edistymispalkki tarvitse niitä.
        """
        if self.timeline is None or self.mix_progress.get("running"):
            return {"fresh": 0, "expected": 0}
        roles = resolve_roles(self.timeline, self.settings.tracks)
        fresh, total = mix.freshness(self.timeline, roles, self.settings.audio)
        return {"fresh": fresh, "expected": total}

    def adopt_mix(self) -> None:
        """Ottaa levyllä jo olevan käsitellyn äänen tämän istunnon käyttöön.

        Käsittelyn tulos jää lähteen viereen, mutta ``mix_result`` katoaa
        istunnon mukana. Ilman tätä sama jakso uudestaan avattuna vietäisiin
        raakana, vaikka valmis ``[mix]`` on levyllä ja ajan tasalla.

        Kutsutaan latauksessa ja viennissä, ei säätösilmukassa: kutsu tekee
        ``stat``-kutsun kutakin mikkitiedostoa kohti, ja tiedoston lukeminen
        ei kuulu siihen silmukkaan. Jo tiedettyjä ei ylikirjoiteta — oikea
        ajo tietää enemmän kuin levyn tarkastelu.

        Ei ota ``lock``ia itse: vienti pitää sitä jo, eikä ``threading.Lock``
        ole uudelleensyötettävä. Kutsuja vastaa lukosta.
        """
        if self.timeline is None or self.mix_progress.get("running"):
            return
        roles = resolve_roles(self.timeline, self.settings.tracks)
        found = mix.adopt(self.timeline, roles, self.settings.audio)
        for key, path in found.replacements.items():
            if key not in self.mix_result.replacements:
                self.mix_result.replacements[key] = path
                self.mix_result.skipped += 1
        have = {k for k, _ in self.mix_result.room}
        for key, path in found.room:
            if key not in have:
                self.mix_result.room.append((key, path))
                self.mix_result.skipped += 1

    def _mix_command(self) -> list[str]:
        return [sys.executable, "-m", "autoraffkat.audio.worker"]

    def stop_mix(self) -> bool:
        """Lopettaa käsittelyn lapsiprosessin. Palauttaa oliko jotain lopetettavaa."""
        child = self._mix_child
        if child is None:
            return False
        self.mix_progress["stopped"] = True
        child.kill()
        return True

    def run_mix(self, force: bool = False) -> None:
        """Käsittelee äänet taustalla. Kestää minuutteja, ei kuulu silmukkaan.

        ``force`` käsittelee myös ajan tasalla olevat uudestaan. Käyttäjä on
        varmistanut sen erikseen: painike kertoo kun työ on tehty, eikä
        minuuttien ajoa aloiteta vahingossa.
        """
        assert self.timeline is not None
        self.mix_progress.update(
            {
                "done": 0,
                "total": 0,
                "current": "",
                "stage": "",
                "fraction": 0.0,
                "eta": 0,
                "running": True,
            }
        )

        # Käsittely omassa prosessissaan: liitännäinen on ladattava
        # pääsäikeessä, ja palvelimen pääsäie ajaa tapahtumasilmukkaa. Sama
        # ratkaisu estää liitännäistä kaatamasta palvelinta. Ks. audio/worker.py.
        spec = {
            "xml_path": self.timeline.source_path,
            "settings": self.settings.to_json(),
            "force": bool(force),
        }
        command = self._mix_command()
        self.mix_progress["stopped"] = False
        try:
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            self._mix_child = child
            assert child.stdin is not None and child.stdout is not None
            json.dump(spec, child.stdin)
            child.stdin.close()

            payload: dict = {}
            for line in child.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    print(line, flush=True)  # lapsen oma loki, jo etuliitteellä
                    continue
                kind = message.pop("kind", "")
                if kind == "progress":
                    self.mix_progress.update(
                        message | {"eta": round(message.get("eta", 0.0))}
                    )
                elif kind in ("done", "failed"):
                    payload = message
            child.wait()

            if self.mix_progress.get("stopped"):
                # Pysäytetty: valmiiksi ehtineet tiedostot käyttöön kuten
                # aina (``adopt``), keskeneräinen ei — sen leima puuttuu.
                self.adopt_mix()
            elif "error" in payload:
                self.mix_result = mix.MixResult(errors={"mix": payload["error"]})
            elif payload:
                result = mix.MixResult(
                    processed=payload.get("processed", 0),
                    skipped=payload.get("skipped", 0),
                    gains=payload.get("gains", {}),
                    errors=payload.get("errors", {}),
                    replacements=payload.get("replacements", {}),
                    room=[tuple(pair) for pair in payload.get("room", [])],
                    program_trim=payload.get("program_trim", 0.0),
                )
                with self.lock:
                    self.mix_result = result
            elif child.returncode != 0:
                self.mix_result = mix.MixResult(
                    errors={"mix": t("audio.worker_died", code=child.returncode)}
                )
        except Exception as exc:  # taustasäie ei saa kaatua hiljaa
            self.mix_result = mix.MixResult(errors={"mix": str(exc)})
            traceback.print_exc()
        finally:
            self._mix_child = None
            self.mix_progress["running"] = False
            self.mix_progress["stage"] = ""

    def compute(self) -> dict:
        """Ajaa päätöskerroksen ja kokoaa vastauksen käyttöliittymälle.

        Puutteelliset roolit palautuvat ``ok: False`` ja luettavana listana,
        eivät HTTP-virheenä: ne ovat normaali välitila silmukassa.

        Avain ``_grid`` on sisäinen: vienti tarvitsee saman päätöksen, eikä sitä
        lasketa kahdesti. Se poistetaan ennen JSONiksi kirjoittamista.
        """
        if self.timeline is None or self.analysis is None:
            raise HTTPException(409, self.load_error or t("export.not_loaded"))
        started = time.perf_counter()
        roles = resolve_roles(self.timeline, self.settings.tracks)
        problems = list(roles.problems)
        for track in self.timeline.tracks:
            cfg = self.settings.tracks.get(track.key)
            if not cfg or cfg.role != ROLE_MIC:
                continue
            problems += [
                self.analysis.errors[k]
                for k in track.media_keys
                if k in self.analysis.errors
            ]
        if problems:
            return {"ok": False, "problems": problems, "ms": 0.0}
        try:
            grid, program_start, program_end = build_grid(
                self.analysis, self.settings.tracks, roles
            )
        except AnalysisError as exc:
            return {"ok": False, "problems": [str(exc)], "ms": 0.0}

        # Mitatut reaktiohetket päätökselle: aikakatkaisu tietää vain että
        # aikaa on kulunut, mittaus että jotain tapahtuu. Taulukkona, koska
        # päätöskerros ei lue tiedostoja.
        marks = self.reaction_marks(grid, roles, program_start)
        decision = decide(grid, self.settings.globals, marks=marks)
        lane = self.reaction_lane(grid, roles, program_start, decision)
        names = [speaker.name for speaker in grid.speakers]
        seats_view = self.seats_view(grid, roles)
        counts: dict[str, int] = {}
        for seg in decision.segments:
            counts[seg.label] = counts.get(seg.label, 0) + 1
        elapsed = (time.perf_counter() - started) * 1000.0
        return {
            "ok": True,
            "problems": [],
            "program": {
                "start": float(program_start),
                "end": float(program_end),
                "duration": float(program_end - program_start),
            },
            "segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "duration": s.duration,
                    "label": s.label,
                    "angle": s.angle,
                }
                for s in decision.segments
            ],
            "counts": counts,
            # Laajan tunnus on aineistoa, ei käyttöliittymän tekstiä: sama
            # merkkijono päätyy vientiin rooliksi. Käyttöliittymä kääntää sen
            # näytölle, ja tarvitsee siihen tiedon siitä mikä tunnus se on.
            "wide_label": WIDE_LABEL,
            # Reaktiokuvat samaan palkkiin: niiden ajoitus suhteessa puheeseen
            # on koko kysymys, eikä sitä näe erillisestä listasta.
            "preview": build_preview(grid, decision, reactions=lane,
                                     window=self.preview_window),
            # Myös listaan: palkista näkee rytmin, listasta tarkan hetken.
            "reactions": [
                {"speaker": WIDE_LABEL if index < 0 else names[index],
                 "start": float(start), "end": float(end)}
                for start, end, index in lane
            ],
            # Tuoreus mukaan säätökierrokselle, jotta painike vanhenee samalla
            # hetkellä kuin tulos: asetuksen muutos tekee valmiista työstä
            # vanhentunutta, ja se on nähtävä kysymättä erikseen.
            "mix_fresh": self.mix_freshness(),
            # Laajojen ja ryhmäkuvien istujat vasemmalta oikealle, osittain.
            # Näkyviin, koska mitattu järjestys voi olla väärin ja pystyvienti
            # rajaisi silloin väärän ihmisen — ja sen näkee vasta viennistä.
            "seats": seats_view,
            "ms": round(elapsed, 1),
            "_grid": (grid, program_start, program_end, decision),
        }


def _video_json(state: AppState) -> dict:
    """Kuvan mittausten tila käyttöliittymälle.

    Tiedostojen määrä on huonoin saatavilla oleva luku: neljä lähikuvaa
    tarkoittaa kahta kameraa kahdessa osassa, ei neljää kuvaa. Ruudut ja
    portin läpäisseet hetket kertovat mitä oikeasti on.

    Läpäisseiden määrä lasketaan joka kyselyllä, koska se muuttuu heti kun
    porttia liikuttaa — numpyta valmiiden taulukoiden yli, ei yhtään
    tiedostonlukua, joten se kelpaa säätökierrokselle.
    """
    frames = faces = 0
    for table in state.video_tables.values():
        found = table.get("found")
        if found is None:
            continue
        frames += int(len(found))
        faces += int(found.sum())

    candidates = placed = None
    # Mihin panorointi puhujat asettaa. Näkyviin, koska muuten ominaisuutta
    # ei voi arvioida ennen kuin sen on vienyt ja kuunnellut — ja väärin
    # päin oleva panorointi kuulostaa oikealta kunnes vertaa kuvaan. Sama
    # sääntö kuin reaktiokerroksella: näytetään myös kytkimen ollessa pois.
    pans = state.measured_pans()
    if state.video_tables and state.timeline is not None and state.analysis:
        try:
            roles = resolve_roles(state.timeline, state.settings.tracks)
            grid, program_start, _ = build_grid(
                state.analysis, state.settings.tracks, roles)
            # Laskenta ei katso ``reactions``-asetusta, samasta syystä kuin
            # mittauskaan: luku kertoo mitä aineistossa on, ja asetus
            # päättää käytetäänkö sitä. Muuten se näyttäisi nollaa
            # silloinkin kun ehdokkaita on satoja.
            wanted = dataclasses_replace(state.settings.globals, reactions=True)
            # Kaksi lukua, koska ne vastaavat eri kysymyksiin: portin läpi
            # kertoo mitä aineistossa on ja liikkuu säätimen mukana,
            # vientiin päätyvät on käytännössä ``reaction_spacing``in
            # määräämä. Pelkkä jälkimmäinen saa säätimen näyttämään
            # rikkinäiseltä — mitattuna se liikkui 121:stä 129:ään samalla
            # kun ehdokkaat menivät 1118:sta 1572:een.
            candidates = len(reactions.candidates(
                grid, roles, state.timeline, state.video_tables,
                wanted, float(program_start)))
            placed = len(reactions.find(
                grid, roles, state.timeline, state.video_tables,
                wanted, float(program_start),
                decision=decide(grid, state.settings.globals)))
        except (AnalysisError, ValueError, KeyError):
            candidates = placed = None

    return {
        "progress": dict(state.video_progress),
        "measured": len(state.video_tables),
        "frames": frames,
        "faces": faces,
        "candidates": candidates,
        "placed": placed,
        "pans": pans,
        "seating": bool(state.seating) or state.seating_running,
        "errors": sorted(state.video_errors.values()),
    }


def _audio_warnings(state: AppState, roles, replacements: dict) -> list[str]:
    """Kertoo jos vienti käyttää raakaa ääntä vaikka käsittely on päällä.

    Vienti viittaa vain valmiisiin tiedostoihin, joten kesken käsittelyn
    vietäessä tulos on ehjä mutta käsittelemätön. Se on juuri sellainen ero
    jota ei huomaa Final Cutissa ennen kuin kuuntelee — ja silloin leikkaus on
    jo tehty, eikä uusi vienti tuo tehtyjä muokkauksia mukanaan.
    """
    if state.timeline is None or not state.settings.audio.enabled:
        return []
    expected = {
        item.key
        for keys in roles.mics.values()
        for key in keys
        for item in state.timeline.track_media(key)
        if item.path
    }
    # Muistiinpanot ensin: ne kertovat mitä jäi tekemättä vaikka tiedosto
    # syntyi — ohitettu liitännäinen, tavoitetaso johon ei osuttu. Tiedostot
    # ovat paikallaan, joten alla oleva tarkistus ei huomaisi niistä mitään.
    said: list[str] = []
    for notes in state.mix_result.notes.values():
        for note in notes:
            if note not in said:
                said.append(note)

    missing = expected - set(replacements)
    if not missing:
        return said
    if state.mix_progress.get("running"):
        return [*said,
                t("export.audio_running", missing=len(missing), total=len(expected))]
    return [*said,
            t("export.audio_missing", missing=len(missing), total=len(expected))]


def _track_json(state: AppState, track) -> dict:
    """Yksi raita käyttöliittymälle: rooli, säätimet ja osat.

    Monikamerassa raita on sama kulma useassa osassa, joten mitat ja
    varoitukset kootaan osista. Käyttöliittymä näyttää yhden rivin, ei kuutta.
    """
    assert state.timeline is not None
    items = state.timeline.track_media(track.key)
    span = state.timeline.track_span(track.key) or (0, 0)
    first = items[0] if items else None
    errors = (
        [state.analysis.errors.get(m.key, "") for m in items] if state.analysis else []
    )
    facts = probe.info(first.path) if first and first.path else {}
    return {
        "key": track.key,
        "name": track.name,
        "kind": "video" if track.has_video else "audio",
        "probe": facts,
        # Osien yhteiskesto ja -koko: raita on yksi asia, vaikka tiedostoja
        # olisi monta.
        "total_size": sum((probe.info(m.path).get("size") or 0) for m in items),
        "total_duration": sum((probe.info(m.path).get("duration") or 0) for m in items),
        "path": first.path if first else "",
        "missing": any(m.path and not os.path.exists(m.path) for m in items),
        "has_video": track.has_video,
        "has_audio": track.has_audio,
        "width": first.width if first else 0,
        "height": first.height if first else 0,
        "fps": (
            round(float(1 / first.frame_duration), 3)
            if first and first.frame_duration
            else None
        ),
        "audio_channels": first.audio_channels if first else 0,
        "timeline_start": float(span[0]),
        "timeline_end": float(span[1]),
        "parts": [
            {
                "name": m.name,
                "path": m.path,
                "missing": bool(m.path) and not os.path.exists(m.path),
            }
            for m in items
        ],
        "angle_name": first.angle_name if first else "",
        "thumb": bool(track.has_video and first and first.path),
        "config": state.settings.config_for(track.key).to_json(),
        "envelope_error": next((e for e in errors if e), ""),
    }


def movement_styles() -> tuple[str, ...]:
    from .. import movement as movement_mod

    return movement_mod.STYLES


def _state_json(state: AppState) -> dict:
    """Koko tila käyttöliittymälle: raidat, roolit, säätimet ja edistyminen."""
    timeline = state.timeline
    tracks = (
        [_track_json(state, t) for t in timeline.tracks] if timeline is not None else []
    )
    return {
        "xml_path": state.xml_path,
        "settings_path": project.settings_path(state.xml_path),
        "output_path": project.next_output_path(
            state.xml_path, project.name_tag(state.settings)
        ),
        "name": timeline.name if timeline else "",
        "kind": timeline.kind if timeline else "",
        "parts": len(timeline.multicams) if timeline else 0,
        "fps": (round(float(1 / timeline.frame_duration), 3) if timeline else None),
        "tracks": tracks,
        "globals": state.settings.globals.to_json(),
        "progress": state.progress,
        "inherited_from": state.inherited_from,
        "language": state.language,
        "languages": list(LANGUAGES),
        "audio": state.settings.audio.to_json(),
        # Mitatut oletukset käyttöliittymälle. Se merkitsee poikkeaman
        # suljetulle riville, ja poikkeaman on tultava samasta paikasta kuin
        # arvot itse — JavaScriptiin kirjoitettu kopio ajautuisi erilleen
        # hiljaa, ja silloin merkki näyttäisi väärää tai ei mitään.
        "audio_defaults": AudioSettings().to_json(),
        "video": _video_json(state),
        # Palojen ylärajan ja automaattivalinnan on oltava käyttöliittymässä
        # sama luku kuin käsittelyssä: se riippuu koneesta, ei asetuksista.
        # Alustojen lukemat palvelimelta, jotta käyttöliittymä ja käsittely
        # puhuvat samoista luvuista eikä niitä ole kahdessa paikassa.
        "loudness_targets": LOUDNESS_TARGETS,
        "cores": os.cpu_count() or 1,
        "workers_auto": chain.worker_count(),
        "render": dict(state.render_progress),
        "mix": {
            "progress": state.mix_progress,
            "ready": len(state.mix_result.replacements),
            "room": len(state.mix_result.room),
            "skipped": state.mix_result.skipped,
            # Käyttöliittymä erottaa tästä kaksi tilannetta jotka näyttävät
            # muuten samalta: ajo joka teki työtä ja ajo jolla ei ollut
            # mitään tehtävää.
            "processed": state.mix_result.processed,
            "program_trim": state.mix_result.program_trim,
            **state.mix_freshness(),
            "gains": state.mix_result.gains,
            "errors": list(state.mix_result.errors.values()),
        },
        "audio_preview": state.audio_preview,
        "error": state.load_error,
    }


def create_app(state: AppState) -> FastAPI:
    """Rakentaa sovelluksen annetun tilan ympärille.

    Tila annetaan ulkoa, jotta testit voivat ajaa saman rajapinnan ilman
    palvelinprosessia.
    """
    app = FastAPI(title="autoraffkat", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def use_language(request, call_next):
        """Kieli pyynnön kontekstiin ennen kuin mitään viestejä syntyy."""
        i18n.set_language(state.language)
        return await call_next(request)

    @app.post("/api/language")
    def set_language(payload: dict):
        """Käyttöliittymän kieli. Tallentuu asetuksiin ja periytyy jaksosta
        toiseen, kuten muutkin asetukset."""
        state.language = i18n.normalise(payload.get("language"))
        i18n.set_language(state.language)
        with state.lock:
            state.settings.language = state.language
            # Kieli ei ole tallentamisen arvoinen virhe.
            with contextlib.suppress(OSError):
                project.save(state.xml_path, state.settings)
        return {"language": state.language, "languages": list(LANGUAGES)}

    @app.get("/")
    def index():
        """Käyttöliittymän sivu, tyyli ja skripti muokkausajalla versioituna.

        Ilman versiota selain tarjoilee vanhaa tyyliä uuden skriptin kanssa, ja
        tulos on rikkinäinen tavalla jota kukaan ei osaa yhdistää välimuistiin.
        """
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for name in (
            "app.js",
            "i18n.js",
            "style.css",
            "favicon.ico",
            "favicon.png",
            "favicon.svg",
            "apple-touch-icon.png",
            "icon.png",
        ):
            static_file = STATIC_DIR / name
            if static_file.exists():
                stamp = int(static_file.stat().st_mtime)
                html = html.replace(f"/static/{name}", f"/static/{name}?v={stamp}")
        return Response(html, media_type="text/html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        """Selainten vakiokuvake juuripolusta."""
        fav = STATIC_DIR / "favicon.ico"
        if fav.is_file():
            return FileResponse(fav, media_type="image/x-icon")
        return Response(status_code=404)

    @app.get("/apple-touch-icon.png", include_in_schema=False)
    @app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
    def apple_touch_icon():
        """Kuvake iOS/macOS-selainpikakuvakkeille."""
        icon = STATIC_DIR / "apple-touch-icon.png"
        if icon.is_file():
            return FileResponse(icon, media_type="image/png")
        return Response(status_code=404)

    @app.get("/api/thumb")
    def thumb(track: str):
        """Ruutu raidan kuvasta. Puretaan vasta pyydettäessä.

        Kulmien nimet ovat ``1``, ``2`` ja ``3``, joten roolituksen tekeminen
        ilman kuvaa on arvailua. Purku on ffmpegiä, joten se ei kuulu
        latausvaiheeseen — selain pyytää nämä omaan tahtiinsa.
        """
        if state.timeline is None:
            raise HTTPException(404, t("export.not_loaded"))
        for item in state.timeline.track_media(track):
            path = thumbs.for_item(item)
            if path:
                # Välimuistin avain sisältää muokkausajan, joten sisältö ei
                # muutu saman URLin alla.
                return FileResponse(
                    path,
                    media_type="image/jpeg",
                    headers={"Cache-Control": "max-age=86400"},
                )
        return Response(status_code=404)

    @app.get("/api/defaults")
    def defaults():
        """Tehdasasetukset. Säätimiä on paljon, ja perintä vie huonon arvon
        seuraavaan jaksoon — ilman paluuta siitä ei pääse takaisin."""
        return {"globals": Globals().to_json(), "audio": AudioSettings().to_json()}

    @app.get("/api/plugins")
    def list_plugins():
        """Asennetut VST3- ja AU-liitännäiset. Haetaan vasta pyydettäessä."""
        return {"plugins": chain.plugins()}

    @app.get("/api/plugin-params")
    def plugin_parameters(path: str = ""):
        """Yhden liitännäisen säätimet.

        Erillinen pyyntö liitännäisluettelosta, koska tämä lataa
        liitännäisen: se kestää sekunteja, eikä sitä saa tehdä 800:lle.
        """
        try:
            specs, total = chain.parameter_specs(path)
        except ChainError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"params": specs, "total": total}

    @app.post("/api/plugin-editor")
    def plugin_editor():
        """Avaa liitännäisen oman ikkunan ja tallettaa sen jättämän tilan.

        Lapsiprosessissa, koska ``show_editor`` on kutsuttava pääsäikeestä
        ja se **estää** sen kunnes ikkuna suljetaan — palvelimen pääsäie
        ajaa tapahtumasilmukkaa. Sama syy kuin käsittelyllä, ks.
        ``speechmix.editor``.

        Tämä on ainoa tie liitännäisen malliin: dxRevive julkaisee neljä
        parametria, eikä mallin valinta ole yksikään niistä.
        """
        audio = state.settings.audio
        try:
            result = editor.open_editor(
                audio.plugin_path, audio.plugin_params, audio.plugin_state
            )
        except ChainError as exc:
            raise HTTPException(400, str(exc)) from exc
        with state.lock:
            audio.plugin_state = result.state
            merged = dict(audio.plugin_params)
            merged.update(_plugin_params(result.params))
            audio.plugin_params = merged
        project.save(state.xml_path, state.settings)
        return _state_json(state)

    @app.post("/api/video")
    def measure_video():
        """Käynnistää lähikuvien mittauksen taustalle.

        Painike eikä automaatti: purku on minuutteja, ja useimmiten
        reaktiokuvia ei haluta lainkaan. Tulos on levyllä välimuistissa,
        joten toinen ajo maksaa sekunteja.
        """
        if state.timeline is None or state.analysis is None:
            raise HTTPException(409, state.load_error or t("export.not_loaded"))
        if not state.progress.get("ready"):
            raise HTTPException(409, t("video.not_ready"))
        # Vastaus on **vain** mittauksen tila, ei koko tila. Koko tilan
        # palauttaminen houkutteli sijoittamaan sen selaimessa suoraan
        # `state`:en, jolloin juuri liikutettu säädin hyppäsi takaisin
        # siihen mitä palvelimelle oli ehditty tallentaa. Mittauksella ei
        # ole mitään sanottavaa asetuksista, joten se ei niitä palauta.
        state.start_measure_video()
        return {"video": _video_json(state)}

    @app.get("/api/state")
    def get_state():
        """Koko tila. Käyttöliittymä kysyy tämän avatessa ja edistymistä pollatessa."""
        return _state_json(state)

    @app.post("/api/reload")
    def reload_xml():
        """Lukee lähde-XML:n uudestaan levyltä, esimerkiksi uuden viennin jälkeen."""
        state.load()
        return _state_json(state)

    @app.post("/api/open")
    def open_xml(payload: dict):
        """Avaa toisen XML-tiedoston tai paketin."""
        path = str((payload or {}).get("path") or "").strip()
        if not path or not os.path.exists(path):
            raise HTTPException(
                400, t("read.file_missing", path=path or "(polku puuttuu)")
            )
        # Lukko on load():n sisällä, eikä threading.Lock ole rekursiivinen:
        # sen ottaminen tässä jumitti avauksen ikuisesti. Pyyntö ei palannut,
        # ja koska load() nollaa edistymisen ennen lukkoa, käyttöliittymä jäi
        # lukemaan «verhokäyrät 0/0» loputtomiin.
        # Paketti on hakemisto, ja juuri sen polun sekä pywebview'n dialogi
        # että Finder palauttavat: .fcpxmld on Finderille tiedosto. Ilman
        # tätä avaus kaatui «[Errno 21] Is a directory».
        state.xml_path = pick.resolve(path)
        state.load()
        return _state_json(state)

    @app.post("/api/pick")
    def pick_xml():
        """Finderin valintaikkuna palvelimen puolelta.

        Selaimessa ei ole tiedostovalitsinta joka antaisi polun: <input type=
        "file"> antaa sisällön muttei sijaintia, ja koko työkalu toimii
        poluilla. Natiivi-ikkunassa tämän hoitaa pywebview, selaimessa ei
        mikään — siksi ikkuna avataan täällä. Palvelin on aina samalla
        koneella kuin selain, joten ikkuna aukeaa oikealle näytölle.
        """
        if not pick.has_native_picker():
            return {"path": "", "unavailable": True}
        start = os.path.dirname(state.xml_path) if state.xml_path else ""
        return {"path": pick.native(start, force=True) or ""}

    @app.post("/api/pick-folder")
    def pick_folder():
        """Järjestelmän hakemistovalintaikkuna palvelimen puolelta."""
        if not pick.has_native_picker():
            return {"path": "", "unavailable": True}
        start = os.path.dirname(state.xml_path) if state.xml_path else ""
        return {"path": pick.native_folder(start, force=True) or ""}

    @app.post("/api/relink")
    def relink_files(payload: dict | None = None):
        """Etsii ja uudelleenlinkittää puuttuvat mediatiedostot."""
        if state.timeline is None:
            raise HTTPException(409, state.load_error or t("export.not_loaded"))
        search_dir = str((payload or {}).get("search_dir") or "").strip()
        from ..relink import relink_timeline

        relinked = relink_timeline(
            state.timeline,
            search_dir=search_dir if search_dir else None,
            xml_path=state.xml_path,
        )
        if relinked:
            with state.lock:
                if state.analysis:
                    for k in relinked:
                        state.analysis.errors.pop(k, None)
            threading.Thread(target=state._analyze, daemon=True).start()
        return {
            "ok": True,
            "relinked": len(relinked),
            "items": relinked,
        }

    @app.post("/api/settings")
    def post_settings(payload: dict):
        """Ottaa säätimet vastaan, ajaa päätöksen ja tallentaa asetukset.

        Tämä on silmukan kuuma polku: kutsutaan jokaisesta liukusäätimen
        liikkeestä, joten tässä ei saa tehdä muuta kuin päätöskerros ja pieni
        JSON-kirjoitus.
        """
        with state.lock:
            state.apply(payload)
            result = state.compute()
            result.pop("_grid", None)
            # Nimi seuraa säätimiä, joten ruudulla näkyvä polku muuttuu niiden
            # mukana. Muuten se lupaisi tiedostoa jota vienti ei kirjoita.
            result["output_path"] = project.next_output_path(
                state.xml_path, project.name_tag(state.settings)
            )
            try:
                project.save(state.xml_path, state.settings)
            except OSError as exc:
                result.setdefault("problems", []).append(
                    t("export.settings_failed", error=exc)
                )
        return result

    @app.post("/api/export")
    def export(payload: dict | None = None):
        """Kirjoittaa leikatun FCPXML:n uutena tiedostona lähteen viereen.

        Ottaa säätimet vastaan samassa pyynnössä, jotta vienti käyttää varmasti
        sitä mitä ruudulla näkyy eikä edellistä tallennettua tilaa.
        """
        want_render = bool((payload or {}).get("render"))
        if want_render and state.render_progress.get("running"):
            raise HTTPException(409, t("render.busy"))
        shot_list: list | None = [] if want_render else None
        with state.lock:
            if payload:
                state.apply(payload)
            result = state.compute()
            if not result.get("ok"):
                return JSONResponse(
                    {"ok": False, "problems": result.get("problems", [])},
                    status_code=400,
                )
            _grid, program_start, program_end, decision = result["_grid"]
            assert state.timeline is not None
            roles = resolve_roles(state.timeline, state.settings.tracks)
            mic_tracks: list[tuple[str, str]] = []
            for name in roles.speakers:
                for key in roles.mics.get(name, []):
                    mic_tracks.append((key, name))
            out_path = project.next_output_path(
                state.xml_path, project.name_tag(state.settings)
            )
            # Final Cut näyttää projektin nimen, ei tiedostonimeä, joten
            # erotteleva osa on liitettävä siihen tai tuonnit ovat
            # selaimessa erottamattomia.
            shown_name = project.fcp_project_name(
                state.settings.globals.project_name,
                out_path,
                stamp=project.stamp_now(),
            )
            if os.path.abspath(out_path) == os.path.abspath(state.xml_path):
                raise HTTPException(400, t("export.would_overwrite"))
            if os.path.dirname(out_path).endswith(project.BUNDLE_EXT):
                # Paketti kuuluu Final Cutille. Jos polku joskus laskettaisiin
                # sinne, se on virhe eikä asia jota yritetään silti.
                raise HTTPException(400, t("export.inside_bundle"))
            try:
                # Käsitelty ääni otetaan mukaan jos se on olemassa ja
                # ajan tasalla. Vanhentunutta ei käytetä hiljaa.
                # Levyllä jo oleva käsitelty ääni mukaan: rooli on voinut
                # vaihtua avaamisen jälkeen, eikä painamatta jäänyt nappi saa
                # olla syy siihen että vienti viittaa raakaan ääneen.
                state.adopt_mix()
                result = (
                    state.mix_result
                    if state.settings.audio.enabled
                    else mix.MixResult()
                )
                replacements = {
                    k: v for k, v in result.replacements.items() if os.path.exists(v)
                }
                room = [(k, v) for k, v in result.room if os.path.exists(v)]
                warnings = _audio_warnings(state, roles, replacements)

                # Reaktiokuvat omalle lanelleen, ks. CLAUDE.md. Asetus
                # päällä ja lopputuloksessa ei mitään on tässä projektissa
                # tuttu vika, joten kumpikin tyhjä tapaus kerrotaan: ei
                # mittauksia, ja mittaukset mutta ei läpäisijöitä.
                # Vaimennus menee vientiin käyränä eikä tiedostoihin, joten
                # «asetus päällä, tuloksessa ei mitään» ei saa jäädä hiljaa —
                # se on tässä projektissa toistuva vika, ja nyt se osuisi
                # kohtaan jota ei kuule ennen kuin miksaa Final Cutissa.
                ducks = mix.duck_envelopes(
                    _grid, state.settings.audio, float(program_start)
                )
                if (state.settings.audio.duck
                        and state.settings.audio.duck_db < 0 and not ducks):
                    warnings.append(t("export.duck_none"))
                # Häivytys samaan käyrään: se on tasopäätös ketjun jälkeen
                # niin kuin vaimennuskin, eikä siksi tarvitse omaa rakennetta
                # vientiin. Rajat tulevat puheentunnistuksesta, jotta liuku
                # jää hiljaisuuteen eikä syö ensimmäistä sanaa.
                ducks = mix.program_fades(
                    _grid, float(program_start), float(program_end), ducks
                )

                # Panorointi päällä mutta tuloksessa ei mitään: sama
                # vikaluokka kuin reaktioilla, ja se osui tähän oikeasti —
                # irrotettu medialevy jätti istumajärjestyksen tyhjäksi ja
                # vienti kirjoitti nolla panorointia sanomatta mitään.
                if state.settings.globals.panning and not state.pans_now():
                    warnings.append(t("export.pan_none"))

                shots = state.reactions_now(_grid, roles, program_start)
                if state.settings.globals.reactions and not shots:
                    warnings.append(t("video.none_measured")
                                    if not state.video_tables
                                    else t("video.no_candidates"))

                # Pystyviennin kehystys: sama kahden tyhjän tapauksen sääntö.
                # Mittaamaton jakso saa letterboxin, mutta kokonaan hiljainen
                # tulos olisi «toimiva vienti joka ei tehnyt mitään», ja se
                # kerrotaan eri sanoin kuin tyhjä mittaus.
                reframer = None
                framed = 0
                segments = decision.segments
                if state.settings.globals.vertical:
                    closes = reframe.close_up_tables(
                        state.video_tables, state.timeline, roles)
                    # Laaja ja ryhmäkuva rajataan puhujaan: kuva pilkotaan
                    # puhujan mukaan ja kukin pala kehystetään hänen
                    # kasvoilleen, jos hänet tunnistettiin siitä tiedostosta.
                    found, covered = state.crowd_seats(_grid, roles)
                    followed = {
                        key: people for key, people in covered.items()
                        if any(i.key in found for i in state.timeline.track_media(key))
                    }
                    segments = reframe.focus_segments(
                        decision.segments, _grid, followed,
                        state.settings.globals.min_shot)
                    reframer = reframe.Reframer(
                        closes, reframe.look(closes, state.timeline, roles),
                        crowd=found, crowd_tables=state.crowd_tables,
                        names=[lane.name for lane in _grid.speakers])
                    framed = reframe.framed_count(
                        reframer, state.timeline, segments)
                    if not state.video_tables:
                        warnings.append(t("export.vertical_unmeasured"))
                    elif not framed:
                        warnings.append(t("export.vertical_unframed"))
                if (state.settings.globals.movement
                        and state.settings.globals.movement_style == "shorts"):
                    # Shorts: pitkät lähikuvat punch-ineiksi puhujan
                    # painotuksissa, ks. movement.punch_segments.
                    from .. import movement as movement_mod

                    segments = movement_mod.punch_segments(
                        segments, _grid, state.settings.globals.min_shot)
                if state.timeline.multicams:
                    # Monikamerassa ulos tulee monikameraleikkaus: kuvakulman
                    # voi vaihtaa Final Cutissa jälkikäteen.
                    xml = build_multicam_fcpxml(
                        state.timeline,
                        segments,
                        mic_tracks,
                        program_start,
                        program_end,
                        shown_name,
                        replacements=replacements,
                        room=room,
                        settings=state.settings,
                        source=state.xml_path,
                        reactions=shots,
                        roles=roles,
                        pans=state.pans_now(),
                        ducks=ducks,
                        reframer=reframer,
                        shots=shot_list,
                    )
                else:
                    # Hiljainen pudotus littanaan vientiin ei saa jäädä
                    # sanomatta: käyttäjä huomaa vasta Final Cutissa, ettei
                    # kuvakulmaa voi vaihtaa, ja syy (lähde on
                    # «Synkronoi klipit», ei monikameraklippi) ei näy siellä.
                    warnings.append(t("export.flat_no_multicam"))
                    xml = build_fcpxml(
                        {m.key: m for m in state.timeline.media},
                        segments,
                        mic_tracks,
                        state.timeline.frame_duration,
                        program_start,
                        program_end,
                        shown_name,
                        replacements=replacements,
                        room=room,
                        settings=state.settings,
                        source=state.xml_path,
                        reframer=reframer,
                        tc_start=state.timeline.tc_start,
                        shots=shot_list,
                    )
                write_fcpxml(out_path, xml)
            except (WriteError, OSError) as exc:
                raise HTTPException(400, str(exc)) from exc
            project.save(state.xml_path, state.settings)
            rendering = None
            if want_render:
                movie = os.path.splitext(out_path)[0] + ".mp4"
                job = state.render_job(shot_list, mic_tracks, replacements, room,
                                       ducks, program_start, program_end, movie)
                # Käynnissä heti eikä vasta säikeessä: muuten vastauksen jälkeen
                # heti kysytty tila näyttäisi valmiilta, ja painike palaisi.
                state.render_progress.update({"running": True, "fraction": 0.0,
                                              "path": movie, "error": "",
                                              "stopped": False})
                threading.Thread(target=state.run_render, args=(job,), daemon=True).start()
                rendering = {"path": movie, "running": True}
        # Seuraavan viennin nimi mukaan: ruudulla näkyvä polku on juuri
        # kirjoitettu, ja ilman tätä se jäisi lupaamaan väärää tiedostoa.
        return {
            "render": rendering,
            "ok": True,
            "path": out_path,
            "cuts": len(decision.segments),
            "mixed": len(replacements),
            "room": len(room),
            "reactions": len(shots),
            "warnings": warnings,
            "next_path": project.next_output_path(
                state.xml_path, project.name_tag(state.settings)
            ),
        }

    @app.post("/api/mix")
    def run_mix(payload: dict | None = None):
        """Käynnistää äänenkäsittelyn taustalle.

        Erillinen painike eikä osa vientiä: käsittely kestää minuutteja, ja
        vienti on silmukan nopea pää. Valmiit tiedokset jäävät levylle, joten
        seuraavat viennit käyttävät niitä ilman uutta ajoa.
        """
        if state.timeline is None:
            raise HTTPException(409, state.load_error or t("export.not_loaded"))
        if state.mix_progress.get("running"):
            return {"ok": True, "running": True}
        force = bool((payload or {}).get("force"))
        with state.lock:
            if payload:
                state.apply(payload)
            state.settings.audio.enabled = True
            project.save(state.xml_path, state.settings)
        threading.Thread(target=state.run_mix, args=(force,), daemon=True).start()
        return {"ok": True, "running": True}

    @app.post("/api/render/stop")
    def stop_render():
        """Pysäyttää renderöinnin: ffmpegit lopetetaan, tiedostoa ei jää."""
        state.render_stop.set()
        return {"ok": True}

    @app.post("/api/mix/stop")
    def stop_mix():
        """Pysäyttää äänenkäsittelyn. Valmiit tiedostot jäävät käyttöön."""
        return {"ok": True, "stopped": state.stop_mix()}

    @app.post("/api/final-cut")
    def open_in_final_cut(payload: dict):
        """Avaa viedyn XML:n suoraan Final Cutissa.

        Vienti päättyy siihen että tiedosto on levyllä, ja seuraava askel on
        aina sen tuonti — polun kopioiminen käsin on turha välivaihe. ``open``
        antaa Final Cutille tuonti-ikkunan, ei siis riko mitään jos painallus
        oli vahinko.
        """
        path = str((payload or {}).get("path", "")).strip()
        if not path or not os.path.exists(path):
            raise HTTPException(404, t("export.file_missing"))
        if sys.platform != "darwin":
            raise HTTPException(400, t("export.only_macos"))
        done = subprocess.run(["open", "-a", "Final Cut Pro", path],
                              check=False, capture_output=True, text=True)
        if done.returncode:
            # ``open`` kertoo syyn stderrissä; ilman tätä nappi näyttäisi
            # toimivan vaikka Final Cutia ei ole asennettu.
            raise HTTPException(400, done.stderr.strip() or t("export.no_fcp"))
        return {"ok": True}

    @app.post("/api/reveal")
    def reveal(payload: dict):
        """Näytä tiedosto Finderissa/tiedostonhallinnassa."""
        path = str(payload.get("path", "")).strip()
        if not path or not os.path.exists(path):
            raise HTTPException(404, t("export.file_missing"))
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer.exe", f"/select,{path}"], check=False)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", os.path.dirname(path) or "."], check=False)
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
