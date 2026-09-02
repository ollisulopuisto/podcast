"""TUI: asetukset ruudulla, ajo taustalla, loki ruudulle.

Ajuri pistetään testeissä välikäsiin (`runner`), joten testi ei kutsu
`colab`ia eikä tarvitse verkkoa. Se mitä TUI:n testataan tekevän on:
kerää asetukset kentistä, rakenna suunnitelma, syötä loki ruudulle.
Rikkinäinen lokin kirjoitus näkyy poikkeuksena pilotissa, joten sen
sisältöä ei tarvitse lukea takaisin.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from colabtranscribe.tui import TranscribeApp


class FakeRunner:
    def __init__(self):
        self.calls: list[list[list[str]]] = []

    def __call__(self, commands, log, timeout=None):
        self.calls.append(commands)
        log("colab new -s testi --gpu T4")
        log("valmis")


def run_scenario(coroutine_factory):
    asyncio.run(coroutine_factory())


def test_collect_options_reads_the_fields(tmp_path: Path):
    async def scenario():
        app = TranscribeApp()
        async with app.run_test() as pilot:
            app.query_one("#session").value = "testi"
            app.query_one("#input").value = str(tmp_path)
            app.query_one("#thr").value = "-42"
            options = app.collect_options()
            assert options.session == "testi"
            assert options.input_dir == str(tmp_path)
            assert options.thr == -42
            await pilot.pause()

    run_scenario(scenario)


def test_run_button_plans_and_logs(tmp_path: Path):
    (tmp_path / "puhe.wav").write_bytes(b"")
    fake = FakeRunner()
    holder: dict[str, TranscribeApp] = {}

    async def scenario():
        app = TranscribeApp(runner=fake)
        holder["app"] = app
        async with app.run_test() as pilot:
            app.query_one("#input").value = str(tmp_path)
            app.query_one("#output").value = str(tmp_path / "out")
            # Näppäin eikä klikkaus: lomake on pidempi kuin ruutu, ja
            # ruudun ulkopuolisen painikkeen klikkaus on OutOfBounds.
            await pilot.press("r")
            deadline = asyncio.get_event_loop().time() + 5
            while not fake.calls and asyncio.get_event_loop().time() < deadline:
                await pilot.pause()
                await asyncio.sleep(0.02)
            await pilot.pause()

    run_scenario(scenario)

    assert fake.calls, "ajoa ei käynnistynyt"
    plan = fake.calls[0]
    heads = [c[:2] for c in plan]
    assert ["colab", "new"] in heads and ["colab", "stop"] in heads
    uploaded = [c for c in plan if c[:2] == ["colab", "upload"]]
    assert any("puhe.wav" in c[-2] for c in uploaded)
