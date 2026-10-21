"""Pure scoring helpers for picking expressive video frames. No platform calls here.

Inputs come from a face and pose detector (Apple Vision in pycapslap, the same
shapes in youthumber) already turned into plain tuples. Coordinates are Vision's:
normalized 0–1, origin bottom-left, y up. Face landmark points are relative to the
face's own bounding box.

The thresholds below are hand-set from Vision's coordinate ranges, not tuned on real
footage yet, so expect decent but imperfect ranking.
"""

from __future__ import annotations

import math

Point = tuple[float, float]
Joint = tuple[float, float, float]  # x, y, confidence
Box = tuple[float, float, float, float]  # x, y (bottom edge), width, height

MIN_JOINT_CONFIDENCE = 0.3
# How close a hand's wrist must be to a body-pose wrist to belong to that body.
MAX_ARM_DISTANCE = 0.08


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def expression_score(landmarks: dict[str, list[Point]]) -> float:
    """0–1: smiling (corners lifted, wide mouth), mouth open (talking), eyebrows raised."""
    outer = landmarks.get("outerLips") or []
    if len(outer) < 3:
        return 0.0

    left = min(outer, key=lambda p: p[0])
    right = max(outer, key=lambda p: p[0])
    width = right[0] - left[0]
    if width <= 0:
        return 0.0

    mid_y = _mean([p[1] for p in outer])
    corner_lift = ((left[1] + right[1]) / 2 - mid_y) / width
    smile = 0.5 * _clamp01((corner_lift + 0.02) / 0.14) + 0.5 * _clamp01(
        (width - 0.40) / 0.15
    )

    inner = landmarks.get("innerLips") or []
    opening = (
        (max(p[1] for p in inner) - min(p[1] for p in inner)) / width if inner else 0.0
    )
    mouth_open = _clamp01((opening - 0.08) / 0.35)

    brow_raise = 0.0
    brows, eyes = landmarks.get("leftEyebrow"), landmarks.get("leftEye")
    if brows and eyes:
        gap = _mean([p[1] for p in brows]) - _mean([p[1] for p in eyes])
        brow_raise = _clamp01((gap - 0.10) / 0.12)

    return 0.5 * smile + 0.3 * mouth_open + 0.2 * brow_raise


def gesture_score(hand: dict[str, Joint], face: Box, aspect: float = 16 / 9) -> float:
    """0–1: a hand raised to chest height or above; highest when the index finger points.

    ``aspect`` (width/height) makes x and y distances comparable in a 16:9 frame.
    """
    pts = {
        name: (x * aspect, y)
        for name, (x, y, conf) in hand.items()
        if conf >= MIN_JOINT_CONFIDENCE
    }
    if "wrist" not in pts or "middleMCP" not in pts:
        return 0.0
    palm = math.dist(pts["wrist"], pts["middleMCP"])
    if palm <= 0:
        return 0.0

    _, face_y, _, face_h = face
    raised = _clamp01((pts["wrist"][1] - (face_y - 2 * face_h)) / (2 * face_h))

    def extension(finger: str) -> float | None:
        tip, mcp = pts.get(f"{finger}Tip"), pts.get(f"{finger}MCP")
        return math.dist(tip, mcp) / palm if tip and mcp else None

    index = extension("index")
    others = [
        e for e in (extension(f) for f in ("middle", "ring", "little")) if e is not None
    ]
    pointing = 0.0
    if index is not None and others:
        pointing = _clamp01((index - 0.6) / 0.3) * _clamp01((0.8 - _mean(others)) / 0.3)

    return raised * (0.5 + 0.5 * pointing)


def _face_center(face: Box) -> Point:
    x, y, w, h = face
    return (x + w / 2, y + h / 2)


def _nearest_face(faces: list[Box], point: Point) -> int | None:
    if not faces:
        return None
    return min(range(len(faces)), key=lambda i: math.dist(_face_center(faces[i]), point))


def assign_hands_to_faces(
    faces: list[Box], bodies: list[dict], hand_wrists: list[Point]
) -> list[int | None]:
    """Which face each hand belongs to.

    A hand is matched to the body-pose skeleton whose wrist it sits on, and that
    skeleton to the face its nose is in, so an arm reaching across the frame still
    counts for its owner. Without a matching arm, the nearest face gets it.
    """

    def face_for_body(body: dict) -> int | None:
        nose = body.get("nose")
        if not nose or nose[2] < MIN_JOINT_CONFIDENCE:
            return None
        for i, (x, y, w, h) in enumerate(faces):
            if x <= nose[0] <= x + w and y <= nose[1] <= y + h:
                return i
        return _nearest_face(faces, nose[:2])

    body_faces = [face_for_body(b) for b in bodies]
    owners: list[int | None] = []
    for wrist in hand_wrists:
        best, best_distance = None, MAX_ARM_DISTANCE
        for body, face in zip(bodies, body_faces, strict=True):
            if face is None:
                continue
            for bx, by, conf in body.get("wrists", []):
                distance = math.dist((bx, by), wrist)
                if conf >= MIN_JOINT_CONFIDENCE and distance <= best_distance:
                    best, best_distance = face, distance
        owners.append(best if best is not None else _nearest_face(faces, wrist))
    return owners


def head_shoulders_box(
    face: Box,
    image_width: int,
    image_height: int,
    side: float = 1.2,
    above: float = 0.6,
    below: float = 2.4,
) -> tuple[int, int, int, int]:
    """Pixel crop (left, top, right, bottom; top-left origin) around a face that also
    takes in the shoulders and hands in front of the chest. Margins are in face sizes."""
    x, y, w, h = face
    face_w, face_h = w * image_width, h * image_height
    left = x * image_width - side * face_w
    right = (x + w) * image_width + side * face_w
    top = (1 - (y + h)) * image_height - above * face_h
    bottom = (1 - y) * image_height + below * face_h
    return (
        int(max(0, left)),
        int(max(0, top)),
        int(min(image_width, right)),
        int(min(image_height, bottom)),
    )
