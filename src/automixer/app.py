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
        pass

    def action_close(self):
        self.app.pop_screen()

    BINDINGS = [("f12", "app.pop_screen", "Close Log"), ("escape", "app.pop_screen", "Close Log")]

class AutomixerApp(App):
    CSS = """
    #main_container { padding: 1; }
    .field { margin: 1 0; }
    #log { height: 1fr; min-height: 5; border: solid gray; background: $surface; }
    #log_container { padding: 2; background: $surface; border: thick $primary; height: 80%; width: 80%; }
    #log_header { text-style: bold; margin-bottom: 1; }
    #debug_log { height: 1fr; }
    #mix_btn { margin: 1 0; width: 100%; }
    #mix_progress { margin-bottom: 1; }
    #current_op_label { text-style: bold; color: $accent; margin: 1 0; }
    #track_selection_list { height: 10; border: solid $accent; }
    .chain_box { border: round $primary; padding: 1; margin: 1; height: auto; background: $surface; }
    .chain_header { color: $accent; text-style: bold; margin-bottom: 1; }
    .dsp_row { height: 3; align: left middle; }
    .dsp_label { width: 15; }
    .dsp_input { width: 10; }
    #spot_list { height: 8; border: solid $secondary; }
    #render_inputs { height: auto; }
    #render_inputs > Vertical { width: 50%; }
    #plugin_list { height: 10; border: solid $accent; }
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
                    "peak_enabled": True,
                    "lev_enabled": True,
                    "multiband_enabled": False,
                    "plugin_paths": []
                },
                "music": {
                    "carve_enabled": True,
                    "carve_strength": 0.5,
                    "duck_enabled": True,
                    "duck_threshold": -30,
                    "plugin_paths": []
                }
            }
        }
        self.spots = []
        self.audio_files = []
        self.system_plugins = []

    def log_system(self, msg):
        self.log_messages.append(msg)
        try: self.query_one("#log", Log).write_line(msg)
        except: pass
        for screen in self.app.screen_stack:
            if isinstance(screen, LogScreen):
                try: screen.query_one("#debug_log", Log).write_line(msg)
                except: pass

    def action_toggle_log(self):
        ls = LogScreen()
        self.push_screen(ls)
        def populate():
            log_widget = ls.query_one("#debug_log", Log)
            for msg in self.log_messages: log_widget.write_line(msg)
        self.call_after_refresh(populate)

    def scan_system_plugins(self):
        paths = [
            "/Library/Audio/Plug-Ins/Components",
            os.path.expanduser("~/Library/Audio/Plug-Ins/Components"),
            "/Library/Audio/Plug-Ins/VST3",
            os.path.expanduser("~/Library/Audio/Plug-Ins/VST3")
        ]
        self.system_plugins = []
        for p in paths:
            if os.path.exists(p):
                for f in os.listdir(p):
                    if f.endswith(('.component', '.vst3')):
                        self.system_plugins.append(os.path.join(p, f))
        self.system_plugins.sort()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("1. Assets"):
                yield Vertical(
                    Label(f"Scanning: {self.work_dir}"),
                    SelectionList(id="track_selection_list"),
                    Horizontal(
                        Button("🎤 Speech", variant="primary", id="mark_speech_btn"),
                        Button("🎵 Music", variant="warning", id="mark_music_btn"),
                        classes="field"
                    ),
                    Label("Selected:"),
                    ListView(id="track_roles_list"),
                )
            
            with TabPane("2. Dynamics"):
                with Horizontal():
                    with Vertical(classes="chain_box"):
                        yield Label("SPEECH BUS (Per-Track)", classes="chain_header")
                        yield Checkbox("High-Pass (80Hz)", value=True, id="speech_hp_enable")
                        yield Checkbox("Multiband Mode", value=False, id="speech_multiband_enable")
                        yield Checkbox("Peak Tamer", value=True, id="speech_peak_enable")
                        yield Checkbox("Leveler", value=True, id="speech_lev_enable")
                    
                    with Vertical(classes="chain_box"):
                        yield Label("MUSIC BUS (Global)", classes="chain_header")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Spectral Carve", value=True, id="music_carve_enable")
                            yield Input(value="0.5", id="music_carve_strength", classes="dsp_input")
                        with Horizontal(classes="dsp_row"):
                            yield Checkbox("Auto-Ducking", value=True, id="music_duck_enable")
                            yield Input(value="-30", id="music_duck_thresh", classes="dsp_input")
                
                yield Vertical(
                    Button("🔍 Scan for Ad Break", variant="primary", id="analyze_btn"),
                    ListView(id="spot_list"),
                )

            with TabPane("3. Plugins"):
                yield Vertical(
                    Label("System Plugins (Select to add to SPEECH tracks):"),
                    SelectionList(id="speech_plugin_list"),
                    Label("System Plugins (Select to add to MUSIC bus):"),
                    SelectionList(id="music_plugin_list"),
                    Button("Refresh Plugin List", id="refresh_plugins_btn")
                )

            with TabPane("4. Render"):
                yield Vertical(
                    Button("🚀 RENDER FINAL MIX", variant="success", id="mix_btn"),
                    Label("Ready", id="current_op_label"),
                    ProgressBar(total=100, show_eta=True, id="mix_progress"),
                    Horizontal(
                        Vertical(Label("LUFS:"), Input(value="-16.0", id="target_lufs")),
                        Vertical(Label("Output:"), Input(value=self.config["output_path"], id="output_path")),
                        id="render_inputs"
                    ),
                    Log(id="log"),
                )
        yield Footer()

    def on_mount(self):
        self.action_refresh()
        self.action_refresh_plugins()

    def action_refresh(self):
        extensions = ('.wav', '.mp3', '.flac', '.m4a', '.ogg')
        self.log_system(f"Scanning files...")
        self.audio_files = sorted([os.path.join(self.work_dir, f) for f in os.listdir(self.work_dir) if f.lower().endswith(extensions)])
        sl = self.query_one("#track_selection_list", SelectionList)
        sl.clear_options()
        for f in self.audio_files: sl.add_option(Selection(os.path.basename(f), f))

    def action_refresh_plugins(self):
        self.scan_system_plugins()
        for id in ["#speech_plugin_list", "#music_plugin_list"]:
            sl = self.query_one(id, SelectionList)
            sl.clear_options()
            for p in self.system_plugins: sl.add_option(Selection(os.path.basename(p), p))

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id in ("mark_speech_btn", "mark_music_btn"):
            role = "speech" if event.button.id == "mark_speech_btn" else "music"
            for f in self.query_one("#track_selection_list", SelectionList).selected:
                self.config["tracks"] = [t for t in self.config["tracks"] if t["path"] != f]
                self.config["tracks"].append({"name": os.path.basename(f), "path": f, "type": role})
            self.update_track_roles_display()
        elif event.button.id == "analyze_btn": self.run_analysis()
        elif event.button.id == "mix_btn": self.run_mix()
        elif event.button.id == "refresh_plugins_btn": self.action_refresh_plugins()

    def update_track_roles_display(self):
        rl = self.query_one("#track_roles_list", ListView)
        rl.clear()
        for t in self.config["tracks"]:
            icon = "🎤" if t["type"] == "speech" else "🎵"
            rl.append(ListItem(Label(f"{icon} {t['type'].upper()}: {t['path']}")))

    def run_analysis(self):
        speech = [t for t in self.config["tracks"] if t["type"] == "speech"]
        if not speech: return self.notify("No speech tracks!", severity="error")
        path = speech[0]["path"]
        self.log_system(f"Analyzing {path}...")
        def task():
            try:
                data, sr = sf.read(path)
                if len(data.shape) > 1: data = data.mean(axis=1)
                self.spots = SpotAnalyzer(sr=sr).find_spots(data)
                self.call_from_thread(self.update_spots)
            except Exception as e: self.log_system(f"Error: {e}")
        threading.Thread(target=task).start()

    def update_spots(self):
        lv = self.query_one("#spot_list", ListView)
        lv.clear()
        for s in self.spots: lv.append(ListItem(Label(f"Pause at {s//60:.0f}:{s%60:05.2f}")))

    def sync_config_from_ui(self):
        s_bus = self.config["buses"]["speech"]
        s_bus["hp_enabled"] = self.query_one("#speech_hp_enable", Checkbox).value
        s_bus["multiband_enabled"] = self.query_one("#speech_multiband_enable", Checkbox).value
        s_bus["peak_enabled"] = self.query_one("#speech_peak_enable", Checkbox).value
        s_bus["lev_enabled"] = self.query_one("#speech_lev_enable", Checkbox).value
        s_bus["plugin_paths"] = self.query_one("#speech_plugin_list", SelectionList).selected
        
        m_bus = self.config["buses"]["music"]
        m_bus["carve_enabled"] = self.query_one("#music_carve_enable", Checkbox).value
        m_bus["carve_strength"] = float(self.query_one("#music_carve_strength", Input).value)
        m_bus["duck_enabled"] = self.query_one("#music_duck_enable", Checkbox).value
        m_bus["duck_threshold"] = float(self.query_one("#music_duck_thresh", Input).value)
        m_bus["plugin_paths"] = self.query_one("#music_plugin_list", SelectionList).selected

        processed = {"speech": s_bus, "music": m_bus}
        # Backward compatibility for Mixer processing loop
        processed["speech"]["processors"] = [{"type": "plugin", "path": p} for p in s_bus["plugin_paths"]]
        processed["music"]["processors"] = [{"type": "plugin", "path": p} for p in m_bus["plugin_paths"]]
        
        self.config["buses"] = processed
        self.config["target_lufs"] = float(self.query_one("#target_lufs", Input).value)
        self.config["output_path"] = self.query_one("#output_path", Input).value
        sl = self.query_one("#spot_list", ListView)
        if sl.index is not None and sl.index < len(self.spots): self.config["ad_spot"] = self.spots[sl.index]

    def run_mix(self):
        if not self.config["tracks"]: return self.notify("Add tracks!", severity="error")
        try: self.sync_config_from_ui()
        except ValueError: return self.notify("Invalid settings", severity="error")
        progress = self.query_one("#mix_progress", ProgressBar)
        op_label = self.query_one("#current_op_label", Label)
        progress.progress = 0
        def progress_callback(val, msg):
            def update_ui():
                progress.progress = val
                op_label.update(msg)
                self.log_system(f"[{val}%] {msg}")
            self.call_from_thread(update_ui)
        def task():
            try:
                Mixer(self.config).run(progress_callback=progress_callback)
                self.call_from_thread(lambda: op_label.update("✅ Done!"))
                self.call_from_thread(lambda: self.notify("Mix Ready!"))
            except Exception as e: self.log_system(f"❌ Error: {e}")
        threading.Thread(target=task).start()

if __name__ == "__main__":
    app = AutomixerApp(work_dir=sys.argv[1] if len(sys.argv) > 1 else ".")
    app.run()
