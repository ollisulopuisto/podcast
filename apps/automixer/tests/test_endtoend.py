"""Koko miksaus läpi, oikeilla tiedostoilla.

Yksikkötestit kertovat että jaetut vaiheet toimivat. Tämä kertoo että
automixer todella kutsuu niitä: että `SpeechChainProcessor` on raidan
ketjussa, että `CeilingProcessor` on masterissa, ja että tulos on sitä mitä
ketju lupaa. Ilman tätä johdotusvirhe — vaihe rakennettu mutta ei lisätty —
menisi läpi vihreänä, ja se on tämän koodikannan tyypillinen vika: kelvollinen
tiedosto, puhdas ajo, ei poikkeusta, väärä tulos.
"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf
from scipy import signal as sp_signal

from automixer.cli_mix import Mixer
from automixer.domain import shared

RATE = 48000


def write_speech(path, seconds: float = 4.0, level: float = 0.2, hz: float = 130.0):
    """Puhemainen purske hiljaisuudella ympärillä, ja pari naksua taukoon."""
    rng = np.random.default_rng(20260827)
    t = np.arange(int(seconds * RATE)) / RATE
    voice = (
        0.6 * np.sin(2 * np.pi * hz * t)
        + 0.3 * np.sin(2 * np.pi * (hz * 2.8) * t)
        + 0.1 * np.sin(2 * np.pi * 2600 * t)
    )
    envelope = np.zeros_like(t)
    for start, length in ((0.3, 1.0), (1.8, 0.8), (3.0, 0.7)):
        envelope[int(start * RATE) : int((start + length) * RATE)] = 1.0
    envelope = sp_signal.savgol_filter(envelope, 2049, 2)
    audio = voice * envelope * level + 0.001 * rng.normal(size=t.size)

    # Naksut taukoon, jotta naksunpoistolla on jotain tekemistä.
    for i in range(3):
        at = int((1.5 + i * 0.03) * RATE)
        click = np.sin(2 * np.pi * 9000 * np.arange(48) / RATE) * 0.15
        audio[at : at + 48] += click * np.hanning(48)

    sf.write(path, audio.astype(np.float32), RATE)
    return audio


def true_peak_db(audio: np.ndarray) -> float:
    dense = sp_signal.resample_poly(np.asarray(audio, dtype=np.float64), 4, 1, axis=0)
    return 20.0 * np.log10(float(np.abs(dense).max()) + 1e-12)


@pytest.fixture
def session(tmp_path):
    """Kaksi puhujaa, ei musiikkia: puhepolku on se joka vaihtui."""
    write_speech(tmp_path / "olli.wav", level=0.2, hz=130.0)
    write_speech(tmp_path / "panu.wav", level=0.05, hz=190.0)
    return {
        "project": "testi",
        "target_lufs": -16.0,
        "output_path": str(tmp_path / "mix.wav"),
        "tracks": [
            {"name": "Olli", "path": str(tmp_path / "olli.wav"), "type": "speech"},
            {"name": "Panu", "path": str(tmp_path / "panu.wav"), "type": "speech"},
        ],
    }


def render(session) -> np.ndarray:
    Mixer(session).run()
    audio, rate = sf.read(session["output_path"])
    assert rate == RATE
    return audio


def test_the_mix_renders_and_is_stereo(session):
    mix = render(session)
    assert mix.ndim == 2 and mix.shape[1] == 2
    assert np.abs(mix).max() > 0.0, "miksaus on hiljainen"


def test_the_master_obeys_the_true_peak_ceiling(session):
    """Vanha katto oli näytehuippu −1,0 dBFS, ja jätti todellisen huipun yli.

    Näytteiden **väliin** jäävä huippu on se joka leikkaa D/A-muuntimessa ja
    lossy-koodauksessa, eikä se näy näytteitä katsomalla.
    """
    mix = render(session)
    assert true_peak_db(mix) <= shared.CEILING_DB + 0.1


def test_the_quiet_speaker_is_brought_up_to_the_loud_one(session):
    """Ketju normalisoi jokaisen raidan ennen kompressointia.

    Aineistossa toinen puhuja on 12 dB hiljaisempi. Jos normalisointi
    putoaisi pois johdotuksesta, miksaus valmistuisi silti — toinen puhuja
    olisi vain kuulumattomissa.
    """
    mix = render(session)
    mono = mix.mean(axis=1)

    # Kummankin puhujan oma jakso, aineiston verhokäyrästä.
    first = mono[int(0.4 * RATE) : int(1.2 * RATE)]
    second = mono[int(1.9 * RATE) : int(2.5 * RATE)]

    def rms_db(x):
        return 20.0 * np.log10(float(np.sqrt(np.mean(x**2))) + 1e-12)

    assert abs(rms_db(first) - rms_db(second)) < 6.0


def test_the_chain_does_not_change_the_length(session):
    """Pituus on viennin ehto. Jokainen jaettu vaihe säilyttää sen, ja
    `chain.process` nostaa virheen jos jokin ei säilytä."""
    expected = sf.info(session["tracks"][0]["path"]).frames
    mix = render(session)
    assert mix.shape[0] == expected


def test_the_declicker_runs_on_the_way_through(session, monkeypatch):
    """Naksunpoisto on ketjussa, ei vain saatavilla.

    Vanha `DeSmackProcessor` oli johdotettu ja muutti nolla näytettä; sitä ei
    olisi huomannut mistään. Tämä katsoo että kirjaston oma tulee kutsutuksi.
    """
    calls = []
    real = shared.declick

    def counting(audio, rate, sensitivity=0.5):
        calls.append(sensitivity)
        return real(audio, rate, sensitivity)

    monkeypatch.setattr("speechmix.chain.declick", counting)
    render(session)
    assert len(calls) == 2, "naksunpoiston pitäisi ajaa kummallekin raidalle"


def alternating(path, turns, seconds: float = 12.0, hz: float = 130.0,
                level: float = 0.2, hum: float = 0.0):
    """Yksi mikki: oma puhe annetuilla vuoroilla, ja jatkuva oma pohja.

    ``hum`` on tämän mikin oma matalatasoinen jatkuva sisältö samalla
    taajuudella kuin sen puhe. Se on mittauksen kahva: vaimennus koskee
    **tätä mikkiä**, joten sen sulkeutuminen näkyy juuri tässä taajuudessa
    silloin kun mikin omistaja on hiljaa.
    """
    rng = np.random.default_rng(int(hz))
    t = np.arange(int(seconds * RATE)) / RATE
    voice = 0.6 * np.sin(2 * np.pi * hz * t) + 0.3 * np.sin(2 * np.pi * hz * 2.8 * t)
    envelope = np.zeros_like(t)
    for start, length in turns:
        envelope[int(start * RATE) : int((start + length) * RATE)] = 1.0
    envelope = sp_signal.savgol_filter(envelope, 2049, 2)
    audio = voice * envelope * level + hum * np.sin(2 * np.pi * hz * t)
    audio = audio + 0.0002 * rng.normal(size=t.size)
    sf.write(path, audio.astype(np.float32), RATE)
    return audio


@pytest.fixture
def turn_taking(tmp_path):
    """Vuorottelevat puhujat, kummallakin oma taajuus ja oma jatkuva pohja."""
    alternating(tmp_path / "a.wav", [(0.5, 2.0), (5.5, 2.0), (10.0, 1.5)],
                hz=130.0, hum=0.002)
    alternating(tmp_path / "b.wav", [(3.0, 2.0), (8.0, 1.5)],
                hz=470.0, hum=0.002)
    return {
        "project": "vuorottelu",
        "target_lufs": -16.0,
        "output_path": str(tmp_path / "mix.wav"),
        "tracks": [
            {"name": "A", "path": str(tmp_path / "a.wav"), "type": "speech"},
            {"name": "B", "path": str(tmp_path / "b.wav"), "type": "speech"},
        ],
        "buses": {"speech": {}, "music": {}},
    }


def _band_db(audio, low, high, at, span=1.2):
    """Kaistan energia yhdellä aikavälillä, desibeleinä."""
    mono = np.asarray(audio).mean(axis=1)
    piece = mono[int(at * RATE) : int((at + span) * RATE)]
    sos = sp_signal.butter(6, [low, high], "bandpass", fs=RATE, output="sos")
    band = sp_signal.sosfilt(sos, piece)
    return 20.0 * np.log10(float(np.sqrt(np.mean(band**2))) + 1e-12)


def test_a_microphone_closes_while_its_owner_is_silent(turn_taking):
    """Ruudukko on johdotettu, ja vaimennus osuu toisen puheen alle.

    Tämä on se ominaisuus jota automixerilla ei ollut: `DuckingProcessor`
    sivuketjuttaa musiikkipedin, mutta **mikrofonin** sulkeminen sen
    omistajan ollessa hiljaa on eri asia, ja se tuli kirjastosta vasta kun
    puheruudukko saatiin rakennettua wav-raidoista.

    Mitataan A:n taajuudesta B:n vuoron aikana: siellä kuuluva 130 Hz on
    pelkkää vuotoa A:n mikistä, ja juuri sen vaimennus sulkee.
    """
    turn_taking["buses"]["speech"] = {"mic_duck_enabled": False}
    without = render(turn_taking)
    turn_taking["output_path"] = turn_taking["output_path"].replace(".wav", "-2.wav")
    turn_taking["buses"]["speech"] = {"mic_duck_enabled": True}
    with_duck = render(turn_taking)

    # B:n vuoro on 3,0–5,0 s. 130 Hz siellä on **A:n mikistä**, ja juuri se
    # mikki on kiinni. (Vaimennus ei ylety siihen mitä A:sta on vuotanut B:n
    # raidalle — se on ristivuodon vähennyksen työtä, ei portin.)
    quiet_off = _band_db(without, 100, 170, at=3.4)
    quiet_on = _band_db(with_duck, 100, 170, at=3.4)
    assert quiet_off - quiet_on > 3.0, (quiet_off, quiet_on)

    # A:n omalla vuorolla 0,5–2,5 s mikään ei saa sulkeutua.
    own_off = _band_db(without, 100, 170, at=1.0)
    own_on = _band_db(with_duck, 100, 170, at=1.0)
    assert abs(own_off - own_on) < 1.5, (own_off, own_on)


def test_the_speech_grid_reaches_the_chain_as_the_rider_mask(turn_taking, monkeypatch):
    """Kuljettajan maski tulee ruudukosta, eikä se saa olla ``None``.

    Ilman maskia `chain.process` ohittaa tasonkuljettajan äänettömästi —
    kelvollinen tiedosto, puhdas ajo, ei poikkeusta, vaihe tekemättä. Juuri
    se on tämän koodikannan tyypillinen vika, joten johdotus tarkistetaan
    eikä uskota.
    """
    from automixer.domain import processor as processor_mod

    seen = []
    original = processor_mod.SpeechChainProcessor.__init__

    def spy(self, target_lufs, settings=None, speaking=None):
        seen.append(speaking)
        original(self, target_lufs, settings=settings, speaking=speaking)

    monkeypatch.setattr(processor_mod.SpeechChainProcessor, "__init__", spy)
    render(turn_taking)

    assert len(seen) == 2, seen
    assert all(mask is not None for mask in seen), "kummallakin mikillä on maski"
    assert any(mask.any() for mask in seen), "maskissa pitää olla puhetta"
