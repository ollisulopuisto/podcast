# autoraffkat

FCPXML in, FCPXML out. The picture cuts to whoever is talking. Nothing is
rendered.

Code, comments and docstrings are in **Finnish** — they are for the
maintainers. Documentation and everything the user sees is in English and
Finnish. Keep it that way.

## Two layers, don't mix them

`audio/envelope.py` is slow (ffmpeg, seconds) and cached to disk. Write the
cache through an open file handle: `np.save` appends `.npy` to a *path* that
lacks it, so saving to `<key>.npy.tmp` wrote `<key>.npy.tmp.npy` and the
rename then failed silently into `except OSError`. The cache never worked and
nothing said so — test the property, never the speed, because a fixture small
enough to be fast hides a cache that is missing every time. `decide.py`
is fast (numpy, milliseconds) and runs on every adjustment. No file reading may
leak into `decide.py` or into `analysis.build_grid` which it calls — that
breaks the interface response time, which is the single most important
requirement here.

`decide.py` must not loop over individual samples either. Loops walk runs
(`_runs`), of which there are thousands, not samples, of which there are
hundreds of thousands.

## Time is a Fraction

All time read from and written to XML passes through `timeline.py` as a
`Fraction`. Floating point is acceptable only in the analysis layer. The
reason: rounding error accumulates over thousands of frames and leaves gaps on
the timeline.

FCPXML time semantics: a clip's `offset` is in the host's local time base,
whose zero is the host's `start`. A child's absolute position is therefore
`host_absolute + (child_offset - host_start)`. This applies to attached clips
and to sync-clip contents alike, and it is the entire idea behind
`fcpxml/read.py`'s `_walk`.

In a multicam, additionally: the angle's content must be clipped to the
`mc-clip`'s duration (`_walk`'s `bounds`), because an angle spans the whole
multicam and the same multicam can appear on the spine twice.

In a sync-clip, Final Cut represents detached and deactivated audio components
using `<sync-source><audio-role-source role="…" active="0"/></sync-source>`.
The reader collects these muted roles and ignores matching `<audio>` and
`<asset-clip>` elements. Role matching is downward: muting `dialogue` mutes
`dialogue.dialogue-1`, but muting a specific sub-role leaves other sub-roles
and the parent active.

## A track is not a media file

The unit of roling is `Timeline.tracks`, not `Timeline.media`. In a multicam
the same angle is a different file in each part but one track. Everything that
reads roles, controls or `Segment.angle` speaks in track keys. Without this,
`Roles.wide_key` and `closes` would be lists and every site reading them would
have to handle several keys.

A synced angle is two tracks, not one. The usual Final Cut workflow syncs
each camera with one microphone and builds the multicam from the pairs, so an
angle is a sync clip holding a camera and a mic. Grouped by angle, the pair
was one card that could not take two roles; the same angle carried the
guest's mic in one part and Mikko's in the next; and a mic sitting in two
angles (a part with fewer mics than cameras) was on two tracks and played
twice. `_build_tracks` therefore splits such an angle: the camera is grouped
by angle as before, the mic by file name with the part counter dropped
(`_group_sounds`): first `Tomi_001`/`Tomi_002`, then names that differ in one
counter position (`Tomi 1`/`Tomi 2`, `Vieras-A`/`-B`, `ZOOM0001_Tr2`/
`ZOOM0002_Tr2`). Never two files of the same multicam, and never when two
files of one multicam fit the same pattern (`Mic 1`, `Mic 2` then `Mic 3`):
that is a guess that would make two people one track, while leaving them
apart costs one extra card. Plain one-file angles keep their old keys, so saved roles
still inherit.

The export follows. When the picture's angle holds a mic, that angle is
`srcEnable="all"` with the camera's role off and the mic's on — `video` would
silence the person on screen. A mic in two angles plays from the picture's
angle when it is there, otherwise from an angle already playing another
mic, otherwise its first — never from two. An angle can hold several mics (a
camera synced to a multitrack recorder): it is one `mc-source` with all of
them, and a mic of that angle that plays from elsewhere is written
`active="0"` rather than left out, since an unlisted role may play. Roles
are stamped on the **mic's clip**, not the whole angle: a camera muted by the
role `dialogue.dialogue-1` would otherwise take the mic's role, fall out of
the mute and sum under the mic. Established from a real project (hmh hannes,
2026-09-24) and not yet by importing the result into Final Cut — do that
before trusting it.

## Roles are inherited between episodes

A new episode with no settings of its own reads the nearest previous
`*.autoraffkat.json` and takes the roles of matching track keys from it. This
is the entire reason a track key is derived from the filename rather than the
angle name or `angleID`: in a series the cameras stay, the angle numbers do
not. Change how the key is derived and inheritance stops working silently.

Loading a plug-in and using one are different rules. pedalboard loads only
on the main thread; it processes from any thread. The error text says
"pass reset=False if calling this plugin from a non-main thread", which
points at processing and hides that the constraint is on loading — a lazy
per-thread load looks reasonable and fails every time. `PluginPool` builds
every instance in its constructor, on whichever thread constructs it, and
hands one to each piece.

The plug-in runs in a child process, and that is not an optimisation.
pedalboard loads a VST3 only on the **main thread**; the server's main thread
is the event loop and cannot be held for minutes. Hosting it in the server
worked by luck until it stopped. `audio/worker.py` reads a job on stdin and
reports progress as line-delimited JSON, so a plug-in that crashes takes
nothing else with it, and the child builds its own envelopes — which is why
ducking can no longer be skipped for lack of them.

