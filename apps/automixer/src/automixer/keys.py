"""The ``?`` key: the keys panel for both terminal interfaces.

Textual draws the Footer and its keys panel (``HelpPanel``) from each
screen's ``BINDINGS``, so that list is already the one place a key is
written down. What was missing was a way in: the panel opened only from the
command palette (Ctrl+P, "Keys"), which you have to know about first.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import HelpPanel

#: Lisätään kummankin sovelluksen BINDINGSiin. Esc on piilossa alariviltä ja
#: käytössä vain paneelin ollessa auki (`check_action`), joten se ei vie
#: Esciä keneltäkään muulta.
KEYS_BINDINGS = [
    Binding("question_mark", "toggle_keys", "Keys"),
    Binding("escape", "hide_keys", "Close keys", show=False),
]


class KeysHelp:
    """Actions for ``KEYS_BINDINGS``; mix in before ``App``."""

    def _keys_open(self) -> bool:
        return bool(self.screen.query(HelpPanel))

    def action_toggle_keys(self) -> None:
        """Open the keys panel, or close it if it is open."""
        if self._keys_open():
            self.action_hide_help_panel()
        else:
            self.action_show_help_panel()

    def action_hide_keys(self) -> None:
        """Close the keys panel."""
        self.action_hide_help_panel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Esc belongs to the keys panel only while the panel is open."""
        if action == "hide_keys":
            return self._keys_open()
        return super().check_action(action, parameters)
