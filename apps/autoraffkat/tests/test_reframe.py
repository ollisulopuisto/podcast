"""Reframing: the face lands on the centreline and the maths is known.

Every number here is derived in ``reframe.py`` from Apple's own FCPXML
documentation — position is percent of the project's height on both axes,
scale a fraction of the clip's fitted baseline — and the first real import
into Final Cut is what settles the derivation, not this file.
"""

from fractions import Fraction

import numpy as np

from autoraffkat import reframe
from autoraffkat.model import MediaItem, Placement
from autoraffkat.timeline import ZERO


def test_fill_scale_of_16x9_source():
    """16:9 source in a 9:16 project: Spatial Conform «Fill» fills the
    height, so the scale on top of it is 1.0 (it was 3.1605 relative to
    fit before the export wrote the conform)."""
    r = reframe.plan_shot(0.5, 0.5, 1920, 1080)
    assert r is not None
    assert r.scale == 1.0
    assert r.pos_x == 0.0
    assert r.pos_y == 0.0


def test_face_left_of_centre_moves_picture_right():
    """cx 0.3: the picture shifts right so the face lands on the centreline.

    Displayed width after fill is 3413 px; a 20 % shift of that is
    0.2 · 3413 / 19.2 ≈ 35.5 percent-of-height units.
    """
    r = reframe.plan_shot(0.3, 0.5, 1920, 1080)
    assert r.pos_x > 0
    assert abs(r.pos_x - 35.55) < 0.5


def test_face_right_of_centre_moves_picture_left():
    r = reframe.plan_shot(0.7, 0.5, 1920, 1080)
    assert r.pos_x < 0
    assert abs(r.pos_x + 35.55) < 0.5


def test_position_never_reveals_a_gap():
    """The clamp holds inside the content even for a face at the frame edge.

    A nonzero offset may never show anything beside the content: at
    percent-of-height units the offset in pixels is pos_x · 19.2, and the
    content has (displayed − project) / 2 pixels of slack on each side.
    """
    displayed = 1920 * 1920 / 1080
    slack = (displayed - 1080) / 2
    for cx in (0.0, 0.05, 0.5, 0.95, 1.0):
        r = reframe.plan_shot(cx, 0.5, 1920, 1080)
        assert abs(r.pos_x) * 19.2 <= slack + 0.01


def test_no_source_dims_gives_nothing():
    """Without dimensions there is nothing to compute — and no transform."""
    assert reframe.plan_shot(0.5, 0.5, 0, 0) is None


def test_source_already_taller_than_16x9_is_identity():
    """A source that already fills the height needs no crop — none is written.

    Fit already fills the height when the source is narrower than 9:16; a
    scale would only magnify. 1080×1920 is the extreme case.
    """
    assert reframe.plan_shot(0.3, 0.5, 1080, 1920) is None


# ------------------------------------------------------------- taulukoista


def _table(n=10, cx=0.5, found=True):
    """Testitaulukko samassa muodossa kuin ``measure_file`` tuottaa."""
    # Kasvolaatikko jonka keskipiste on ``cx``: kehystys lukee laatikkoa.
    return {
        "times": np.arange(n, dtype=np.float32),
        "found": np.full(n, found),
        "cx": np.full(n, 0.5, dtype=np.float32),
        "x": np.full(n, cx - 0.05, dtype=np.float32),
        "w": np.full(n, 0.1, dtype=np.float32),
        "y": np.full(n, 0.4, dtype=np.float32),
        "h": np.full(n, 0.2, dtype=np.float32),
    }


def _item(key="CLOSE_A", width=1920, height=1080, dur=36):
    item = MediaItem(key=key, name=key, path="", src="", width=width, height=height)
    item.placements.append(Placement(ZERO, ZERO, Fraction(dur)))
    return item