Ducking must never fail quietly. It depends on the envelopes, which are
computed in a background thread on load, and pressing the button first left
the grid unbuilt and the masks empty with nothing said. The setting read
-9 dB and the output had none. Processing now waits for the analysis, and
"the setting is on and no microphone matched a mask" is an error, not a
silence — because the symptom is not silence either: independent
normalisation lifts each microphone's bleed of the other speaker, separation
drops from 19.2 dB to 15.2, and the same voice arriving twice a few
milliseconds apart is a comb filter. It is audible only when both tracks
play together, which is to say only after the export.

The same silent-failure class hit debleed, independently, because it reads
the same grid on its own condition. `audio/worker.py` built the speaker grid
`if audio.duck:` only; `mix.py` needs it separately for debleed
(`solo_masks(grid) if settings.debleed else {}`) and already turns a missing
grid into `result.errors["debleed"]` rather than silence — but only if the
grid was ever attempted. With duck off and debleed on, the grid stayed
`None` and debleed no-opped with no error and no warning short of the
terminal log line, on real material two independently very quiet mic tracks
(source ≈ −36 to −39 LUFS) each got +26 dB / +35 dB of makeup gain to reach
target with their bleed of each other un-removed. The fix builds the grid
whenever `duck or debleed` is on, in `worker.py`, not in `mix.py` — the
function already had the right contract, the caller just didn't always
give it what the contract needed.

A de-clicker's threshold is a rate, not a multiplier. Correcting the
reference from a local maximum to a local mean without changing the
multiplier turned a no-op into a distortion generator: measured on real
speech, 2 % of all samples, 550–640 corrections per second, the signal
altered −10 dB relative to itself. It passed every test, because the tests
asked whether a planted click was removed and never how many were found.
Calibrate on how often the artefact really occurs — lip smacks are a few a
minute — and keep the ceiling in `declick`, which raises the threshold until
the findings fit and corrects nothing if they never do.

The plug-in slot is flavour, not a replacement mechanism. There is one
slot, it runs first, and it never stands in for a stage of the chain. The
reason it exists at all is that a speech-restoration model is the one thing
here we have no opinion about and cannot ship; everything after it —
de-essing, the three bounded compressors, the true-peak ceiling, the
normalisation order — was measured, and those numbers are the tool. Letting
a second plug-in in would quietly undo them: someone loads a limiter in
front of ours and the ceiling guarantee stops being true with nothing to say
so. A user who wants their own chain should cut here and master in their
DAW. This is an automation tool, not a worse DAW.

A plug-in window from a plain Python process opens behind everything. The
window is created — measured 536×392 at (0, 37), on screen, thirteenth from
the front — but macOS does not treat the process as a GUI application, so it
never comes forward and the button looks broken. `speechmix.editor` sets
`NSApplicationActivationPolicyRegular` and activates, once before opening and
once after the plug-in has drawn. The title is pedalboard's ("Pedalboard"),
not the plug-in's.

Not everything that changes the result is a parameter. dxRevive publishes
four automatable parameters and the **model selector is not one of them** —
Studio 2 lives in the plug-in's own state, reachable only through its own
interface. `speechmix.editor` opens that interface in a child process
(`show_editor` is main-thread-only *and* blocks until the window closes, so
it cannot run in the server) and saves `raw_state` with the episode. Both
ends of that child process are the library's — the window and the parser
that reads it — because a host that reads the line protocol without knowing
what writes it is guessing; `server/app.py` calls `open_editor` and stores
what comes back. State
is applied before parameters so a saved value cannot override the panel's
slider; a state from another plug-in is opaque and is ignored rather than
raised. It is in `FINGERPRINT_FIELDS`, because a different model is a
different result.

Bleed is linear, so subtract it — do not gate it. The same voice in two
microphones a few milliseconds apart is a comb filter, and it is what a
summed pair sounds like when it sounds metallic. Ducking cannot reach it:
measured on a real episode, the masks fired correctly and closed the
microphone on 64 % of the frames where only the other person spoke, and
*infinite* attenuation still moved the ripple only 6.22 dB → 6.01, because
the gaps fall on the turn-taking boundaries where the bleed is loudest — and
overlapping speech needs both microphones open regardless. `audio/debleed.py`
estimates the leakage path as an FIR filter over the passages where only the
source speaks and subtracts it everywhere: coherence 0.1069 → 0.0098 after
the chain, own speech kept at r = 0.9993. It runs on the raw audio **before**
the plug-in, because a generative plug-in does not preserve the linear
relation between tracks and after it no filter can remove the bleed. And it
measures its own output: a filter that eats the target's own speech is
refused with a reason, because that mistake is only audible after the export.

The level rider comes first, and it cannot work from the signal alone.
A slow level ride before the compressors is the stage every hand-made mix
starts with and ours lacked: it removes the speaker's *own* variation so the
compressor only has to catch what is left, instead of doing the rider's job
badly — fast and level-dependent instead of slow and even.

Two things had to be measured before it worked, and both went the wrong way
first. **Deciding "speech" from the level is worse than not riding at all.**
On a two-microphone recording half of what is loud on a track is the other
person: measured, the level heuristic called 74 % of Nyman's blocks speech
when 53 % were his own, and the two agreed on only 38 %. The rider dutifully
lifted the leakage — the noise floor rose 3.5 dB and the level spread got
*worse*, 2.88 → 3.37 dB. So the mask comes from the grid, the same
raw-measured source ducking uses, and without a mask `ride` returns the audio
untouched rather than guessing.

**And the gain must return to unity outside its own speaker's speech, not
hold.** Holding is what a one-microphone rider does and it is right there;
here the pause *is the other person talking*, so a held boost lands straight
on their leakage. Measured, separation between own speech and leakage fell
19.1 → 14.8 dB. Returning to zero keeps it at 18.7.

