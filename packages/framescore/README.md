# framescore

Picks the expressive frames of a video. Pure Python, no platform code: the
detector (Apple Vision on macOS, for now) turns its results into plain tuples,
and this package scores and ranks them.

- `scoring`: expression (smile, open mouth, raised eyebrows), gesture (a raised
  hand, most of all a pointing one), linking hands to people through their arm,
  and the head-and-shoulders crop.
- `ranking`: `FrameCandidate`, `rank_candidates` (capture quality weighted 0.7,
  normalized sharpness 0.3) and `sharpness`, an edge-variance measure on grey pixels.

Coordinates follow Vision: normalized 0–1, origin bottom-left, y up.

Used by `pycapslap` (thumbnail suggestions) and `youthumber`. Nothing here imports
either app. The weights and thresholds are hand-set, not tuned on footage yet.

```
uv run --directory packages/framescore pytest -q
```
