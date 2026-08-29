"""automixerin istunto kirjaston saumana: mikit huoneessa, ruudukko päälle.

Tähän asti automixerilla oli jaettu **ketju** mutta ei jaettua
**päätöskerrosta**. `SPEECHMIX-INVENTORY.md` kirjasi seurauksen kahdesti:
tasonkuljettaja «tarvitsee puheruudukon, eikä automixerilla ole mikrofoneja
joista sellaista rakentaa», ja ristivuodon vähennys «on yhä auki, ja
tarvitsee sekin ruudukon». Kumpikin oli väärä johtopäätös oikeasta
havainnosta: mikrofoneja on, ne ovat vain wav-tiedostoja aikajanalla eivätkä
FCPXML:n kulmia.

`domain/room.py` on se muunnos, ja se on kaikki mitä puuttui. Sen jälkeen
vaimennus, ristivuoto ja tasonkuljettaja ovat samaa koodia kuin
autoraffkatilla — nämä testit ajavat ne läpi automixerin omalla muodolla.

Tässä tiedostossa ei ole mlx:ää. Se on tarkoituksellista: laskenta on numpyä
ja scipyä ja kuuluu kirjastolle, ja mlx-vapaa moduuli on testattavissa myös
siellä missä mlx:ää ei ole.
"""

from __future__ import annotations

import numpy as np
import pytest

from automixer.domain import room
from speechmix.masks import HOP

RATE = 16000


def _talk(seconds: float, turns, rate: int = RATE, level: float = 0.25,
          floor: float = 3e-4, seed: int = 11) -> np.ndarray:
    """Puhetta annetuilla väleillä, pohjakohinaa muualla."""
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    out = (rng.normal(size=n) * floor).astype(np.float32)
    for start, stop in turns:
        lo, hi = int(start * rate), int(stop * rate)
        out[lo:hi] += (rng.normal(size=hi - lo) * level).astype(np.float32)
    return out


def _two_speakers(seconds=8.0):
    """Vuorotellen: A puhuu ensin, B sitten, ja niin edelleen."""
    a = _talk(seconds, [(0.5, 2.0), (4.5, 6.0)], seed=1)
    b = _talk(seconds, [(2.5, 4.0), (6.5, 7.8)], seed=2)
    return [room.Mic("A", a), room.Mic("B", b)]


def test_a_wav_track_becomes_a_track_with_one_span():
    """Sauma: tiedoston alkuhetki ja pituus, ei muuta."""
    heard = room.listen([room.Mic("A", _talk(4.0, [(1.0, 2.0)]), start_sec=2.5)], RATE)

    track = heard.tracks["A"]
    assert len(track.spans) == 1
    assert track.spans[0].programme_start == pytest.approx(2.5)
    assert track.spans[0].programme_end == pytest.approx(6.5)
    assert track.speaker == "A"
    # Ruudukko kattaa koko ohjelman, myös sen osan jossa tätä raitaa ei ole.
    assert heard.grid.n_frames == pytest.approx(int(6.5 / HOP), abs=1)


def test_the_grid_knows_who_is_talking():
    """Ruudukko on koko puuttuva kerros, ja tämä on sen väite."""
    heard = room.listen(_two_speakers(), RATE)

    lanes = {lane.name: lane for lane in heard.grid.speakers}
    assert set(lanes) == {"A", "B"}
    assert lanes["A"].on[int(1.0 / HOP)], "A puhuu sekunnilla 1"
    assert not lanes["A"].on[int(3.0 / HOP)], "sekunnilla 3 puhuu B"
    assert lanes["B"].on[int(3.0 / HOP)]
    assert not lanes["B"].on[int(1.0 / HOP)]


def test_a_track_that_starts_later_lands_where_it_starts():
    """Aikajanan siirtymä on jaksossa, ei näytteissä.

    automixerin väylä siirtää raitaa summatessaan, joten ruudukon on
    tiedettävä sama siirtymä — muuten vaimennus osuisi väärään kohtaan
    juuri niillä raidoilla joilla siirtymä on.
    """
    late = room.Mic("B", _talk(4.0, [(0.5, 2.0)], seed=3), start_sec=10.0)
    heard = room.listen([room.Mic("A", _talk(4.0, [(0.5, 2.0)], seed=1)), late], RATE)

    lanes = {lane.name: lane for lane in heard.grid.speakers}
    assert lanes["B"].on[int(11.0 / HOP)], "B:n puhe on aikajanalla 10,5–12"
    assert not lanes["B"].on[int(1.0 / HOP)]


def test_ducking_closes_the_quiet_microphone_and_only_there():
    """Toinen sauma: sama päätös, poltettuna näytteisiin.

    autoraffkat kirjoittaa käyrän Final Cutin keyframeiksi. automixerillä ei
    ole mitään mihin automaatio kirjoitettaisiin — se vie valmiin wavin —
    joten se kertoo saman käyrän näytteisiin. Sama laskenta, eri emissio.
    """
    heard = room.listen(_two_speakers(), RATE)

    points = heard.duck_envelopes(room.DuckSettings())
    assert set(points) >= {"A"}, "A:n mikin pitäisi sulkeutua B:n puheen alla"

    frames = int(8.0 * RATE)
    gain = heard.duck_gain("A", points["A"], frames)

    # B puhuu 2,5–4,0 s: A:n mikki on kiinni sen alla.
    assert gain[int(3.2 * RATE)] < 0.9
    # A puhuu 0,5–2,0 s: oma mikki auki.
    assert gain[int(1.2 * RATE)] == pytest.approx(1.0)


