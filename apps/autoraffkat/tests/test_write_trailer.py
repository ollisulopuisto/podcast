"""Trailerin kolmikaistainen FCPXML: spine = koko ruutu, päällä ylä- ja alapuolikas."""

from fractions import Fraction
from xml.etree import ElementTree as ET

import pytest

from autoraffkat.finalcut.write import WriteError
from autoraffkat.finalcut.write_trailer import build_trailer_fcpxml
from autoraffkat.trailer import TrailerSource


def _src(w=1920, h=1080, fd=Fraction(1, 25), audio=True):
    return TrailerSource(path="/media/trailer.mp4", name="trailer", width=w,
                         height=h, frame_duration=fd, duration=Fraction(10),
                         has_audio=audio)


def _doc(**kw):
    pieces = kw.pop("pieces", [(0.0, 2.0), (2.0, 5.0), (5.0, 10.0)])
    xs = kw.pop("xs", [0.2, 0.5, 0.9])
    src = kw.pop("src", _src())
    return ET.fromstring(build_trailer_fcpxml(src, pieces, xs, "Review", **kw))


def _spine(root):
    # Projektin spine, ei paneeliyhdistelmien spinet resources-lohkossa.
    return root.find(".//project/sequence/spine")


def test_sequence_is_vertical_and_spine_has_one_full_clip_per_piece():
    root = _doc()
    fmt = root.find(".//format[@id='r1']")
    assert (fmt.get("width"), fmt.get("height")) == ("1080", "1920")
    clips = list(_spine(root))
    assert len(clips) == 3
    assert [c.get("name") for c in clips] == ["Full 01", "Full 02", "Full 03"]
    # ei aukkoja: jokaisen alku on edellisen loppu
    end = Fraction(0)
    for c in clips:
        off = _t(c.get("offset"))
        assert off == end
        end = off + _t(c.get("duration"))
    assert end == Fraction(10)


def _t(text):
    text = text.rstrip("s")
    return Fraction(text)


def test_each_spine_clip_carries_a_top_and_a_bottom_half_connected_lane():
    root = _doc()
    for clip in _spine(root):
        kids = [k for k in clip if k.tag == "ref-clip"]
        assert [k.get("lane") for k in kids] == ["1", "2"]
        assert kids[0].get("name").startswith("Top")
        assert kids[1].get("name").startswith("Bottom")
        # FCP tulkitsee liitetyn klipin offsetin isännän aikajanalle, ei
        # projektin aikajanalle (varmistettu 2026-11-19): suhteellinen nolla.
        assert kids[0].get("offset") == "0s"
        assert kids[0].get("duration") == clip.get("duration")
        # Yhdistelmän sisällä oleva klippi alkaa samasta lähteen kohdasta.
        media = _media_by_id(root, kids[0].get("ref"))
        inner = media.find(".//asset-clip")
        assert inner.get("start") == clip.get("start")


def _media_by_id(root, media_id):
    return next(m for m in root.iter("media") if m.get("id") == media_id)


def test_default_enablement_is_top_half_only():
    root = _doc()
    clip = _spine(root)[0]
    top, bottom = [k for k in clip if k.tag == "ref-clip"]
    assert top.get("enabled") in (None, "1")
    assert bottom.get("enabled") == "0"
    assert clip.get("enabled") in (None, "1")


def test_enabled_lane_can_be_bottom_or_none():
    for choice, want in (("bottom", ("0", None)), ("none", ("0", "0"))):
        top, bottom = [k for k in _spine(_doc(enabled_lane=choice))[0]
                       if k.tag == "ref-clip"]
        assert top.get("enabled") == want[0] or (want[0] is None and top.get("enabled") in (None, "1"))
        assert bottom.get("enabled") == want[1] or (want[1] is None and bottom.get("enabled") in (None, "1"))
    with pytest.raises(WriteError):
        _doc(enabled_lane="left")


