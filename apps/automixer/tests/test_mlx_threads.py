"""mlx-taulukot kuuluvat sille säikeelle joka ne loi.

Tämä on hiljainen vika siihen asti kunnes se ei ole. mlx:n oletusvirta on
säiekohtainen: säikeessä luotu `mx.array` kantaa sen säikeen virran, ja kun
tulosta kosketaan pääsäikeestä, mlx nostaa
``RuntimeError: There is no Stream(gpu, 3) in current thread``. Virhe ei tule
siitä säikeestä joka rikkoi asian, vaan seuraavasta käytöstä — eli
tyypillisesti aivan muualta kuin `ThreadPoolExecutor`ista jonka takia se
tapahtui.

mlx 0.30.6 salli tämän, 0.32.2 ei. Ero ei ollut se, että työtila päivitti
kirjaston liian pitkälle: säikeistys oli väärin kummallakin versiolla, ja
0.30.6 vain ei sanonut siitä. Siksi tämä korjataan eteenpäin eikä
naulaamalla mlx taaksepäin — sama koodi rikkoutuisi silti käyttäjän koneella
sillä hetkellä kun mlx päivittyy.

Rinnakkaisuutta ei menetetä: mlx:n työ menee jo laitteelle jonoon, ja kolme
Python-säiettä jotka syöttävät samaa laitetta odottavat samaa jonoa. Mittaus
tälle aineistolle: kolmen kaistan `MultibandCompressorProcessor.process`
44,1 kHz:n sekunnilla 0,31 s säikeillä ja 0,29 s ilman.
"""

from __future__ import annotations

import mlx.core as mx
import numpy as np

from automixer.domain.bus import Bus
from automixer.domain.processor import GainProcessor, MultibandCompressorProcessor
from automixer.domain.track import Track


def _tone(sr: int = 44100, seconds: float = 1.0, hz: float = 100.0) -> np.ndarray:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return (0.8 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def test_multiband_result_is_usable_on_the_calling_thread():
    """Kaistat saa laskea rinnakkain, mutta tulos palaa kutsujalle."""
    sr = 44100
    processed = MultibandCompressorProcessor(
        peak_enabled=True, lev_enabled=True
    ).process(mx.array(_tone(sr)), sr)

    # `.item()` on se kohta jossa säieväärinkäytös paljastuu: siihen asti
    # taulukko on laiska eikä kukaan ole pyytänyt siltä lukua.
    assert mx.max(mx.abs(processed)).item() < 0.8


def test_bus_mixdown_is_usable_on_the_calling_thread(tmp_path):
    """Väylä prosessoi raidat ja summaa ne — kaikki samalla säikeellä."""
    sr = 44100
    bus = Bus("speech")
    for name, pan in (("vasen", -0.5), ("oikea", 0.5)):
        track = Track(name, str(tmp_path / f"{name}.wav"), pan=pan)
        track.signal = mx.array(_tone(sr))
        track.sr = sr
        track.add_processor(GainProcessor(gain_db=-3.0))
        bus.add_track(track)

    mixed = bus.process(sr)

    assert mixed.shape[1] == 2
    assert float(mx.max(mx.abs(mixed)).item()) > 0.0
