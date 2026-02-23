import os
import yaml
import sys
import threading
import soundfile as sf
from typing import List

from textual.app import App, ComposeResult
from textual.widgets import (Header, Footer, TabbedContent, TabPane, 
                             Input, Button, Label, ListView, ListItem, 
                             Log, SelectionList, Checkbox, Static)
from textual.widgets.selection_list import Selection
from textual.containers import Vertical, Horizontal, Container, Grid
from textual.binding import Binding

from src.automixer.analyzer import SpotAnalyzer
from src.automixer.cli_mix import Mixer

class AutomixerApp(App):
    CSS = """
    #main_container {
        padding: 1;
    }
    .field {
        margin: 1 0;
    }
    #log {
        height: 8;
        border: solid gray;
        background: $surface;
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
        align: middle left;
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+s", "save", "Save Config"),
        Binding("r", "refresh", "Refresh Files"),
    ]

    def __init__(self):
        super().__init__()
        # Initial config with transparent defaults
        self.config = {
            "project": "New Podcast",
            "target_lufs": -16.0,
            "output_path": "output.wav",
            "tracks": [],
            "ad_spot": 0.0,
            "ad_duration": 30.0,
            "buses": {
                "speech": {
                    "hp_enabled": True,
                    "hp_freq": 80,
                    "comp_enabled": True,
                    "comp_threshold": -18,
                    "comp_ratio": 3.0
                },
                "music": {
                    "hp_enabled": False,
                    "hp_freq": 100,
                    "duck_enabled": True,
                    "duck_threshold": -30,
                    "duck_ratio": 8.0
                }
            }
        }
        self.spots = []
        self.audio_files = []

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("1. Audio Assets"):
                yield Vertical(
                    Label("Select audio files in directory:"),
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
                        yield Label("SPEECH BUS (Mono Sum)", classes="chain_header")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("High-Pass", value=True, id="speech_hp_enable")
                            yield Input(value="80", id="speech_hp_freq", classes="dsp_input")
                            yield Label("Hz")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Compressor", value=True, id="speech_comp_enable")
                            yield Input(value="-18", id="speech_comp_thresh", classes="dsp_input")
                            yield Label("dB")
                        with Horizontal(classes="dsp_row"):
                            yield Label("Ratio:", classes="dsp_label")
                            yield Input(value="3.0", id="speech_comp_ratio", classes="dsp_input")
                    
                    with Vertical(classes="chain_box"):
                        yield Label("MUSIC BUS (Stereo Sum)", classes="chain_header")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("High-Pass", value=False, id="music_hp_enable")
                            yield Input(value="100", id="music_hp_freq", classes="dsp_input")
                            yield Label("Hz")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Spectral Carve", value=True, id="music_carve_enable")
                            yield Input(value="0.5", id="music_carve_strength", classes="dsp_input")
                            yield Label("0..1")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Auto-Ducking", value=True, id="music_duck_enable")
                            yield Input(value="-30", id="music_duck_thresh", classes="dsp_input")
                            yield Label("dB")
                
                yield Vertical(
                    Button("🔍 Scan for Natural Ad Break", variant="primary", id="analyze_btn"),
                    Label("Suggested Insertion Spots:"),
                    ListView(id="spot_list"),
                )

            with TabPane("3. Render"):
                yield Vertical(
                    Grid(
                        Vertical(
                            Label("Target LUFS:"),
                            Input(value="-16.0", id="target_lufs"),
                        ),
                        Vertical(
                            Label("Output Filename:"),
                            Input(value="final_mix.wav", id="output_path"),
                        ),
                        columns=2
                    ),
                    Button("🚀 RENDER FINAL MIX", variant="success", id="mix_btn"),
                    Log(id="log"),
                )
        yield Footer()

    def on_mount(self):
        self.action_refresh()

    def action_refresh(self):
        extensions = ('.wav', '.mp3', '.flac', '.m4a', '.ogg')
        self.audio_files = sorted([f for f in os.listdir('.') if f.lower().endswith(extensions)])
        selection_list = self.query_one("#track_selection_list", SelectionList)
        selection_list.clear()
        for f in self.audio_files:
            selection_list.add_option(Selection(f, f))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id in ("mark_speech_btn", "mark_music_btn"):
            role = "speech" if event.button.id == "mark_speech_btn" else "music"
            selected_files = self.query_one("#track_selection_list", SelectionList).selected
            for f in selected_files:
                self.config["tracks"] = [t for t in self.config["tracks"] if t["path"] != f]
                self.config["tracks"].append({"name": os.path.basename(f), "path": f, "type": role})
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
            self.notify("No speech tracks selected.", variant="error")
            return
        path = speech_tracks[0]["path"]
        log = self.query_one("#log", Log)
        log.write_line(f"Analyzing {path} for pauses...")
        def task():
            try:
                data, sr = sf.read(path)
                if len(data.shape) > 1: data = data.mean(axis=1)
                analyzer = SpotAnalyzer(sr=sr)
                self.spots = analyzer.find_spots(data)
                self.call_from_thread(self.update_spots)
            except Exception as e:
                self.call_from_thread(lambda: self.notify(f"Analysis Error: {e}", variant="error"))
        threading.Thread(target=task).start()

    def update_spots(self):
        list_view = self.query_one("#spot_list", ListView)
        list_view.clear()
        for s in self.spots:
            list_view.append(ListItem(Label(f"Pause at {s//60:.0f}:{s%60:05.2f}")))

    def sync_config_from_ui(self):
        """Map UI state back to the config object for the Mixer."""
        # Speech Bus
        s_bus = self.config["buses"]["speech"]
        s_bus["hp_enabled"] = self.query_one("#speech_hp_enable", Checkbox).value
        s_bus["hp_freq"] = float(self.query_one("#speech_hp_freq", Input).value)
        s_bus["comp_enabled"] = self.query_one("#speech_comp_enable", Checkbox).value
        s_bus["comp_threshold"] = float(self.query_one("#speech_comp_thresh", Input).value)
        s_bus["comp_ratio"] = float(self.query_one("#speech_comp_ratio", Input).value)
        
        # Music Bus
        m_bus = self.config["buses"]["music"]
        m_bus["hp_enabled"] = self.query_one("#music_hp_enable", Checkbox).value
        m_bus["hp_freq"] = float(self.query_one("#music_hp_freq", Input).value)
        m_bus["carve_enabled"] = self.query_one("#music_carve_enable", Checkbox).value
        m_bus["carve_strength"] = float(self.query_one("#music_carve_strength", Input).value)
        m_bus["duck_enabled"] = self.query_one("#music_duck_enable", Checkbox).value
        m_bus["duck_threshold"] = float(self.query_one("#music_duck_thresh", Input).value)

        # Build actual processor list for Mixer
        processed_buses = {"speech": {"processors": []}, "music": {"processors": []}}
        if s_bus["hp_enabled"]:
            processed_buses["speech"]["processors"].append({"type": "highpass", "freq": s_bus["hp_freq"]})
        if s_bus["comp_enabled"]:
            processed_buses["speech"]["processors"].append({"type": "compressor", "threshold": s_bus["comp_threshold"], "ratio": s_bus["comp_ratio"]})
        
        if m_bus["hp_enabled"]:
            processed_buses["music"]["processors"].append({"type": "highpass", "freq": m_bus["hp_freq"]})
            
        self.config["buses"] = processed_buses
        self.config["target_lufs"] = float(self.query_one("#target_lufs", Input).value)
        self.config["output_path"] = self.query_one("#output_path", Input).value
        
        spot_list = self.query_one("#spot_list", ListView)
        if spot_list.index is not None and spot_list.index < len(self.spots):
            self.config["ad_spot"] = self.spots[spot_list.index]

    def run_mix(self):
        if not self.config["tracks"]:
            self.notify("Add tracks first!", variant="error")
            return
        
        try:
            self.sync_config_from_ui()
        except ValueError:
            self.notify("Invalid number in signal chain settings", variant="error")
            return

        log = self.query_one("#log", Log)
        log.clear()
        log.write_line("Mixing with custom signal chain...")
        
        def task():
            try:
                mixer = Mixer(self.config)
                mixer.run()
                self.call_from_thread(lambda: log.write_line("✅ Production Render Complete!"))
                self.call_from_thread(lambda: self.notify("Mix Ready!"))
            except Exception as e:
                self.call_from_thread(lambda: log.write_line(f"❌ Error: {str(e)}"))
        threading.Thread(target=task).start()

if __name__ == "__main__":
    app = AutomixerApp()
    app.run()
