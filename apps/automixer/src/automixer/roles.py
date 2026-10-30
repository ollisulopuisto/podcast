"""Shared speech/music actions for the track-selection buttons and keys."""
import os

from textual.binding import Binding
from textual.widgets import Button, SelectionList

ROLE_BINDINGS = [
    Binding("s", "mark_speech", "Mark Speech"),
    Binding("m", "mark_music", "Mark Music"),
]


class TrackRoleActions:
    """Use the same selected paths and configuration shape as the role buttons."""

    def action_mark_speech(self) -> None:
        self._assign_selected_role("speech")

    def action_mark_music(self) -> None:
        self._assign_selected_role("music")

    def _assign_selected_role(self, role: str) -> None:
        focused = self.focused
        if not (
            (isinstance(focused, SelectionList) and focused.id == "track_selection_list")
            or (isinstance(focused, Button) and focused.id in ("mark_speech_btn", "mark_music_btn"))
        ):
            return
        selected = self.query_one("#track_selection_list", SelectionList).selected
        if not selected:
            return
        for path in selected:
            self.config["tracks"] = [t for t in self.config["tracks"] if t["path"] != path]
            self.config["tracks"].append({"name": os.path.basename(path), "path": path, "type": role})
        self.update_track_roles_display()