What it is worth, measured on ten minutes of real speech: own-speech level
spread 6.72 → 6.44 dB and 6.46 → 5.67 dB, with separation and noise floor
unchanged. Modest, because real speech variation is mostly sentence-scale
emphasis, which the rider deliberately leaves alone. Note also what the same
measurement said about the premise: the compressor does **not** cost
separation either (19.1 → 19.0), so the rider is not the answer to leakage —
de-bleeding still is.

Compute the lags you need, never the whole correlation. `debleed.path`
wants 2048 lags and was slicing them out of a full `2n-1` correlation. A
64-minute microphone is 184 million samples, so that correlation is 368
million floats and its FFT rounds up to the next fast length — gigabytes. At
20 minutes it survived; at 64 it did not, and the "no path" guard turned the
failure into a **reason string instead of an error**. The symptom was that
de-bleeding worked on the short parts of an episode and silently gave up on
the long ones, which reads as "this material is harder" rather than as a bug.
`_lags` accumulates the same sums blockwise: identical to 1e-16 relative,
36 s for the whole file, and both directions now solve at −4.12 and −3.77 dB
with own speech kept at 0.9998.

This is the third instance of the same mistake in this codebase, after
`np.correlate(..., "full")` in the shift measurement and `keyframe_times`
reading every packet to pick 24 frames. When a computation ends in a slice,
check what it computed to get there.

The block's tail must be **zero-padded, not shortened**. When the signal runs
out, a shortened window makes `correlate(..., "valid")` return a single
value, so only lag zero is filled and the "filter" is one number rather than
a path. That hits the final block of every run, and it looks like it worked.

Independent per-microphone normalisation lifts bleed. Two microphones
normalised to the same LUFS get different gains — measured +25.6 dB and
+22.5 dB on one episode — and the 3.1 dB difference lands on the quieter
microphone's bleed of the louder speaker, worsening the comb by exactly that
much. A gentle level rider per track with the loudness set on the programme
avoids it; our chain does not, which is part of why de-bleeding is needed.

## Where people sit is measured, not configured

`staging.py` derives the seating order from the same Vision measurements the
reaction layer already caches, so it costs nothing extra and belongs in the
settings loop. The measure is `turn` — the nose relative to the midpoint of
the eyes — and **its sign is the opposite of the obvious guess**: two people
sitting opposite each other look at each other, so the one on the *left*
looks *right* and has a positive `turn`. Measured on a real episode, the
left-hand speaker read +0.46 and the right-hand one −0.28, the same in both
parts. This was settled by extracting frames and looking at them, not by
reasoning about coordinate systems, because the reasoning gives the wrong
answer confidently. Framing (`cx`) does not work for this: on the same
episode both speakers sat in the right half of their own close-up, +0.51 and
+0.60, which describes the camera operator rather than the room.

The pan positions are spread evenly by *order*, never in proportion to the
measured angle: the angle gives the ordering reliably and the distance not at
all, since it depends on how the chairs happen to be turned and on the lens.
Three speakers are therefore left, centre, right. The spread is tiny on
purpose — a few percent, ±3 at the widest — because speech belongs in the
middle and a wide spread turns a two-hander into a radio play. Above five
speakers nothing is panned: the positions would be closer together than the
measurement is accurate, and then centre beats almost-centre.

Panning goes on the **angle**, not on the clip. Final Cut writes
`adjust-panner` in both places, and only one of them is the feature: a panner
on the `mc-clip` moves every angle together, which is turning the desk rather
than panning, and both speakers land in the same spot. The per-angle form
lives inside `<audio-role-source>`, and it was settled by having Final Cut
write one — the DTD permits it in both places and predicts neither. Three
literals came out of that file and none were guessable: the mode is the
string `"1 (Stereo Left/Right)"`, volume values carry their unit (`"-27dB"`),
and a `<keyframe time=…>` is in the **host's local time base**, the same base
as the `mc-clip`'s `start`, not timeline time. `adjust-volume` and
`adjust-panner` also come *before* `mc-source` in the DTD's order.

Panning does not need the reaction measurement, and must not wait for it.
The two features ask different questions at different prices: reactions look
for *moments*, so every keyframe is a candidate and the decode is minutes;
seating decides one sign per speaker. Measured, **five random frames got the
sign right 400 times out of 400** — the classes sit at +0.46 and −0.28, so
the median settles immediately. `measure.sample_file` therefore takes 24
frames spread across the file, which is far more than needed on purpose,
because some frames have no face in them and the sample must not shrink to
nothing by chance. `SIDE_MIN_FRAMES` is 5 for the same reason it is not 100:
a hundred would have forced the full decode back.

The trap there is `keyframe_times`, and it is the entire cost. It reads
every packet in the file with ffprobe, which on a 20-minute clip is longer
than the frame extraction it was meant to serve — the first version of the
light scan timed out at five minutes doing nothing else. The sample needs no
timestamps at all: `-ss` finds the nearest keyframe by itself, and a seating
position is not tied to a moment. `measure.duration` reads one header field
instead, and the scan went from over 300 s to **22.9 s serial**, four files
in parallel after that.

Both switches start their own scan. A feature that silently requires another
feature's button to have been pressed is a feature that looks broken, so
turning panning on samples the picture and turning reaction shots on starts
the full measurement. The buttons stay, because a minutes-long run is
something you may want to repeat deliberately.

