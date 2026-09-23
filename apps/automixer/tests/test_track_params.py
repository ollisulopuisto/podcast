"""Liitännäisen asetukset raitakohtaisesti: yksi puhuja tarvitsee enemmän.

Pikis 2026-09-11: Panun huone on kaikuisa, ja sama dxRevive-määrä kaikille
jättää hänet muita kaukaisemmaksi. Väylän asetus on oletus, raidan oma
voittaa sen — sekä komentorivillä että TUI:ssa.
"""

from __future__ import annotations

import asyncio

from automixer import cli_mix

DXREVIVE = "/Library/Audio/Plug-Ins/VST3/Accentize-dxRevive.vst3"


def test_track_params_are_parsed_per_track_and_plugin():
    got = cli_mix.parse_track_params("panu/dxrevive:mix=50; Kari/dxrevive:mix=25,gain=-3")
    assert got == {"panu": {"dxrevive": {"mix": 50.0}},
                   "kari": {"dxrevive": {"mix": 25.0, "gain": -3.0}}}
    assert cli_mix.parse_track_params("") == {}


def test_a_tracks_own_params_win_over_the_bus():
    bus = {"type": "plugin", "path": DXREVIVE, "params": {"mix": 25.0, "gain": 0.0}}
    own = cli_mix.parse_track_params("panu/dxrevive:mix=50")
    # Raidan nimi voi olla tiedostonimi, jossa puhujan nimi on osana.
    panu = cli_mix.track_plugin_params(bus, "2026-09-11--guest232006--panu.wav", own)
    assert panu == {"mix": 50.0, "gain": 0.0}
    assert cli_mix.track_plugin_params(bus, "olli", own) == {"mix": 25.0, "gain": 0.0}


def test_the_mixer_gives_each_speaker_their_own_params(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf

    from automixer.domain.processor import GainProcessor

    rng = np.random.default_rng(1)
    t = np.arange(48000 * 6) / 48000
    for i, name in enumerate(("olli", "panu")):
        # Vuorotellen puhuvat purskeet ja kohinapohja: puheruudukko tarvitsee
        # hiljaisuutta josta pohja mitataan.
        gate = ((t // 1.0) % 2 == i).astype(float)
        voice = 0.2 * np.sin(2 * np.pi * (130 + 60 * i) * t) * gate
        sf.write(tmp_path / f"{name}.wav",
                 (voice + 1e-3 * rng.normal(size=t.size)).astype(np.float32), 48000)
    seen = []

    def spy(self, p_cfg):
        seen.append(p_cfg.get("params"))
        return GainProcessor(0.0)

    monkeypatch.setattr(cli_mix.Mixer, "_create_processor", spy)
    config = {
        "target_lufs": -16.0, "output_path": str(tmp_path / "mix.wav"),
        "tracks": [{"name": n, "path": str(tmp_path / f"{n}.wav"), "type": "speech"}
                   for n in ("olli", "panu")],
        "track_params": cli_mix.parse_track_params("panu/dxrevive:mix=50"),
        "buses": {"speech": {"processors": [
            {"type": "plugin", "path": DXREVIVE, "params": {"mix": 25.0}}]}},
    }
    cli_mix.Mixer(config).run()
    assert seen == [{"mix": 25.0}, {"mix": 50.0}]


def test_the_tui_sends_track_params_to_the_mixer(tmp_path):
    from textual.widgets import Input

    from automixer.app import AutomixerApp

    async def scenario():
        app = AutomixerApp(work_dir=str(tmp_path))
        async with app.run_test() as pilot:
            app.query_one("#track_params_input", Input).value = "panu/dxrevive:mix=50"
            await pilot.pause()
            app.sync_config_from_ui()
        return app.config

    config = asyncio.run(scenario())
    assert config["track_params"] == {"panu": {"dxrevive": {"mix": 50.0}}}


def test_the_plugin_runs_in_parallel_pieces_like_autoraffkat(monkeypatch):
    """dxRevive käyttää yhtä ydintä, ja ainoa tie muihin on useampi
    instanssi rinnakkain (`chain.load_pool`). autoraffkat teki niin —
    mitattuna 168 -> 68 s 20 minuutin tiedostolla — automixer ajoi yhden."""
    from automixer.domain.processor import ExternalPluginProcessor
    from speechmix import chain

    seen = {}

    def pool(path, params=None, count=1, state=None):
        seen.update(path=path, count=count, state=state)
        return "pool"

    monkeypatch.setattr(chain, "load_pool", pool)
    processor = ExternalPluginProcessor(DXREVIVE, {"mix": 50.0}, state="abc")
    assert processor.plugin == "pool"
    assert seen == {"path": DXREVIVE, "count": chain.worker_count(0), "state": "abc"}
