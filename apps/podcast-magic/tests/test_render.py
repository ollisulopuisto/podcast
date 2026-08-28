"""Miksauksen renderöinti: leikkeet sisään, ohjelma-WAV ulos.

Purku on tässä **injektoitu**. Kaksi syytä. Ensinnäkin CI ei skippaa: testi
joka tarvitsee ffmpegin on testi joka on vihreä koneilla joilla sitä ei ole,
ja se on sama kuin ettei sitä olisi. Toiseksi renderöinnin viat eivät ole
purussa vaan summauksessa — mihin kohtaan leike osuu, mistä kohtaa
tiedostoa se luetaan, mitä lohkon rajalla tapahtuu. Purku on ffmpegin
ongelma; nämä ovat meidän.
"""

from __future__ import annotations

import wave

import numpy as np
import pytest

from podcastmagic.nhsx import render
from podcastmagic.nhsx.mix import Clip, Mix

SR = 1000  # testien näytetaajuus: laskettava käsin, riittävän tiheä
PROBE = 0.01  # ``ramp``in asteikko, ks. siellä


def constant(value: float = 1.0, channels: int = 1):
    """Purkaja, joka antaa vakiota niin paljon kuin pyydetään."""

    def decode(path, start, length, sample_rate):
        n = int(round(length * sample_rate))
        return np.full((n, channels), value, dtype=np.float32)

    return decode


def ramp(sample_rate: int = SR):
    """Purkaja, jonka näyte **on** sen aika tiedostossa — sadasosina.

    Näin renderöidystä ohjelmasta voi lukea suoraan, mistä kohtaa lähdettä
    kukin näyte tuli — juuri se muunnos jonka voi tehdä väärin ilman että
    mikään kaatuu.

    Sadasosina eikä sekunteina, koska ohjelma on ääntä: sekunnissa 30 oleva
    näyte olisi arvo 30,0 ja rajautuisi ykköseen ennen kuin sitä ehtii
    lukea. ``PROBE`` on se sama luku toisin päin.
    """

    def decode(path, start, length, sample_rate):
        n = int(round(length * sample_rate))
        t = start + np.arange(n, dtype=np.float32) / sample_rate
        return (t * PROBE).reshape(-1, 1)

    return decode


def one(**kwargs) -> Mix:
    base = {"path": "a.wav", "speaker": "Olli", "start": 0.0, "length": 1.0,
            "file_offset": 0.0}
    base.update(kwargs)
    clip = Clip(**base)
    return Mix(clips=[clip], duration=max(2.0, clip.end))


def render_all(mixdown, **kwargs) -> np.ndarray:
    kwargs.setdefault("sample_rate", SR)
    kwargs.setdefault("decode", constant())
    return np.concatenate(list(render.blocks(mixdown, **kwargs)))


# --- Geometria ----------------------------------------------------------


def test_the_render_is_as_long_as_the_programme():
    out = render_all(Mix(clips=[], duration=2.5))
    assert out.shape == (2500, 2)
    assert not out.any()


def test_a_clip_lands_where_the_area_puts_it():
    out = render_all(one(start=1.0, length=0.5))
    left = out[:, 0]
    assert not left[:1000].any()
    assert left[1000:1500].all()
    assert not left[1500:].any()


def test_the_offset_chooses_which_part_of_the_source_is_heard():
    """Ohjelma-aika ja tiedostoaika ovat eri asia, ja tämä on se ero."""
    out = render_all(one(start=1.0, length=0.5, file_offset=30.0), decode=ramp())
    # Näyte = sen aika lähdetiedostossa. Ohjelman sekunnissa 1,0 pitää
    # kuulua tiedoston sekunti 30,0 — ei sekunti 1,0 eikä 31,0.
    assert out[1000, 0] / render.pan_of(0.0)[0] / PROBE == pytest.approx(30.0, abs=0.01)
    assert out[1250, 0] / render.pan_of(0.0)[0] / PROBE == pytest.approx(30.25, abs=0.01)


def test_the_same_source_twice_reads_two_different_places():
    mixdown = Mix(
        clips=[
            Clip("a.wav", "Olli", start=0.0, length=0.5, file_offset=0.0),
            Clip("a.wav", "Olli", start=1.0, length=0.5, file_offset=60.0),
        ],
        duration=2.0,
    )
    out = render_all(mixdown, decode=ramp())
    gain = render.pan_of(0.0)[0] * PROBE
    assert out[100, 0] / gain == pytest.approx(0.1, abs=0.01)
    assert out[1100, 0] / gain == pytest.approx(60.1, abs=0.01)


def test_a_clip_running_past_the_programme_end_is_cut_not_wrapped():
    out = render_all(Mix(clips=[Clip("a.wav", "Olli", 1.5, 2.0, 0.0)], duration=2.0))
    assert out.shape == (2000, 2)
    assert out[1500:, 0].all()


