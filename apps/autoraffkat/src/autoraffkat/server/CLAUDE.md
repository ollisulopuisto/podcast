The browser interface. Moved from `apps/autoraffkat/CLAUDE.md`; the smoke-test rule stays there.

## Visibility is assigned per shot

The setup asks which speakers are visible on each video track. A video card
shows the track and one checkbox per known speaker; the `covers` list on that
track is the single source for all of those selections. A speaker may appear
on several tracks, and one track may cover several speakers. Do not turn shots
into speaker slots or require a special wide/group/close role.

A separate context checkbox marks the preferred establishing shot. It writes
`config.context`; an enabled video track writes `role: "shot"` and its
`config.covers`, while a track with neither coverage nor context writes
`role: "unused"`. Audio tracks are independent: a named microphone writes
`role: "mic"` and `config.speaker`, otherwise it is unused. Microphone names
form the editable speaker roster, and renaming the last microphone for a
speaker updates all video `covers` references atomically.

The server persists settings format 2 and migrates saved close/group/wide roles
before returning state to the browser. Keep the browser payload on the same
`tracks[key].role/covers/context` shape; do not create a second client-side
coverage model. Track keys are stable shot identities. Coverage labels can
repeat, so preview coloring and cut rows must resolve a shot by its track key
rather than by label.

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