Panning is on or off, and the amount is not a setting. "How much panning"
is a question the user has no answer to — it is precisely the number this tool
exists to decide, and offering it as a slider is handing the responsibility
back. The width lives in `staging.PAN_WIDTH` where it can be measured and
argued about; a test fails if a pan amount reappears in `Globals` or
`TrackConfig`. This is the same rule as "if you can write down the
measurement that sets a default, the slider does not belong on the first
screen", taken one step further: here it does not belong on any screen.

What the panel shows instead is **where the speakers were placed** — left,
centre, right — and it shows it whether the switch is on or off. Panning that
is the wrong way round sounds perfectly fine until you compare it with the
picture, so the placement has to be checkable without exporting first. Same
rule as the reaction lane being drawn while its switch is off.

Nothing is written when the pan is zero. An empty `adjust-panner` is a
setting like any other as far as Final Cut is concerned, so an unmeasured
episode has to produce byte-for-byte the file it produced before the feature
existed; a test asserts exactly that.

## Sensitivity and gain are not the same thing

Sensitivity is a threshold above the noise floor, so gain does not move it —
the floor moves by the same amount. Gain only affects how microphones compare
against each other during overlapping speech. Change this and the controls
start interfering with each other.

A microphone is always mono out, even from a stereo source. Two channels
break the arithmetic in three places silently: de-bleeding reads only the
first channel, the programme ceiling sums stems of differing channel counts
by broadcasting them, and panning is a mono-source idea to begin with. The
`mono` flag is in the fingerprint, so a stereo source that used to be
processed as stereo counts as stale.

`audio/CLAUDE.md` holds the sections that were here (loaded when working in that directory).

## Microphone to the angle, room tone to a lane — and why

Microphone audio goes into the export inside the multicam clip (`mc-source`),
so it cannot lose sync no matter how the user edits in Final Cut. Room tone is
a connected clip, because `mc-source` has no level control — and therefore it
**can** drift on a ripple edit. If someone finds a way to make room tone an
angle with a level, that is an improvement.

`video/CLAUDE.md` holds the sections that were here (loaded when working in that directory).

## The rhythm engine, and why you will miss it

`decide.py` is not a threshold machine. It carries an editing model added in
v26.08.22.48, and nothing in the module names says so — a whole session was
spent rebuilding reaction-shot placement from scratch before noticing it was
already there. If you are about to decide *when* something appears on
screen, read this first.

**1/f tempo** (`_compute_tempo`). Turn-taking rate over a rolling 45 s
window, normalised to its own mean and clipped to 0.7–1.4. It scales the
local minimum shot length as `min_shot / sqrt(tempo)`: quick exchanges cut
faster, monologues slower. Two traps are already paid for. The window slides
inward at the edges instead of shrinking, because a zero-padded convolution
read the first and last 22 seconds as the slowest material in the programme
regardless of content. And it is a summed-area table, not a convolution: the
window is 2250 steps and the direct version cost 75 ms on a two-hour
programme — most of the decision layer, which has to stay in milliseconds.

**J-cuts and L-cuts** are `lead` and `hang`. Lead moves the picture *before*
the new speaker starts; hang keeps the previous face while they fall silent.
Hang is refused during overlapping speech, because then the cut is not caused
by anyone stopping.

**Pause snapping.** Long monologues break at real speech pauses or breath
dips, not on a timer.

**Presets are this model's parameters**, not a preference: broadcast 2.5 s
minimum with J/L cuts, mellow 4.5 s, hectic 1.4 s.

**The programme always starts and ends on the wide, and it is not a
setting.** `_bookend_wide` runs last, after `_force_wide`. The first shot
tells the viewer where they are and who is in the room; a programme opening
on a close-up drops them into a face without the space. The last one lets
go. Removing it in Final Cut is one cut, and that is exactly why it is not
an option: flipping a default costs one drag once, an option costs every
user a decision — the same reasoning as panning having no amount slider.
The length is the programme's own `min_shot`, not a constant of its own, or
it would drift against the rhythm presets where 1.4 s and 4.5 s mean
different shots. A shot too short to split — under two minimums — becomes
wide whole, because one decent shot beats two flashes, and a programme with
no room for three shots is honestly all wide.

Note what it does **not** override: `wide_every=0` still means "never break
a long take to the wide". Two different rules, and the tests read the middle
of the cut (`middle()` in `test_decide.py`) so that every other rule is
measured without the bookends in the way.

The reaction layer cannot undo it, and that is load-bearing rather than
lucky. Reaction shots go on a positive lane, i.e. over the picture, so they
could cover the opening frames — except `fits` demands `min_shot` of margin
at both edges of the host shot, and a bookend is exactly `min_shot` long.
Shrink that margin and you silently switch off a different feature.

**There are two reaction-shot mechanisms, and they do not know about each
other.** `LONGTAKE_REACTION` cuts to the co-host on the spine when one
person has held the floor too long — a timeout, and blind to what the
co-host is doing. The `video/` + `reactions.py` layer measures when the
listener is actually worth looking at and places shots on their own lane.
The measured one is the stronger signal: it knows *that something is
happening*, where the timeout only knows *that time has passed*. They are united: the long-take rule breaks at a measured moment when one
is within `REACTION_REACH` (4 s), and falls back to the timeout when none
is. The measurement reaches `decide.py` as a plain `(speakers, n)` boolean
array from `reactions.marks` — an array, never a file read, and measured at
24.3 ms → 24.2 ms for `decide()` with marks against without. `marks()`
itself costs 24 ms, so it is cached on the settings that feed it; recomputing
it every settings round would have spent a quarter of the response budget on
something that rarely changes.

