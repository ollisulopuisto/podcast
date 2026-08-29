"""Aktiivisuus mitataan raidan omasta pohjakohinasta, ei kiinteästä luvusta.

Kiinteä −35 dBFS tarkoittaa eri asiaa jokaisella mikillä, koska se liikkuu
esivahvistuksen mukana. Hiljaiseksi ajettu mikki menettää oikeaa puhetta ja
kohiseva päästää vuodon läpi — kumpikaan ei näy tuloksessa mitenkään, koska
molemmat tuottavat kelvollisen istunnon.

Sääntö tulee kirjastosta (`speechmix.grid`), tasojen mittaaminen jää tänne:
istunto on viisi raitaa kertaa 75 minuuttia, eikä se mahdu muistiin yhtenä
liukulukutaulukkona.
"""

from __future__ import annotations

import numpy as np

from podcastmagic import nhsx
from podcastmagic.silence.detect import noise_floor_of, speech_intervals
from podcastmagic.silence.presets import Settings
from speechmix import grid, masks


def tone(seconds: float, dbfs: float) -> np.ndarray:
    """Tasainen kohina annetulla tasolla."""
    amplitude = 10 ** (dbfs / 20.0)
    return np.full(int(16000 * seconds), amplitude, np.float32)


def test_the_margin_and_the_dominance_come_from_the_library():
    """Sama luku kahdessa paikassa on se ajautuminen jota vastaan tämä tehdään."""
    assert Settings().sensitivity == grid.FLOOR_MARGIN_DB
    assert Settings().dominance == masks.DUCK_DOMINANCE_DB


def test_the_floor_is_read_from_the_track_itself():
    samples = tone(12.0, -70.0)
    samples[16000:32000] = 10 ** (-20.0 / 20.0)  # sekunti puhetta
    floor = noise_floor_of((samples * 32768).astype(np.int16))
    assert -75.0 < floor < -60.0, floor


def test_a_quiet_microphone_keeps_its_speech(monkeypatch, session_file):
    """Hiljaiseksi ajettu mikki: puhe on −45 dBFS, pohja −70.

    Kiinteä −35 dBFS pudotti tästä jokaisen sanan — mikki on vaimea, ei
    hiljainen. Oma pohja + 12 dB päästää ne läpi.
    """
    # Tiedoston pitää olla olemassa; sisältö tulee monkeypatchista.
    (session_file.parent / "olli.wav").write_bytes(b"")
    samples = tone(12.0, -70.0)
    for start, end in ((1.0, 1.45), (1.5, 1.85), (8.0, 8.55)):
        samples[int(start * 16000) : int(end * 16000)] = 10 ** (-45.0 / 20.0)
    monkeypatch.setattr(
        "podcastmagic.silence.detect.audio_io.decode_pcm",
        lambda path: (samples * 32768).astype(np.int16),
    )
    session = nhsx.read(session_file)
    result = speech_intervals(session, session.tracks[0], Settings(rms=True))
    assert result.words_levelled == 3
    assert result.words_quiet == 0
    assert len(result.intervals) == 3


def test_hiss_does_not_pass_as_speech(monkeypatch, session_file):
    """Kohiseva mikki: kaikki on −30 dBFS, myös se mikä ei ole puhetta.

    Kiinteä −35 dBFS päästi tästä kaiken läpi, eli tason tarkistus oli
    päällä eikä tehnyt mitään. Oma pohja + 12 dB pudottaa kohinan.
    """
    (session_file.parent / "olli.wav").write_bytes(b"")
    samples = tone(12.0, -30.0)
    monkeypatch.setattr(
        "podcastmagic.silence.detect.audio_io.decode_pcm",
        lambda path: (samples * 32768).astype(np.int16),
    )
    session = nhsx.read(session_file)
    result = speech_intervals(session, session.tracks[0], Settings(rms=True))
    assert result.words_levelled == 3
    assert result.words_quiet == 3
    assert result.intervals == []
