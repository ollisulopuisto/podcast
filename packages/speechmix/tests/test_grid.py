"""Who is talking, measured on the raw microphones.

One rule, and it is autoraffkat's, because autoraffkat's is the one measured
on real material: a floor at the 20th percentile of a **smoothed** level
curve, and speech is what clears it by ``FLOOR_MARGIN_DB``. This module used
to answer the same question with its own numbers -- a 10th-percentile floor,
an 8 dB margin, and a dominance test folded into the decision -- and two
answers to one question in one package is the drift this workspace exists to
prevent.

What the dominance test was for is done by the margin. Measured on
``_two_mics`` below, where the bleed sits 18.4 dB under the direct voice:

    rule                                   own speech      other's bleed
    10th pct + 8 dB + dominance             100.0 %            0.4 %
    10th pct + 8 dB, no dominance           100.0 %            0.4 %
    autoraffkat: smoothed, 20th pct, 12 dB  100.0 %            0.0 %

The first two lines are the same number, so the dominance test was deciding
nothing here -- the docstring this file used to carry said bleed "is loud
enough to fool a level threshold", and on this fixture it is not. Dominance
still decides which microphone stays *open* when two are genuinely active;
that is ``masks.duck_masks``, and it is where autoraffkat has always had it.
Keeping it out of the decision also makes ``only()`` purer, which is what
de-bleeding estimates its filter from.
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
    """The margin over a measured floor is what rejects the bleed."""
    mic_a, mic_b, gate_a, gate_b = _two_mics()
    speech = grid.speech_grid({"a": mic_a, "b": mic_b}, RATE)

    mask_a = speech.mask("a")
    assert mask_a[gate_a & ~gate_b].mean() > 0.95, "missed its own speaker"
    # Tighter than the 0.05 this asked for before: autoraffkat's rule measured
    # 0.0 % here where the old one measured 0.4 %.
    assert mask_a[gate_b & ~gate_a].mean() < 0.01, "fired on the other speaker's bleed"


def test_the_rule_is_autoraffkats_measured_one():
    """The constants are the ones measured on 77 minutes of real material.

    A copy of a measured number is two answers to one question, and the copy
    is the one that goes stale. autoraffkat reads these same names.
    """
    assert grid.NOISE_PERCENTILE == 20.0
    assert grid.FLOOR_MARGIN_DB == 12.0
    assert grid.SMOOTH_SECONDS == 0.10


def test_smoothing_does_not_invent_level_at_the_edges():
    """Zero-padding a **dB** curve pads with 0 dBFS, which is full scale.

    ``np.convolve(..., "same")`` hangs the kernel off both ends and fills the
    missing cells with zero. In the linear domain that is silence; in dB it is
    the loudest a signal can be. Measured on a constant −240 dB curve with the
    100 ms kernel, the first cell came back at −144 dB: **96 dB of level that
    is not in the material**, at the programme's first and last 40 ms.

    Nothing crashed. The curve was valid, the length was right, and the only
    symptom was a microphone reading as active at the very start and end of
    every programme — which is a cut decision and a ducking event.

    The edge value is replicated instead: the quietest honest assumption is
    that the material just outside the curve looks like the material at its
    edge.
    """
    flat = np.full(200, -240.0, dtype=np.float32)
    out = grid.smooth(flat)
    assert out.shape == flat.shape
    assert np.allclose(out, -240.0), f"edges invented level: {out[:3]}, {out[-3:]}"

    # And it still smooths: a one-cell spike is spread over the kernel.
    spike = np.full(200, -60.0, dtype=np.float32)
    spike[100] = 0.0
    smoothed = grid.smooth(spike)
    assert smoothed[100] < 0.0, "the spike must be averaged down"
    assert smoothed[99] > -60.0, "and its neighbours lifted"


def test_the_decision_is_one_function_both_hosts_call():
    """``lane`` is the rule; everything around it is how a host gets levels.

    autoraffkat aligns cached envelopes onto a programme grid and has a
    per-track sensitivity and gain; automixer measures raw stems that already
    share a time base. Those are different plumbing for the same decision, and
    the decision is here.
    """
    n = 100
    db = np.full(n, -60.0)
    db[20:40] = -10.0
    valid = np.ones(n, dtype=bool)
    floor = grid.noise_floor(db, valid)

    lane = grid.lane("a", [(db, valid, floor, 12.0, 0.0)])

    assert lane.name == "a"
    assert lane.on[30] and not lane.on[5]
    # Gain moves the level, never the threshold: the floor moves with it.
    louder = grid.lane("a", [(db, valid, floor, 12.0, 6.0)])
    assert np.array_equal(lane.on, louder.on), "gain must not move the threshold"
    assert louder.level[30] == pytest.approx(lane.level[30] + 6.0)


def test_a_speaker_with_two_files_is_one_lane():
    """In a multicam the same microphone is a different file in each part."""
    n = 100
    quiet = np.full(n, -60.0)
    first = quiet.copy()
    first[10:20] = -10.0
    second = quiet.copy()
    second[60:70] = -10.0
    valid = np.ones(n, dtype=bool)

    lane = grid.lane("a", [
        (first, valid, grid.noise_floor(first, valid), 12.0, 0.0),
        (second, valid, grid.noise_floor(second, valid), 12.0, 0.0),
    ])

    assert lane.on[15] and lane.on[65]


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
    # Dominanssi ei ole päätöksessä: se on ``duck_masks``issa, jonne
    # autoraffkat on sen aina laittanut.
    assert "dominance" not in grid.speech_grid.__code__.co_varnames

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
