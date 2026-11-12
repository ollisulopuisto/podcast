"""Paketti: asetusten säilyvyys ja klippisuunnitelman rakennus."""

from fractions import Fraction

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
    from xml.etree import ElementTree as ET

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
