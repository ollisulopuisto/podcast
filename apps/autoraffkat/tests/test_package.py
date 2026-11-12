"""Paketti: asetusten säilyvyys ja klippisuunnitelman rakennus."""

from fractions import Fraction
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from autoraffkat.package import (
    BED_UNDER_SPEECH_DB,
    TAIL_UNDER_DB,
    BedSettings,
    CreditsSettings,
    PackageSettings,
    TitleCard,
    audio_clips,
    parse_settings,
    throughout_curve,
    video_clips,
)


def test_settings_round_trip():
    settings = PackageSettings(
        intro=TitleCard(mode="file", path="/m/alku.mov"),
        outro=TitleCard(mode="generated", text="Kiitos!", duration=6.0),
        credits=CreditsSettings(mode="file", path="/m/tekstit.mov", placement="both"),
        beds=BedSettings(
            mode="throughout", throughout_path="/m/pohja.wav", keep_music_level=True
        ),
    )
    again = PackageSettings.from_json(settings.to_json())
    assert again == settings
    import json

    assert parse_settings(json.dumps(settings.to_json())) == settings


def test_empty_json_gives_defaults():
    settings = PackageSettings.from_json({})
    assert settings.intro.mode == "off"
    assert settings.beds.mode == "intro_outro"
    assert settings.credits.placement == "end"
    assert video_clips(settings, Fraction(0), Fraction(60)) == []
    assert audio_clips(settings, Fraction(0), Fraction(60), []) == []


def test_file_cards_need_measured_durations():
    settings = PackageSettings(
        intro=TitleCard(mode="file", path="/m/alku.mov"),
        outro=TitleCard(mode="file", path="/m/loppu.mov"),
    )
    # Kestoja ei ole mitattu: ei arvata, klippejä ei tule.
    assert video_clips(settings, Fraction(0), Fraction(60)) == []
    clips = video_clips(
        settings,
        Fraction(0),
        Fraction(60),
        durations={"/m/alku.mov": 4.0, "/m/loppu.mov": 5.0},
    )
    assert [(c.kind, float(c.start), float(c.end)) for c in clips] == [
        ("intro", 0.0, 4.0),
        ("outro", 55.0, 60.0),
    ]
    assert all(c.lane > 0 for c in clips)


def test_credits_both_places_and_after_intro():
    settings = PackageSettings(
        intro=TitleCard(mode="generated", text="Alku", duration=4.0),
        credits=CreditsSettings(mode="generated", text="Tekijät", duration=6.0, placement="both"),
    )
    clips = video_clips(settings, Fraction(0), Fraction(60))
    by_kind = {c.kind: c for c in clips}
    assert float(by_kind["intro"].end) == 4.0
    assert float(by_kind["credits_start"].start) == 4.0
    assert float(by_kind["credits_end"].end) == 60.0


def test_generated_card_needs_text():
    settings = PackageSettings(intro=TitleCard(mode="generated", text="  "))
    assert video_clips(settings, Fraction(0), Fraction(60)) == []


def test_bed_gain_fits_under_speech():
    settings = PackageSettings(
        beds=BedSettings(mode="intro_outro", intro_path="/m/pohja.wav")
    )
    clips = audio_clips(
        settings,
        Fraction(0),
        Fraction(60),
        speech=[(8.0, 55.0)],
        durations={"/m/pohja.wav": 10.0},
        bed_loudness={"/m/pohja.wav": -14.0},
        speech_lufs=-16.0,
    )
    assert len(clips) == 1
    (clip,) = clips
    assert clip.kind == "bed_intro"
    assert float(clip.start) == 0.0 and float(clip.end) == 10.0
    # Pohjan äänekkäin hetki (-14) sovitetaan puheen (-16) alle 1 dB:llä → -3 dB.
    assert clip.base_gain_db == -16.0 - BED_UNDER_SPEECH_DB - (-14.0)


