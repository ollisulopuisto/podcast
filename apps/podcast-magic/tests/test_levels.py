"""Tason tarkistus ja se, ettei se saa jäädä tekemättä hiljaa."""

from __future__ import annotations

import numpy as np
import pytest
from podcastmagic import audio, nhsx
from podcastmagic.jobs import Job, Progress
from podcastmagic.silence import run as runner
from podcastmagic.silence.detect import speech_intervals
from podcastmagic.silence.presets import Settings


def progress():
    return Progress(Job(id=0, module="testi", label="testi"))


def test_dbfs_matches_the_full_scale_definition():
    loud = np.full(16000, 0.5, np.float32)
    assert abs(audio.dbfs(loud, 0.0, 1.0) - (-6.02)) < 0.05
    # Int16 luetaan samaksi luvuksi: välimuisti pitää raakaa muotoa.
    assert abs(audio.dbfs((loud * 32768).astype(np.int16), 0.0, 1.0) - (-6.02)) < 0.05


def test_an_empty_slice_is_silence_not_full_scale():
    """Nollan pituinen jakso olisi nollana täysi taso ja pääsisi läpi."""
    assert audio.dbfs(np.zeros(100, np.float32), 1.0, 1.0) == float("-inf")


def test_quiet_words_are_dropped(monkeypatch, session_file):
    """Vuodon vaimeat sanat jäävät pois, oma puhe jää."""
    (session_file.parent / "olli.wav").write_bytes(b"")
    samples = np.zeros(16000 * 12, np.float32)
    samples[16000 : int(1.45 * 16000)] = 0.3  # vain ensimmäinen sana on kuuluva
    monkeypatch.setattr(
        "podcastmagic.silence.detect.audio_io.decode_pcm",
        lambda path: (samples * 32768).astype(np.int16),
    )
    session = nhsx.read(session_file)
    result = speech_intervals(session, session.tracks[0], Settings(rms=True))
    assert result.words_seen == 3
    assert result.words_levelled == 3
    assert result.words_quiet == 2
    assert len(result.intervals) == 1


def test_the_level_check_never_silently_does_nothing(session_file):
    """Tarkistus päällä ja yhtään ääntä ei levyllä = virhe, ei hiljaisuus.

    Ilman tätä tulos on täsmälleen sama kuin ilman tarkistusta, ja
    käyttöliittymä kertoi että se on päällä. Ero kuuluu vasta valmiissa
    jaksossa.
    """
    with pytest.raises(RuntimeError, match="Tason tarkistus"):
        runner.run(str(session_file), Settings(rms=True), progress())


def test_without_the_level_check_a_missing_file_is_no_obstacle(session_file):
    result = runner.run(str(session_file), Settings(rms=False), progress())
    assert result["written"]


def test_a_missing_file_lets_its_words_through(monkeypatch, session_file):
    """Ilman ääntä tasoa ei voi mitata, eikä sana silloin katoa.

    Liikaa vaimennettu jakso on pahempi virhe kuin liian vähän vaimennettu:
    jälkimmäisen kuulee kerran, edellisestä puuttuu puhetta.
    """
    session = nhsx.read(session_file)
    result = speech_intervals(session, session.tracks[0], Settings(rms=True))
    assert len(result.intervals) == 3
    assert result.words_levelled == 0
    assert result.missing_audio == ["olli.wav"]
