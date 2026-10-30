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
        return base.BackendInfo(
            key=self.key, label=self.label, available=True, device="testi"
        )

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
            words=base.words_from_segments(raw["segments"]),
            text=raw["text"],
            language="fi",
            raw=raw,
        )


@pytest.fixture
def wired(monkeypatch, session_file):
    """Istunto, jonka äänet ovat olemassa ja jonka moottori on tekaistu."""
    for name in ("olli.wav", "panu.wav"):
        (session_file.parent / name).write_bytes(b"")
    backend = FakeBackend()
    monkeypatch.setattr(runner, "resolve", lambda key: backend)
    monkeypatch.setattr(
        runner.audio_io, "decode", lambda path: np.zeros(16000, np.float32)
    )
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
        "backend",
        "model",
        "language",
        "fillers",
        "vad",
        "initial_prompt",
        "paragraphs",
        "align",
    }


def test_alignment_is_not_in_the_fingerprint_because_it_has_its_own_cache():
    """Kohdistus ei vaihda Whisperin tulosta vaan korjaa sen, joten sen päällekytkentä
    lukee valmiin litteroinnin eikä ajaa mallia uudestaan. Kohdistuksen oma
    välimuisti on nimetty Whisperin tunnisteella ja kohdistuksen versiolla."""
    assert Options(align=True).fingerprint() == Options(align=False).fingerprint()
    assert Options.from_dict({}).align is False
    assert Options.from_dict({"align": True}).align is True


def test_non_whisper_backend_is_part_of_the_transcript_fingerprint():
    whisper = Options(backend="mlx")
    assert whisper.fingerprint() != Options(backend="orukeet").fingerprint()
    assert whisper.fingerprint() != Options(backend="parakeet-ultra").fingerprint()


def test_transcript_cache_path_uses_the_resolved_backend(tmp_path):
    options = Options(backend="auto")
    mlx = runner.cache_path(tmp_path, "/audio/episode.wav", options, backend_key="mlx")
    faster = runner.cache_path(
        tmp_path, "/audio/episode.wav", options, backend_key="faster-whisper"
    )
    assert mlx != faster
    assert mlx.name.startswith("episode.mlx-")
    assert faster.name.startswith("episode.faster-whisper-")


def test_orukeet_requires_word_alignment_before_opening_the_session(monkeypatch):
    from podcastmagic.transcribe.backends.base import BackendInfo

    class OrukeetBackend:
        key = "orukeet"

        def info(self):
            return BackendInfo("orukeet", "Orukeet", True)

    monkeypatch.setattr(runner, "resolve", lambda _key: OrukeetBackend())
    with pytest.raises(RuntimeError, match="lauseajat"):
        runner.run("does-not-exist.nhsx", Options(backend="orukeet"), progress_handle())


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
    assert next(w.text for w in written.file_by_name("olli.wav").words()) == "Terve"


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
    plan = runner.plan(str(session_file))
    assert [i["name"] for i in plan.todo] == []
    assert [i["name"] for i in plan.skipped] == ["olli.wav"]
    assert [i["name"] for i in plan.missing] == ["panu.wav"]


def test_zero_length_words_still_have_a_length():
    words = base.words_from_segments(
        [{"words": [{"word": "hei", "start": 1.0, "end": 1.0}]}]
    )
    assert words[0].length > 0


# --- Kohdistus jälkivaiheena -------------------------------------------------


def available(monkeypatch, aligner):
    """Kohdistin saatavilla ja tekaistu: neuroverkkoa ei ladata."""
    monkeypatch.setattr(
        runner.align,
        "availability",
        lambda: {"available": True, "reason": "", "install": ""},
    )
    monkeypatch.setattr(runner.align, "make_aligner", lambda: aligner)


def shifting_aligner(chunk, words):
    """Sana i alkaa 0,6 + 0,7 * i sekuntia ikkunan alusta; Whisperin sanat ovat 0,5 ja 1,2."""
    return [(0.6 + 0.7 * i, 0.9 + 0.7 * i) for i in range(len(words))]


def panu_words(path):
    return [(w.text, w.start) for w in nhsx.read(path).file_by_name("panu.wav").words()]