def test_audio_only_on_the_spine_clip():
    root = _doc()
    clip = _spine(root)[0]
    assert clip.get("srcEnable") is None
    lanes = [k for k in clip if k.tag == "ref-clip"]
    assert len(lanes) == 2
    for k in lanes:
        assert k.get("srcEnable") == "video"
    root = _doc(src=_src(audio=False))
    assert root.find(".//asset").get("hasAudio") is None


def test_half_lanes_have_the_same_zoom_and_mirror_positions():
    root = _doc(xs=[0.3, 0.3, 0.3])
    clip = _spine(root)[0]
    top, bottom = [k for k in clip if k.tag == "ref-clip"]
    # Peilitut paneelipaikat ulkoisina sijainteina (yhdistelmä on 1080×960).
    assert top.find("adjust-transform").get("position") == "0 25"
    assert bottom.find("adjust-transform").get("position") == "0 -25"
    # 1080×960-puolikas: käyttäjän varmistama zoomi 0,96 (2026-11-19),
    # tasainen molemmilla akseleilla, EI rajausta.
    transforms = [
        _media_by_id(root, k.get("ref")).find(".//asset-clip/adjust-transform")
        for k in (top, bottom)
    ]
    assert transforms[0].get("scale") == transforms[1].get("scale") == "0.96 0.96"
    tx = float(transforms[0].get("position").split()[0])
    # kohde x=0.3: ikkuna 1215 px, keskipiste 607,5 → sijainti keskittää sen
    # yhdistelmän omassa kehyksessä (960 px = 9,6/%).
    assert tx == pytest.approx(-(607.5 - 960) * 0.96 / 9.6)
    assert tx == float(transforms[1].get("position").split()[0])
    for k in (top, bottom):
        seq = _media_by_id(root, k.get("ref")).find("sequence")
        assert seq.find(".//adjust-crop") is None
        assert seq.find(".//adjust-conform").get("type") == "none"


def test_half_lanes_are_panel_sized_compounds_that_clip():
    """Puolikkaan zoomi 0,96 ylittää paneelin korkeuden (1080·0,96 = 1037 >
    960), ja ilman rajausta vain projektin reunat leikkaavat: saumassa
    näkyisi toinen kaista (Devin Review #252, 2026-11-20). Puolikkaat ovat
    nyt paneelinkokoisia yhdistelmäklippejä, joiden oma 1080×960-kehys
    leikkaa yli menevän — sama kuva kuin Ollin käsin varmistamassa
    korjauksessa, mutta sauma on tarkka."""
    root = _doc(xs=[0.3, 0.3, 0.3])
    clip = _spine(root)[0]
    top, bottom = [k for k in clip if k.tag == "ref-clip"]
    assert top.find("adjust-transform").get("position") == "0 25"
    assert bottom.find("adjust-transform").get("position") == "0 -25"
    assert top.get("srcEnable") == "video"
    assert bottom.get("enabled") == "0"   # alakaista on oletuksena pois päältä
    media = next(m for m in root.iter("media") if m.get("id") == top.get("ref"))
    seq = media.find("sequence")
    fmt = root.find(f".//format[@id='{seq.get('format')}']")
    assert (fmt.get("width"), fmt.get("height")) == ("1080", "960")
    inner = seq.find(".//asset-clip/adjust-transform")
    assert inner.get("scale") == "0.96 0.96"
    # Ikkunan keskitys on yhdistelmän omissa yksiköissä (960 px = 9,6/%).
    tx = float(inner.get("position").split()[0])
    assert tx == pytest.approx(-(607.5 - 960) * 0.96 / 9.6)
    assert seq.find(".//adjust-crop") is None