def test_keep_music_level_skips_the_fit():
    settings = PackageSettings(
        beds=BedSettings(
            mode="intro_outro", intro_path="/m/pohja.wav", keep_music_level=True
        )
    )
    (clip,) = audio_clips(
        settings,
        Fraction(0),
        Fraction(60),
        speech=[(8.0, 55.0)],
        durations={"/m/pohja.wav": 10.0},
        bed_loudness={"/m/pohja.wav": -14.0},
        speech_lufs=-16.0,
    )
    assert clip.base_gain_db == 0.0


def test_intro_bed_curve_rises_and_ducks():
    settings = PackageSettings(
        beds=BedSettings(mode="intro_outro", intro_path="/m/pohja.wav")
    )
    (clip,) = audio_clips(
        settings,
        Fraction(0),
        Fraction(120),
        speech=[(12.0, 110.0)],
        durations={"/m/pohja.wav": 20.0},
    )
    # Johdanto on kylmä avaus: käyrä nousee ja vaimenee puheen alkaessa.
    assert len(clip.curve) >= 3
    levels = [db for _, db in clip.curve]
    assert min(levels) < 0.0
    assert max(levels) == 0.0
    assert all(t >= 0.0 for t, _ in clip.curve)


def test_throughout_bed_ducks_every_speech_span():
    settings = PackageSettings(
        beds=BedSettings(mode="throughout", throughout_path="/m/pohja.wav")
    )
    (clip,) = audio_clips(
        settings,
        Fraction(0),
        Fraction(60),
        speech=[(5.0, 10.0), (20.0, 30.0)],
        durations={"/m/pohja.wav": 60.0},
    )
    assert float(clip.start) == 0.0 and float(clip.end) == 60.0
    levels = [db for _, db in clip.curve]
    assert levels.count(TAIL_UNDER_DB) >= 4  # kaksi puhejaksoa, alku + loppu kummallekin
    times = [t for t, _ in clip.curve]
    assert times == sorted(times)


def test_throughout_curve_covers_the_whole_span():
    points = throughout_curve(0.0, 10.0, [(3.0, 5.0)])
    assert points[0] == (0.0, 0.0)
    assert points[-1][0] == 10.0
    assert any(db == TAIL_UNDER_DB for _, db in points)


def test_beds_off_gives_no_clips():
    settings = PackageSettings(beds=BedSettings(mode="off", intro_path="/m/pohja.wav"))
    assert audio_clips(settings, Fraction(0), Fraction(60), []) == []


def test_package_lanes_in_multicam_export(fixture_dir, validate_fcpxml):
    """Kortit lane 3, pohja lane -4 vaimennuskäyröineen; tulos menee DTD:stä."""
    from autoraffkat.finalcut.read import read_fcpxml
    from autoraffkat.finalcut.write import build_multicam_fcpxml
    from autoraffkat.model import Segment
    from autoraffkat.package import (
        BedSettings,
        PackageSettings,
        TitleCard,
        audio_clips,
        video_clips,
    )

    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    settings = PackageSettings(
        intro=TitleCard(mode="file", path="/pkg/alku.mov"),
        outro=TitleCard(mode="file", path="/pkg/loppu.mov"),
        beds=BedSettings(mode="intro_outro", intro_path="/pkg/pohja.wav"),
    )
    durations = {"/pkg/alku.mov": 4.0, "/pkg/loppu.mov": 5.0, "/pkg/pohja.wav": 20.0}
    vclips = video_clips(settings, Fraction(0), Fraction(36), durations)
    aclips = audio_clips(
        settings, Fraction(0), Fraction(36), speech=[(10.0, 30.0)], durations=durations
    )
    xml = build_multicam_fcpxml(
        tl,
        [Segment("WIDE", "Laaja", 0.0, 36.0)],
        [],
        Fraction(0),
        Fraction(36),
        "Paketti",
        package=(vclips, aclips),
    )
    root = ET.fromstring(xml)
    attached = root.findall(".//spine/mc-clip/asset-clip")
    by_lane = {}
    for clip in attached:
        by_lane.setdefault(clip.get("lane"), []).append(clip)
    titles = by_lane.get("3", [])
    assert [c.get("name").split(":")[0] for c in titles] == ["intro", "outro"]
    beds = by_lane.get("-4", [])
    assert len(beds) == 1
    assert beds[0].get("audioRole") == "music.Musiikkipohja"
    keyframes = beds[0].findall(".//keyframe")
    assert keyframes, "pohjalla pitää olla vaimennuskäyrä"
    assert all(k.get("value", "").endswith("dB") for k in keyframes)
    # Korttien assetit ovat pelkkää kuvaa, pohjan pelkkää ääntä.
    assets = {a.get("id"): a for a in root.iter("asset")}
    for title in titles:
        asset = assets[title.get("ref")]
        assert asset.get("hasVideo") == "1" and asset.get("hasAudio") is None
    bed_asset = assets[beds[0].get("ref")]
    assert bed_asset.get("hasAudio") == "1" and bed_asset.get("hasVideo") is None
    validate_fcpxml(xml, "package.fcpxml")


