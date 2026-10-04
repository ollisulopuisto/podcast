Video measurement. Moved from `apps/autoraffkat/CLAUDE.md`.

## The video layer caches measurements, never scores

`video/` is the third slow layer, and its seam is placed where the change is
expected: **the detector.** `video/detect.py` holds a registry of detectors,
each of which looks at one frame and returns numbers, knowing nothing about
the timeline, the speakers or the scoring. Its `name` and `version` go into
the cache key, so swapping detectors invalidates the cache by itself —
without that, a new detector would read the old one's traces and the result
would be valid, accepted and wrong.

What is cached is the **measurements**, not the score. Adjusting the weights
is then free, and the weights are the part expected to be tuned.
`reactions.py` is the fast layer over it: numpy, no file reading, same rule
as `decide.py` because it runs in the settings loop.

Only keyframes are decoded (`-skip_frame nokey`): measured at 70× realtime
against 16× for a full decode, which is one frame a second at a camera's
usual keyframe interval. Use `-fps_mode passthrough`, never `-vsync 0` —
current ffmpeg does not know the latter at all, and without either the
keyframes are stretched back to full rate, so the same picture arrives
dozens of times with the timestamps out of step with the frames. A test
fails if the frame count returns to full rate: nothing crashes when it does,
it just gets 25× slower in silence.

Frames and timestamps are paired by index, so a length mismatch means every
measurement sits at the wrong moment. That is an error, not a warning. A
frame where the detector found nothing stays in the table as zeros with
`found` false — dropping it would shift every index after it.

Only close-ups of speakers who are actually silent at some point get
decoded. Decoding is the whole cost of the feature, so that narrowing
happens *before* the decode, not after.

Vision's `yaw` is a bin, not an angle. Measured across 9995 frames of real
footage it takes exactly five values — multiples of 45° — and `roll` takes
three, while `smile`, `eyes` and `size`, computed from the landmarks here,
take about nine thousand each. So the one component that separated good
reaction frames from bad was effectively binary, and the continuous ones did
not separate at all. `turn` and `tilt` come from the nose relative to the
midpoint of the eyes, divided by the eye span so face size and distance stay
out of it. `yaw` remains: as a bin, "turned away" is what it detects well.

Reaction shots obey the cut that was already made. Placement began as pure
greed — best score first, 25 s apart, knowing nothing about the edit — and
measured on a real episode that put 18 of 121 within 0.2 s of a cut (a
flash, not a shot), 7 on their own speaker's close-up (a jump cut to the
same face), and 18 inside a host shot under 3 s. `reactions.fits` refuses
all three, and the conditions are applied **before** thinning: otherwise an
interval is spent on a candidate that is then rejected, and no acceptable
one can take its place.

The margin around a cut is `min_shot`, not a constant of its own. A second
was enough to keep a reaction from touching a boundary, but not enough for
the *host* shot to exist: measured, a cut from the wide to Wancke and 1.04 s
later a reaction — the close-up had not begun. The host's head and tail are
shots like any other, so they get the programme's own minimum, which is the
same condition `decide._force_wide` uses to decide whether its three-beat
form may split. One second remains the floor, because a flash is a flash at
any setting. Measured on the real episode: 22 of 98 sat under two seconds
from a cut; the rule costs 14 shots and moves the nearest to 2.50 s.

The interval follows `decide._compute_tempo`, the same 1/f measure that
scales `min_shot`. A fixed interval made the reaction layer the most
metronomic thing in the programme — measured, its interval spread was
σ 10 s against everything else's variation; with the placement rules and
tempo it is σ 17 s. Note there are **two** reaction mechanisms: the older
`LONGTAKE_REACTION` cuts to the co-host on the spine during a monologue and
already used the rhythm engine, and this one puts them on their own lane.