def test_ducking_off_is_a_flat_gain_not_a_missing_key():
    """Asetus pois päältä ja tuloksessa ei mitään on eri asia kuin virhe."""
    heard = room.listen(_two_speakers(), RATE)
    assert heard.duck_envelopes(room.DuckSettings(duck=False)) == {}
    assert heard.duck_gain("A", [], int(8.0 * RATE)).tolist() == [1.0]


def test_the_rider_mask_is_the_speakers_own_speech_not_the_level():
    """Signaalista pääteltynä puolet «puheesta» olisi toisen vuotoa.

    Mitattuna autoraffkatilla: tasoheuristiikka kutsui 74 % lohkoista
    puheeksi kun 53 % oli omaa, ja ne olivat samaa mieltä 38 %:sta. Kuljettaja
    nosti vuotoa, pohjakohina nousi 3,5 dB ja tasonvaihtelu **huononi**.
    Maski tulee siis ruudukosta, ei signaalista.
    """
    heard = room.listen(_two_speakers(), RATE)
    block = int(0.5 * RATE)
    count = int(8.0 * RATE) // block

    own = heard.own_speech("A", block, count)

    assert own is not None
    assert own[int(1.0 / 0.5)], "A puhuu lohkossa 1,0–1,5 s"
    assert not own[int(3.0 / 0.5)], "sekunnilla 3 puhuu B, ei A"


def test_a_lone_microphone_has_nothing_to_duck_against():
    """Yksi mikki *on* ohjelma: ei toista jonka alle piiloutua."""
    heard = room.listen([room.Mic("A", _talk(4.0, [(0.5, 2.0)]))], RATE)
    assert heard.duck_envelopes(room.DuckSettings()) == {}
    assert heard.solo_masks() == {}


def test_the_leak_of_the_other_microphone_is_subtracted():
    """Vuoto on lineaarinen, joten se voidaan vähentää.

    Sama väite kuin kirjaston omassa testissä, mutta automixerin muodolla:
    kaksi wav-raitaa, ruudukko niistä, ja `solo_masks` kertoo mistä kohtaa
    suodin estimoidaan. Kohteen oma puhe ei saa lähteä mukana — se on se
    virhe joka kuuluu vasta viennin jälkeen.
    """
    from scipy import signal as sig

    rate = 16000
    seconds = 120.0
    rng = np.random.default_rng(5)
    n = int(rate * seconds)
    t = np.arange(n) / rate
    # Vuorottelevat puheenvuorot, tarpeeksi pitkät estimointiin.
    source = (rng.normal(size=n) * (np.sin(2 * np.pi * 0.05 * t) > 0.0)).astype(
        np.float32
    )
    own = (rng.normal(size=n) * (np.sin(2 * np.pi * 0.05 * t) < -0.3)).astype(
        np.float32
    )
    leak = np.zeros(200)
    leak[80], leak[95], leak[120] = 0.18, -0.07, 0.04
    target = (own + sig.fftconvolve(source, leak)[:n]).astype(np.float32)

    heard = room.listen([room.Mic("A", target), room.Mic("B", source)], rate)
    cleaned, notes = heard.debleed("A", target, {"B": source})

    assert not notes, notes
    solo_source = (source != 0) & (own == 0)
    def level(x):
        return 10 * np.log10(float(np.mean(np.asarray(x)[solo_source] ** 2)) + 1e-30)
    assert level(target) - level(cleaned) > 6.0, "vuodon pitäisi vaimentua"

    solo_target = (own != 0) & (source == 0)
    kept = float(np.corrcoef(target[solo_target], cleaned[solo_target])[0, 1])
    assert kept > 0.99, kept


def test_a_refused_filter_says_why_instead_of_going_quiet():
    """Asetus päällä ja tuloksessa ei mitään on tämän projektin toistuva vika."""
    heard = room.listen(_two_speakers(), RATE)
    a = heard.samples_of("A")

    cleaned, notes = heard.debleed("A", a, {"B": heard.samples_of("B")})

    # Kahdeksassa sekunnissa ei ole tarpeeksi yksinpuhetta estimointiin.
    assert notes, "hylkäyksen syyn on tultava ulos"
    assert np.array_equal(cleaned, a), "hylätty suodin ei saa muuttaa mitään"


def test_two_microphones_cannot_share_a_name():
    """Kaksi samannimistä raitaa katoaisi hiljaa yhdeksi kaistaksi.

    Ruudukko, vaimennus ja vuodon vähennys avaimetaan puhujan nimellä.
    Törmäys ei kaataisi mitään — toinen mikki vain jäisi pois ruudukosta,
    eikä siitä sanottaisi mitään. Asetus päällä ja tuloksessa ei mitään on
    tämän projektin toistuva vika, joten tämä on virhe.
    """
    same = [
        room.Mic("A", _talk(4.0, [(0.5, 2.0)], seed=1)),
        room.Mic("A", _talk(4.0, [(2.5, 3.5)], seed=2)),
    ]
    with pytest.raises(ValueError, match="A"):
        room.listen(same, RATE)
