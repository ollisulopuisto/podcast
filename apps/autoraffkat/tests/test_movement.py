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


def _talk_grid(seconds=40, loud=(5.0, 12.0, 20.0, 28.0), quiet=(8.0, 16.0, 24.0)):
    """Yksi puhuja: kovat lauseen alut ``loud``, hiljaiset ``quiet``.

    Jokainen lause on 2,5 s ja sitä edeltää tauko, jotta alku on alku.
    """
    import numpy as np

    from autoraffkat.decide import Grid, SpeakerLanes
    from autoraffkat.model import HOP

    n = int(seconds / HOP)
    on = np.zeros(n, dtype=bool)
    level = np.full(n, -60.0, dtype=np.float32)
    for starts, db in ((loud, -18.0), (quiet, -30.0)):
        for t in starts:
            a, b = int(t / HOP), int((t + 2.5) / HOP)
            on[a:b] = True
            level[a:b] = db
    lane = SpeakerLanes("Host", level, on, "CAM A")
    return Grid(n=n, program_start=0.0, speakers=[lane], wide_key="W")


def test_punch_ins_land_on_loud_sentence_starts():
    """Pitkä lähikuva pilkotaan saman kameran kuviksi kovissa lauseen
    aluissa, ja palat vuorottelevat perus- ja punch-in-rajauksen välillä.
    Hiljaiset alut eivät ole painotuksia."""
    from autoraffkat.model import Segment

    cut = [Segment("W", "Laaja", 0.0, 3.0), Segment("CAM A", "Host", 3.0, 40.0)]
    out = movement.punch_segments(cut, _talk_grid(), min_shot=2.5)
    assert out[0].angle == "W" and not out[0].punch
    pieces = [s for s in out if s.angle == "CAM A"]
    starts = [round(s.start, 1) for s in pieces]
    assert starts[0] == 3.0
    # Leikkaukset kovien alkujen kohdalla (hieman ennen), ei hiljaisten.
    for t in starts[1:]:
        assert any(abs(t - (loud - movement.PUNCH_LEAD)) < 0.05 for loud in (5, 12, 20, 28)), starts
    assert [s.punch for s in pieces] == [i % 2 == 1 for i in range(len(pieces))]
    assert all(b.start - a.start >= 2.5 - 1e-6 for a, b in pairwise(pieces))
    assert pieces[-1].end == 40.0


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
