# Automixer role commands

Approved follow-up to the overnight PR suggestions. Source on agent/approved-podcast-followup, not published/merged/released.

- `s` assigns selected tracks to speech, `m` to music, while the track selection or corresponding role button has focus. Other fields and selections do not trigger assignment.
- Both buttons and keys use the same TrackRoleActions implementation. Empty selection does nothing, multi-selection replaces roles by path.
- Bindings remain non-priority and appear in Textual's existing `?` help and footer. No new toolbar/speaker model.

Validation: six portable Textual tests pass (three existing/new key-help coverage plus role assignment/safety tests); five existing mlx-marked cases are excluded on Linux. Pinned Ruff0.17.2 passes across the repository. An isolated real-Textual role harness is visually inspected, not the full native audio mixer. No native mixer/audio validation or installer. No push/PR/CI under the current no-cost publication hold.
