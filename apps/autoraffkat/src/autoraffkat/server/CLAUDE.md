The browser interface. Moved from `apps/autoraffkat/CLAUDE.md`; the smoke-test rule stays there.

## The pair is a row, not a drawing

A close-up and its microphone are one thing, and the interface has to say so
without being read. It is a patch bay: one **slot** per row — video cell on the
left, audio cell on the right, the speaker's name once in the strip between
them. The pair is adjacency, so the cable is a horizontal line in a fixed-width
strip. It is CSS, not geometry: nothing is measured, nothing is redrawn on
hover or resize, and a crossing cable is not possible to express. The whole
`drawCables` / `chipEls` / `getBoundingClientRect` machinery that the two-list
layout needed is gone, and it should not come back.

The top row is for the tracks that belong to nobody: the wide shot and the room
tone. They are shared by the whole episode the way the other rows belong to one
person. Unassigned tracks live in a tray below the bay, not as rows — a track
with no slot has no pair and therefore no row.

**A slot sets the role.** `assign()` is the only place that writes
`config.role` and `config.speaker`, and it derives both from where the card
landed: video into a speaker slot is `close`, audio is `mic`, video into the
shared slot is `wide`, audio into it is `audio.room_track`, and the tray is
`unused`. There is no role menu any more. Add a new role and it needs a place
to sit, not a new option in a list.

The group shot is that rule applied once. A camera showing some speakers but
not all gets a row of its own (`+ group shot`), and the microphones of the
people in it are dropped on that row's audio side — a camera with two mics
is a two-shot, which is how people describe it. The name then lives on each
mic card, since the row holds several people. A mic sits on the group row
only when its speaker has no close-up of their own; someone who has one
stays on their row and joins the shot through the card's **Also in the
shot** buttons. Moving a mic away from the row takes the person out of the
shot (`pruneCovers`), so a shot never names someone nobody carries. The name is a reference, so renaming a slot or a mic card
rewrites it in every group shot (`renameCovers`); a name no microphone
carries is a roling problem, never silently dropped, because the symptom
would be a camera that is simply never used.

**The name is written once.** It lives on the slot, so a pair cannot break by a
typo on the second track — which is what the old per-track text field made easy
and invisible. Renaming a slot writes to every member track.

**Drag and click are one path.** `picked` holds the lifted track key; both
`dragstart` and a click on a card set it, and every drop target reads it.
`dataTransfer` carries the key too, but only as the native affordance — a
browser will not let `dragover` read it, and the keyboard has no `dataTransfer`
at all. `dropTarget()` wires all four events in one place so the mouse and the
keyboard cannot end up disagreeing about what is allowed.

Below 900 px the two columns cannot sit side by side. Then the slot stacks —
name first, then its video and audio cards — which is the same grouping in a
different direction, and the connector is hidden because adjacency already says
it.

## The first screen ranks controls; it does not hide them

The audio panel showed 26 sliders, eight of them for one feature. The rule:
**if you can write down the measurement that sets a default, the slider does
not belong on the first screen.** That separates the numbers we measured from
the few where taste varies — ducking depth, the plug-in's Mix, the platform
target. Nothing is removed: every control is still there, one disclosure
away, and now carries its measurement (`why.<key>` in `i18n.js`) beside the
number.

A row with two actions must not highlight as one. Switching a setting on and
looking inside it are different intentions, and a hover covering the whole
row — checkbox included — promises a single target where there are two. A
checkbox at the far left is read as the label's own checkbox, which makes
clicking the name look like it toggles. Opening is a button holding the name,
value and chevron, and only that highlights; the switch sits after it beside
the chevron. The switch is never inside the button: that would be one click
doing both things, and a control inside a `<button>` is invalid.

A preset's own numbers are its definition, not controls layered on it. The
rhythm preset's four sliders were always visible, and moving one switched the
preset to Custom in passing — the choice changed as a side effect. They now
appear only under Custom, carrying the values the preset had.

A closed row must show that something inside it changed, and name it.
Disclosure that hides a setting the user already moved is worse than no
disclosure — the knob vanishes and cannot be found. Same principle as
`project.name_tag` writing deviating controls into the export filename: the
deviation is visible one level up. `audio_defaults` comes from
`AudioSettings()` over `/api/state`, never a copy in JavaScript, because a
copy drifts silently and then the marker is wrong rather than missing.
Opening a row does not redraw the panel — that would swap a slider out from
under the cursor mid-drag.

## Static files are versioned

`index.html` is served with `app.js`, `i18n.js` and `style.css` given their
modification time as a query parameter. Without it the browser serves an old
stylesheet with a new script, and the layout breaks in a way nobody connects to
caching. This happened once already.
