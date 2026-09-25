"""Mikroliike: suunnitelma on deterministinen ja sen rajat pitävät.

Liike on valekameraa: sen on pysyttävä alueessa jonka katsoja alitajuisesti
kokee vaihteluna eikka leikkauksena. Jokainen raja tässä tiedostossa on
sellainen joka rikkuessaan näkyy katsojalle — liian iso hyppy leikkaukseksi,
liian pitkä toistuva kehys metronomiksi.
"""

from itertools import pairwise

from autoraffkat import movement


def _durations(count: int, spec: tuple[float, ...] = (2.0, 6.0, 12.0)):
    return [spec[i % len(spec)] for i in range(count)]


def test_planning_is_deterministic():
    """Sama siemen tuo saman suunnitelman: vienti on toistettava."""
    durs = _durations(90)
    assert movement.plan(durs, [False] * len(durs)) == movement.plan(
        durs, [False] * len(durs)
    )


def test_different_seed_gives_a_different_plan():
    durs = _durations(90)
    assert movement.plan(durs, [False] * len(durs), seed=1) != movement.plan(
        durs, [False] * len(durs), seed=2
    )


def test_scale_stays_between_100_and_106_percent():
    """Koko alue on rajattu: liike näkyy, mutta ei laadun heikkenemisenä."""
    durs = _durations(300)
    for move in movement.plan(durs, [False] * len(durs)):
        for value in (move.start_scale, move.end_scale):
            assert movement.SCALE_MIN <= value <= movement.SCALE_MAX


def test_short_clip_is_never_animated():
    """Alle kolmen sekunnin kuva ehtii alkaa ja loppua ennen kuin liike on
    havaittavissa — siitä ei kirjoiteta mitään liikettä."""
    durs = [2.9] * 40
    assert all(not m.animated for m in movement.plan(durs, [False] * len(durs)))


def test_long_clips_receive_a_noticeable_push():
    """Pitkä puheenvuoro saa puskun joka huomataan: vähintään 4 %.

    2–5 % oli käyttäjän mukaan liian hidas havaittavaksi (2026-09-25):
    kokoero kuvan aikana on nähtävä, muuten liike on olematta.
    """
    durs = [15.0] * 60
    animated = [m for m in movement.plan(durs, [False] * len(durs)) if m.animated]
    assert animated, "yksikään pitkä klippi ei liikkunut"
    for move in animated:
        push = abs(move.end_scale - move.start_scale)
        assert 0.04 <= movement.PUSH_MIN <= push <= movement.PUSH_MAX


def test_adjacent_scale_jump_is_bounded():
    """Vierekkäisten kuvien skaalaero pysää pienenä: iso hyppy luetaan
    leikkaukseksi eikä kameran vaihdoksi."""
    durs = _durations(300)
    moves = movement.plan(durs, [False] * len(durs))
    for prev, cur in pairwise(moves):
        # Skaalat ovat neljän desimaalin tarkkuudella; binääriluvuissa
        # 1.037 - 1.007 on 0.030000000000000027, joten vertailu tehdään
        # samalla tarkkuudella jolla arvot on kirjoitettu.
        assert round(abs(cur.start_scale - prev.start_scale), 4) <= movement.MAX_JUMP


def test_identical_framing_never_repeats_too_long():
    """Sama kehys montaa klippiä putkeen on metronomi, ei kamera."""
    durs = _durations(300)
    moves = movement.plan(durs, [False] * len(durs))
    run = 1
    for prev, cur in pairwise(moves):
        run = run + 1 if abs(cur.start_scale - prev.start_scale) < 0.005 else 1
        assert run <= movement.MAX_REPEAT + 1


def test_wide_shots_get_no_movement():
    """Laajassa ei ole aihetta valekameralle: se kertoo missä ollaan, ja
    vertical-konversio rajaa sen joka tapauksessa omalla tavallaan."""
    durs = _durations(30)
    wides = [i % 3 == 0 for i in range(len(durs))]
    for move, wide in zip(movement.plan(durs, wides), wides):
        if wide:
            assert not move.animated
            assert move.start_scale == 1.0
            assert move.end_scale == 1.0