def test_project_settings_carry_the_package():
    from autoraffkat.project import ProjectSettings, name_tag

    settings = ProjectSettings()
    assert settings.package.intro.mode == "off"
    settings.package.intro.mode = "file"
    settings.package.intro.path = "/m/alku.mov"
    settings.package.beds.mode = "throughout"
    settings.package.beds.throughout_path = "/m/pohja.wav"
    again = ProjectSettings.from_json(settings.to_json())
    assert again.package == settings.package
    settings.globals.name_tags = True
    assert "pkg" in name_tag(settings)
    # Oletustila ei kuulu nimeen.
    plain = ProjectSettings()
    plain.globals.name_tags = True
    assert "pkg" not in name_tag(plain)


def test_apply_reads_the_package_payload():
    from autoraffkat.server.app import AppState

    state = AppState(xml_path="")
    state.apply(
        {
            "package": {
                "intro": {"mode": "file", "path": "/m/alku.mov"},
                "outro": {"mode": "generated", "text": "Hei!", "duration": 6},
                "credits": {"mode": "file", "path": "/m/t.mov", "placement": "both"},
                "beds": {
                    "mode": "throughout",
                    "throughout_path": "/m/pohja.wav",
                    "keep_music_level": True,
                },
            }
        }
    )
    pk = state.settings.package
    assert pk.intro.mode == "file" and pk.intro.path == "/m/alku.mov"
    assert pk.outro.mode == "generated" and pk.outro.duration == 6.0
    assert pk.credits.placement == "both"
    assert pk.beds.mode == "throughout" and pk.beds.keep_music_level
    # Roska ei päädy kenttiin.
    state.apply({"package": {"intro": {"mode": "roska"}, "beds": {"mode": "roska"}}})
    assert state.settings.package.intro.mode == "file"
    assert state.settings.package.beds.mode == "throughout"


def test_package_plan_uses_probed_durations(monkeypatch):
    from types import SimpleNamespace

    from autoraffkat import probe
    from autoraffkat.project import ProjectSettings
    from autoraffkat.server.app import _package_plan

    monkeypatch.setattr(
        probe,
        "info",
        lambda path: {
            "/m/alku.mov": {"duration": 4.0, "video": {"width": 3840, "height": 2160}},
            "/m/pohja.wav": {"duration": 30.0, "audio": {"channels": 2, "rate": 48000}},
        }.get(path, {}),
    )
    monkeypatch.setattr(probe, "loudness", lambda path: -20.0)

    settings = ProjectSettings()
    settings.package.intro.mode = "file"
    settings.package.intro.path = "/m/alku.mov"
    settings.package.beds.intro_path = "/m/pohja.wav"
    settings.audio.enabled = True
    settings.audio.target_lufs = -16.0
    state = SimpleNamespace(settings=settings)
    grid = SimpleNamespace(speakers=(), n=0, program_start=0.0)
    warnings = []

    plan = _package_plan(state, grid, Fraction(0), Fraction(60), warnings)
    assert plan is not None
    vclips, aclips = plan
    assert [c.kind for c in vclips] == ["intro"]
    assert (vclips[0].width, vclips[0].height) == (3840, 2160)
    assert [c.kind for c in aclips] == ["bed_intro"]
    assert float(aclips[0].end) == 30.0
    # Tasonsovitus: -16 - 1 - (-20) = +3 dB.
    assert aclips[0].base_gain_db == 3.0
    assert warnings == []