Four seconds is the reach because a break dragged further starts to feel
like a different part of the turn. The measured moment also beats the breath
point: a breath says you *may* cut here, a measured moment says there is
something to look at.

`LONGTAKE_REACTION_WIDE` is the three-beat form — reaction, wide, back to the
speaker. Returning through the wide is a softer cut than close-up straight to
close-up, and the wide restores the geography. It only splits when both
halves clear `min_shot`; below that it would be two flashes rather than two
shots.

What the preview shows and what the export writes must agree, or the
difference must be stated. The reaction lane is drawn even when the switch
is off — that is the only way to judge the feature before committing to it —
and for one version that meant the panel showed 96 shots while the export
wrote none, correctly and silently. Anything drawn but not exported says so
on its face.

`apply()` reads globals from a name list, and forgetting to extend it is
silent. Every reaction setting was missing from it: the switch showed, the
sliders moved, nothing reached the server, every state refresh reset it, and
the export correctly wrote zero reaction shots. Everything worked except the
thing that was asked for. `test_every_global_the_interface_shows_can_be_set`
walks every `Globals` field and fails on any that cannot round-trip, so the
next field added has to be listed or explicitly excused.

A reaction shot on a lane is a nested `mc-clip`, not an `asset-clip`. The
first attempt referenced the angle's asset directly: valid DTD, clean
import, and **nothing on the timeline at all**. A hand-made comparison in
Final Cut showed the real shape — a nested `mc-clip` with the host's own
`ref`, its angle chosen by `<mc-source angleID=…>`. As a multicam clip it
also stays in sync, which a separate file reference would not. Times are in
the host's local base, so for a synchronous placement `offset` and `start`
are the same number; Final Cut's own file differs only because that clip was
dragged there by hand. Final Cut writes `srcEnable="all"`; ours must be
`video`, or the close-up's camera microphone sums over the processed mics.

Keywords are where Final Cut shows what a clip is. The browser displays a
multicam clip's *media* name — every shot reads "A-osa" — so the `name`
attribute buys nothing there and the index's Tags tab stays empty. The
speaker goes on as a `<keyword>`, and the DTD fixes the order: `mc-source*`,
then nested clips, then keywords. Put the keyword before the lanes and the
import fails validation.

## Speculative picture goes on its own lane

Reaction shots — cutting to the listener while someone else talks — are not
part of the base cut and must not be written into the `mc-clip` as angle
switches. They go on a **positive lane** as connected clips (mics and twins
are all on negative lanes, so positive is free).

The reason is reversibility without recomputation. Removing an angle switch
means exporting again, and by then the previous export is usually already
imported into Final Cut and edited by hand — the work `next_output_path`
exists to protect. A lane makes removal one selection, leaves the multicam
underneath untouched frame for frame, and gives a free A/B by toggling.

Three rules come with it. The clips are **video only**, explicitly and
verified by importing: a connected clip from a close-up carries that
camera's audio, which would sum with the processed microphones — the same
family as the `uid` collapse and `srcEnable` beating `active`. They ship
**enabled**, because a lane that is off by default is never evaluated. And
`project.name_tag` records them like `audio`, so the export is
distinguishable in the browser.

The known cost is drift: connected clips can move on a ripple edit. For room
tone that is a tolerated compromise; for a reaction shot it means landing on
the wrong moment, which is the only thing it is for. A nested `mc-clip` on
the lane may avoid it — but that is a construction Final Cut does not write
itself, so it has to be settled by importing, not by reasoning.

## Final Cut is stricter than our own reader

The export must be validated against Final Cut's own DTD
(`/Applications/Final Cut Pro.app/.../Interchange.framework/.../FCPXMLv1_*.dtd`,
`xmllint --dtdvalid`). Our reader accepts far more than the importer: once
`tcFormat` was written onto `mc-clip`, which the reader accepted but which
killed the entire import. `clip` and `asset-clip` know that attribute,
`mc-clip` does not.

Derived files do not go inside the `.fcpxmld` bundle but beside it, taking the
bundle's name. The bundle belongs to Final Cut.

An export never lands on an existing file. `project.next_output_path` walks
`-cut`, `-cut v2`, `v3` … until it finds a free name, and `pick`'s
`_OUTPUT_RE` recognises the numbered ones as our own so they are not offered
back as a source. The reason is not tidiness: the previous export is usually
already imported into Final Cut and edited by hand, and that work has no other
source to be rebuilt from.

Final Cut shows `<project name>`, never the file name — so the distinguishing
part of the file name has to be in it too (`project.fcp_project_name`), or
every import looks the same in the browser and the numbering that keeps the
files apart buys nothing where it is actually read.

The name also carries the settings (`project.name_tag`): the rhythm preset
always, deviating controls after it, `audio` when the microphones were
processed. `_OUTPUT_RE` therefore accepts a tag between the suffix and the
number — but only words the tool writes itself, so a foreign
`interview-cut down.fcpxml` is still a valid source. The numbering runs within
one tag: a cut made with different controls is a new file, not a new version.

The whole settings set goes into the exported XML as well. The DTD says
`sequence (note?, spine, metadata?)`, so the `<note>` goes before the spine and
the `<metadata>` after it — the order is part of the rule, not a style choice.
The note is translated (it is a user-visible Final Cut field); the `md` keys
are not, they are machine-readable and prefixed `fi.autoraffkat.`.

## User-visible text is translated, code is not

Everything the user reads goes through translation: server messages via
`i18n.py`'s `t()`, browser strings via `static/i18n.js`'s `T()`. A new error
message means a new key in both languages — a hard-coded string shows up in the
wrong language and nobody notices until a user complains.

Code, comments and docstrings stay in Finnish. They are for the maintainers.

