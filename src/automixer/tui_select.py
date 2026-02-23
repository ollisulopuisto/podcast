from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, ListView, ListItem, Label
from textual.binding import Binding
import yaml
import sys
import os

class SpotSelectionApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    ListView {
        border: solid green;
    }
    ListItem {
        padding: 1;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("enter", "select", "Select Spot"),
    ]
    
    def __init__(self, spots_file, config_file):
        super().__init__()
        self.spots_file = spots_file
        self.config_file = config_file
        self.spots = []
        if os.path.exists(spots_file):
            with open(spots_file, "r") as f:
                self.spots = [float(line.strip()) for line in f if line.strip()]
                
    def compose(self) -> ComposeResult:
        yield Header()
        yield Label(f"Select an ad insertion spot for {self.config_file}")
        # Group spots by minute to make it easier to read?
        # For now, just a list
        yield ListView(
            *[ListItem(Label(f"Spot at {s:.2f}s ({s//60:.0f}:{s%60:05.2f})")) for s in self.spots],
            id="spot_list"
        )
        yield Footer()
        
    def action_select(self):
        list_view = self.query_one("#spot_list", ListView)
        if list_view.index is not None:
            selected_spot = self.spots[list_view.index]
            self.save_selection(selected_spot)
            self.notify(f"Selected spot at {selected_spot:.2f}s")
            self.exit(selected_spot)
            
    def save_selection(self, spot):
        config = {}
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f) or {}
                
        config["ad_spot"] = spot
        
        with open(self.config_file, "w") as f:
            yaml.dump(config, f)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.automixer.tui_select <spots_file> <config_file>")
        sys.exit(1)
        
    app = SpotSelectionApp(sys.argv[1], sys.argv[2])
    app.run()