def test_full_lane_fills_the_frame_and_follows_the_subject():
    left = _spine(_doc(xs=[0.1, 0.1, 0.1]))[0]
    right = _spine(_doc(xs=[0.9, 0.9, 0.9]))[0]
    lt, rt = left.find("adjust-transform"), right.find("adjust-transform")
    # Koko ruutu: peittävä tasainen skaala 1920/1080, EI rajausta; kohteen
    # seuraaminen tapahtuu pelkällä sijainnilla (kuten ennen 2026-11-19
    # korjausta, mutta nyt ilman ikkunan kaksoiskäyttöä).
    assert lt.get("scale") == rt.get("scale") == "1.77778 1.77778"
    lx = float(lt.get("position").split()[0])
    rx = float(rt.get("position").split()[0])
    assert lx > 0 > rx  # kohde vasemmalla: kuvaa siirretään oikealle
    assert lx == pytest.approx(-(303.75 - 960) * (1920 / 1080) / 19.2)
    assert rx == pytest.approx(-(1616.25 - 960) * (1920 / 1080) / 19.2)
    assert _spine(_doc())[0].find("adjust-crop") is None


def test_emitted_transform_centres_the_window_on_the_panel():
    """Final Cutin varmistettu sääntö ilman rajausta (2026-11-19): kehys =
    lähde × tasainen skaala, keskittyy projektiin + sijainti, ja reunan
    yli menevä osa leikkautuu. Ikkunan keskipisteen on osuttava paneelin
    keskipisteeseen ja kehyksen on peitettävä paneeli."""
    from autoraffkat.finalcut.write_trailer import crop_window

    root = _doc()
    full = _spine(root)[0]
    top = next(k for k in full if k.tag == "ref-clip")
    top_inner = _media_by_id(root, top.get("ref")).find(".//asset-clip")

    def maps(clip, panel, frame_h=1920):
        at = clip.find("adjust-transform")
        s, s2 = map(float, at.get("scale").split())
        assert s == s2  # tasainen
        px, py = map(float, at.get("position").split())
        unit = frame_h / 100

        def point(x, y):
            return ((1080 - 1920 * s) / 2 + px * unit + x * s,
                    (frame_h - 1080 * s) / 2 - py * unit + y * s)

        win = crop_window(1920, 1080, panel[2], panel[3], 0.2)
        cx, cy = point(win[0] + win[2] / 2, win[1] + win[3] / 2)
        assert (cx, cy) == pytest.approx(
            (panel[0] + panel[2] / 2, panel[1] + panel[3] / 2), abs=0.5)
        # kehys peittää paneelin kaikkialla
        fx0, fy0 = point(0, 0)
        fx1, fy1 = point(1920, 1080)
        assert fx0 <= panel[0] + 0.5 and fx1 >= panel[0] + panel[2] - 0.5
        assert fy0 <= panel[1] + 0.5 and fy1 >= panel[1] + panel[3] - 0.5

    maps(full, (0, 0, 1080, 1920))
    # Puolikas: keskitys tapahtuu yhdistelmän omassa 1080×960-kehyksessä.
    maps(top_inner, (0, 0, 1080, 960), frame_h=960)


def test_dtd_order_conform_transform_then_connected_clips():
    """Ei rajausta (2026-11-19): jäljelle jäävät konformi ja siirto,
    sitten liitetyt klipit (puolikkaat ovat viittauksia yhdistelmiin)."""
    clip = _spine(_doc())[0]
    assert [k.tag for k in clip] == [
        "adjust-conform", "adjust-transform",
        "ref-clip", "ref-clip"]


def test_resolve_dialect_writes_1_9_with_src():
    root = _doc(dialect="resolve")
    assert root.get("version") == "1.9"
    assert root.find(".//asset").get("src")
    assert root.find(".//media-rep") is None


def test_mismatched_inputs_and_empty_pieces_are_errors():
    with pytest.raises(WriteError):
        _doc(xs=[0.5])
    with pytest.raises(WriteError):
        _doc(pieces=[], xs=[])
    with pytest.raises(WriteError):
        _doc(dialect="avid")


def test_ntsc_frame_rate_stays_frame_exact():
    root = _doc(src=_src(fd=Fraction(1001, 24000)),
                pieces=[(0.0, 3.337), (3.337, 10.0)], xs=[0.5, 0.5])
    clips = list(_spine(root))
    end = Fraction(0)
    for c in clips:
        end += _t(c.get("duration"))
    # kokonaiskesto on kehysten kokonaismäärä
    assert (end / Fraction(1001, 24000)).denominator == 1