The language is a `ContextVar`, not a global: audio processing runs in a
background thread while the interface is asking for state.

`server/CLAUDE.md` holds the sections that were here (loaded when working in that directory).

## Every shot covers a set of speakers

The decision layer does not know "close-up" and "wide" as kinds, only who a
shot shows: a close-up covers one speaker, a group shot (`GroupShot`) some,
the wide everyone. A speaker without a close-up of their own goes to the
tightest group shot they are in, then the wide; overlapping speech under the
wide rule goes to the tightest group shot that shows *everyone talking*,
then the wide. Group shots are numbered after the speakers in `want` and in
`Decision.chosen` (`len(speakers) + g`), and `_shot_active` gives each one
an activity row — any of its speakers talking — so the L-cut hang works on
them unchanged. The preview names them (`preview.groups`), or the browser
would paint a group shot in some speaker's colour.

Group shots are never reframed and never measured for reactions:
`reframe.close_up_tables` drops their tables even when a cached measurement
exists from when the same camera was a close-up, because the median face of
a two-shot is one of the two people, and cropping to it cuts the other out.

## The interface has a smoke test, and it is not optional

`node --check` validates syntax only, so it does not notice an undefined
variable. One got through: `renderAudio` referenced a `busy` variable that had
been removed, which aborted the whole render — "Reload" span forever and the
console showed nothing but a `ReferenceError`.

`tests/ui_smoke.js` loads `i18n.js` and `app.js` into a stub DOM and runs every
render function in both languages, with audio processing on and off and with
processing in progress. The state comes from the server for real
(`_state_json`), so a field renamed at only one end fails here too.

Three things keep it honest, and none of them are decoration:

* `test_smoke_catches_an_undefined_variable` injects a broken reference and
  asserts the harness notices. A smoke test that passes everything protects
  nothing.
* The harness fires every registered event handler. Rendering alone runs about
  half the file; clicks, selects and text fields are the other half, and that
  is where an undefined variable hides. It fires one generation at a time:
  handlers that redraw the track list create a whole new set of elements, and
  firing the detached ones again on the next pass multiplies them until node
  runs out of heap. The next pass renders the same interface anyway.
* Every top-level function is wrapped in a counter, and the run **fails** if
  any was never called. Add a function without covering it and the test says
  so by name. Anything genuinely unreachable goes in `NEVER_CALLED_OK` with a
  reason.

CI (`.github/workflows/tests.yml`) runs the suite on macOS with ffmpeg and
Node, and fails if the interface smoke test skipped — a silent skip would
leave exactly this class of bug unguarded.

Note when writing the harness: `let state` in `app.js` is a lexical binding,
not a property of the global object, so `context.state = ...` does not reach
it. Assign it from inside the context.

## Micro-movement is a transform on the angle, or nothing at all

`movement.py` plans a subtle, deterministic scale treatment (100–110 %; pushes of 4–8 %, raised from 2–5 % on 2026-09-25 because the user could not see them) for
the vertical workflow: import the export, run Smart Conform, and the zooms
are already there. Four rules hold it together:

* **The transform goes on the video angle's `mc-source`, never on the
  `mc-clip`.** The DTD gives `mc-clip` no `adjust-transform` at all —
  `mc-source` is `audio-role-source*` *then* `%intrinsic-params-video;`, so
  the transform comes after the muted role. Writing it on the clip would be
  the `tcFormat` failure again: our reader accepts it and the whole import
  dies. The flat export puts it directly on the `asset-clip`, before the
  attached microphones.
* **Identity writes nothing.** A clip whose move is exactly 1.00 gets no
  `adjust-transform` — an empty element is a setting as far as Final Cut is
  concerned, the same rule as a zero pan. The switch off must produce
  byte-for-byte the file the tool produced before the feature existed.
* **The thresholds are not controls.** Amount, jump ceiling, repeat limit,
  the animation threshold and the seed live in `movement.py` with their
  reasoning; the interface has the switch and nothing else. "How much
  movement" is the same kind of question as "how much panning", and it gets
  the same answer.
* **Scale only, and wides stay still.** Position is never written — Smart
  Conform's framing is the authority, and in a 9:16 crop a horizontal
  nudge pushes the subject off centre. A wide already *is* the room, so it
  gets no movement; it carries its label as a keyword («Laaja»), which is
  how a batch of wide shots is selected in Final Cut's index.

The keyframe form is Apple's own example — `param name="scale"` in x-y
pairs as fractions (1 = 100 %), interpolation left at the DTD's
`curve="smooth"` default, the softness being the feature — **but the times
are in the host clip's local time base**, `start` to `start + duration`, the
same rule Final Cut wrote for `adjust-volume` and `adjust-panner`. The first
version wrote them from zero, reading "the clip's own time" off an example
whose clip happened to start at zero; on a multicam clip `start` is the
multicam's own time, both keyframes landed before the clip began, and the
push never moved (139 animated clips on the real episode, found by the video
files session measuring an export, 2026-09-25). Not yet confirmed by an
import — do that before trusting it. The keyframe overrides the attribute,
so the attribute carries the static case.

## Rendering draws the export, it does not decide anything

**Render video** writes the export and an MP4 beside it (`render.py`). The
user's workflow (2026-09-25): the whole episode as a vertical video goes to
a separate app that picks short-clip spots, and those are cut from the
render without reopening Final Cut; Final Cut stays for when the edit is
adjusted by hand. So the render must look like Final Cut's export of the
same XML, and the only way to guarantee that is to decide nothing here: the
writer hands over a `Shot` for every spine and reaction clip — file, file
time, scale at start and end, position — built from the same numbers it
writes (`_record`), and the audio is the same processed files, duck curves,
pans and room tone as the export (`AppState.render_job`).

