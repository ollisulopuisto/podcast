"""Ohjelmatason päätökset automixerissa: tasapaino ja masterointi.

Molemmat ovat samat kuin autoraffkatissa ja tulevat samasta kirjastosta.
Tämä testaa johdotuksen — että automixer todella kutsuu niitä.
"""

import mlx.core as mx
import numpy as np

from automixer.domain.bus import Bus
from automixer.domain.processor import Processor
from automixer.domain.track import Track

RATE = 48000


class _Backoff(Processor):
    """Ketju joka ilmoittaa luopuneensa tasosta, muuten läpäisee."""

    def __init__(self, db):
        self.backed_off_db = db

    def process(self, signal, sr, progress_callback=None):
        return signal


def _track(name, db):
    track = Track(name, f"/{name}.wav")
    track.signal = mx.array(np.full(RATE, 0.1, dtype=np.float32))
    track.add_processor(_Backoff(db))
    return track


def test_one_speakers_backoff_is_shared_so_the_balance_stays():
    """Vartija laskee sen puhujan tasoa jonka crest on vaarassa. Yksin
    sovellettuna se siirtää tasapainoa — jaksossa 55 noin 3,6 dB — joten
    sama lasku tehdään kaikille, kuten autoraffkatin `shared_backoff`."""
    bus = Bus("speech")
    bus.add_track(_track("a", -3.0))
    bus.add_track(_track("b", 0.0))
    bus.process(RATE)
    levels = [float(np.abs(np.array(t.signal)).max()) for t in bus.tracks]
    assert abs(20 * np.log10(levels[1] / 0.1) - -3.0) < 0.01
    assert abs(20 * np.log10(levels[0] / 0.1)) < 0.01


def test_speakers_are_spread_as_narrowly_as_in_autoraffkat():
    """Sama leveys kuin autoraffkatissa, jaetusta kirjastosta. automixer
    levitti aina ±10 %:iin — kahdella puhujalla kolme kertaa leveämmälle —
    ja kuudesta ylöspäin keskelle, koska paikat olisivat epätarkkuutta."""
    from automixer.cli_mix import speaker_pans
    from speechmix import panning

    assert speaker_pans(2) == [-0.015, 0.015]
    assert speaker_pans(3) == [-0.02, 0.0, 0.02]
    assert speaker_pans(panning.PAN_MAX_SPEAKERS + 1) == [0.0] * (panning.PAN_MAX_SPEAKERS + 1)
    assert speaker_pans(1) == [0.0]
