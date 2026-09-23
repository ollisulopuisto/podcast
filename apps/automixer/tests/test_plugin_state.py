"""Liitännäisen oma tila (dxReviven malli) komentoriviltä ja TUI:sta.

Mallin valinta ei ole dxReviven parametri vaan sen oma tila. automixer
osasi viedä tilan liitännäiselle, mutta sitä ei voinut antaa mistään:
pikis 2026-09-11 -ajo (dxRevive 25/25/50, kuunneltuna paras) vaati skriptin
joka luki Studio 2 -tilan autoraffkatin jakson asetuksista.
"""

from __future__ import annotations

import asyncio
import json

import numpy as np
import soundfile as sf

from automixer import cli_mix

DXREVIVE = "/Library/Audio/Plug-Ins/VST3/Accentize-dxRevive.vst3"


def test_a_state_is_read_from_any_of_the_files_that_hold_one(tmp_path):
    raw = tmp_path / "tila.txt"
    raw.write_text("U3R1ZGlvIDI=\n", encoding="utf-8")
    own = tmp_path / "automixer-plugin.json"
    own.write_text(json.dumps({"plugin": DXREVIVE, "state": "b3du"}), encoding="utf-8")
    episode = tmp_path / "jakso.autoraffkat.json"
    episode.write_text(json.dumps({"audio": {"plugin_state": "ZXBp"}}), encoding="utf-8")
    assert cli_mix.load_plugin_state(raw) == "U3R1ZGlvIDI="
    assert cli_mix.load_plugin_state(own) == "b3du"
    assert cli_mix.load_plugin_state(episode) == "ZXBp"


def test_the_cli_passes_the_state_to_the_speech_plugins(tmp_path, monkeypatch):
    state = tmp_path / "tila.txt"
    state.write_text("U3R1ZGlvIDI=", encoding="utf-8")
    wav = tmp_path / "olli.wav"
    sf.write(wav, np.zeros(48000, dtype=np.float32), 48000)
    seen = []
    monkeypatch.setattr(cli_mix, "Mixer", lambda config: type(
        "M", (), {"run": lambda self: seen.append(config)})())
    monkeypatch.setattr("sys.argv", ["automixer", str(wav), "--speech-plugins", DXREVIVE,
                                     "--plugin-state", str(state)])
    cli_mix.main()
    assert [p["state"] for p in seen[0]["buses"]["speech"]["processors"]] == ["U3R1ZGlvIDI="]


def test_the_tui_opens_the_plugin_window_and_keeps_the_state(tmp_path, monkeypatch):
    from textual.widgets import Button

    from automixer import app as tui
    from speechmix import editor

    monkeypatch.setattr(editor, "open_editor",
                        lambda path, params=None, state=None, **k: editor.EditorResult(state="bmV3"))

    async def scenario():
        mixer = tui.AutomixerApp(work_dir=str(tmp_path))
        async with mixer.run_test() as pilot:
            mixer.selected_speech_plugins = {DXREVIVE}
            mixer.query_one("#plugin_editor_btn", Button).press()
            for _ in range(50):
                await pilot.pause(0.05)
                if mixer.plugin_state:
                    break
            mixer.sync_config_from_ui()
        return mixer

    mixer = asyncio.run(scenario())
    assert mixer.plugin_state == "bmV3"
    assert mixer.config["buses"]["speech"]["processors"][0]["state"] == "bmV3"
    # Tila jää kansioon, jotta seuraava ajo samasta jaksosta saa saman mallin.
    assert cli_mix.load_plugin_state(tmp_path / tui.PLUGIN_STATE_FILE) == "bmV3"
