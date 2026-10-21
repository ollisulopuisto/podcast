"""Picks the expressive frames of a video: scoring and ranking, no platform code."""

from framescore.ranking import FrameCandidate, rank_candidates, sharpness
from framescore.scoring import (
    assign_hands_to_faces,
    expression_score,
    gesture_score,
    head_shoulders_box,
)

__all__ = [
    "FrameCandidate",
    "assign_hands_to_faces",
    "expression_score",
    "gesture_score",
    "head_shoulders_box",
    "rank_candidates",
    "sharpness",
]
