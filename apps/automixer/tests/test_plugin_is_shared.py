"""Liitännäinen on jaettu ketju, ei toinen toteutus siitä.

`ExternalPluginProcessor` latasi liitännäisen itse: `pedalboard.load_plugin`,
säätimet `setattr`illa, `print` virheeksi. Se ei kaatanut mitään koskaan —
se oli vain kolme hiljaista eroa kirjastoon, ja jokainen niistä on tässä
väitteenä:

* tila ei kulkenut perille lainkaan, joten ajettiin liitännäisen oletusmallia
* `reset` puuttui, joten liitännäisen tila jatkui raidalta toiselle
* pituutta ei tarkistettu, joten viiveellinen liitännäinen siirsi synkan

Viimeinen testi on rakenteellinen, kuten `test_shared_chain.py`:ssä: se
väittää että tämä kutsuu kirjaston **oliota** eikä omaa kopiotaan siitä.
Uudelleen kopioitu funktio joka sattuu olemaan identtinen kaatuu silti, ja
se on tarkoitus — kopio ei kaadu koskaan, se alkaa vain hiljaa erota.
"""

from __future__ import annotations

import mlx.core as mx
import numpy as np
import pytest

from automixer.domain import processor
from automixer.domain.processor import ExternalPluginProcessor
from speechmix import chain

RATE = 48000


class _Fake:
    """Liitännäinen joka muistaa miten sitä kutsuttiin."""

    parameters: dict = {}

    def __init__(self, latency: int = 0):
        self.latency = latency
        self.calls: list[bool] = []

    def process(self, audio, rate, reset=False):
        self.calls.append(reset)
        return audio[:, : audio.shape[1] - self.latency]


def test_the_plugins_own_state_reaches_the_plugin(monkeypatch):
    """Malli ei ole parametri, ja ilman tilaa sitä ei voi valita.

    dxRevive julkaisee neljä parametria — ohitus, tulo- ja lähtövahvistus,
    ja Mix — eikä mallin valinta ole yksikään niistä. Vanha toteutus ei
    ottanut tilaa vastaan lainkaan, joten täällä ajettiin aina sitä mallia
    jonka liitännäinen sattuu ottamaan oletuksena.
    """
    seen: dict = {}

    def watch(path, params=None, state=None):
        seen.update(path=path, params=params, state=state)
        return _Fake()

    monkeypatch.setattr(chain, "load_plugin", watch)
    ExternalPluginProcessor("/x.vst3", {"mix": 50.0}, "U3R1ZGlvIDI=")
    assert seen == {
        "path": "/x.vst3",
        "params": {"mix": 50.0},
        "state": "U3R1ZGlvIDI=",
    }


def test_a_plugin_that_changes_length_is_refused(monkeypatch):
    """Viiveellinen liitännäinen siirtää kaiken jälkeensä tulevan.

    Mitattuna dxRevivella 4641 näytettä. Vanha toteutus palautti tuloksen
    sellaisenaan: kelvollista ääntä, ei poikkeusta, väärä synkka.
    """
    monkeypatch.setattr(chain, "load_plugin", lambda *a, **k: _Fake(latency=4641))
    unit = ExternalPluginProcessor("/x.vst3")
    with pytest.raises(chain.ChainError, match="length"):
        unit.process(mx.zeros((RATE,)), RATE)


def test_the_plugin_is_reset_between_tracks(monkeypatch):
    """Ilman nollausta raita kuulostaa siltä mikä sitä edelsi."""
    fake = _Fake()
    monkeypatch.setattr(chain, "load_plugin", lambda *a, **k: fake)
    unit = ExternalPluginProcessor("/x.vst3")
    unit.process(mx.zeros((RATE,)), RATE)
    unit.process(mx.zeros((RATE,)), RATE)
    assert fake.calls == [True, True]


def test_a_bad_path_is_told_before_the_mix_starts(monkeypatch):
    """Väärä polku on kerrottava ennen kuin minuuttien ajo alkaa.

    Vanha toteutus latasi vasta ensimmäisellä käsittelyllä ja nieli virheen
    `print`iin, jolloin ajo jatkui käsittelemättömällä signaalilla ja
    lopputulos oli hiljaa väärä.
    """
    with pytest.raises(chain.ChainError, match="not found"):
        ExternalPluginProcessor("/ei/ole/mitaan.vst3")


def test_mono_and_stereo_keep_their_shape(monkeypatch):
    """Kirjasto puhuu (kanavat, näytteet); automixer molempia muotoja."""
    monkeypatch.setattr(chain, "load_plugin", lambda *a, **k: _Fake())
    unit = ExternalPluginProcessor("/x.vst3")

    mono = unit.process(mx.zeros((RATE,)), RATE)
    assert np.array(mono).shape == (RATE,)

    stereo = unit.process(mx.zeros((RATE, 2)), RATE)
    assert np.array(stereo).shape == (RATE, 2)


def test_it_calls_the_library_and_not_a_copy_of_it(monkeypatch):
    """Rakenteellinen: kirjaston **olio**, ei oma toisinto siitä.

    Väite ei ole tekstistä vaan kutsusta: kirjaston funktio korvataan, ja
    jos se ei mene perille, tässä on jälleen oma toteutus. Uudelleen
    kopioitu funktio joka sattuu olemaan identtinen läpäisisi tekstihaun.
    """
    assert processor.chain is chain

    called: list[str] = []
    monkeypatch.setattr(
        chain, "load_plugin", lambda *a, **k: (called.append("load"), _Fake())[1]
    )
    monkeypatch.setattr(
        chain,
        "apply_plugin",
        lambda plugin, audio, rate: (called.append("apply"), audio)[1],
    )
    ExternalPluginProcessor("/x.vst3").process(mx.zeros((RATE,)), RATE)
    assert called == ["load", "apply"]


def test_the_module_no_longer_loads_plugins_itself():
    """`pedalboard` ei ole enää tämän moduulin riippuvuus lainkaan.

    Tuotu nimi, ei lähdeteksti: omat kommentit kertovat mitä täällä *oli*,
    eikä testi saa kaatua siihen että historia on kirjoitettu auki.
    """
    assert not hasattr(processor, "pedalboard")
