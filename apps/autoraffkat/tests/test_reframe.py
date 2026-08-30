"""Reframing: the face lands on the centreline and the maths is known.

Every number here is derived in ``reframe.py`` from Apple's own FCPXML
documentation — position is percent of the project's height on both axes,
scale a fraction of the clip's fitted baseline — and the first real import
into Final Cut is what settles the derivation, not this file.
"""

from autoraffkat import reframe


def test_fill_scale_of_16x9_source():
    """16:9 source in a 9:16 project: fill the height, scale 3.1605."""
    r = reframe.plan_shot(0.5, 1920, 1080)
    assert r is not None
    assert abs(r.scale - 3.1605) < 0.001
    assert r.pos_x == 0.0
    assert r.pos_y == 0.0


def test_face_left_of_centre_moves_picture_right():
    """cx 0.3: the picture shifts right so the face lands on the centreline.

    Displayed width after fill is 3413 px; a 20 % shift of that is
    0.2 · 3413 / 19.2 ≈ 35.5 percent-of-height units.
    """
    r = reframe.plan_shot(0.3, 1920, 1080)
    assert r.pos_x > 0
    assert abs(r.pos_x - 35.55) < 0.5


def test_face_right_of_centre_moves_picture_left():
    r = reframe.plan_shot(0.7, 1920, 1080)
    assert r.pos_x < 0
    assert abs(r.pos_x + 35.55) < 0.5


def test_position_never_reveals_a_gap():
    """The clamp holds inside the content even for a face at the frame edge.

    A nonzero offset may never show anything beside the content: at
    percent-of-height units the offset in pixels is pos_x · 19.2, and the
    content has (displayed − project) / 2 pixels of slack on each side.
    """
    displayed = 1920 * 1920 / 1080
    slack = (displayed - 1080) / 2
    for cx in (0.0, 0.05, 0.5, 0.95, 1.0):
        r = reframe.plan_shot(cx, 1920, 1080)
        assert abs(r.pos_x) * 19.2 <= slack + 0.01


def test_no_source_dims_gives_nothing():
    """Without dimensions there is nothing to compute — and no transform."""
    assert reframe.plan_shot(0.5, 0, 0) is None


def test_source_already_taller_than_16x9_is_identity():
    """A source that already fills the height needs no crop — none is written.

    Fit already fills the height when the source is narrower than 9:16; a
    scale would only magnify. 1080×1920 is the extreme case.
    """
    assert reframe.plan_shot(0.3, 1080, 1920) is None