def test_package_plan_warns_about_missing_files(monkeypatch):
    from types import SimpleNamespace

    from autoraffkat import probe
    from autoraffkat.project import ProjectSettings
    from autoraffkat.server.app import _package_plan

    monkeypatch.setattr(probe, "info", lambda path: {})
    settings = ProjectSettings()
    settings.package.intro.mode = "file"
    settings.package.intro.path = "/m/poissa.mov"
    state = SimpleNamespace(settings=settings)
    grid = SimpleNamespace(speakers=(), n=0, program_start=0.0)
    warnings = []

    plan = _package_plan(state, grid, Fraction(0), Fraction(60), warnings)
    assert plan is None
    assert warnings and "poissa.mov" in warnings[0]


def test_package_plan_off_gives_nothing():
    from types import SimpleNamespace

    from autoraffkat.project import ProjectSettings
    from autoraffkat.server.app import _package_plan

    state = SimpleNamespace(settings=ProjectSettings())
    grid = SimpleNamespace(speakers=(), n=0, program_start=0.0)
    warnings = []
    assert _package_plan(state, grid, Fraction(0), Fraction(60), warnings) is None
    assert warnings == []


def test_writer_records_title_shots_for_render(fixture_dir):
    """Kortti menee sekä XML:ään että Renderin kuvalistaan samoilla ajoilla."""
    from autoraffkat.finalcut.read import read_fcpxml
    from autoraffkat.finalcut.write import build_multicam_fcpxml
    from autoraffkat.model import Segment
    from autoraffkat.package import PackageSettings, TitleCard, video_clips

    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    settings = PackageSettings(
        intro=TitleCard(mode="file", path="/pkg/alku.mov"),
    )
    vclips = video_clips(settings, Fraction(0), Fraction(36), {"/pkg/alku.mov": 4.0})
    shots = []
    build_multicam_fcpxml(
        tl,
        [Segment("WIDE", "Laaja", 0.0, 36.0)],
        [],
        Fraction(0),
        Fraction(36),
        "Paketti",
        package=(vclips, []),
        shots=shots,
    )
    titles = [s for s in shots if s.lane == 3]
    assert len(titles) == 1
    assert titles[0].path == "/pkg/alku.mov"
    assert titles[0].start == 0
    assert titles[0].end == int(4.0 / float(tl.frame_duration))


def test_render_job_adds_beds_as_stereo_sources():
    from types import SimpleNamespace

    from autoraffkat.package import PackageAudioClip
    from autoraffkat.project import ProjectSettings
    from autoraffkat.server.app import AppState

    state = AppState(xml_path="")
    state.timeline = SimpleNamespace(
        media_by_key=lambda: {},
        track_media=lambda key: [],
        media=[],
        frame_duration=Fraction(1, 25),
    )
    bed = PackageAudioClip(
        kind="bed_intro",
        name="bed",
        path="/m/pohja.wav",
        start=Fraction(0),
        end=Fraction(10),
        curve=[(0.0, 0.0), (2.0, -6.0)],
        base_gain_db=3.0,
    )
    job = state.render_job(
        [], [], {}, [], [], Fraction(0), Fraction(60), "/tmp/out.mp4",
        package=([], [bed]),
    )
    (source,) = job["sources"]
    assert source.path == "/m/pohja.wav"
    assert source.placements == [(0.0, 10.0, 0.0)]
    assert source.duck == [(0.0, 0.0), (2.0, -6.0)]
    assert source.gain_db == 3.0
    assert source.stereo