def test_a_short_stretch_elsewhere_keeps_the_frame():
    """Viisi sekuntia muualla ei ole uusi kehys.

    Ennen kehys oli kuvan omien rivien mediaani, jolloin jokainen kuva
    rajattiin hieman eri kohtaan. Käyttäjän toive (2026-09-25): rajaus
    pysyy vakaana läpi jakson ja siirtyy vain pitkäkestoisesta
    liikkeestä, ks. ``steady``. Kuvan omat rivit päättävät yhä sen, onko
    kasvoja ylipäätään löytynyt.
    """
    from autoraffkat.reframe import Reframer

    item = _item()
    table = _table(10, cx=0.5)
    # Liike rajauksen sisällä. Jos kasvot jäisivät reunasta ulos, kuva
    # siirtyy kuitenkin — ks. test_a_shot_where_the_face_would_be_cut…
    table["x"][:5] = 0.44 - 0.05
    framer = Reframer({item.key: table})
    first = framer.from_item(item, 0.0, 4.0)
    second = framer.from_item(item, 5.0, 9.0)
    assert first.pos_x == second.pos_x


def test_too_few_found_rows_gives_nothing():
    """Yksittäinen osumakin on sattuma, ei kehystys."""
    from autoraffkat.reframe import Reframer

    item = _item()
    table = _table(10, cx=0.4)
    table["found"][:] = False
    table["found"][4] = True
    assert Reframer({item.key: table}).from_item(item, 0.0, 9.0) is None


def test_missing_table_gives_nothing():
    """Mittaamaton tiedosto saa letterboxin, ei arvausta."""
    from autoraffkat.reframe import Reframer

    item = _item(key="MITTAAMATON")
    assert Reframer({}).from_item(item, 0.0, 9.0) is None


def test_span_outside_the_media_gives_nothing():
    """Aukon tai osarajan ulkopuolella ei ole sijoitusta eikä aikaa."""
    from autoraffkat.reframe import Reframer

    item = _item()
    assert Reframer({item.key: _table()}).from_item(item, 40.0, 50.0) is None


def test_a_group_shot_is_never_cropped_to_one_face():
    """Kahden kuva saa letterboxin, vaikka kameralle olisi mittaus.

    Mittaus on olemassa jos sama kamera oli joskus lähikuva. Mediaanikasvo
    kahden kuvassa on toisen ihmisen kasvot, ja rajaus leikkaisi toisen
    pois — kelvollinen vienti, väärä kuva, eikä mikään kerro.
    """
    from types import SimpleNamespace

    from autoraffkat.reframe import Reframer, close_up_tables

    close, group = _item("CLOSE_A"), _item("TWO_SHOT")
    timeline = SimpleNamespace(
        track_media=lambda key: {"A": [close], "B": [group]}.get(key, []))
    roles = SimpleNamespace(closes={"Host": "A"}, groups={"B": ["Host", "Guest"]})
    tables = close_up_tables(
        {close.key: _table(), group.key: _table()}, timeline, roles)
    assert Reframer(tables).from_item(group, 0.0, 9.0) is None
    assert Reframer(tables).from_item(close, 0.0, 9.0) is not None


# ------------------------------------------- täyttö ja kasvojen koko (2026-09-25)


def _boxes(n=10, x=0.45, y=0.5, w=0.1, h=0.2, cx=0.5):
    """Taulukko jossa kasvojen laatikko: Vision antaa sen kuvan
    normalisoiduissa koordinaateissa, origo **alhaalla** vasemmalla."""
    table = _table(n)
    table["cx"] = np.full(n, cx, dtype=np.float32)
    for name, value in (("x", x), ("y", y), ("w", w), ("h", h)):
        table[name] = np.full(n, value, dtype=np.float32)
    return table