# ------------------------------------------------ shorts-tyyli (2026-09-25)


def _turn_grid(seconds=40):
    """Host puhuu, Guest keskeyttää kahdesti; Hostilla on myös pelkkä tauko.

    Host 3–10, Guest 10,5–12, Host 12,5–20, (tauko) Host 21–30,
    Guest 30,5–31, Host 31,5–39.
    """
    import numpy as np

    from autoraffkat.decide import Grid, SpeakerLanes
    from autoraffkat.model import HOP

    n = int(seconds / HOP)

    def lane(name, key, spans):
        on = np.zeros(n, dtype=bool)
        for a, b in spans:
            on[int(a / HOP):int(b / HOP)] = True
        return SpeakerLanes(name, np.where(on, -25.0, -60.0).astype(np.float32), on, key)

    return Grid(n=n, program_start=0.0, wide_key="W", speakers=[
        lane("Host", "CAM A", [(3, 10), (12.5, 20), (21, 30), (31.5, 39)]),
        lane("Guest", "CAM B", [(10.5, 12), (30.5, 31)]),
    ])


def test_punch_ins_land_where_the_speaker_takes_the_floor_back():
    """Punch vain puhujan vaihtuessa: kun puhuja jatkaa toisen välihuomautuksen
    jälkeen. Pelkkä tauko saman puhujan puheessa ei ole — koko jakson
    litteroinnista mitattuna tauon pituus, huippu, tason lasku eikä sävelkulku
    erottanut lauseen alkua lauseen keskeltä (video files, 540 alkua); vain
    puhujan vaihto erotti. Käyttäjä 2026-09-25: puhujan vaihto riittää."""
    from autoraffkat.model import Segment

    cut = [Segment("W", "Laaja", 0.0, 3.0), Segment("CAM A", "Host", 3.0, 40.0)]
    out = movement.punch_segments(cut, _turn_grid(), min_shot=2.5)
    pieces = [s for s in out if s.angle == "CAM A"]
    starts = [round(s.start, 2) for s in pieces]
    assert starts == [3.0, round(12.5 - movement.PUNCH_LEAD, 2),
                      round(31.5 - movement.PUNCH_LEAD, 2)], starts
    assert [s.punch for s in pieces] == [False, True, False]
    assert pieces[-1].end == 40.0


def test_each_return_to_a_speaker_alternates_the_framing():
    """Kun kuva palaa puhujaan (hän ottaa vuoron), rajaus vaihtuu perus- ja
    punch-rajauksen välillä: vuoron vaihtuminen näkyy koon vaihtumisena."""
    from autoraffkat.model import Segment

    cut = [Segment("CAM A", "Host", 3.0, 10.4), Segment("CAM B", "Guest", 10.4, 12.4),
           Segment("CAM A", "Host", 12.4, 20.0), Segment("CAM B", "Guest", 20.0, 21.0),
           Segment("CAM A", "Host", 21.0, 30.0)]
    out = movement.punch_segments(cut, _turn_grid(), min_shot=2.5)
    host = [s.punch for s in out if s.angle == "CAM A"]
    assert host == [False, True, False]


def test_shorts_plan_jumps_a_full_punch_or_not_at_all():
    """Saman kameran leikkauksessa koko joko pysyy tai hyppää punchin
    verran — välistä hyppy näyttää virheeltä. Punch on 112 %, pusku vain
    pilkkomattomassa pitkässä kuvassa, ja laaja pysyy paikallaan."""
    durs = [4.0, 5.0, 4.0, 12.0, 3.0]
    wides = [False, False, False, False, True]
    punches = [False, True, False, False, False]
    moves = movement.plan(durs, wides, style="shorts", punches=punches,
                          split=[True, True, True, False, False])
    assert moves[0] == movement.Move(1.0, 1.0)
    assert moves[1] == movement.Move(movement.PUNCH, movement.PUNCH) and movement.PUNCH == 1.12
    assert moves[2] == movement.Move(1.0, 1.0)
    assert moves[3].start_scale == 1.0 and moves[3].end_scale - 1.0 >= movement.PUSH_MIN
    assert moves[4] == movement.Move(1.0, 1.0)
