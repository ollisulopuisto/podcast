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
    """Koko alue on tarkoituksella 1.00–1.06: zoomin ei saa nähdä."""
    durs = _durations(300)
    for move in movement.plan(durs, [False] * len(durs)):
        for value in (move.start_scale, move.end_scale):
            assert movement.SCALE_MIN <= value <= movement.SCALE_MAX


def test_short_clip_is_never_animated():
    """Alle kolmen sekunnin kuva ehtii alkaa ja loppua ennen kuin liike on
    havaittavissa — siitä ei kirjoiteta mitään liikettä."""
    durs = [2.9] * 40
    assert all(not m.animated for m in movement.plan(durs, [False] * len(durs)))


def test_long_clips_receive_a_slow_push():
    """Pitkä puheenvuoro saa hitaan puskun 2–5 % — jos mitään ei koskaan
    liiku, ominaisuus on olematta eikä mikään valita."""
    durs = [15.0] * 60
    animated = [m for m in movement.plan(durs, [False] * len(durs)) if m.animated]
    assert animated, "yksikään pitkä klippi ei liikkunut"
    for move in animated:
        push = abs(move.end_scale - move.start_scale)
        assert movement.PUSH_MIN <= push <= movement.PUSH_MAX


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