# --- Summaus ------------------------------------------------------------


def test_two_tracks_sum():
    mixdown = Mix(
        clips=[
            Clip("a.wav", "Olli", 0.0, 1.0, 0.0),
            Clip("b.wav", "Panu", 0.0, 1.0, 0.0),
        ],
        duration=1.0,
    )
    out = render_all(mixdown, decode=constant(0.25))
    assert out[500, 0] == pytest.approx(2 * 0.25 * render.pan_of(0.0)[0])


def test_the_sum_is_clamped_and_the_clipping_is_reported():
    """Ylivuoto ei saa kiertyä. Kiertynyt summa on rätinää, ei kovaa ääntä."""
    mixdown = Mix(clips=[Clip("a.wav", f"P{i}", 0.0, 1.0, 0.0) for i in range(8)], duration=1.0)
    report = render.Report()
    out = render_all(mixdown, decode=constant(1.0), report=report)
    assert out.max() == pytest.approx(1.0)
    assert out.min() >= -1.0
    assert report.clipped > 0
    assert report.peak > 1.0


def test_a_programme_that_does_not_clip_says_its_peak():
    report = render.Report()
    render_all(one(), decode=constant(0.5), report=report)
    assert report.clipped == 0
    assert report.peak == pytest.approx(0.5 * render.pan_of(0.0)[0])


# --- Taso, panorointi, häivytys ----------------------------------------


def test_gain_scales_the_result():
    out = render_all(one(gain=0.5))
    assert out[500, 0] == pytest.approx(0.5 * render.pan_of(0.0)[0])


def test_a_pan_puts_the_signal_on_one_side():
    out = render_all(one(pan=-1.0))
    assert out[500, 0] == pytest.approx(1.0)
    assert out[500, 1] == pytest.approx(0.0, abs=1e-6)


def test_a_fade_in_is_a_ramp_in_the_result():
    out = render_all(one(length=1.0, fade_in=1.0))
    left = out[:1000, 0]
    assert left[0] == pytest.approx(0.0)
    assert left[999] == pytest.approx(render.pan_of(0.0)[0], abs=0.01)
    # Monotoninen: häivytys ei saa hyppiä.
    assert np.all(np.diff(left) >= -1e-6)


def test_a_stereo_source_keeps_its_sides():
    def decode(path, start, length, sample_rate):
        n = int(round(length * sample_rate))
        out = np.zeros((n, 2), dtype=np.float32)
        out[:, 0] = 1.0  # vain vasen kanava
        return out

    out = render_all(one(), decode=decode)
    assert out[500, 0] > 0.0
    assert out[500, 1] == pytest.approx(0.0, abs=1e-6)


# --- Lohkot -------------------------------------------------------------


def test_the_block_size_does_not_change_the_result():
    """Tämä on koko lohkorakenteen tarkistus.

    Ohjelmaa ei pidetä muistissa kokonaisena — tunnin jakso olisi 48 kHz:llä
    stereona 1,4 GB — vaan se kirjoitetaan lohko kerrallaan. Silloin jokainen
    lohkon raja on paikka jossa leike voi katketa, häivytys alkaa alusta tai
    lähteestä luetaan väärä kohta. Mikään niistä ei kaada mitään: tulos on
    kelvollinen WAV, jossa on naksahdus minuutin välein.

    Sama miksaus kahdella lohkokoolla on ainoa tarkistus joka näkee ne
    kaikki kerralla.
    """
    mixdown = Mix(
        clips=[
            Clip("a.wav", "Olli", 0.3, 2.4, 10.0, gain=0.8, fade_in=0.4, fade_out=0.6),
            Clip("b.wav", "Panu", 1.1, 1.9, 5.0, pan=0.5),
        ],
        duration=3.5,
    )
    whole = render_all(mixdown, decode=ramp(), block=10.0)
    chopped = render_all(mixdown, decode=ramp(), block=0.25)
    assert whole.shape == chopped.shape
    np.testing.assert_allclose(whole, chopped, atol=1e-5)


def test_a_fade_belongs_to_the_clip_not_to_the_block():
    """Häivytys lasketaan koko leikkeelle ja viipaloidaan, ei lasketa uudestaan."""
    mixdown = one(start=0.0, length=2.0, fade_in=2.0)
    out = render_all(mixdown, block=0.25)
    left = out[:2000, 0]
    # Yksi nouseva ramppi alusta loppuun, ei kahdeksan pientä.
    assert np.all(np.diff(left) >= -1e-6)
    assert left[1000] == pytest.approx(0.5 * render.pan_of(0.0)[0], abs=0.02)


# --- ffmpegin komentorivi ----------------------------------------------


