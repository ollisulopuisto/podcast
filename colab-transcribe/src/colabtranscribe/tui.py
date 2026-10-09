"""TUI: asetukset lomakkeella, ajo taustatyöläisenä, loki ruudulle.

Sama ajuri kuin komentorivillä — TUI vain kerää kentistä `RunOptions`in ja
antaa sen `plan_commands`ille. Ajo pyörii säikeessä, jotta ruutu ei jääty:
säikeestä ruutuun kirjoittaminen menee `call_from_thread`in kautta, koska
Textualin käyttöliittymä ei ole säieturvallinen.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DirectoryTree,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Select,
    Switch,
)

from . import driver, picker, session
from .onboarding import OnboardingReport, check_environment
from .options import GPUS, PRESETS, RunOptions

CommandLog = Callable[[str], None]
Runner = Callable[[list[list[str]], CommandLog, float | None], int]


class DirectoryPickerModal(ModalScreen[str | None]):
    """Interaktiivinen kansionvalintaikkuna TUI:n sisällä."""

    CSS = """
    DirectoryPickerModal {
        align: center middle;
    }
    #picker-dialog {
        width: 80%;
        height: 80%;
        border: solid $accent;
        background: $surface;
        padding: 1;
    }
    #picker-tree {
        height: 1fr;
        border: solid $primary;
    }
    #picker-buttons {
        height: auto;
        margin-top: 1;
        align: right middle;
    }
    #picker-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, start_dir: str = "", prompt: str = "") -> None:
        super().__init__()
        self._start_dir = (
            start_dir if start_dir and Path(start_dir).is_dir() else str(Path.home())
        )
        self._prompt = prompt or "Valitse kansio"
        self._selected: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog"):
            yield Label(self._prompt)
            yield Label(f"Valittu: {self._start_dir}", id="picker-selected-label")
            yield DirectoryTree(self._start_dir, id="picker-tree")
            with Horizontal(id="picker-buttons"):
                yield Button("Valitse", id="picker-select", variant="primary")
                yield Button("Peruuta", id="picker-cancel")

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self._selected = str(event.path)
        self.query_one("#picker-selected-label", Label).update(
            f"Valittu: {self._selected}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-select":
            self.dismiss(self._selected or self._start_dir)
        elif event.button.id == "picker-cancel":
            self.dismiss(None)


class FilePickerModal(ModalScreen[str | None]):
    """Interaktiivinen tiedostonvalintaikkuna TUI:n sisällä."""

    CSS = """
    FilePickerModal {
        align: center middle;
    }
    #file-picker-dialog {
        width: 80%;
        height: 80%;
        border: solid $accent;
        background: $surface;
        padding: 1;
    }
    #file-picker-tree {
        height: 1fr;
        border: solid $primary;
    }
    #file-picker-buttons {
        height: auto;
        margin-top: 1;
        align: right middle;
    }
    #file-picker-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, start_dir: str = "", prompt: str = "") -> None:
        super().__init__()
        self._start_dir = (
            start_dir if start_dir and Path(start_dir).is_dir() else str(Path.home())
        )
        self._prompt = prompt or "Valitse tiedosto"
        self._selected: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="file-picker-dialog"):
            yield Label(self._prompt)
            yield Label(f"Valittu: {self._start_dir}", id="file-picker-selected-label")
            yield DirectoryTree(self._start_dir, id="file-picker-tree")
            with Horizontal(id="file-picker-buttons"):
                yield Button("Valitse", id="file-picker-select", variant="primary")
                yield Button("Peruuta", id="file-picker-cancel")

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        self._selected = str(event.path)
        self.query_one("#file-picker-selected-label", Label).update(
            f"Valittu: {self._selected}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "file-picker-select":
            self.dismiss(self._selected)
        elif event.button.id == "file-picker-cancel":
            self.dismiss(None)


class OnboardingModal(ModalScreen[None]):

    """Alkuasetusten opastus ja tarkistusikkuna."""

    CSS = """
    OnboardingModal {
        align: center middle;
    }
    #onboarding-dialog {
        width: 85%;
        height: 85%;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    #onboarding-scroll {
        height: 1fr;
    }
    .item-ok {
        color: $success;
        text-style: bold;
    }
    .item-missing {
        color: $error;
        text-style: bold;
    }
    .instruction-box {
        margin: 0 0 1 2;
        padding: 0 1;
        background: $panel;
    }
    #onboarding-buttons {
        height: auto;
        margin-top: 1;
        align: right middle;
    }
    #onboarding-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, checker: Callable[[], OnboardingReport] | None = None) -> None:
        super().__init__()
        self._checker = checker or check_environment

    def compose(self) -> ComposeResult:
        with Vertical(id="onboarding-dialog"):
            yield Label(
                "colab-transcribe: Alkuasetukset ja vaatimukset", id="onboarding-title"
            )
            with VerticalScroll(id="onboarding-scroll"):
                yield from self._build_items()
            with Horizontal(id="onboarding-buttons"):
                yield Button(
                    "Tarkista uudelleen", id="recheck_onboarding", variant="primary"
                )
                yield Button("Sulje", id="close_onboarding")

    def _build_items(self) -> ComposeResult:
        report = self._checker()
        for item in report.items:
            icon = "✓" if item.ok else "✗"
            cls = "item-ok" if item.ok else "item-missing"
            req = " (pakollinen)" if item.required else ""
            yield Label(f"[{icon}] {item.title}{req}: {item.current_value}", classes=cls)
            if not item.ok and item.instructions:
                yield Label(item.instructions, classes="instruction-box")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close_onboarding":
            self.dismiss()
        elif event.button.id == "recheck_onboarding":
            scroll = self.query_one("#onboarding-scroll", VerticalScroll)
            scroll.remove_children()
            scroll.mount_all(list(self._build_items()))


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
    .path-row {
        height: auto;
        width: 1fr;
    }
    .path-row Input {
        width: 1fr;
    }
    .path-row Button {
        width: auto;
        margin-left: 1;
    }
    #fields Select {
        width: 1fr;
    }
    #runrow {
        height: auto;
        margin-top: 1;
    }
    #runrow Button {
        margin-right: 1;
    }
    #progress-pane {
        height: auto;
        margin-top: 1;
        margin-bottom: 1;
    }
    #progress-status {
        color: $text-muted;
        text-style: bold;
    }
    #progress-bar {
        width: 1fr;
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
        folder_picker: Callable[[str, str], str | None] | None = None,
        file_picker: (
            Callable[[str, str, list[str] | tuple[str, ...] | None], str | None] | None
        ) = None,
        onboarding_checker: Callable[[], OnboardingReport] | None = None,
        auto_onboard: bool | None = None,
    ) -> None:
        super().__init__()
        self.title = "colab-transcribe"
        self.sub_title = "litterointi ja Auto-Silence Colabissa"
        self._initial = options or RunOptions.from_env()
        # Välikäsitetyt testiä varten: oletus on se ajuri joka myös
        # komentorivillä ajaa.
        self._runner: Runner = runner or driver.run
        self._folder_picker = folder_picker
        self._file_picker = file_picker
        if onboarding_checker is not None:
            self._onboarding_checker = onboarding_checker
        elif runner is not None:
            self._onboarding_checker = lambda: OnboardingReport(items=[])
        else:
            self._onboarding_checker = check_environment

        if auto_onboard is not None:
            self._auto_onboard = auto_onboard
        else:
            self._auto_onboard = runner is None or onboarding_checker is not None
        self._is_running = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="form"):
            with Vertical(id="fields"):
                yield Label("Istunto")
                with Horizontal(classes="path-row"):
                    yield Input(value=self._initial.session, id="session")
                    yield Button(
                        "Pysäytä istunto", id="stop_session_btn", variant="error"
                    )

                yield Label("Syötekansio tai äänitiedosto")
                with Horizontal(classes="path-row"):
                    yield Input(value=self._initial.input_dir, id="input")
                    yield Button("Valitse…", id="browse_input")


                yield Label("Tulostekansio")
                with Horizontal(classes="path-row"):
                    yield Input(value=self._initial.output_dir, id="output")
                    yield Button("Valitse…", id="browse_output")

                yield Label("RMS-kynnys (dB)")
                yield Input(value=str(self._initial.thr), id="thr")
                yield Label("Häntä (s)")
                yield Input(value=str(self._initial.tail), id="tail")
                yield Label("Minimitauko (s)")
                yield Input(value=str(self._initial.gap), id="gap")
                yield Label("Täytesanat")
                yield Input(value=self._initial.prompt, id="prompt")

                yield Label("GPU")
                yield Select(
                    [(g, g) for g in GPUS],
                    value=self._initial.gpu,
                    id="gpu",
                    allow_blank=False,
                )
                yield Label("Esiasetus")
                yield Select(
                    [(p, p) for p in PRESETS],
                    value=self._initial.preset,
                    id="preset",
                    allow_blank=False,
                )
                yield Label("Siirtotapa")
                yield Select(
                    [
                        ("Google Drive (erittäin nopea)", "drive"),
                        ("Suora Colab-lataus (hidas, ilman Drivea)", "direct"),
                    ],
                    value=self._initial.transfer,
                    id="transfer",
                    allow_blank=False,
                )
                yield Label("Auto-Silence (pois: vain litterointi)")
                yield Switch(value=self._initial.silence, id="silence")
                yield Label("RMS-tarkistus")
                yield Switch(value=self._initial.rms, id="rms")
            with Horizontal(id="runrow"):
                yield Button("Aja", id="run", variant="primary")
                yield Button("Alkuasetukset", id="onboarding_btn")
                yield Label("q = lopeta, r = aja", id="hint")
            with Vertical(id="progress-pane"):
                yield Label("Odottaa ajoa...", id="progress-status")
                yield ProgressBar(id="progress-bar", total=100.0, show_eta=False)
        yield RichLog(id="log", markup=False, highlight=False, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        if self._auto_onboard:
            report = self._onboarding_checker()
            if not report.is_ready:
                self.push_screen(OnboardingModal(checker=self._onboarding_checker))

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
            transfer=str(self.query_one("#transfer", Select).value),
            rms=self.query_one("#rms", Switch).value,
            silence=self.query_one("#silence", Switch).value,
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
        elif event.button.id == "browse_input":
            self.browse_folder("#input", "Valitse syöte (.nhsx, kansio tai äänitiedosto)")
        elif event.button.id == "browse_output":
            self.browse_folder("#output", "Valitse tulostekansio")
        elif event.button.id == "stop_session_btn":
            sess_name = (
                self.query_one("#session", Input).value.strip() or self._initial.session
            )

            def _stop_worker() -> None:
                self.call_from_thread(
                    self._write_log, f"Pysäytetään istunto '{sess_name}'..."
                )
                res = session.stop_session(sess_name)
                msg = (
                    f"Istunto '{sess_name}' pysäytetty."
                    if res == 0
                    else f"Pysäytys palautti koodin {res}."
                )
                self.call_from_thread(self._write_log, msg)

            self.run_worker(_stop_worker, thread=True, exclusive=False)
        elif event.button.id == "onboarding_btn":
            self.push_screen(OnboardingModal(checker=self._onboarding_checker))

    def browse_folder(self, target_input_id: str, prompt: str) -> None:
        initial = self.query_one(target_input_id, Input).value.strip()

        if self._folder_picker is not None or picker.has_native_picker():
            picker_fn = self._folder_picker or picker.pick_folder
            file_picker_fn = self._file_picker or picker.pick_file

            def _worker() -> None:
                chosen = picker_fn(initial, prompt)
                if chosen:
                    chosen_path = Path(chosen)
                    if (
                        target_input_id == "#input"
                        and chosen_path.is_dir()
                        and not driver.has_nhsx_files(chosen_path)
                    ):
                        audio_chosen = file_picker_fn(
                            chosen,
                            "Ei .nhsx-istuntoa löytynyt. Valitse äänitiedosto",
                            picker.AUDIO_EXTENSIONS,
                        )
                        if audio_chosen:
                            chosen = audio_chosen
                    self.call_from_thread(self._set_input_value, target_input_id, chosen)

            self.run_worker(_worker, thread=True, exclusive=False)
        else:

            def on_dismiss(chosen: str | None) -> None:
                if chosen:
                    chosen_path = Path(chosen)
                    if (
                        target_input_id == "#input"
                        and chosen_path.is_dir()
                        and not driver.has_nhsx_files(chosen_path)
                    ):

                        def on_file_dismiss(audio_chosen: str | None) -> None:
                            self._set_input_value(
                                target_input_id, audio_chosen or chosen
                            )

                        self.push_screen(
                            FilePickerModal(
                                start_dir=chosen,
                                prompt="Ei .nhsx-istuntoa löytynyt. Valitse äänitiedosto",
                            ),
                            on_file_dismiss,
                        )
                    else:
                        self._set_input_value(target_input_id, chosen)

            self.push_screen(
                DirectoryPickerModal(start_dir=initial, prompt=prompt), on_dismiss
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "input" and event.value.strip():
            out_input = self.query_one("#output", Input)
            cur_out = out_input.value.strip()
            if not cur_out or cur_out == "output" or cur_out.endswith("/output"):
                val_path = Path(event.value.strip())
                base_dir = val_path.parent if val_path.is_file() else val_path
                out_input.value = str(base_dir / "output")

    def _set_input_value(self, target_input_id: str, value: str) -> None:
        self.query_one(target_input_id, Input).value = value
        if target_input_id == "#input" and value:
            out_input = self.query_one("#output", Input)
            cur_out = out_input.value.strip()
            if not cur_out or cur_out == "output" or cur_out.endswith("/output"):
                val_path = Path(value)
                base_dir = val_path.parent if val_path.is_file() else val_path
                out_input.value = str(base_dir / "output")


    def start_job(self) -> None:
        """Asetukset kentistä, suunnitelma komennoiksi, ajo taustalle."""
        if self._is_running:
            self.notify("Ajo on jo käynnissä!", severity="warning")
            return
        try:
            options = self.collect_options()
        except ValueError as error:
            self.notify(str(error), severity="error")
            return
        if not options.input_dir:
            self.notify("Syötekansio puuttuu.", severity="error")
            return
        report = self._onboarding_checker()
        if not report.is_ready:
            self.notify("Apuohjelmat tai tunnistetiedot puuttuvat!", severity="error")
            self.push_screen(OnboardingModal(checker=self._onboarding_checker))
            return
        self._is_running = True
        run_btn = self.query_one("#run", Button)
        run_btn.disabled = True
        run_btn.label = "Ajetaan..."
        self.run_worker(partial(self._job, options), thread=True, exclusive=True)

    def _set_progress(self, progress: float, status: str) -> None:
        try:
            bar = self.query_one("#progress-bar", ProgressBar)
            bar.update(progress=min(max(float(progress), 0.0), 100.0))
            lbl = self.query_one("#progress-status", Label)
            lbl.update(status)
        except Exception:
            pass

    def _set_progress_status(self, status: str) -> None:
        try:
            lbl = self.query_one("#progress-status", Label)
            lbl.update(status)
        except Exception:
            pass

    def _job(self, options: RunOptions) -> None:
        try:
            self.call_from_thread(self._set_progress, 0.0, "Valmistellaan ajoa...")
            files = driver.list_input_files(Path(options.input_dir))
            reuse_session = False
            if session.is_session_alive(options.session):
                if options.reset_session:
                    self.call_from_thread(
                        self._write_log,
                        f"Suljetaan olemassa oleva Colab-istunto '{options.session}'...",
                    )
                    session.stop_session(options.session)
                else:
                    reuse_session = True
                    self.call_from_thread(
                        self._write_log,
                        f"Käytetään olemassa olevaa Colab-istuntoa '{options.session}'.",
                    )

            plan = driver.plan_commands(options, files, reuse_session=reuse_session)

            recorded_lines: list[str] = []

            def _parse_progress_from_line(line: str) -> None:
                line_s = line.strip()
                if "Koko putki suoritettu onnistuneesti" in line_s or line_s == "valmis":
                    self._set_progress(100.0, "Valmis! Kaikki vaiheet suoritettu.")
                elif "[vaihe 1/4]" in line_s:
                    self._set_progress(35.0, line_s)
                elif "[vaihe 2/4" in line_s:
                    m = re.search(r"\((\d+)/(\d+)\)", line_s)
                    if m:
                        idx, tot = int(m.group(1)), int(m.group(2))
                        pct = 40.0 + (idx / max(tot, 1)) * 35.0
                        self._set_progress(pct, line_s)
                    else:
                        self._set_progress(40.0, line_s)
                elif "[vaihe 3/4]" in line_s:
                    self._set_progress(80.0, line_s)
                elif "[vaihe 4/4" in line_s:
                    self._set_progress(90.0, line_s)

            def log(line: str) -> None:
                recorded_lines.append(line)
                self.call_from_thread(self._write_log, line)
                self.call_from_thread(_parse_progress_from_line, line)

            def on_progress(pct: float, status: str) -> None:
                self.call_from_thread(self._set_progress, pct, status)

            sig = inspect.signature(self._runner)
            kwargs = {}
            if "on_progress" in sig.parameters:
                kwargs["on_progress"] = on_progress

            code = self._runner(plan, log, timeout=driver.COMMAND_TIMEOUT, **kwargs)
            if code == 0:
                summary = "ajo valmis"
                self.call_from_thread(
                    self._set_progress, 100.0, "Valmis! Ajo onnistui."
                )
                transcripts = driver.parse_generated_transcripts("\n".join(recorded_lines))
                for t in transcripts:
                    self.call_from_thread(self._write_log, f"Litterointi valmis: {t}")
            else:
                summary = f"ajo pysähtyi koodiin {code}"
                self.call_from_thread(
                    self._set_progress_status, f"Ajo pysähtyi koodiin {code}"
                )
            self.call_from_thread(self._write_log, summary)

        finally:

            def _reset_btn() -> None:
                self._is_running = False
                try:
                    btn = self.query_one("#run", Button)
                    btn.disabled = False
                    btn.label = "Aja"
                except Exception:
                    pass

            self.call_from_thread(_reset_btn)

    def _write_log(self, line: str) -> None:
        self.query_one("#log", RichLog).write(line)