def test_output_reads_back_with_our_own_reader(tmp_path):
    from autoraffkat.finalcut.read import read_fcpxml

    path = tmp_path / "t.fcpxml"
    path.write_text(build_trailer_fcpxml(
        _src(), [(0.0, 4.0), (4.0, 10.0)], [0.4, 0.6], "Review"), encoding="utf-8")
    tl = read_fcpxml(str(path))
    assert tl.frame_duration == Fraction(1, 25)
    assert any(m.path.endswith("trailer.mp4") for m in tl.media)


from conftest import needs_ffmpeg  # noqa: E402


@needs_ffmpeg
def test_plan_to_fcpxml_on_a_synthetic_three_scene_clip(tmp_path):
    from test_trailer import _synthetic

    from autoraffkat import trailer

    path = _synthetic(tmp_path / "t.mp4")
    src, cuts, xs = trailer.plan(path)
    assert len(cuts) == 3
    assert xs[0] < 0.4 < 0.6 < xs[2]
    root = ET.fromstring(build_trailer_fcpxml(src, cuts, xs, "Review"))
    assert len(list(_spine(root))) == 3
    # jaksotaulukkoa ei tarvitse laskea uudelleen: toinen kutsu käyttää välimuistia
    assert trailer.plan(path)[1] == cuts
    fixed = trailer.plan(path, every=3.0)[1]
    assert fixed[0] == (0.0, 3.0)


def _asset_url(asset):
    """Median osoite: FCP-murtumassa media-repissä, Resolven 1.9:ssä src-attribuutissa."""
    rep = asset.find("media-rep")
    return rep.get("src") if rep is not None else asset.get("src")


def test_connected_lanes_use_a_video_only_asset_so_audio_is_not_doubled():
    root = _doc()
    assets = {a.get("id"): a for a in root.findall(".//asset")}
    spine_ref = _spine(root)[0].get("ref")
    assert assets[spine_ref].get("hasAudio") == "1"
    lanes = [k for k in _spine(root)[0] if k.tag == "ref-clip"]
    assert lanes
    for lane in lanes:
        assert lane.get("ref") != spine_ref
        inner = _media_by_id(root, lane.get("ref")).find(".//asset-clip")
        assert inner.get("ref") != spine_ref
        assert assets[inner.get("ref")].get("hasAudio") is None
        url = _asset_url(assets[inner.get("ref")])
        assert url == "file:///media/trailer.mp4"
        assert url == _asset_url(assets[spine_ref])


def test_silent_source_keeps_a_single_asset():
    root = _doc(src=_src(audio=False))
    assert len(root.findall(".//asset")) == 1


def test_ntsc_rates_from_ffprobe_floats_snap_to_the_exact_fraction(monkeypatch):
    from autoraffkat import trailer
    for fps, expect in [(29.97, Fraction(1001, 30000)),
                        (23.976, Fraction(1001, 24000)),
                        (59.94, Fraction(1001, 60000)),
                        (119.88, Fraction(1001, 120000)),
                        (23.98, Fraction(50, 1199)),
                        (25.0, Fraction(1, 25))]:
        monkeypatch.setattr(trailer, "info", lambda p, fps=fps: {
            "video": {"width": 1920, "height": 1080, "fps": fps},
            "duration": 10.0, "audio": {}})
        assert trailer.probe_source("/x/t.mp4").frame_duration == expect


def test_export_errors_follow_the_language():
    from autoraffkat import i18n
    i18n.set_language("en")
    try:
        with pytest.raises(WriteError) as err:
            _doc(pieces=[], xs=[])
        assert "tyhj" not in str(err.value).lower()
        assert str(err.value).startswith("The ") or "piece" in str(err.value).lower()
        assert not str(err.value).startswith("trailer.")
    finally:
        i18n.set_language("fi")
    with pytest.raises(WriteError) as err:
        _doc(pieces=[], xs=[])
    assert not str(err.value).startswith("trailer.")
    assert "pala" in str(err.value).lower()