def test_the_face_is_where_its_box_is_not_where_its_landmarks_average():
    """``cx`` on maamerkkien keskiarvo **kasvolaatikon** sisällä, ei kuvassa.

    Visionin ``normalizedPoints`` normalisoidaan kasvojen omaan laatikkoon,
    joten ``cx`` on ~0,5 missä tahansa kasvot ovat ja liikkuu vain kun pää
    kääntyy. Kehystys luki sitä kuvan paikkana ja keskitti siis
    käytännössä kuvan keskelle. Paikka on laatikko: ``x + w/2``.
    """
    from autoraffkat.reframe import Reframer

    item = _item()
    table = _boxes(x=0.60, w=0.10, cx=0.5)  # kasvot kohdassa 0,65
    shot = Reframer({item.key: table}).from_item(item, 0.0, 9.0)
    assert shot is not None
    # 0,15 kuvan leveydestä, täytössä 3413 px leveä, 19,2 px yksikkö.
    assert abs(shot.pos_x - (-0.15 * 3413.33 / 19.2)) < 0.5


def test_fill_is_the_baseline_and_the_units_match_final_cut():
    """Final Cutin oma pystypohja: Spatial Conform «Fill», Tomi 1,22 ja
    sijainti -30,7292. Täytössä skaala on suhteessa täytettyyn kokoon
    (1,0 = korkeus täynnä) ja sijainti prosentteina projektin korkeudesta.

    Kasvojen paikka on johdettu näistä luvuista, joten testi ei todista
    kehystystä vaan yksiköt: sama laskenta tuottaa Final Cutin kirjoittaman
    luvun takaisin.
    """
    shot = reframe.plan_shot(0.64168, 0.5, 1920, 1080, zoom=1.22)
    assert abs(shot.scale - 1.22) < 1e-9
    assert abs(shot.pos_x - (-30.7292)) < 0.05
    centred = reframe.plan_shot(0.5, 0.5, 1920, 1080)
    assert (centred.scale, centred.pos_x, centred.pos_y) == (1.0, 0.0, 0.0)


def test_faces_are_evened_out_by_zooming_the_smaller_ones():
    """Suurimmat kasvot pysyvät 100 %:ssa, muut zoomataan samankokoisiksi.

    Käsin tehdyssä pohjassa Tomin kamera oli zoomattu 1,22:een, jotta hänen
    kasvonsa olivat Mikon kokoiset. Katto on 1,25: täyttö suurentaa jo
    1080-lähteen 1920:een, ja jokainen lisäprosentti on pehmeämpi kuva.
    """
    from types import SimpleNamespace

    items = {k: _item(k) for k in ("MIKKO", "TOMI", "KAUKANA")}
    timeline = SimpleNamespace(track_media=lambda key: [items[key]] if key in items else [])
    roles = SimpleNamespace(closes={"Mikko": "MIKKO", "Tomi": "TOMI", "Kaukana": "KAUKANA"})
    tables = {"MIKKO": _boxes(h=0.30), "TOMI": _boxes(h=0.246), "KAUKANA": _boxes(h=0.10)}
    look = reframe.look(tables, timeline, roles)
    assert look.zooms["MIKKO"] == 1.0
    assert abs(look.zooms["TOMI"] - 0.30 / 0.246) < 1e-3
    assert look.zooms["KAUKANA"] == reframe.MAX_ZOOM == 1.25


def test_a_zoomed_face_lands_on_the_reference_eyeline():
    """Zoomatun kasvot samalle korkeudelle kuin 100 %:n kameran kasvot.

    Täytössä pystysuunnassa ei ole liikkumavaraa, joten 100 %:n kamera
    määrää silmälinjan; zoomattua voi siirtää sen verran kuin zoomi antaa.
    """
    # Kasvot 0,40 ylhäältä, silmälinja 0,45: kuvaa siirretään alas.
    shot = reframe.plan_shot(0.5, 0.40, 1920, 1080, zoom=1.2, eyeline=0.45)
    moved = (0.40 - 0.5) * 1920 * 1.2 - (0.45 - 0.5) * 1920
    assert abs(shot.pos_y - moved / 19.2) < 1e-6
    # Liikkumavaraa on vain (1,2 - 1) * 1920 / 2 = 192 px: ei reunaa näkyviin.
    far = reframe.plan_shot(0.5, 0.05, 1920, 1080, zoom=1.2, eyeline=0.6)
    assert abs(far.pos_y) * 19.2 <= 192 + 1e-6


# ------------------------------------ laaja ja ryhmäkuva puhujan mukaan


