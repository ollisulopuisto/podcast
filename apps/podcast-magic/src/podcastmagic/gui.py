"""Natiivi työpöytäikkuna (pywebview) ja taustalla pyörivä palvelin."""

from __future__ import annotations

import socket
import sys
import threading
import time
from typing import Any

import uvicorn

from . import paths
from .server.app import create_app


def free_port(start: int = 8741) -> int:
    """Ensimmäinen vapaa portti. Toinen avoin ikkuna ei saa jäädä ilman."""
    port = start
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    raise RuntimeError("Vapaata porttia ei löytynyt.")


class BackgroundServer:
    """Taustasäikeessä pyörivä Uvicorn."""

    def __init__(self, app: Any, host: str = "127.0.0.1", port: int = 8741):
        self.host = host
        self.port = port
        config = uvicorn.Config(app=app, host=host, port=port, log_level="warning",
                                access_log=False)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self.thread.start()

    def wait(self, timeout: float = 10.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.server.started:
                return True
            time.sleep(0.02)
        return False

    def stop(self) -> None:
        self.server.should_exit = True


class DesktopApi:
    """Selaimen ja Pythonin välinen silta natiiveille valintaikkunoille."""

    def __init__(self, window: Any = None):
        self.window = window

    def open_session_dialog(self) -> str | None:
        if not self.window:
            return None
        import webview

        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Hindenburg (*.nhsx)", "All files (*.*)"),
        )
        return result[0] if result else None


def launch(
    session: str = "",
    start_dir: str = "",
    host: str = "127.0.0.1",
    port: int = 8741,
    debug: bool = False,
) -> None:
    """Käynnistää palvelimen ja avaa ikkunan. Palaa vasta kun ikkuna suljetaan."""
    import webview

    app = create_app(start_dir=start_dir, session=session)
    server = BackgroundServer(app, host=host, port=free_port(port))
    server.start()
    if not server.wait():
        server.stop()
        raise RuntimeError("Palvelimen käynnistys aikakatkaistiin.")

    api = DesktopApi()
    window = webview.create_window(
        title="Podcast Magic",
        url=server.url,
        width=1080,
        height=860,
        min_size=(760, 560),
        background_color="#16181c",
        js_api=api,
    )
    api.window = window
    window.events.closed += server.stop

    icon = paths.get_app_icon_path()
    icon_str = str(icon) if icon else None
    if sys.platform == "darwin" and icon_str:
        try:
            import AppKit

            image = AppKit.NSImage.alloc().initByReferencingFile_(icon_str)
            if image and image.isValid():
                AppKit.NSApplication.sharedApplication().setApplicationIconImage_(image)
        except Exception:  # noqa: BLE001 — kuvake on koriste, ei ehto
            pass

    try:
        webview.start(debug=debug, icon=icon_str)
    finally:
        server.stop()
        server.thread.join(timeout=2.0)
