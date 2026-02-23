import os
import yaml
import sys
import threading
import soundfile as sf
from typing import List

from textual.app import App, ComposeResult
from textual.widgets import (Header, Footer, TabbedContent, TabPane, 
                             Input, Button, Label, ListView, ListItem, 
                             Log, SelectionList, Checkbox, Static, ProgressBar)
from textual.widgets.selection_list import Selection
from textual.containers import Vertical, Horizontal, Container, Grid
from textual.binding import Binding
from textual.screen import ModalScreen

from src.automixer.analyzer import SpotAnalyzer
from src.automixer.cli_mix import Mixer
from src.automixer import __version__

class LogScreen(ModalScreen):
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("SYSTEM LOG (Press F12 or Esc to close)", id="log_header"),
            Log(id="debug_log"),
            id="log_container"
        )

    def on_mount(self):
        # Initialize with current app log history if possible
        pass

    def action_close(self):
        self.app.pop_screen()

    BINDINGS = [("f12", "app.pop_screen", "Close Log"), ("escape", "app.pop_screen", "Close Log")]

class AutomixerApp(App):
    CSS = """
    #main_container {
        padding: 1;
    }
    .field {
        margin: 1 0;
    }
    #log {
        height: 1fr;
        min-height: 5;
        border: solid gray;
        background: $surface;
    }
    #log_container {
        padding: 2;
        background: $surface;
        border: thick $primary;
        height: 80%;
        width: 80%;
    }
    #log_header {
        text-style: bold;
        margin-bottom: 1;
    }
    #debug_log {
        height: 1fr;
    }
    #mix_btn {
        margin: 1 0;
        width: 100%;
    }
    #mix_progress {
        margin-bottom: 1;
    }
    #current_op_label {
        text-style: bold;
        color: $accent;
        margin: 1 0;
    }
    #track_selection_list {
        height: 10;
        border: solid $accent;
    }
    .chain_box {
        border: round $primary;
        padding: 1;
        margin: 1;
        height: auto;
        background: $surface;
    }
    .chain_header {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    .dsp_row {
        height: 3;
        align: left middle;
    }
    .dsp_label {
        width: 15;
    }
    .dsp_input {
        width: 10;
    }
    #spot_list {
        height: 8;
        border: solid $secondary;
    }
    #render_inputs {
        height: auto;
    }
    #render_inputs > Vertical {
        width: 50%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+s", "save", "Save Config"),
        Binding("r", "refresh", "Refresh Files"),
        Binding("f12", "toggle_log", "System Log"),
    ]

    def __init__(self, work_dir="."):
        super().__init__()
        self.work_dir = os.path.abspath(work_dir)
        self.log_messages = []
        self.config = {
            "project": os.path.basename(self.work_dir),
            "target_lufs": -16.0,
            "output_path": os.path.join(self.work_dir, "final_mix.wav"),
            "tracks": [],
            "ad_spot": 0.0,
            "ad_duration": 30.0,
            "buses": {
                "speech": {
                    "hp_enabled": True,
                    "hp_freq": 80,
                    "peak_enabled": True,
                    "peak_threshold": -12,
                    "lev_enabled": True,
                    "lev_threshold": -22
                },
                "music": {
                    "hp_enabled": False,
                    "hp_freq": 100,
                    "carve_enabled": True,
                    "carve_strength": 0.5,
                    "duck_enabled": True,
                    "duck_threshold": -30
                }
            }
        }
        self.spots = []
        self.audio_files = []

    def log_system(self, msg):
        self.log_messages.append(msg)
        try:
            self.query_one("#log", Log).write_line(msg)
        except:
            pass
        
        for screen in self.app.screen_stack:
            if isinstance(screen, LogScreen):
                try:
                    screen.query_one("#debug_log", Log).write_line(msg)
                except:
                    pass

    def action_toggle_log(self):
        ls = LogScreen()
        self.push_screen(ls)
        def populate():
            log_widget = ls.query_one("#debug_log", Log)
            for msg in self.log_messages:
                log_widget.write_line(msg)
        self.call_after_refresh(populate)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("1. Audio Assets"):
                yield Vertical(
                    Label(f"Scanning directory: {self.work_dir}"),
                    SelectionList(id="track_selection_list"),
                    Horizontal(
                        Button("🎤 Add as SPEECH", variant="primary", id="mark_speech_btn"),
                        Button("🎵 Add as MUSIC", variant="warning", id="mark_music_btn"),
                        classes="field"
                    ),
                    Label("Selected Tracks:"),
                    ListView(id="track_roles_list"),
                )
            
            with TabPane("2. Signal Chain"):
                with Horizontal():
                    with Vertical(classes="chain_box"):
                        yield Label("SPEECH BUS (Auto-Gain)", classes="chain_header")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("High-Pass", value=True, id="speech_hp_enable")
                            yield Label(" (80Hz Sub-cut)", classes="dsp_label")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Multiband Mode", value=False, id="speech_multiband_enable")
                            yield Label(" (3-band dynamic)", classes="dsp_label")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Peak Tamer", value=True, id="speech_peak_enable")
                            yield Label(" (Intelligent)", classes="dsp_label")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Leveler", value=True, id="speech_lev_enable")
                            yield Label(" (Auto-Reference)", classes="dsp_label")
                    
                    with Vertical(classes="chain_box"):
                        yield Label("MUSIC BUS (Spectral Carve)", classes="chain_header")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Spectral Carve", value=True, id="music_carve_enable")
                            yield Input(value="0.5", id="music_carve_strength", classes="dsp_input")
                            yield Label("0..1")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Auto-Ducking", value=True, id="music_duck_enable")
                            yield Input(value="-30", id="music_duck_thresh", classes="dsp_input")
                            yield Label("dB")
                        with Horizontal(classes="dsp_row"):
                            yield Label("AU Plugin Path:", classes="dsp_label")
                            yield Input(placeholder="/Path/to/Plugin.component", id="music_plugin_path")
                
                yield Vertical(
                    Button("🔍 Scan for Natural Ad Break", variant="primary", id="analyze_btn"),
                    Label("Suggested Insertion Spots:"),
                    ListView(id="spot_list"),
                )

            with TabPane("3. Render"):
                yield Vertical(
                    Button("🚀 RENDER FINAL MIX", variant="success", id="mix_btn"),
                    Label("Ready", id="current_op_label"),
                    ProgressBar(total=100, show_eta=True, id="mix_progress"),
                    Horizontal(
                        Vertical(
                            Label("Target LUFS:"),
                            Input(value="-16.0", id="target_lufs"),
                        ),
                        Vertical(
                            Label("Output Filename:"),
                            Input(value=self.config["output_path"], id="output_path"),
                        ),
                        id="render_inputs"
                    ),
                    Log(id="log"),
                )
        yield Footer()

    def on_mount(self):
        self.action_refresh()

    def action_refresh(self):
        extensions = ('.wav', '.mp3', '.flac', '.m4a', '.ogg')
        self.log_system(f"Scanning {self.work_dir} for audio files...")
        self.audio_files = sorted([
            os.path.join(self.work_dir, f) 
            for f in os.listdir(self.work_dir) 
            if f.lower().endswith(extensions)
        ])
        
        selection_list = self.query_one("#track_selection_list", SelectionList)
        selection_list.clear_options()
        for f_path in self.audio_files:
            f_name = os.path.basename(f_path)
            selection_list.add_option(Selection(f_name, f_path))
        self.log_system(f"Found {len(self.audio_files)} matching files.")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id in ("mark_speech_btn", "mark_music_btn"):
            role = "speech" if event.button.id == "mark_speech_btn" else "music"
            selected_paths = self.query_one("#track_selection_list", SelectionList).selected
            for f_path in selected_paths:
                self.config["tracks"] = [t for t in self.config["tracks"] if t["path"] != f_path]
                self.config["tracks"].append({
                    "name": os.path.basename(f_path), 
                    "path": f_path, 
                    "type": role
                })
            self.update_track_roles_display()
        
        elif event.button.id == "analyze_btn":
            self.run_analysis()
            
        elif event.button.id == "mix_btn":
            self.run_mix()

    def update_track_roles_display(self):
        roles_list = self.query_one("#track_roles_list", ListView)
        roles_list.clear()
        for t in self.config["tracks"]:
            icon = "🎤" if t["type"] == "speech" else "🎵"
            roles_list.append(ListItem(Label(f"{icon} {t['type'].upper()}: {t['path']}")))

    def run_analysis(self):
        speech_tracks = [t for t in self.config["tracks"] if t["type"] == "speech"]
        if not speech_tracks:
            self.notify("No speech tracks selected.", severity="error")
            return
        path = speech_tracks[0]["path"]
        self.log_system(f"Starting analysis of {path} for pauses...")
        def task():
            try:
                data, sr = sf.read(path)
                if len(data.shape) > 1: data = data.mean(axis=1)
                analyzer = SpotAnalyzer(sr=sr)
                self.spots = analyzer.find_spots(data)
                self.call_from_thread(self.update_spots)
            except Exception as e:
                self.log_system(f"Analysis Error: {e}")
                self.call_from_thread(lambda: self.notify(f"Analysis Error: {e}", severity="error"))
        threading.Thread(target=task).start()

    def update_spots(self):
        list_view = self.query_one("#spot_list", ListView)
        list_view.clear()
        for s in self.spots:
            list_view.append(ListItem(Label(f"Pause at {s//60:.0f}:{s%60:05.2f}")))
        self.log_system(f"Found {len(self.spots)} potential ad spots.")

    def sync_config_from_ui(self):
        """Map UI state back to the config object for the Mixer."""
        # Speech Bus
        s_bus = self.config["buses"]["speech"]
        s_bus["hp_enabled"] = self.query_one("#speech_hp_enable", Checkbox).value
        s_bus["multiband_enabled"] = self.query_one("#speech_multiband_enable", Checkbox).value
        s_bus["peak_enabled"] = self.query_one("#speech_peak_enable", Checkbox).value
        s_bus["lev_enabled"] = self.query_one("#speech_lev_enable", Checkbox).value
        
        # Music Bus
        m_bus = self.config["buses"]["music"]
        m_bus["carve_enabled"] = self.query_one("#music_carve_enable", Checkbox).value
        m_bus["carve_strength"] = float(self.query_one("#music_carve_strength", Input).value)
        m_bus["duck_enabled"] = self.query_one("#music_duck_enable", Checkbox).value
        m_bus["duck_threshold"] = float(self.query_one("#music_duck_thresh", Input).value)
        m_bus["plugin_path"] = self.query_one("#music_plugin_path", Input).value

        # Build actual processor list for Mixer
        processed_buses = {"speech": {"processors": []}, "music": {"processors": []}}
        
        processed_buses["speech"]["hp_enabled"] = s_bus["hp_enabled"]
        processed_buses["speech"]["multiband_enabled"] = s_bus["multiband_enabled"]
        processed_buses["speech"]["peak_enabled"] = s_bus["peak_enabled"]
        processed_buses["speech"]["lev_enabled"] = s_bus["lev_enabled"]
        
        # Music Bus Configuration
        processed_buses["music"]["carve_enabled"] = m_bus["carve_enabled"]
        processed_buses["music"]["carve_strength"] = m_bus["carve_strength"]
        processed_buses["music"]["duck_enabled"] = m_bus["duck_enabled"]
        processed_buses["music"]["duck_threshold"] = m_bus["duck_threshold"]
        
        if m_bus["plugin_path"]:
            processed_buses["music"]["processors"].append({
                "type": "plugin", 
                "path": m_bus["plugin_path"]
            })
            
        self.config["buses"] = processed_buses
        self.config["target_lufs"] = float(self.query_one("#target_lufs", Input).value)
        self.config["output_path"] = self.query_one("#output_path", Input).value
        
        spot_list = self.query_one("#spot_list", ListView)
        if spot_list.index is not None and spot_list.index < len(self.spots):
            self.config["ad_spot"] = self.spots[spot_list.index]

    def run_mix(self):
        if not self.config["tracks"]:
            self.notify("Add tracks first!", severity="error")
            return
        
        try:
            self.sync_config_from_ui()
        except ValueError:
            self.notify("Invalid number in signal chain settings", severity="error")
            return

        progress = self.query_one("#mix_progress", ProgressBar)
        op_label = self.query_one("#current_op_label", Label)
        
        progress.progress = 0
        op_label.update("Starting Mixer...")
        self.log_system("🚀 Starting Production Mix...")
        
        def progress_callback(val, msg):
            def update_ui():
                progress.progress = val
                op_label.update(msg)
                self.log_system(f"[{val}%] {msg}")
            self.call_from_thread(update_ui)

        def task():
            try:
                mixer = Mixer(self.config)
                mixer.run(progress_callback=progress_callback)
                def finish_ui():
                    self.log_system("✅ Production Render Complete!")
                    op_label.update("✅ All Done!")
                self.call_from_thread(finish_ui)
                self.call_from_thread(lambda: self.notify("Mix Ready!"))
            except Exception as e:
                def error_ui():
                    self.log_system(f"❌ Error: {str(e)}")
                    op_label.update("❌ Error Occurred")
                self.call_from_thread(error_ui)
        threading.Thread(target=task).start()

if __name__ == "__main__":
    import sys
    # Use the first command line argument as the working directory, or default to current
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    app = AutomixerApp(work_dir=target_dir)
    app.run()