On macOS the picture is drawn by **AVFoundation** (`render_av.py`), the
engine Final Cut sits on: shots go onto one `AVMutableComposition` straight
from the camera files, each with its transform (a ramp for micro-movement),
and one export session decodes, transforms and encodes on the GPU — no
per-shot processes, no frame on the CPU. Measured on an M1 Max with a 60 s
zoom shot: ffmpeg 5.2 s and 10.0 s of CPU, AVFoundation 5.3 s and 2.0 s. One
session is one hardware pipeline (~11× real time); two in parallel reach
16×, four 15× — the machine has two encoders — so the programme is split in
two at a shot boundary and joined by stream copy. Never next to a black
gap: AVFoundation silently drops an empty stretch at the end of an export,
and the join lost 9 frames. It also refuses to overwrite a file ("Cannot
Save", -11823). ffmpeg stays as the fallback and the Windows path, and the
same marker tests run against both.

Two ffmpeg facts cost a measurement each. `crop` does not reconfigure when
its input size changes mid-stream: under an animated `scale` its `in_w`
stayed the first frame's width and a test marker slid 185 px where the real
move is 48 — so the scaled size is computed from the frame index in both
filters. And the two filters do not agree on `n`: `scale`'s runs one ahead
of `crop`'s (first frame 3.5 px off), so the index comes from the timestamp
(`round(t*fps)`), which both see alike. Each shot is its own segment, then
a stream-copy concat: a filter graph of hundreds of shots is fragile, and
frame counts per shot make the length exact by construction. Audio is
made and AAC-encoded in its own thread while the picture draws, and the
picture's parts and the audio are joined in **one** stream copy, without
`+faststart` (it rewrites the whole file, needed only for web playback): on
a 46-minute episode on an M2 the step after the picture took 73 s, mostly
the audio encode and two extra copies of a multi-GB file. Audio is
summed in one-minute blocks — an hour of two microphones in memory is
gigabytes. Pan follows FCP's balance for a mono clip in a stereo project
(full level both sides at centre), not constant power.

The ffmpeg path wobbles on a slow zoom and AVFoundation does not. Both the
scaled size (even pixels) and the crop offset are integers, stepping at
different moments, so a push ticks back and forth: measured on a 125-frame
push, rms 0.60 px off the smooth path, max 1.16, 82 reversals — seen by the
user as a side-to-side sway in a close-up. AVFoundation's transform is
subpixel: 0.02 px, no reversals. `test_a_slow_zoom_moves_smoothly_without_wobble`
holds the AV path; the ffmpeg path fails it and is not fixed yet.

## Two movement styles: calm and shorts

`movement_style` picks between two editing languages, and the user asked
for the second as an option, not a replacement (2026-09-25). **Calm** is
camera variation: jumps under 3 %, slow random pushes. **Shorts** is
short-form editing: punch-ins come **on speaker changes** (`punch_segments`):
inside a close-up where the speaker resumes after someone else spoke, and
at every return to a speaker, whose framing alternates base/punch per
camera. The first version punched in on loud onsets after a pause, and a
full-episode transcript said that was wrong — of 540 onsets, pause length
(precision 0.28 at 0.3 s, 0.34 at 1 s against a 0.26 base rate), onset
peak, level fall and pitch fall all failed to separate sentence starts from
the ½–1 s thinking pauses these speakers take mid-sentence; only a change of
speaker did. Sentence boundaries would need a transcript, and the only
acceptable transcriber is colab-transcribe (the user, 2026-09-25: local is
too slow). The size between
same-camera cuts either stays or jumps a full punch; a push is only for an
unsplit long shot where the same speaker goes on, and always inward, since
the release is the cut. The base framing sits off-axis with lead room
toward the gaze (`reframe.LEAD_ROOM`, from the measured `turn` sign) and
the punch is centred — the user's idea: the cut then changes composition
as well as size, so 112 % reads as intentional where a pure size jump would
need ~15 %, and a Full HD source is spared (fill × punch = 1.99×).

Any static zoom (a punch, a calm framing) is planned into the framing
itself (`extra`), not multiplied on afterwards: Final Cut scales about the
frame centre, so a zoom applied to a position computed at 100 % slides an
off-centre face off the centre line. Calm-style positions moved a few px
when this went in; that is the fix, not drift.

## Reframe is Spatial Conform «Fill» plus a measured transform

`reframe.py` answers the vertical workflow: the export is already
1080×1920, so importing is the final step instead of Smart Conform being
the middle one. The rules it lives by:

* **The base is Final Cut's own.** Every picture in a vertical export gets
  `<adjust-conform type="fill"/>` on its angle, before the transform — the
  exact form of the user's hand-made vertical template (hmh hannes
  vertical base, 2026-09-25). Scale is then relative to the *filled* size:
  1.0 fills the height (a 16:9 source shows 1080 of its 3413 px), and the
  template's own `scale="1.22"` / `position="-30.7292 -8.59375"` come back
  out of the same arithmetic, which is what the units test holds. An
  unmeasured shot or a wide stays centred in the fill, never guessed.
