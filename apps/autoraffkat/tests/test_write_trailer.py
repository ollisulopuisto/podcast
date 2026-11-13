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
    return root.find(".//spine")


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
        kids = [k for k in clip if k.tag == "asset-clip"]
        assert [k.get("lane") for k in kids] == ["1", "2"]
        assert kids[0].get("name").startswith("Top")
        assert kids[1].get("name").startswith("Bottom")
        # liitetyn klipin offset on isännän lähdeaika: sama kuin isännän start
        assert kids[0].get("offset") == clip.get("start")
        assert kids[0].get("start") == clip.get("start")
        assert kids[0].get("duration") == clip.get("duration")


def test_default_enablement_is_top_half_only():
    root = _doc()
    clip = _spine(root)[0]
    top, bottom = [k for k in clip if k.tag == "asset-clip"]
    assert top.get("enabled") in (None, "1")
    assert bottom.get("enabled") == "0"
    assert clip.get("enabled") in (None, "1")


def test_enabled_lane_can_be_bottom_or_none():
    for choice, want in (("bottom", ("0", None)), ("none", ("0", "0"))):
        top, bottom = [k for k in _spine(_doc(enabled_lane=choice))[0]
                       if k.tag == "asset-clip"]
        assert top.get("enabled") == want[0] or (want[0] is None and top.get("enabled") in (None, "1"))
        assert bottom.get("enabled") == want[1] or (want[1] is None and bottom.get("enabled") in (None, "1"))
    with pytest.raises(WriteError):
        _doc(enabled_lane="left")


def test_audio_only_on_the_spine_clip():
    root = _doc()
    clip = _spine(root)[0]
    assert clip.get("srcEnable") is None
    for k in clip:
        if k.tag == "asset-clip":
            assert k.get("srcEnable") == "video"
    root = _doc(src=_src(audio=False))
    assert root.find(".//asset").get("hasAudio") is None


def test_half_lanes_have_the_same_zoom_and_mirror_positions():
    clip = _spine(_doc(xs=[0.3, 0.3, 0.3]))[0]
    top, bottom = [k for k in clip if k.tag == "asset-clip"]
    tt = top.find("adjust-transform")
    bt = bottom.find("adjust-transform")
    assert tt.get("scale") == bt.get("scale")
    ty = float(tt.get("position").split()[1])
    by = float(bt.get("position").split()[1])
    assert ty == pytest.approx(-by)
    assert ty > 0
    assert top.find("adjust-crop") is not None
    assert top.find("adjust-conform").get("type") == "none"


def test_full_lane_fills_the_frame_and_follows_the_subject():
    left = _spine(_doc(xs=[0.1, 0.1, 0.1]))[0].find("adjust-transform")
    right = _spine(_doc(xs=[0.9, 0.9, 0.9]))[0].find("adjust-transform")
    lx = float(left.get("position").split()[0])
    rx = float(right.get("position").split()[0])
    assert lx > 0 > rx  # kohde vasemmalla: kuvaa siirretään oikealle
    assert left.get("scale") == right.get("scale")
    crop = _spine(_doc())[0].find("adjust-crop/crop-rect")
    assert float(crop.get("left")) + float(crop.get("right")) > 50


def test_dtd_order_crop_conform_transform_then_connected_clips():
    clip = _spine(_doc())[0]
    assert [k.tag for k in clip] == [
        "adjust-crop", "adjust-conform", "adjust-transform",
        "asset-clip", "asset-clip"]


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
    assert len(list(root.find(".//spine"))) == 3
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
    lanes = [k for k in _spine(root)[0] if k.tag == "asset-clip"]
    assert lanes
    for lane in lanes:
        assert lane.get("ref") != spine_ref
        assert assets[lane.get("ref")].get("hasAudio") is None
        url = _asset_url(assets[lane.get("ref")])
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