def test_run_with_alignment_writes_the_aligned_starts(wired, session_file, monkeypatch):
    available(monkeypatch, shifting_aligner)
    handle = progress_handle()
    result = runner.run(str(session_file), Options(align=True), handle)
    words = panu_words(result["written"])
    assert [t for t, _ in words] == ["yksi", "kaksi"]
    assert words[0][1] == pytest.approx(0.6) and words[1][1] == pytest.approx(1.3)
    assert result["aligned"] == 2
    assert any("kohdistettu 2" in line for line in handle._job.log)


def test_run_without_alignment_never_touches_the_aligner(
    wired, session_file, monkeypatch
):
    monkeypatch.setattr(
        runner.align, "availability", lambda: pytest.fail("asked whether it is available")
    )
    monkeypatch.setattr(
        runner.align, "make_aligner", lambda: pytest.fail("loaded the aligner")
    )
    result = runner.run(str(session_file), Options(), progress_handle())
    assert panu_words(result["written"])[0][1] == pytest.approx(0.5)
    assert result["aligned"] == 0


def test_alignment_requested_but_not_installed_stops_before_transcribing(
    wired, session_file, monkeypatch
):
    monkeypatch.setattr(
        runner.align,
        "availability",
        lambda: {
            "available": False,
            "reason": "puuttuu: torch",
            "install": "uv sync --extra align",
        },
    )
    with pytest.raises(RuntimeError, match="uv sync --extra align"):
        runner.run(str(session_file), Options(align=True), progress_handle())
    assert wired.calls == 0
    assert not runner.output_path(str(session_file)).exists()


def test_turning_alignment_on_reuses_the_whisper_transcript(
    wired, session_file, monkeypatch
):
    runner.run(str(session_file), Options(), progress_handle())
    assert wired.calls == 1
    available(monkeypatch, shifting_aligner)
    result = runner.run(str(session_file), Options(align=True), progress_handle())
    assert wired.calls == 1
    assert panu_words(result["written"])[0][1] == pytest.approx(0.6)


def test_alignment_is_cached_next_to_the_whisper_transcript(
    wired, session_file, monkeypatch
):
    available(monkeypatch, shifting_aligner)
    runner.run(str(session_file), Options(align=True), progress_handle())
    directory = runner.transcripts_dir(str(session_file))
    cached = runner.align.cache_path(
        directory, str(session_file.parent / "panu.wav"), Options()
    )
    assert cached.is_file()
    # Toinen ajo ei lataa kohdistinta: sama tulos tulee välimuistista.
    monkeypatch.setattr(
        runner.align, "make_aligner", lambda: pytest.fail("loaded the aligner")
    )
    result = runner.run(str(session_file), Options(align=True), progress_handle())
    assert panu_words(result["written"])[0][1] == pytest.approx(0.6)


def test_alignment_that_aligned_nothing_is_an_error_and_writes_no_session(
    wired, session_file, monkeypatch
):
    def broken(chunk, words):
        raise RuntimeError("malli kaatui")

    available(monkeypatch, broken)
    with pytest.raises(RuntimeError, match="Kohdistus"):
        runner.run(str(session_file), Options(align=True), progress_handle())
    assert not runner.output_path(str(session_file)).exists()


def test_the_audio_is_decoded_once_per_file_when_it_is_transcribed_and_aligned(
    wired, session_file, monkeypatch
):
    """Tunnin ääni on satoja megatavuja: litterointi ja kohdistus jakavat saman purun."""
    decoded = []

    def decode(path):
        decoded.append(path)
        return np.zeros(16000, np.float32)

    monkeypatch.setattr(runner.audio_io, "decode", decode)
    available(monkeypatch, shifting_aligner)
    runner.run(str(session_file), Options(align=True), progress_handle())
    assert len(decoded) == 1


def test_the_aligner_is_loaded_once_however_many_files_there_are(
    wired, session_file, monkeypatch
):
    loaded = []

    def factory():
        loaded.append(1)
        return shifting_aligner

    monkeypatch.setattr(
        runner.align,
        "availability",
        lambda: {"available": True, "reason": "", "install": ""},
    )
    monkeypatch.setattr(runner.align, "make_aligner", factory)
    # force: molemmat tiedostot (olli ja panu) litteroidaan, joten kohdistettavia on kaksi.
    result = runner.run(
        str(session_file), Options(align=True), progress_handle(), force=True
    )
    assert result["files"] == 2 and loaded == [1]