The measurement says *when*, the programme decides *what*. A reaction shot
does not have to be the measured face. Left alone the layer repeats itself:
measured on the real episode, 49 of 83 consecutive reaction shots showed the
same face as the one before, and consecutive close-ups are exactly the cut
`LONGTAKE_REACTION_WIDE` softens by going through the wide. `reactions._vary`
sends the second of a repeated pair to the wide instead — 1 of 83 afterwards,
split 31 / 27 / 26 across the three shots. It is a repetition breaker, not an
alternation: the wide spends the measurement that caused the cut, because a
face is small in it. `Reaction.speaker` therefore stays the measured person
(it is the reason, and `fits` needs it) and `Reaction.shot` names the track
actually shown. Nothing is substituted when the host shot is already the wide.

The gate decides which moments qualify; `reaction_spacing` decides how many
are used. Measured: a gate of 0.03 → 0.40 moves the candidates from 461 to
1875, while what reaches the export moves only from 94 to 131, because
thinning takes one moment per interval and qualifying moments always
outnumber intervals. Showing only the exported count made the gate slider
look broken. Both numbers belong on screen, and `reactions.candidates()`
exists separately from `find()` for that reason.

A word boundary does not exist in this data. The reaction shot arrived too
fast, and the obvious fix — snap the cut to a word — has nothing to snap to:
the envelope switches at syllable rate. Measured over 77 minutes, 26 452
on/off transitions, speech runs median 0.22 s and pauses 0.14 s, so every
reaction was already within 0.06 s of a "boundary" and the metric decided
nothing. What is available is a **pause**: `_snap` moves the cut to the
nearest moment where nobody speaks for `PAUSE` (0.3 s), searching `PAUSE_REACH`
(0.5 s) either way. That is a sentence boundary, and the ear hears it as one.

The cut leads the measured frame. Keyframes come one per second, so a
measurement says the listener looked good *somewhere* in that second — cut at
its start and the picture arrives after the reaction began. `reaction_lead`
(0.4 s) moves it earlier, the same reasoning as a J-cut's lead, clamped so it
can never precede the programme's start. And the length is 2.2 s, not 1.6:
below two seconds the shot begins and ends before a viewer has read the face.

The reaction score is a **gate**, not a ranking. The bar for a reaction shot
is not "outstanding" but "not disqualifying" — in a finished edit most of
them are unremarkable and only have to avoid embarrassment. Measured on 381
candidates against 23 hand marks the two classes do not overlap at all —
worst good 0.0721, best bad 0.0943 — so the threshold goes in the gap.
0.080 keeps all twelve marked good, admits none of the eleven marked bad,
and passes 60 % of candidates; the same job on the quantised `yaw` let 95 %
through. It sits on the tight half of the gap because a missed reaction shot
costs nothing and a disqualifying one costs the take. So the threshold
is the control that matters and the ordering among survivors barely does —
which is why `eyes` and `size` default to zero weight. `eyes` was actively
harmful: a hard laugh closes the eyes, and rewarding open eyes buried
exactly the frames that were worth cutting to.

Video files are decoded four at a time, and four is measured, not chosen.
Decoding one stream does not spread across cores, so the parallelism has to
be across files: measured 22× realtime for one, 38× for two, 73× for four —
and then it stops, 72× at six and 71× at eight. The ceiling is neither the
disk nor the CPU: during a decode `dd` pulled 759 MB/s off the same drive
while the decode held its 254 MB/s, and 66 % of the CPU was idle even at
eight. It is the number of hardware h264 decoders, which threads cannot
add to. On the real path the whole job went 990 s → 476 s.

Measuring the video is a button, and it runs in a thread. Decoding is
minutes and most episodes do not want reaction shots, so it must not happen
on load; the disk cache is what makes pressing it affordable a second time.
A thread suffices — the child process elsewhere is pedalboard's requirement
to load a VST3 on the main thread, and Vision has no such constraint. Both
empty cases are reported separately in the export warnings: on with nothing
measured, and measured with nothing passing the gate, are different
situations, and silence is how this project's recurring failure gets missed.