def test_the_seek_comes_before_the_input():
    """``-ss`` ennen ``-i``:tä, ja tämä on ainoa paikka jossa sen näkee.

    Väärällä puolella se antaa täsmälleen saman äänen — ffmpeg purkaa vain
    tiedoston alusta asti ja heittää pois. Tulos on oikea ja esikatselu
    kestää minuutteja tunnin nauhalla. Kellosta mitattuna eron näkisi vasta
    tiedostolla joka on liian iso testattavaksi, joten se väitetään
    komennosta.
    """
    cmd = render.decode_command("a.wav", 3600.0, 3.0, 48000)
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1].startswith("3600")
    # Kesto menee -i:n jälkeen: ennen sitä se rajaisi hakua, ei ulostuloa.
    assert cmd.index("-t") > cmd.index("-i")


# --- WAV ----------------------------------------------------------------


def test_a_written_wav_reads_back_with_the_right_shape(tmp_path):
    out = tmp_path / "ohjelma.wav"
    report = render.to_wav(one(), str(out), sample_rate=SR, decode=constant(0.5))
    with wave.open(str(out)) as w:
        assert w.getnchannels() == 2
        assert w.getframerate() == SR
        assert w.getsampwidth() == 3
        assert w.getnframes() == 2000
    assert report.duration == pytest.approx(2.0)


def test_sixteen_bit_is_sixteen_bit(tmp_path):
    out = tmp_path / "ohjelma.wav"
    render.to_wav(one(), str(out), sample_rate=SR, bit_depth=16, decode=constant(0.5))
    with wave.open(str(out)) as w:
        assert w.getsampwidth() == 2
        frames = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2)
    assert frames[500, 0] == pytest.approx(0.5 * render.pan_of(0.0)[0] * 32767, abs=2)


def test_twentyfour_bit_comes_back_at_the_level_it_went_in(tmp_path):
    """24-bittinen näyte on int32:n **kolme alinta** tavua, ei kolmea ylintä.

    Ylimmät kolme olisivat sama luku 8 bittiä siirrettynä eli 48 dB liian
    hiljaa, ja mikään ei kaatuisi: WAV on kelvollinen, kesto oikea, kanavat
    oikein, ja `Report.peak` — joka mitataan liukuluvuista ennen pakkausta —
    kertoisi oikean huipun tiedostosta joka on 256× hiljaisempi.

    Juuri tämä vika oli täällä, ja se jäi kiinni vasta kun ohjelma
    renderöitiin oikeasti ja kuunneltiin. Yksikään testi ei lukenut
    24-bittisiä tavuja takaisin — vain 16-bittiset.
    """
    out = tmp_path / "ohjelma.wav"
    render.to_wav(one(), str(out), sample_rate=SR, bit_depth=24, decode=constant(0.5))
    with wave.open(str(out)) as w:
        raw = w.readframes(w.getnframes())
    # Kolme tavua kerrallaan etumerkillisenä little-endianina.
    b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
    values = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    values = np.where(values >= 1 << 23, values - (1 << 24), values)
    expected = 0.5 * render.pan_of(0.0)[0] * (2**23 - 1)
    assert values.reshape(-1, 2)[500, 0] == pytest.approx(expected, rel=1e-4)


def test_an_unsupported_bit_depth_says_so_rather_than_writing_nonsense(tmp_path):
    with pytest.raises(ValueError):
        render.to_wav(one(), str(tmp_path / "x.wav"), sample_rate=SR, bit_depth=12,
                      decode=constant())


def test_a_source_that_will_not_decode_does_not_take_the_programme_with_it(tmp_path):
    """Yksi puuttuva tiedosto vaientaa oman leikkeensä, ei koko jaksoa."""
    del tmp_path

    def decode(path, start, length, sample_rate):
        if path == "b.wav":
            raise OSError("ei aukea")
        n = int(round(length * sample_rate))
        return np.ones((n, 1), dtype=np.float32)

    mixdown = Mix(
        clips=[
            Clip("a.wav", "Olli", 0.0, 1.0, 0.0),
            Clip("b.wav", "Panu", 0.0, 1.0, 0.0),
        ],
        duration=1.0,
    )
    report = render.Report()
    out = render_all(mixdown, decode=decode, report=report)
    assert out[500, 0] == pytest.approx(render.pan_of(0.0)[0])
    assert report.unreadable == ["b.wav"]


def test_a_short_source_is_padded_not_repeated():
    """Alue voi olla lähdettään pidempi. Loppu on hiljaisuutta, ei alkua uudestaan."""

    def decode(path, start, length, sample_rate):
        del length
        return np.ones((sample_rate // 2, 1), dtype=np.float32)

    out = render_all(one(start=0.0, length=1.0), decode=decode)
    assert out[100, 0] > 0.0
    assert out[900, 0] == pytest.approx(0.0)