def test_flat_export_writes_package_lanes(fixture_dir, validate_fcpxml):
    """Littanä vienti kirjoittaa samat lanet kuin monikamera."""
    from autoraffkat.finalcut.read import read_fcpxml
    from autoraffkat.finalcut.write import build_fcpxml
    from autoraffkat.model import Segment
    from autoraffkat.package import (
        BedSettings,
        PackageSettings,
        TitleCard,
        audio_clips,
        video_clips,
    )

    tl = read_fcpxml(str(fixture_dir / "sync.fcpxml"))
    by_key = {m.key: m for m in tl.media}
    settings = PackageSettings(
        intro=TitleCard(mode="file", path="/pkg/alku.mov"),
        beds=BedSettings(mode="intro_outro", intro_path="/pkg/pohja.wav"),
    )
    durations = {"/pkg/alku.mov": 4.0, "/pkg/pohja.wav": 20.0}
    vclips = video_clips(settings, Fraction(0), Fraction(35), durations)
    aclips = audio_clips(
        settings, Fraction(0), Fraction(35), speech=[(10.0, 30.0)], durations=durations
    )
    xml = build_fcpxml(
        by_key,
        [Segment("WIDE.mp4", "Laaja", 0.0, 35.0)],
        [],
        tl.frame_duration,
        tl.start,
        tl.start + Fraction(35),
        "Paketti",
        source="jakso.fcpxml",
        package=(vclips, aclips),
    )
    root = ET.fromstring(xml)
    attached = root.findall(".//spine/*/asset-clip")
    lanes = {c.get("lane") for c in attached}
    assert "3" in lanes and "-4" in lanes
    bed = next(c for c in attached if c.get("lane") == "-4")
    assert bed.get("audioRole") == "music.Musiikkipohja"
    assert bed.findall(".//keyframe")
    validate_fcpxml(xml, "package-flat.fcpxml")


def test_materialize_generated_without_tekstitys(monkeypatch, tmp_path):
    """Ilman Tekstitystä kortit jäävät ennalleen ja syy kerrotaan."""
    from autoraffkat.package import materialize_generated

    monkeypatch.setattr("shutil.which", lambda name: None)
    settings = PackageSettings(
        intro=TitleCard(mode="generated", text="Otsikko", duration=4.0),
        outro=TitleCard(mode="file", path="/m/loppu.mov"),
    )
    result, problems = materialize_generated(settings, str(tmp_path))
    assert problems
    assert result.intro.mode == "generated"  # ei vaiteta file-tilaan ilman tuotosta
    assert result.outro.mode == "file"  # koskematon
    assert not list(tmp_path.iterdir())  # mitään ei ajettu


def test_materialize_generated_runs_the_cli(monkeypatch, tmp_path):
    """Onnistunut ajo vaihtaa kortin file-tilaan tuotokseen osoittaen."""
    import autoraffkat.package as pkg
    from autoraffkat.package import materialize_generated

    calls = []

    class Done:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = cmd[cmd.index("--out") + 1]
        with open(out, "w") as fh:
            fh.write("mov")
        return Done()

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tekstitys")
    monkeypatch.setattr(pkg, "generated_source_available", lambda: True)
    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    settings = PackageSettings(
        intro=TitleCard(mode="generated", text="Otsikko", duration=4.0),
    )
    result, problems = materialize_generated(settings, str(tmp_path / "pkg"))
    assert problems == []
    assert result.intro.mode == "file"
    assert result.intro.path.endswith("intro.mov")
    cmd = calls[0]
    assert cmd[:2] == ["/usr/bin/tekstitys", "render-alpha"]
    assert "1920x1080" in cmd
    # Sivuvaikutukset: sidecar kirjoitettiin kortin tekstillä.
    import json as json_mod

    sidecar = json_mod.loads((tmp_path / "pkg" / "intro.capslap.json").read_text())
    assert sidecar["segments"][0]["text"] == "Otsikko"
    assert sidecar["segments"][0]["endMs"] == 4000


