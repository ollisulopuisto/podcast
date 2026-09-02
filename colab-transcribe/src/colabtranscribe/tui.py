"""TUI: asetukset lomakkeella, ajo taustatyöläisenä, loki ruudulle.

Sama ajuri kuin komentorivillä — TUI vain kerää kentistä `RunOptions`in ja
antaa sen `plan_commands`ille. Ajo pyörii säikeessä, jotta ruutu ei jääty:
säikeestä ruutuun kirjoittaminen menee `call_from_thread`in kautta, koska
Textualin käyttöliittymä ei ole säieturvallinen.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Select, Switch

from . import driver
from .options import GPUS, PRESETS, RunOptions

CommandLog = Callable[[str], None]
Runner = Callable[[list[list[str]], CommandLog, float | None], int]


class TranscribeApp(App):
    """Asetukset, ajo ja loki yhdessä näkymässä."""

    CSS = """
    #form {
        height: auto;
        padding: 0 1;
    }
    #fields {
        height: auto;
    }
    #fields Input, #fields Select {
        width: 1fr;
    }
    #runrow {
        height: auto;
        margin-top: 1;
    }
    #log {
        height: 1fr;
        border: solid $accent;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Lopeta"),
        Binding("r", "run", "Aja"),
    ]

    def __init__(
        self,
        options: RunOptions | None = None,
        runner: Runner | None = None,
    ) -> None:
        super().__init__()
        self.title = "colab-transcribe"
        self.sub_title = "litterointi ja Auto-Silence Colabissa"
        self._initial = options or RunOptions()
        # Välikäsitetyt testiä varten: oletus on se ajuri joka myös
        # komentorivillä ajaa.
        self._runner: Runner = runner or driver.run

    def compose(self) -> ComposeResult:
        yield Header()
        fields = [
            ("session", "Istunto", self._initial.session),
            ("input", "Syötekansio", self._initial.input_dir),
            ("output", "Tulostekansio", self._initial.output_dir),
            ("thr", "RMS-kynnys (dB)", str(self._initial.thr)),
            ("tail", "Häntä (s)", str(self._initial.tail)),
            ("gap", "Minimitauko (s)", str(self._initial.gap)),
            ("prompt", "Täytesanat", self._initial.prompt),
        ]
        with Vertical(id="form"):
            with Vertical(id="fields"):
                for widget_id, text, value in fields:
                    yield Label(text)
                    yield Input(value=value, id=widget_id)
                yield Label("GPU")
                yield Select([(g, g) for g in GPUS], value=self._initial.gpu, id="gpu", allow_blank=False)
                yield Label("Esiasetus")
                yield Select(
                    [(p, p) for p in PRESETS],
                    value=self._initial.preset,
                    id="preset",
                    allow_blank=False,
                )
                yield Label("RMS-tarkistus")
                yield Switch(value=self._initial.rms, id="rms")
            with Horizontal(id="runrow"):
                yield Button("Aja", id="run", variant="primary")
                yield Label("q = lopeta, r = aja", id="hint")
        yield RichLog(id="log", markup=False, highlight=False)
        yield Footer()

    def collect_options(self) -> RunOptions:
        """Kenttien sisällöt asetuksiksi. Tyhjä kenttä = alkuperäinen oletus."""
        initial = self._initial

        def text(widget_id: str, fallback: str) -> str:
            value = self.query_one(widget_id, Input).value.strip()
            return value or fallback

        def number(widget_id: str, fallback: float) -> float:
            value = text(widget_id, "")
            return float(value) if value else fallback

        return RunOptions(
            session=text("#session", initial.session),
            gpu=str(self.query_one("#gpu", Select).value),
            input_dir=text("#input", initial.input_dir),
            output_dir=text("#output", initial.output_dir),
            preset=str(self.query_one("#preset", Select).value),
            rms=self.query_one("#rms", Switch).value,
            thr=int(number("#thr", initial.thr)),
            tail=number("#tail", initial.tail),
            gap=number("#gap", initial.gap),
            prompt=text("#prompt", initial.prompt),
        )

    def action_run(self) -> None:
        self.query_one("#run", Button).press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            self.start_job()

    def start_job(self) -> None:
        """Asetukset kentistä, suunnitelma komennoiksi, ajo taustalle."""
        try:
            options = self.collect_options()
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        if not options.input_dir:
            self.notify("Syötekansio puuttuu.", severity="error")
            return
        self.run_worker(partial(self._job, options), thread=True, exclusive=True)

    def _job(self, options: RunOptions) -> None:
        files = driver.list_input_files(Path(options.input_dir))
        plan = driver.plan_commands(options, files)

        def log(line: str) -> None:
            self.call_from_thread(self._write_log, line)

        code = self._runner(plan, log, timeout=driver.COMMAND_TIMEOUT)
        summary = "ajo valmis" if code == 0 else f"ajo pysähtyi koodiin {code}"
        self.call_from_thread(self._write_log, summary)

    def _write_log(self, line: str) -> None:
        self.query_one("#log", RichLog).write(line)