def _crowd_grid(seconds=40):
    from autoraffkat.decide import Grid, SpeakerLanes
    from autoraffkat.model import HOP

    n = int(seconds / HOP)

    def lane(name, spans):
        on = np.zeros(n, dtype=bool)
        for a, b in spans:
            on[int(a / HOP):int(b / HOP)] = True
        return SpeakerLanes(name, np.where(on, -30.0, -60.0).astype(np.float32), on, None)

    return Grid(n=n, program_start=0.0, wide_key="W", speakers=[
        lane("Tomi", [(0, 2)]),
        lane("Mikko", [(3, 10), (10.2, 10.6), (20, 30)]),
        lane("Vieras", [(10, 20)]),
    ])


def test_a_group_shot_is_split_where_the_speaker_changes():
    """Pystyviennissä ryhmäkuva on uusi kuva kun puhuja vaihtuu.

    Leikkauksessa kahden kuva on yksi kuva, koska se näyttää molemmat;
    pystyrajaus näyttää vain yhden, joten vuoronvaihto on leikkaus.
    Minimikestoa lyhyempi välähdys (Mikon 0,4 s myötäily) ei ole kuva, ja
    hiljaisuus pitää edellisen.
    """
    from autoraffkat.model import Segment

    cut = [Segment("W", "Laaja", 0.0, 2.0), Segment("CAM 3", "Mikko & Vieras", 2.0, 40.0)]
    out = reframe.focus_segments(cut, _crowd_grid(), {"CAM 3": [1, 2]}, min_shot=1.5)
    assert [(s.angle, round(s.start, 2), round(s.end, 2), s.focus) for s in out] == [
        ("W", 0.0, 2.0, ""),
        ("CAM 3", 2.0, 10.0, "Mikko"),
        ("CAM 3", 10.0, 20.0, "Vieras"),
        ("CAM 3", 20.0, 40.0, "Mikko"),
    ]


def test_a_crowd_shot_is_framed_on_its_speaker():
    """Vierasta puhuessa rajaus on vieraassa, vaikka Mikko istuu oikealla."""
    from autoraffkat.seats import FileSeats, Seat

    item = _item("CAM 3 01.mp4")
    table = {"times": np.arange(40, dtype=np.float32),
             "frame": np.repeat(np.arange(40, dtype=np.int32), 2),
             "x": np.tile(np.array([0.15, 0.65], np.float32), 40),
             "w": np.full(80, 0.1, np.float32), "y": np.full(80, 0.4, np.float32),
             "h": np.full(80, 0.2, np.float32), "mouth": np.zeros(80, np.float32)}
    rows = np.arange(80)
    found = FileSeats(seats={
        1: Seat(1, 0.70, 0.5, 0.2, rows[1::2]),
        2: Seat(2, 0.20, 0.5, 0.2, rows[0::2]),
    })
    framer = reframe.Reframer({}, crowd={item.key: found}, crowd_tables={item.key: table},
                              names=["Tomi", "Mikko", "Vieras"])
    guest = framer.from_item(item, 10.0, 20.0, focus="Vieras")
    mikko = framer.from_item(item, 20.0, 30.0, focus="Mikko")
    assert guest.pos_x > 0 > mikko.pos_x   # vieras vasemmalla -> kuva oikealle
    assert abs(guest.pos_x - (0.30 * 3413.33 / 19.2)) < 0.5
    # Tomi ei ole tässä kuvassa: rajaus näkyvimpään istujaan eikä keskelle,
    # jossa se leikkaisi molemmat kasvot puoliksi.
    elsewhere = framer.from_item(item, 0.0, 2.0, focus="Tomi")
    assert elsewhere is not None and elsewhere.pos_x != 0.0


# ------------------------------------------------------ vakaa kehys (2026-09-25)