* **The face is its bounding box, not `cx`.** `cx`/`cy` are the mean of the
  landmark points, and Vision normalises landmark points *to the face's own
  box* — so `cx` is ~0.5 wherever the face is and moves only when the head
  turns. The first reframe read it as the position in the picture and so
  centred on the middle of the frame, silently. Position is `x + w/2`,
  `1 - (y + h/2)` (Vision's origin is bottom-left); the cached tables have
  had those columns all along. `cx` is still right for what the reaction
  score uses it for: head motion.
* **Zoom evens out face size per camera, not per shot.** `look()` takes each
  close-up camera's median face height over the whole episode; the biggest
  stays at 100 % and the rest zoom to match, capped at `MAX_ZOOM` 1.10 (the
  template needed 1.22 for Tomi, but 1.25 plus micro-movement made 130 %
  shots, which the user found too much on 2026-09-25; the fill is already a
  1.78× enlargement of 1080p). Faces stay slightly unequal rather than soft. Per camera, because the same camera at two zooms in consecutive
  shots looks like a jump; and matching matters most exactly where shot
  and reverse shot alternate quickly. With one close-up nothing zooms.
* **The frame is steady, not per shot.** A shot is framed on the camera
  file's *steady* position (`steady()`), not its own median: a rolling
  30 s median takes out the fidgeting, and the frame moves only when that
  median has stayed more than 0.04 of the width (137 px in the fill, an
  eighth of the crop) away for 30 s — the camera was moved, or someone
  stood up and sat down differently. Per-shot medians made every cut back
  to the same camera land a few pixels elsewhere. The user asked for it
  this way (2026-09-25), and a test holds both halves: 15 s elsewhere does
  nothing, a permanent shift moves the frame once. One exception: when the
  shot's own *median* face box would cross the crop edge, the crop moves
  just enough to hold it (`keep`). Measured on the real episode, that was 2
  of 594 clips — someone leaning for a whole short shot, 14 % of the face
  cut — while momentary movement (median inside) still moves nothing.
* **Vertical position exists only when there is zoom.** At 100 % the
  filled picture *is* the project height and any vertical offset reveals
  an edge. A zoomed camera's face moves to the 100 % camera's face height
  (`eyeline`), clamped to the slack the zoom gives. Faces are always on the
  centre line horizontally, so shot and reverse shot mirror each other.
* **Reframe and micro-movement merge into one `adjust-transform`** —
  Final Cut has only one per clip, so `_transform_lines` composes them:
  reframe is the static scale+position baseline, movement multiplies
  into the scale keyframes. A test holds the product, not the factors.
* **Only a close-up is framed on a face.** A group shot or a wide has
  several, and the median of "the largest face" is whichever person
  happens to be nearest; `close_up_tables` keeps them out even when an old
  measurement exists for that camera. The sequence format is unnamed
  (`FFVideoFormat1920p` does not exist; attributes carry the truth), and
  the sequence-format search enforces the *requested dimensions*, not just
  the frame rate: matching by rate alone handed a 16:9 format to a vertical
  project silently.
* **Turning the switch on starts the scan** when no tables exist, the
  same rule as panning: a feature that silently requires another
  feature's button pressed first is a feature that looks broken.
  `video_missing()` is the one place that decides it, and it counts the
  crowd tables too: with close-ups already measured, the old "no tables"
  test never started the crowd pass.

## Wides and group shots follow the speaker, by mouth

Smart Conform does not know what to do with a wide or a two-shot in 9:16,
so in a vertical export they are **split where the speaker changes**
(`reframe.focus_segments`) and each piece is framed on that speaker's face
(`Segment.focus`). In the 16:9 cut a two-shot is one shot because it shows
both people; a vertical crop shows one, so a turn change is a cut. Silence
and overlap hold the previous speaker, and a piece shorter than `min_shot`
folds into its neighbour. Two things in the export had to stop merging
same-angle neighbours — `_merge_spans` and `_merge_multicam_spans` both
now compare `focus` — because merging was the old defence against Smart
Conform cropping one camera two ways, which is now exactly the point.

Which face is whom is measured, per **file**, not per camera (`seats.py`).
The same camera can hold two people in part 1 and one in part 2 when a
guest leaves and nothing is moved, so each file is matched only against
the speakers who talk during it, and the number of seats comes from how
many faces the frames actually hold. The crowd pass (`measure_file(...,
crowd=True)`) keeps every face of every `CROWD_EVERY`th keyframe (~5 s)
with its inner-lip aperture — measured on a 61-minute camera, extraction
151 s and faces 124 s; extraction is the same either way, the faces drop
to a fifth, and a steady frame gains nothing from denser sampling;
faces under half the median size are background. Seats are a 1-D k-means
on the face centres, and each seat goes to the speaker whose mic is on when
its mouth is open more than when it is off — one frame a second says
nothing, an hour of them does. Position cannot decide it: in the test the
speaker sits on the *right* on purpose. The assignment is the best
permutation of those differences, and `margin` (best minus second best) is
shown on the camera card. It has **not** been calibrated on real footage
yet; that is why the order is on screen and can be fixed by clicking a
name (`TrackConfig.seats`, left to right, inherited like other roles and
restricted per file to the people in it).

A crowd table is its own cache entry (`CROWD` in the key and the path
index): a camera that was a close-up in one episode and a two-shot in the
next must not have one measurement overwrite the other.

## Tests

`tests/make_fixture.py` synthesises the material with ffmpeg: sine bursts at
known positions (`SPEECH_A`, `SPEECH_B`). The project fixture starts at second
1 of the source, the sync clip at zero — comparisons must use the
`source_to_timeline` conversion, not raw numbers.

`multicam.fcpxml` is the same material as two parts: the parts' files are
copies, because grouping looks at the filename rather than the content. There a
timeline moment equals a file moment, so `source_to_timeline` is the identity —
unlike in the project fixture.

Settings are written beside the XML, so tests that export or save need the
`scratch_xml` fixture rather than the shared `fixture_dir`.