def test_package_plan_materializes_generated_cards(monkeypatch, tmp_path):
    """Generoitu kortti ajetaan Tekstityksellä ja sen kesto mitataan tuotoksesta."""
    from types import SimpleNamespace

    import autoraffkat.package as pkg
    from autoraffkat import probe
    from autoraffkat.project import ProjectSettings
    from autoraffkat.server.app import _package_plan

    class Done:
        returncode = 0
        stdout = "{}"
        stderr = ""

    def fake_run(cmd, **kw):
        out = cmd[cmd.index("--out") + 1]
        with open(out, "w") as fh:
            fh.write("mov")
        return Done()

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/tekstitys")
    monkeypatch.setattr(pkg, "generated_source_available", lambda: True)
    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        probe,
        "info",
        lambda path: (
            {"duration": 4.0, "video": {"width": 1920, "height": 1080}}
            if path.endswith(".mov")
            else {}
        ),
    )
    settings = ProjectSettings()
    settings.package.intro.mode = "generated"
    settings.package.intro.text = "Otsikko"
    settings.package.intro.duration = 4.0
    state = SimpleNamespace(settings=settings, xml_path=str(tmp_path / "j.fcpxml"))
    grid = SimpleNamespace(speakers=(), n=0, program_start=0.0)
    warnings = []

    plan = _package_plan(state, grid, Fraction(0), Fraction(60), warnings)
    assert plan is not None
    vclips, _ = plan
    assert [c.kind for c in vclips] == ["intro"]
    assert float(vclips[0].end) == 4.0  # kesto mitattu tuotoksesta, ei arvattu
    assert warnings == []


def test_preview_carries_package_spans():
    """Pakettipalkki rajautuu ikkunaan ja kantaa lajin mukana."""
    import numpy as np

    from autoraffkat.preview import build

    grid = SimpleNamespace(
        n=100,
        duration=100.0,
        program_start=0.0,
        speakers=(),
        shots=(),
        groups=(),
    )
    decision = SimpleNamespace(chosen=np.zeros(100, dtype=np.int32))
    out = build(
        grid,
        decision,
        package_clips=[("intro", 0.0, 4.0), ("bed_intro", 0.0, 20.0),
                       ("outro", 95.0, 100.0)],
        window=(0.0, 50.0),
    )
    kinds = [span["kind"] for span in out["package"]]
    assert kinds == ["intro", "bed_intro"]  # outro ikkunan ulkopuolella
    assert out["package"][0]["end"] == 4.0


def test_preview_spans_without_side_effects(monkeypatch):
    """Esikatselu mittaa kestot ffprobesta mutta ei aja Tekstitystä."""
    from types import SimpleNamespace

    from autoraffkat import probe
    from autoraffkat.project import ProjectSettings
    from autoraffkat.server.app import _package_preview_spans

    monkeypatch.setattr(
        probe, "info", lambda path: {"duration": 6.0} if path == "/m/a.mov" else {}
    )
    settings = ProjectSettings()
    settings.package.intro.mode = "file"
    settings.package.intro.path = "/m/a.mov"
    settings.package.outro.mode = "generated"
    settings.package.outro.text = "Hei"
    settings.package.outro.duration = 3.0
    state = SimpleNamespace(settings=settings)
    spans = _package_preview_spans(state, Fraction(0), Fraction(60))
    assert ("intro", 0.0, 6.0) in spans
    # Generoitu näkyy asetusten kestolla ilman renderöintiä.
    assert ("outro", 57.0, 60.0) in spans


