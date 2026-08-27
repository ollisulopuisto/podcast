"""Litterointi: asetukset, moottorivalinta ja ajon kulku ilman Whisperiä."""

from __future__ import annotations

import numpy as np
import pytest

from podcastmagic import nhsx
from podcastmagic.jobs import Job, Progress
from podcastmagic.transcribe import run as runner
from podcastmagic.transcribe.backends import base, resolve
from podcastmagic.transcribe.models import model_choice
from podcastmagic.transcribe.options import Options


class FakeBackend(base.Backend):
    """Moottori, joka palauttaa kaksi sanaa ja laskee kutsut."""

    key = "fake"
    label = "fake"

    def __init__(self):
        self.calls = 0

    def info(self):
        return base.BackendInfo(key=self.key, label=self.label, available=True, device="testi")

    def transcribe(self, samples, options, progress):
        self.calls += 1
        raw = {
            "text": " yksi kaksi",
            "language": "fi",
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": " yksi kaksi",
                    "words": [
                        {"word": " yksi", "start": 0.5, "end": 0.9},
                        {"word": " kaksi", "start": 1.2, "end": 1.6},
                    ],
                }
            ],
        }
        return base.TranscriptResult(
            words=base.words_from_segments(raw["segments"]), text=raw["text"],
            language="fi", raw=raw,
        )


@pytest.fixture
def wired(monkeypatch, session_file):
    """Istunto, jonka äänet ovat olemassa ja jonka moottori on tekaistu."""
    for name in ("olli.wav", "panu.wav"):
        (session_file.parent / name).write_bytes(b"")
    backend = FakeBackend()
    monkeypatch.setattr(runner, "resolve", lambda key: backend)
    monkeypatch.setattr(runner.audio_io, "decode", lambda path: np.zeros(16000, np.float32))
    return backend


def progress_handle():
    """Kahva ilman työjonoa: testi ajaa työn itse, ei taustasäikeessä."""
    return Progress(Job(id=0, module="testi", label="testi"))


def test_options_keep_an_empty_language_as_automatic():
    assert Options.from_dict({"language": ""}).language == ""
    assert Options.from_dict({}).language == "fi"


def test_fingerprint_separates_models_and_switches():
    a = Options(model="turbo", fillers=True)
    assert a.fingerprint() != Options(model="large-v3", fillers=True).fingerprint()
    assert a.fingerprint() != Options(model="turbo", fillers=False).fingerprint()
    assert a.fingerprint() != Options(model="turbo", vad=False).fingerprint()


def test_fingerprint_fields_are_written_out_by_hand():
    """Uusi asetus ei saa livahtaa tunnisteeseen tai siitä pois huomaamatta.

    Tunniste ratkaisee milloin valmis litterointi luetaan levyltä ja milloin
    ajetaan uudestaan. Jos kenttä lisätään ``Options``iin ja unohdetaan
    tästä, mallin vaihtaminen palauttaa vanhan tuloksen eikä siitä sanota
    mitään — se on juuri se hiljainen väärä tulos jota vastaan tämä on.
    """
    assert set(Options.__dataclass_fields__) == {
        "backend", "model", "language", "fillers", "vad", "initial_prompt",
    }


def test_unknown_model_passes_through_to_both_engines():
    choice = model_choice("mlx-community/whisper-large-v3-turbo-q4")
    assert choice.mlx == choice.faster == "mlx-community/whisper-large-v3-turbo-q4"


def test_resolve_refuses_an_engine_that_is_not_installed():
    with pytest.raises(RuntimeError):
        resolve("ei-tällaista")


def test_run_writes_words_into_the_session(wired, session_file):
    result = runner.run(str(session_file), Options(), progress_handle())
    written = nhsx.read(result["written"])
    # olli.wav oli jo litteroitu, panu.wav ei — vain jälkimmäinen ajettiin.
    assert wired.calls == 1
    assert [w.text for w in written.file_by_name("panu.wav").words()] == ["yksi", "kaksi"]
    assert [w.text for w in written.file_by_name("olli.wav").words()][0] == "Terve"


def test_run_never_touches_the_source(wired, session_file):
    before = session_file.read_text(encoding="utf-8")
    runner.run(str(session_file), Options(), progress_handle())
    assert session_file.read_text(encoding="utf-8") == before


def test_force_transcribes_everything_again(wired, session_file):
    runner.run(str(session_file), Options(), progress_handle(), force=True)
    assert wired.calls == 2


def test_a_finished_transcription_is_read_from_disk(wired, session_file):
    runner.run(str(session_file), Options(), progress_handle())
    assert wired.calls == 1
    cache = runner.transcripts_dir(str(session_file))
    assert list(cache.glob("panu.*.json"))
    # Toinen ajo lukee JSONin eikä kutsu moottoria — mutta kirjoittaa silti
    # sanat istuntoon, koska lähde on aina alkuperäinen istunto.
    result = runner.run(str(session_file), Options(), progress_handle(), force=False)
    assert wired.calls == 1
    assert nhsx.read(result["written"]).file_by_name("panu.wav").transcribed


def test_a_new_model_does_not_reuse_the_old_transcription(wired, session_file):
    runner.run(str(session_file), Options(model="turbo"), progress_handle())
    runner.run(str(session_file), Options(model="large-v3"), progress_handle())
    assert wired.calls == 2


def test_plan_says_what_will_happen(session_file):
    (session_file.parent / "olli.wav").write_bytes(b"")
    plan = runner.plan(str(session_file), Options())
    assert [i["name"] for i in plan.todo] == []
    assert [i["name"] for i in plan.skipped] == ["olli.wav"]
    assert [i["name"] for i in plan.missing] == ["panu.wav"]


def test_zero_length_words_still_have_a_length():
    words = base.words_from_segments(
        [{"words": [{"word": "hei", "start": 1.0, "end": 1.0}]}]
    )
    assert words[0].length > 0
