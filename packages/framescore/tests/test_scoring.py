"""Tests for the pure scoring helpers: expression, gesture, hand-to-person linking, crops."""

from framescore.scoring import (
    assign_hands_to_faces,
    expression_score,
    gesture_score,
    head_shoulders_box,
)


def _lips(corner_y: float, width: float, mid_y: float, inner_open: float) -> dict:
    left, right = 0.5 - width / 2, 0.5 + width / 2
    outer = [
        (left, corner_y),
        (0.5, mid_y + 0.03),
        (right, corner_y),
        (0.5, mid_y - 0.03),
    ]
    inner = [(0.45, mid_y + inner_open / 2), (0.55, mid_y - inner_open / 2)]
    return {"outerLips": outer, "innerLips": inner}


NEUTRAL = {
    **_lips(corner_y=0.25, width=0.40, mid_y=0.25, inner_open=0.02),
    "leftEyebrow": [(0.3, 0.70)],
    "leftEye": [(0.3, 0.62)],
}


def test_a_smile_scores_higher_than_a_neutral_mouth() -> None:
    smile = {**NEUTRAL, **_lips(corner_y=0.31, width=0.52, mid_y=0.25, inner_open=0.02)}

    assert expression_score(smile) > expression_score(NEUTRAL) + 0.2


def test_an_open_mouth_scores_higher_than_a_closed_one() -> None:
    talking = {
        **NEUTRAL,
        **_lips(corner_y=0.25, width=0.40, mid_y=0.25, inner_open=0.16),
    }

    assert expression_score(talking) > expression_score(NEUTRAL) + 0.1


def test_raised_eyebrows_add_to_the_expression_score() -> None:
    surprised = {**NEUTRAL, "leftEyebrow": [(0.3, 0.84)]}

    assert expression_score(surprised) > expression_score(NEUTRAL)


def test_expression_score_is_between_0_and_1_and_tolerates_missing_regions() -> None:
    assert 0.0 <= expression_score(NEUTRAL) <= 1.0
    assert expression_score({}) == 0.0


FACE = (
    0.4,
    0.5,
    0.2,
    0.3,
)  # x, y (bottom, y up), width, height — normalized image coords


def _hand(wrist_y: float, index_ext: float, others_ext: float) -> dict:
    # A hand pointing straight up; palm length 0.06 from wrist to the middle knuckle.
    wrist = (0.5, wrist_y)
    mcp_y = wrist_y + 0.06
    hand = {"wrist": (*wrist, 0.9)}
    for finger, ext in [
        ("index", index_ext),
        ("middle", others_ext),
        ("ring", others_ext),
        ("little", others_ext),
    ]:
        hand[f"{finger}MCP"] = (0.5, mcp_y, 0.9)
        hand[f"{finger}Tip"] = (0.5, mcp_y + 0.06 * ext, 0.9)
    return hand


def test_a_raised_pointing_hand_is_the_strongest_gesture() -> None:
    pointing = gesture_score(_hand(0.3, index_ext=1.0, others_ext=0.3), FACE)
    open_hand = gesture_score(_hand(0.3, index_ext=1.0, others_ext=1.0), FACE)
    fist = gesture_score(_hand(0.3, index_ext=0.3, others_ext=0.3), FACE)

    assert pointing > open_hand > 0
    assert pointing > fist


def test_a_hand_low_in_the_lap_is_not_a_gesture() -> None:
    low_face = (0.4, 0.7, 0.1, 0.15)

    assert gesture_score(_hand(0.3, index_ext=1.0, others_ext=0.3), low_face) == 0.0


def test_gesture_score_ignores_low_confidence_joints() -> None:
    hand = {k: (x, y, 0.1) for k, (x, y, _) in _hand(0.3, 1.0, 0.3).items()}

    assert gesture_score(hand, FACE) == 0.0


def test_hands_are_linked_to_people_through_their_arm_not_the_nearest_face() -> None:
    # 2026-09-23 frame: the host (left) points across the frame; his hand is closer to
    # the guest's face, but body pose puts the host's wrist right at it.
    host_face = (0.12, 0.55, 0.18, 0.32)
    guest_face = (0.69, 0.5, 0.16, 0.3)
    bodies = [
        {
            "nose": (0.206, 0.708, 0.76),
            "wrists": [(0.565, 0.329, 0.73), (0.155, 0.357, 0.74)],
        },
        {"nose": (0.742, 0.65, 0.82), "wrists": []},
    ]
    hand_wrists = [(0.57, 0.35), (0.16, 0.36)]

    assert assign_hands_to_faces([host_face, guest_face], bodies, hand_wrists) == [0, 0]


def test_a_hand_with_no_matching_arm_goes_to_the_nearest_face() -> None:
    faces = [(0.1, 0.5, 0.2, 0.3), (0.7, 0.5, 0.2, 0.3)]

    assert assign_hands_to_faces(faces, [], [(0.85, 0.3)]) == [1]
    assert assign_hands_to_faces([], [], [(0.5, 0.5)]) == [None]


def test_head_shoulders_box_extends_below_the_face_and_stays_in_frame() -> None:
    face = (0.4, 0.5, 0.1, 0.2)  # y is the face's bottom edge, y up
    left, top, right, bottom = head_shoulders_box(face, 1920, 1080)

    face_top_px = (1 - 0.7) * 1080
    face_bottom_px = (1 - 0.5) * 1080
    assert top < face_top_px
    assert bottom > face_bottom_px + 2 * 0.2 * 1080
    assert left < 0.4 * 1920 < 0.5 * 1920 < right

    edge = head_shoulders_box((0.0, 0.0, 0.3, 0.4), 1920, 1080)
    assert edge[0] == 0 and edge[3] == 1080