def test_nearby_speech_does_not_reverse_bed_keyframes():
    """Kaksi lähekkäistä puhejaksoa: vaimennusikkunat menevät päällekkäin,
    mutta käyrän ajat pysyvät nousevina eikä mikään palaa taaksepäin."""
    settings = PackageSettings(
        beds=BedSettings(mode="throughout", throughout_path="/m/pohja.wav")
    )
    (clip,) = audio_clips(
        settings,
        Fraction(0),
        Fraction(60),
        speech=[(10.0, 11.0), (11.2, 12.0)],
        durations={"/m/pohja.wav": 60.0},
    )
    times = [t for t, _ in clip.curve]
    assert times == sorted(times)
    assert len(times) == len(set(times))


def test_credits_end_before_outro():
    """Lopputekstit ja outro eivät soi samoja kehyksiä: tekstit loppuvat
    outron alkuun, vaikka niille olisi jäänyt aikaa outronkin päälle."""
    settings = PackageSettings(
        outro=TitleCard(mode="file", path="/m/loppu.mov"),
        credits=CreditsSettings(mode="file", path="/m/tekstit.mov", placement="end"),
    )
    durations = {"/m/loppu.mov": 5.0, "/m/tekstit.mov": 8.0}
    clips = video_clips(settings, Fraction(0), Fraction(60), durations)
    by_kind = {c.kind: c for c in clips}
    assert by_kind["credits_end"].end == by_kind["outro"].start
    assert by_kind["outro"].end == Fraction(60)


def test_unmeasurable_bed_falls_back_to_ducking():
    """Kun mittaukseen ei ole tilaa, pohja seuraa puhetta throughout-
    käyrällä — ei soi litteänä vaimentamatta (monkeypatch pakottaa
    mittauksen epäonnistumaan)."""
    import autoraffkat.package as pkg

    original = pkg.bed_curve
    pkg.bed_curve = lambda *a, **k: None
    try:
        settings = PackageSettings(
            beds=BedSettings(mode="intro_outro", intro_path="/m/pohja.wav")
        )
        (clip,) = audio_clips(
            settings,
            Fraction(0),
            Fraction(60),
            speech=[(5.0, 10.0)],
            durations={"/m/pohja.wav": 20.0},
        )
    finally:
        pkg.bed_curve = original
    levels = [db for _, db in clip.curve]
    assert min(levels) < 0.0, "varapolku vaimentaa puheen alla"
    times = [t for t, _ in clip.curve]
    assert times == sorted(times)


def test_long_beds_are_clamped_to_the_programme():
    """Ohjelmaa pidempi pohjatiedosto ei karkaa viennin ulkopuolelle, ja
    kun intro ja outro eivät mahdu molemmat, intro lyhenee outron alkuun."""
    settings = PackageSettings(
        beds=BedSettings(
            mode="intro_outro",
            intro_path="/m/alkupohja.wav",
            outro_path="/m/loppupohja.wav",
        )
    )
    clips = audio_clips(
        settings,
        Fraction(0),
        Fraction(10),
        speech=[],
        durations={"/m/alkupohja.wav": 8.0, "/m/loppupohja.wav": 8.0},
    )
    by_kind = {c.kind: c for c in clips}
    assert by_kind["bed_intro"].start == Fraction(0)
    assert by_kind["bed_outro"].end == Fraction(10)
    assert by_kind["bed_intro"].end == by_kind["bed_outro"].start == Fraction(2)
    # Yksisuuntainen puristus: pelkkä pitkä intro puristuu ohjelman loppuun.
    settings.beds.outro_path = ""
    (clip,) = audio_clips(
        settings, Fraction(0), Fraction(10), [], durations={"/m/alkupohja.wav": 30.0}
    )
    assert clip.end == Fraction(10)


