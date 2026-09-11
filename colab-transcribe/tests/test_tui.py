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

from textual.widgets import Button, Input, Select

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
    assert any(c[:2] == ["drive", "upload"] for c in plan)


def test_run_button_with_direct_transfer(tmp_path: Path):
    (tmp_path / "puhe.wav").write_bytes(b"")
    fake = FakeRunner()

    async def scenario():
        app = TranscribeApp(runner=fake)
        async with app.run_test() as pilot:
            app.query_one("#input").value = str(tmp_path)
            app.query_one("#output").value = str(tmp_path / "out")
            app.query_one("#transfer", Select).value = "direct"
            await pilot.press("r")
            deadline = asyncio.get_event_loop().time() + 5
            while not fake.calls and asyncio.get_event_loop().time() < deadline:
                await pilot.pause()
                await asyncio.sleep(0.02)
            await pilot.pause()

    run_scenario(scenario)

    assert fake.calls, "ajoa ei käynnistynyt"
    plan = fake.calls[0]
    assert any(c[:2] == ["colab", "upload"] and "puhe.wav" in c[4] for c in plan)


def test_browse_button_updates_input_path(tmp_path: Path):
    target_dir = tmp_path / "valittu_kansio"
    target_dir.mkdir()

    async def scenario():
        def fake_picker(initial="", prompt=""):
            return str(target_dir)

        app = TranscribeApp(folder_picker=fake_picker)
        async with app.run_test() as pilot:
            # Painetaan syötekansion selauspainiketta
            app.query_one("#browse_input").press()
            await pilot.pause()
            await asyncio.sleep(0.05)
            assert app.query_one("#input").value == str(target_dir)

    run_scenario(scenario)


def test_browse_button_updates_output_path(tmp_path: Path):
    out_dir = tmp_path / "tulosteet"
    out_dir.mkdir()

    async def scenario():
        def fake_picker(initial="", prompt=""):
            return str(out_dir)

        app = TranscribeApp(folder_picker=fake_picker)
        async with app.run_test() as pilot:
            app.query_one("#browse_output").press()
            await pilot.pause()
            await asyncio.sleep(0.05)
            assert app.query_one("#output").value == str(out_dir)

    run_scenario(scenario)


def test_onboarding_modal_opens_when_not_ready():
    from colabtranscribe.onboarding import OnboardingItem, OnboardingReport

    not_ready_report = OnboardingReport(
        items=[
            OnboardingItem(
                key="colab",
                title="Google Colab CLI",
                ok=False,
                current_value="Ei löydy",
                instructions="Asenna: uv tool install google-colab-cli",
            )
        ]
    )

    async def scenario():
        app = TranscribeApp(onboarding_checker=lambda: not_ready_report)
        async with app.run_test() as pilot:
            await pilot.pause()
            # OnboardingModal on ruudulla
            from colabtranscribe.tui import OnboardingModal
            assert any(isinstance(s, OnboardingModal) for s in app.screen_stack)

    run_scenario(scenario)


def test_tui_reuses_active_session(tmp_path: Path, monkeypatch):
    (tmp_path / "puhe.wav").write_bytes(b"")
    fake = FakeRunner()

    from colabtranscribe import session
    monkeypatch.setattr(session, "is_session_alive", lambda name: True)

    async def scenario():
        app = TranscribeApp(runner=fake)
        async with app.run_test() as pilot:
            app.query_one("#input", Input).value = str(tmp_path)
            app.query_one("#output", Input).value = str(tmp_path / "out")
            app.query_one("#run").press()
            await pilot.pause()
            await asyncio.sleep(0.1)

    run_scenario(scenario)
    assert fake.calls, "ajoa ei käynnistynyt"
    plan = fake.calls[0]
    # Koska istunto oli aktiivinen, colab new -komentoa ei ajeta
    assert not any(c[:2] == ["colab", "new"] for c in plan)


def test_tui_stop_session_button(monkeypatch):
    stopped = []
    from colabtranscribe import session
    monkeypatch.setattr(session, "stop_session", lambda name: stopped.append(name) or 0)

    async def scenario():
        app = TranscribeApp()
        async with app.run_test() as pilot:
            app.query_one("#session", Input).value = "custom-sess"
            app.query_one("#stop_session_btn", Button).press()
            await pilot.pause()
            await asyncio.sleep(0.05)

    run_scenario(scenario)
    assert stopped == ["custom-sess"]


def test_tui_log_has_wrap_enabled():
    async def scenario():
        app = TranscribeApp()
        async with app.run_test() as pilot:
            log_widget = app.query_one("#log")
            assert getattr(log_widget, "wrap", False) is True
            await pilot.pause()

    run_scenario(scenario)


def test_tui_disables_run_button_and_prevents_duplicate_runs(tmp_path: Path):
    import threading

    (tmp_path / "audio.wav").write_bytes(b"")

    run_started = threading.Event()
    finish_run = threading.Event()
    call_count = 0

    def slow_runner(commands, log, timeout=None):
        nonlocal call_count
        call_count += 1
        run_started.set()
        # Wait until allowed to finish
        import time
        while not finish_run.is_set():
            time.sleep(0.01)
        return 0

    async def scenario():
        app = TranscribeApp(runner=slow_runner)
        try:
            async with app.run_test() as pilot:
                app.query_one("#input").value = str(tmp_path)
                app.query_one("#output").value = str(tmp_path / "out")

                run_btn = app.query_one("#run", Button)
                assert not run_btn.disabled

                # Start run
                await pilot.press("r")
                await asyncio.sleep(0.05)
                await pilot.pause()

                # Should be disabled and in progress
                assert run_btn.disabled
                assert app._is_running is True

                # Attempt a second run while first is active
                await pilot.press("r")
                await pilot.pause()

                # Runner should still only have been invoked ONCE
                assert call_count == 1

                # Let the first job finish
                finish_run.set()
                await asyncio.sleep(0.05)
                await pilot.pause()

                # Button should be re-enabled
                assert not run_btn.disabled
                assert app._is_running is False
        finally:
            finish_run.set()

    run_scenario(scenario)

