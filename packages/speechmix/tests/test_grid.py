"""Who is talking, measured on the raw microphones.

The decision is a comparison **across** microphones, not a threshold on one.
On a two-microphone recording half of what is loud on a track is the other
person: the level heuristic called 74 % of one track's blocks speech when 53 %
were its owner's, agreeing only 38 % of the time.
"""

import numpy as np
import pytest

from speechmix import grid
from speechmix.errors import EmptyResult

RATE = 48000


def _two_mics(seconds=30.0):
    """A speaks, then B, then both -- and each microphone hears the other."""
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    rng = np.random.default_rng(7)

    def voice(f0, seed):
        body = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 9)) * 0.1
        return body + rng.normal(0, 3e-3, n)

    third = n // 3
    gate_a = np.zeros(n, dtype=bool)
    gate_b = np.zeros(n, dtype=bool)
    gate_a[:third] = True
    gate_a[2 * third :] = True
    gate_b[third:] = True

    a = voice(118.0, 1) * gate_a
    b = voice(197.0, 2) * gate_b
    # Each microphone carries the other voice, a few milliseconds late.
    return a + 0.12 * np.roll(b, 144), b + 0.10 * np.roll(a, 150), gate_a, gate_b


def test_a_microphone_is_active_only_while_its_own_speaker_talks():
    """Bleed is loud enough to fool a level threshold; dominance is not fooled."""
    mic_a, mic_b, gate_a, gate_b = _two_mics()
    speech = grid.speech_grid({"a": mic_a, "b": mic_b}, RATE)

    mask_a = speech.mask("a")
    assert mask_a[gate_a & ~gate_b].mean() > 0.95, "missed its own speaker"
    assert mask_a[gate_b & ~gate_a].mean() < 0.05, "fired on the other speaker's bleed"


def test_only_excludes_the_overlap():
    """De-bleeding estimates on the passages where the source speaks *alone*.

    Anywhere else the target's own voice would be fitted as if it were leakage.
    """
    mic_a, mic_b, gate_a, gate_b = _two_mics()
    speech = grid.speech_grid({"a": mic_a, "b": mic_b}, RATE)

    both = gate_a & gate_b
    assert speech.only("a")[both].mean() < 0.05
    assert speech.only("b")[both].mean() < 0.05
    assert speech.only("b")[gate_b & ~gate_a].mean() > 0.9


def test_an_empty_grid_is_an_error_not_an_empty_mask():
    """A grid with nothing in it is what leaves ducking silently doing nothing
    three stages downstream. It is an error here instead.
    """
    with pytest.raises(EmptyResult):
        grid.speech_grid({}, RATE)
    with pytest.raises(EmptyResult):
        grid.speech_grid({"a": np.zeros(RATE * 5), "b": np.zeros(RATE * 5)}, RATE)


def test_the_grid_feeds_the_masks_that_already_existed():
    """Kaksi ruudukkoa yhdessä paketissa on kaksi vastausta samaan kysymykseen.

    ``masks.duck_masks`` ja ``envelopes.duck_envelopes`` lukevat kaistoja:
    nimi, ``on`` ja ``level``. ``SpeechGrid`` tietää kaikki kolme — se laskee
    tasot päättääkseen kuka on kovin — mutta ei kertonut niitä, joten
    vaimennus ei päässyt käsiksi siihen ruudukkoon jonka tämä moduuli
    rakentaa. Näkymä on se puuttuva lenkki, ei uusi laskenta.
    """
    from speechmix import envelopes, masks

    rate = 8000
    seconds = 12.0
    rng = np.random.default_rng(2)
    n = int(rate * seconds)
    quiet = rng.normal(size=n) * 1e-4
    mic_a = quiet.copy()
    mic_b = quiet.copy()
    for lo, hi in ((1.0, 4.0), (8.0, 11.0)):
        mic_a[int(lo * rate) : int(hi * rate)] += rng.normal(size=int((hi - lo) * rate))
    for lo, hi in ((4.5, 7.5),):
        mic_b[int(lo * rate) : int(hi * rate)] += rng.normal(size=int((hi - lo) * rate))

    speech = grid.speech_grid({"a": mic_a, "b": mic_b}, rate)
    lanes = speech.speakers

    assert [lane.name for lane in lanes] == ["a", "b"]
    assert speech.names == ("a", "b"), "nimet ovat nimiä, kaistat kaistoja"
    assert lanes[0].on.shape == lanes[0].level.shape == (speech.n_frames,)
    assert lanes[0].on[int(2.0 / grid.HOP_SEC)], "a puhuu sekunnilla 2"
    assert not lanes[0].on[int(6.0 / grid.HOP_SEC)], "sekunnilla 6 puhuu b"

    class Settings:
        duck = True
        duck_db = masks.DUCK_DB
        duck_fade = masks.DUCK_FADE
        duck_release = masks.DUCK_RELEASE
        duck_hold = masks.DUCK_HOLD
        duck_lookahead = masks.DUCK_LOOKAHEAD
        duck_min_open = masks.DUCK_MIN_OPEN
        duck_min_closed = masks.DUCK_MIN_CLOSED
        duck_dominance_db = masks.DUCK_DOMINANCE_DB

    closed = masks.duck_masks(speech, Settings())
    assert closed, "vuorottelevilla puhujilla pitäisi syntyä vaimennusta"
    points = envelopes.duck_envelopes(speech, Settings(), 0.0)
    assert points, "ja siitä pitäisi syntyä käyrä"
