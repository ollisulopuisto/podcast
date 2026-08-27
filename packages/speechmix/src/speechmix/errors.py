"""Errors for the shared speech-mixing pipeline.

The recurring failure in this pipeline is a *silent* one: valid output, a clean
import, no exception, and a result nobody notices until they listen.  So the
working rule is: **a feature that produced nothing must say so.**  Setting on
and result empty is an error, not a silence.

Every error below carries a stated reason, because the mistakes these guard
against are only audible after the export.
"""


class SpeechmixError(Exception):
    """Base class for every error raised by the pipeline."""


class EmptyResult(SpeechmixError):
    """A stage was enabled and produced nothing.

    Ducking depends on the speech analysis.  Pressing the button before the
    analysis finished left the masks empty with nothing said: the setting read
    -9 dB and the output had none.  "The setting is on and no microphone
    matched a mask" is an error, not a silence.
    """


class Refused(SpeechmixError):
    """A stage measured its own output and refused to ship it.

    A de-bleed filter that eats the target's own speech is worse than no
    de-bleeding at all, and the damage is only audible after the export.
    """


class Misaligned(SpeechmixError):
    """Stems do not line up, so summing them sample-by-sample would be wrong.

    Summing files sample-by-sample is only correct when the stems line up on
    the timeline.  That is a checked fact, not an assumption: mismatched stems
    are left alone rather than summed at the wrong offset.
    """


class LengthChanged(SpeechmixError):
    """A stage changed the sample count.

    The export references the processed file with the same times as the
    original, so a stage that shortens or lengthens the signal silently moves
    every edit after it.
    """


class NotMono(SpeechmixError):
    """A microphone track arrived with more than one channel.

    A microphone is always mono out, even from a stereo source.  Two channels
    break the arithmetic in three places silently: de-bleeding reads only the
    first channel, the programme ceiling sums stems of differing channel counts
    by broadcasting them, and panning is a mono-source idea.
    """


class MissingBinary(SpeechmixError, FileNotFoundError):
    """ffmpeg or ffprobe was not found anywhere.

    Also a ``FileNotFoundError``, because the hosts' catch sites were written
    before this package existed and catch that. podcast-magic's own
    ``MissingBinary`` is a ``RuntimeError`` instead; when that app moves over,
    reconcile the two rather than routing around them.
    """


class EnvelopeError(SpeechmixError):
    """The RMS envelope could not be produced.

    The caller is an analysis loop that shows this to the user, so a missing
    tool has to arrive as this and not as a bare OSError -- the loop catches
    this one, and the file it could not read is named in the message.
    """
