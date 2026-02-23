from textual.app import App, ComposeResult
from textual.widgets import (Header, Footer, TabbedContent, TabPane, 
                             Input, Button, Label, ListView, ListItem, 
                             ProgressBar, Log, DirectoryTree, Static)
from textual.containers import Vertical, Horizontal, Container
from textual.binding import Binding
import yaml
import os
import soundfile as sf
import threading
import mlx.core as mx
import numpy as np

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
        height: 10;
        border: solid gray;
    }
    .status_label {
        color: green;
        margin: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+s", "save", "Save Config"),
    ]

    def __init__(self):
        super().__init__()
        self.config = {
            "project": "New Podcast",
            "target_lufs": -16.0,
            "output_path": "output.wav",
            "tracks": [],
            "ad_spot": 0.0
        }
        self.spots = []

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent():
            with TabPane("Setup"):
                yield Vertical(
                    Label("Project Name:"),
                    Input(value=self.config["project"], id="project_name"),
                    Label("Target LUFS:"),
                    Input(value=str(self.config["target_lufs"]), id="target_lufs"),
                    Label("Output File:"),
                    Input(value=self.config["output_path"], id="output_path"),
                    Label("Tracks (path, type): e.g. host.wav, speech"),
                    Input(placeholder="Add track: path, type", id="new_track"),
                    Button("Add Track", variant="primary", id="add_track_btn"),
                    ListView(id="track_list"),
                    id="setup_pane"
                )
            with TabPane("Analyze"):
                yield Vertical(
                    Button("Analyze Episode for Ad Spots", id="analyze_btn"),
                    Label("Detected Spots (select one):"),
                    ListView(id="spot_list"),
                    id="analyze_pane"
                )
            with TabPane("Mix"):
                yield Vertical(
                    Button("Run Final Mix", variant="success", id="mix_btn"),
                    ProgressBar(total=100, show_eta=True, id="progress"),
                    Log(id="log"),
                    id="mix_pane"
                )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "add_track_btn":
            val = self.query_one("#new_track", Input).value
            if "," in val:
                path, t_type = [v.strip() for v in val.split(",")]
                self.config["tracks"].append({"name": os.path.basename(path), "path": path, "type": t_type})
                self.query_one("#track_list", ListView).append(ListItem(Label(f"{t_type}: {path}")))
                self.query_one("#new_track", Input).value = ""
        
        elif event.button.id == "analyze_btn":
            self.run_analysis()
            
        elif event.button.id == "mix_btn":
            self.run_mix()

    def run_analysis(self):
        # Find the first speech track
        speech_tracks = [t for t in self.config["tracks"] if t["type"] == "speech"]
        if not speech_tracks:
            self.notify("No speech tracks found for analysis!", variant="error")
            return
            
        path = speech_tracks[0]["path"]
        if not os.path.exists(path):
            self.notify(f"File {path} not found!", variant="error")
            return
            
        self.query_one("#log", Log).write_line(f"Analyzing {path}...")
        
        # We'll run this in a thread if it's long, but for small files we can just do it
        # Let's do a simple non-blocking-ish call if possible or just use a thread
        def task():
            data, sr = sf.read(path)
            if len(data.shape) > 1:
                data = data.mean(axis=1)
            analyzer = SpotAnalyzer(sr=sr)
            self.spots = analyzer.find_spots(data)
            
            # Update UI on main thread
            self.call_from_thread(self.update_spots)
            
        threading.Thread(target=task).start()

    def update_spots(self):
        list_view = self.query_one("#spot_list", ListView)
        list_view.clear()
        for s in self.spots:
            list_view.append(ListItem(Label(f"Spot at {s:.2f}s ({s//60:.0f}:{s%60:05.2f})")))
        self.notify(f"Found {len(self.spots)} spots.")

    def run_mix(self):
        if not self.config["tracks"]:
            self.notify("No tracks added!", variant="error")
            return
            
        # Update config from UI inputs
        self.config["project"] = self.query_one("#project_name", Input).value
        self.config["target_lufs"] = float(self.query_one("#target_lufs", Input).value)
        self.config["output_path"] = self.query_one("#output_path", Input).value
        
        # Get selected spot if any
        spot_list = self.query_one("#spot_list", ListView)
        if spot_list.index is not None:
            self.config["ad_spot"] = self.spots[spot_list.index]

        log = self.query_one("#log", Log)
        log.write_line("Starting mix...")
        
        def task():
            try:
                mixer = Mixer(self.config)
                # We should probably add a way for Mixer to report progress
                mixer.run()
                self.call_from_thread(lambda: log.write_line("Mix complete!"))
                self.call_from_thread(lambda: self.notify("Mix complete!"))
            except Exception as e:
                self.call_from_thread(lambda: log.write_line(f"Error: {str(e)}"))
                
        threading.Thread(target=task).start()

    def action_save(self):
        with open("last_config.yaml", "w") as f:
            yaml.dump(self.config, f)
        self.notify("Configuration saved to last_config.yaml")

if __name__ == "__main__":
    app = AutomixerApp()
    app.run()