def test_small_movement_does_not_move_the_frame():
    """Tuolissa huojuminen ei ole uusi kehys; pitkä siirtymä on.

    Kasvot heiluvat ±0,01 leveydestä koko ajan, 30 s:n käynti 0,7:ssä on
    nousu ja takaisin istumaan, ja 150 s:n kohdalla kamera siirtyy
    pysyvästi niin että kasvot ovat 0,62:ssa.
    """
    rng = np.random.default_rng(3)
    times = np.arange(300, dtype=np.float64)
    x = 0.5 + rng.uniform(-0.01, 0.01, 300)
    x[60:75] = 0.7            # 15 s pois: ei uutta kehystä
    x[150:] += 0.12           # pysyvä siirtymä
    steps = reframe.steady(times, x)
    levels = [round(v, 2) for _t, v in steps]
    assert len(steps) == 2, steps
    assert levels[0] == 0.5 and levels[1] == 0.62
    assert 150 <= steps[1][0] <= 185


def test_consecutive_shots_of_one_camera_frame_identically():
    """Saman kameran kaksi kuvaa samassa kohdassa jaksoa: sama kehys,
    vaikka kasvot heiluisivat — muuten jokainen leikkaus takaisin samaan
    kameraan nytkähtäisi muutaman pikselin."""
    from autoraffkat.reframe import Reframer

    item = _item(dur=120)
    rng = np.random.default_rng(5)
    table = _boxes(n=120, x=0.45)
    table["times"] = np.arange(120, dtype=np.float32)
    table["x"] = (0.45 + rng.uniform(-0.01, 0.01, 120)).astype(np.float32)
    framer = Reframer({item.key: table})
    first = framer.from_item(item, 10.0, 20.0)
    second = framer.from_item(item, 40.0, 55.0)
    assert first.pos_x == second.pos_x


# --------------------------------------------- puolikkaat kasvot (2026-09-25)


def test_a_neighbour_is_either_in_or_out_never_halved():
    """Vieressä istuvan kasvot joko kokonaan pois tai kokonaan mukaan.

    Kahden kuvassa puhujaan keskitetty rajaus leikkasi naapurin kasvot
    reunasta puoliksi. Rajausta siirretään sen verran että naapuri jää
    ulos, kun puhujan kasvot pysyvät silti marginaaleineen sisällä.
    """
    half = 1080 / (1920 * 1920 / 1080) / 2  # rajausikkunan puolikas, lähteen leveydestä
    shot = reframe.plan_shot(0.62, 0.5, 1920, 1080, face_w=0.12,
                             others=[(0.45, 0.12)])
    centre = 0.5 - shot.pos_x * 19.2 / 3413.33
    left, right = centre - half, centre + half
    neighbour = (0.45 - 0.06, 0.45 + 0.06)
    assert left >= neighbour[1] - 1e-6 or right <= neighbour[0] + 1e-6 \
        or (left <= neighbour[0] and right >= neighbour[1])
    assert left <= 0.62 - 0.06 and right >= 0.62 + 0.06  # puhuja kokonaan kuvassa


def test_a_crowd_shot_without_a_speaker_frames_someone_not_the_gap():
    """Kahden kuva jossa kukaan ei puhu (päätykuva, tauko) ei ole keskellä.

    Keskellä on tyhjä väli kahden ihmisen välissä, ja rajaus leikkasi
    molemmat kasvot puoliksi. Rajataan näkyvimpään istujaan.
    """
    from autoraffkat.seats import FileSeats, Seat

    item = _item("CAM 3 01.mp4")
    table = {"times": np.arange(40, dtype=np.float32),
             "frame": np.repeat(np.arange(40, dtype=np.int32), 2),
             "x": np.tile(np.array([0.15, 0.65], np.float32), 40),
             "w": np.full(80, 0.1, np.float32), "y": np.full(80, 0.4, np.float32),
             "h": np.tile(np.array([0.18, 0.22], np.float32), 40),
             "mouth": np.zeros(80, np.float32)}
    rows = np.arange(80)
    found = FileSeats(seats={
        1: Seat(1, 0.70, 0.5, 0.22, rows[1::2], w=0.1),
        2: Seat(2, 0.20, 0.5, 0.18, rows[0::2], w=0.1),
    })
    framer = reframe.Reframer({}, crowd={item.key: found}, crowd_tables={item.key: table},
                              names=["Tomi", "Mikko", "Vieras"])
    shot = framer.from_item(item, 0.0, 5.0)
    assert shot is not None
    assert shot.pos_x < -20   # isompi kasvo oikealla -> kuva vasemmalle