def test_bed_bounds_stay_rational():
    """Rationaaliset ohjelmarajat säilyvät klippien rafoina: ei float-
    kiertoa (repon rationaaliaikasääntö)."""
    settings = PackageSettings(
        beds=BedSettings(mode="throughout", throughout_path="/m/pohja.wav")
    )
    start, end = Fraction(1001, 30), Fraction(3601, 30)
    (clip,) = audio_clips(
        settings, start, end, [], durations={"/m/pohja.wav": 300.0}
    )
    assert clip.start == start and clip.end == end
    assert isinstance(clip.start, Fraction) and isinstance(clip.end, Fraction)


def test_title_format_uses_the_clips_own_frame_rate(fixture_dir):
    """30 fps kortti 25 fps projektissa: assetin formaatti seuraa kortin
    omaa ruutunopeutta, ei projektin — muuten Final Cut venyttää keston."""
    from autoraffkat.finalcut.read import read_fcpxml
    from autoraffkat.finalcut.write import build_multicam_fcpxml
    from autoraffkat.model import Segment

    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    settings = PackageSettings(intro=TitleCard(mode="file", path="/pkg/alku.mov"))
    vclips = video_clips(
        settings, Fraction(0), Fraction(36), durations={"/pkg/alku.mov": 4.0}
    )
    (clip,) = vclips
    clip.fps = 29.97
    xml = build_multicam_fcpxml(
        tl,
        [Segment("WIDE", "Laaja", 0.0, 36.0)],
        [],
        Fraction(0),
        Fraction(36),
        "Paketti",
        package=(vclips, []),
    )
    root = ET.fromstring(xml)
    asset = next(a for a in root.iter("asset") if a.get("hasVideo") == "1"
                 and a.get("name", "").startswith("intro"))
    fmt = {f.get("id"): f for f in root.iter("format")}[asset.get("format")]
    fd = Fraction(fmt.get("frameDuration").rstrip("s"))
    assert abs(float(fd) - 1.0 / 29.97) < 1e-6


def test_compound_audio_keeps_package_clips_single(fixture_dir, validate_fcpxml):
    """Yhdistelmääänellä paketin klipit ovat vain yhdessä rungossa: kortit
    kuvan mukana, pohjat yhdistelmän sisällä — ei kahteen kertaan."""
    from autoraffkat.finalcut.read import read_fcpxml
    from autoraffkat.finalcut.write import build_multicam_fcpxml
    from autoraffkat.model import Segment
    from autoraffkat.project import ProjectSettings

    tl = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    package = PackageSettings(
        intro=TitleCard(mode="file", path="/pkg/alku.mov"),
        beds=BedSettings(mode="intro_outro", intro_path="/pkg/pohja.wav"),
    )
    durations = {"/pkg/alku.mov": 4.0, "/pkg/pohja.wav": 20.0}
    vclips = video_clips(package, Fraction(0), Fraction(36), durations)
    aclips = audio_clips(package, Fraction(0), Fraction(36), [(10.0, 30.0)], durations)
    settings = ProjectSettings()
    settings.globals.compound_audio = True
    xml = build_multicam_fcpxml(
        tl,
        [Segment("WIDE", "Laaja", 0.0, 36.0)],
        [],
        Fraction(0),
        Fraction(36),
        "Paketti",
        settings=settings,
        package=(vclips, aclips),
    )
    root = ET.fromstring(xml)
    (media,) = [m for m in root.iter("media") if m.find("sequence") is not None]
    inner = media.find("sequence/spine")
    outer = root.find(".//project/sequence/spine")

    def refs(node):
        return [c.get("name", "").split(":")[0]
                for c in node.iter("asset-clip")]

    assert "bed_intro" in refs(inner) and "intro" not in refs(inner)
    assert "intro" in refs(outer) and "bed_intro" not in refs(outer)
    validate_fcpxml(xml, "package-compound.fcpxml")
