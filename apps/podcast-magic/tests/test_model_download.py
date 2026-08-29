"""Mallin lataus näkyy lokissa.

Ensimmäinen ajo hakee mallin Hugging Facesta. Se on gigatavun luokkaa, ja
ilman tätä ohjelma seisoo koko sen ajan hiljaa: ei riviä lokissa, palkki
nollassa. Juuri siitä syntyi kysymys «toimiiko litterointi ollenkaan».
"""

from __future__ import annotations

from podcastmagic.transcribe.backends import mlx


class FakeProgress:
    """Kirjaa mitä työlle kerrottiin."""

    def __init__(self):
        self.lines: list[str] = []
        self.fractions: list[float | None] = []

    def log(self, message: str) -> None:
        self.lines.append(message)

    def fraction(self, value: float | None) -> None:
        self.fractions.append(value)


def boom(repo):
    raise AssertionError("valmista mallia ei saa ladata uudestaan")


def test_a_cached_model_says_nothing_and_downloads_nothing(monkeypatch):
    monkeypatch.setattr(mlx, "model_is_cached", lambda repo: True)
    monkeypatch.setattr(mlx, "download_model", boom)

    progress = FakeProgress()
    mlx.ensure_model("mlx-community/whisper-large-v3-turbo", progress)

    assert progress.lines == []


def test_a_missing_model_is_announced_before_the_wait(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(mlx, "model_is_cached", lambda repo: False)
    monkeypatch.setattr(mlx, "download_model", lambda repo: called.append(repo))

    progress = FakeProgress()
    mlx.ensure_model("mlx-community/whisper-large-v3-turbo", progress)

    assert called == ["mlx-community/whisper-large-v3-turbo"]
    # Rivi ennen odotusta, ei sen jälkeen: jälkikäteen kerrottu lataus on
    # sama kuin ei kerrottu.
    assert "whisper-large-v3-turbo" in progress.lines[0]
    assert len(progress.lines) >= 2
    # Osuus tuntemattomaksi ladatessa: nollassa seisova palkki näyttää
    # jumilta, liikkuva kertoo että jotain tapahtuu.
    assert progress.fractions[0] is None
