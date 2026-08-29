"""Moottorit ilman moottoreita: rajapinta, valinta ja edistymispalkin kaappaus."""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from podcastmagic.jobs import Cancelled, Job, Progress
from podcastmagic.transcribe.backends import BACKENDS
from podcastmagic.transcribe.backends import mlx as mlx_backend
from podcastmagic.transcribe.options import Options


def handle():
    job = Job(id=0, module="t", label="t")
    return job, Progress(job)


def fake_mlx(monkeypatch, frames=100, on_call=None):
    """Valemoduuli, joka käyttäytyy kuten mlx-whisper.

    Myös siltä osin että paketin ``transcribe``-attribuutti on funktio ja
    varjostaa samannimisen alimoduulin — juuri se piirre, jonka takia
    moduuli on haettava ``sys.modules``ista.
    """
    tqdm_module = types.SimpleNamespace(tqdm=None)

    def transcribe(audio, **kwargs):
        if on_call is not None:
            on_call(kwargs)
        # Sama kutsu kuin ylävirrassa.
        with submodule.tqdm.tqdm(total=frames, unit="frames", disable=False) as bar:
            for _ in range(10):
                bar.update(frames // 10)
        return {
            "text": " sana",
            "language": "fi",
            "segments": [{"words": [{"word": " sana", "start": 0.0, "end": 0.4}]}],
        }

    submodule = types.ModuleType("mlx_whisper.transcribe")
    submodule.tqdm = tqdm_module
    submodule.transcribe = transcribe

    package = types.ModuleType("mlx_whisper")
    package.transcribe = transcribe  # funktio varjostaa alimoduulin

    monkeypatch.setitem(sys.modules, "mlx_whisper", package)
    monkeypatch.setitem(sys.modules, "mlx_whisper.transcribe", submodule)
    return submodule


def test_progress_comes_from_the_progress_bar(monkeypatch):
    """mlx-whisper ei tarjoa takaisinkutsua, joten osuus luetaan tqdm:stä.

    Ilman tätä tunnin jakso etenee ilman yhtään merkkiä etenemisestä, ja se
    on käyttöliittymä joka näyttää jumiutuneelta.
    """
    module = fake_mlx(monkeypatch)
    _job, progress = handle()
    seen = []
    original = progress.fraction
    monkeypatch.setattr(progress, "fraction", lambda v: (seen.append(v), original(v))[1])

    result = mlx_backend.MlxWhisper().transcribe(np.zeros(16000, np.float32), Options(), progress)
    assert [w.text for w in result.words] == ["sana"]
    assert seen and seen[-1] == 1.0
    # Paikkaus puretaan aina: seuraava kutsu ei saa jäädä edellisen kahvaan.
    assert module.tqdm.tqdm is None


def test_the_patch_is_removed_even_when_transcribing_raises(monkeypatch):
    module = fake_mlx(monkeypatch)

    def boom(kwargs):
        raise ValueError("hajosi")

    sys.modules["mlx_whisper"].transcribe = lambda audio, **kw: boom(kw)
    _job, progress = handle()
    with pytest.raises(ValueError):
        mlx_backend.MlxWhisper().transcribe(np.zeros(10, np.float32), Options(), progress)
    assert module.tqdm.tqdm is None


def test_cancelling_stops_a_file_in_the_middle(monkeypatch):
    fake_mlx(monkeypatch)
    job, progress = handle()
    job.cancel_requested = True
    with pytest.raises(Cancelled):
        mlx_backend.MlxWhisper().transcribe(np.zeros(10, np.float32), Options(), progress)


def test_filler_words_turn_the_suppression_off(monkeypatch):
    """Muistikirjan --suppress_tokens "" --suppress_blank False."""
    seen = {}
    fake_mlx(monkeypatch, on_call=seen.update)
    _job, progress = handle()
    mlx_backend.MlxWhisper().transcribe(np.zeros(10, np.float32), Options(fillers=True), progress)
    assert seen["suppress_tokens"] == [] and seen["suppress_blank"] is False

    seen.clear()
    mlx_backend.MlxWhisper().transcribe(np.zeros(10, np.float32), Options(fillers=False), progress)
    assert "suppress_tokens" not in seen


def test_audio_is_passed_as_samples_not_a_path(monkeypatch):
    """mlx-whisperin oma load_audio kutsuu ffmpegiä PATHista.

    Pakatussa sovelluksessa PATHissa ei ole mitään: binääri on paketin
    sisällä. Polkua antamalla litterointi toimisi kehityskoneella ja
    kaatuisi valmiissa .app-paketissa.
    """
    got = {}
    fake_mlx(monkeypatch, on_call=lambda kw: None)
    original = sys.modules["mlx_whisper"].transcribe
    sys.modules["mlx_whisper"].transcribe = (
        lambda audio, **kw: (got.update(kind=type(audio)), original(audio, **kw))[1]
    )
    _job, progress = handle()
    mlx_backend.MlxWhisper().transcribe(np.zeros(10, np.float32), Options(), progress)
    assert got["kind"] is np.ndarray


def test_missing_engines_report_why_not_how():
    """Asentamaton moottori kertoo mitä puuttuu ja miten se asennetaan."""
    for backend in BACKENDS:
        info = backend.info()
        assert info.key and info.label and info.install
        if not info.available:
            assert info.reason


def test_faster_whisper_maps_the_notebook_switches(monkeypatch):
    """Sama kuin muistikirjan komentorivi, samoilla arvoilla."""
    from podcastmagic.transcribe.backends import faster as faster_backend

    seen = {}

    class FakeModel:
        def transcribe(self, samples, **kwargs):
            seen.update(kwargs)
            info = types.SimpleNamespace(language="fi")
            segment = types.SimpleNamespace(
                id=0, start=0.0, end=0.4, text=" sana",
                words=[types.SimpleNamespace(word=" sana", start=0.0, end=0.4, probability=0.9)],
            )
            return iter([segment]), info

    backend = faster_backend.FasterWhisper()
    monkeypatch.setattr(backend, "_model", lambda name, progress: FakeModel())
    _job, progress = handle()

    result = backend.transcribe(np.zeros(16000, np.float32), Options(fillers=True, vad=True), progress)
    assert [w.text for w in result.words] == ["sana"]
    assert seen["suppress_tokens"] == [] and seen["suppress_blank"] is False
    assert seen["vad_filter"] is True and seen["word_timestamps"] is True

    backend.transcribe(np.zeros(16000, np.float32), Options(fillers=False, vad=False), progress)
    assert seen["suppress_tokens"] == [-1] and seen["suppress_blank"] is True


def test_faster_whisper_progress_is_measured_not_guessed(monkeypatch):
    """Segmentit tulevat generaattorista, joten osuus on mitattu."""
    from podcastmagic.transcribe.backends import faster as faster_backend

    class FakeModel:
        def transcribe(self, samples, **kwargs):
            def segments():
                for end in (2.0, 6.0, 10.0):
                    yield types.SimpleNamespace(id=0, start=0.0, end=end, text="x", words=[])

            return segments(), types.SimpleNamespace(language="fi")

    backend = faster_backend.FasterWhisper()
    monkeypatch.setattr(backend, "_model", lambda name, progress: FakeModel())
    _job, progress = handle()
    seen = []
    monkeypatch.setattr(progress, "fraction", seen.append)
    backend.transcribe(np.zeros(16000 * 10, np.float32), Options(), progress)
    assert seen == [0.2, 0.6, 1.0]