def test_a_short_close_up_is_framed_from_the_camera_position():
    """Alle kolmen sekunnin lähikuva kehystetään siinä missä pitkäkin.

    Kuva vaati kolme omaa löytöä (avainruutu sekunnissa), joten
    nopean rytmin lyhyet kuvat jäivät täytön keskelle: oikealla jaksolla
    252 kuvaa 594:stä, kasvoista 30–100 % rajauksen ulkopuolella (video
    files -istunnon mittaus, 2026-09-25). Paikka tulee tiedoston vakaasta
    portaasta, joten kuvan omien ruutujen määrä ei kerro siitä mitään.
    """
    from autoraffkat.reframe import Reframer

    item = _item()
    table = _table(10, cx=0.7)
    framer = Reframer({item.key: table})
    short = framer.from_item(item, 2.2, 3.6)
    assert short is not None
    assert short.pos_x < -30


def test_a_shot_where_the_face_would_be_cut_shifts_just_enough():
    """Vakaa kehys, paitsi jos kuvan omat kasvot jäisivät reunasta ulos.

    Oikealla jaksolla (video files -istunnon mittaus, 2026-09-25) kaksi
    lyhyttä kuvaa leikkasi 14 % kasvoista: puhuja nojasi sivulle koko
    kuvan ajan. Vakaa porras ei siirry lyhyestä nojauksesta, joten kuvan
    oma mediaanilaatikko pitää rajauksen sisällä — pienimmällä siirrolla,
    ja vain silloin. Hetkellinen liike (mediaani sisällä) ei siirrä mitään.
    """
    from autoraffkat.reframe import Reframer

    item = _item(dur=120)
    table = _boxes(n=120, x=0.45, w=0.1)      # kasvot 0,50:ssa koko jakson
    table["times"] = np.arange(120, dtype=np.float32)
    table["x"][60:64] = 0.57                  # 4 s nojaus: laatikko 0,57–0,67
    framer = Reframer({item.key: table})
    steady_shot = framer.from_item(item, 20.0, 30.0)
    leaning = framer.from_item(item, 60.0, 64.0)
    half = 1080 / 3413.33 / 2
    centre = 0.5 - leaning.pos_x * 19.2 / 3413.33
    pad = reframe.KEEP_PAD * 0.10
    assert centre + half >= 0.67 + pad - 1e-6  # kasvot pehmusteineen sisällä
    assert abs(centre - (0.67 + pad - half)) < 1e-3  # pienin siirto
    assert steady_shot.pos_x == framer.from_item(item, 70.0, 80.0).pos_x


def test_the_kept_face_still_fits_at_the_movement_zoom():
    """Mikroliike zoomaa kuvaa kehyksen päälle, ja se kaventaa rajausta.

    Kehys laskettiin 100 %:lle, ja mikroliikkeen 3–7 %:n lisäzoomi vei
    reunan 17–19 px kasvojen sisään (video files, eea265a: Mikko 86,
    Tomi 536). Pidettävän laatikon on mahduttava koko zoomin ajan.
    Final Cut skaalaa kuvan keskipisteen ympäri ja siirtää sitten, joten
    ikkunan keskipiste lähteessä on 0,5 + (c - 0,5) / m ja puolikas h / m.
    """
    box = (0.57, 0.67)
    headroom = 1.06
    shot = reframe.plan_shot(0.5, 0.5, 1920, 1080, keep=box, headroom=headroom)
    shown = 1920 * 1920 / 1080
    for m in (1.0, headroom):
        half = 1080 / (shown * m) / 2
        centre = 0.5 - shot.pos_x * 19.2 / (shown * m)
        assert centre - half <= box[0] + 1e-9 and box[1] <= centre + half + 1e-9, m
