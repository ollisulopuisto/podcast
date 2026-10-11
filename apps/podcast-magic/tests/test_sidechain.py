"""Sidechain: kanavien välinen tieto opitaan käsin vaimennetuista alueista.

Kaksi todistetta, kumpikin käyttäjän omasta vaimennuksesta:

* Raita B on vaimennettu samalla hetkellä kun raita A puhuu kovempaa:
  B:n taso silloin on A:n vuotoa, ja B:n ja A:n ero on vuodon ero.
* Raitaa B ei ole vaimennettu vaikka A puhuu: B:n sana on oikeaa puhetta,
  koska puhua voi usealla kanavalla yhtä aikaa, ja sen ero A:han on se mikä
  pitää päästää läpi.

Todisteita kerätään vain siltä ajalta jota käyttäjä on muokannut
(viimeisen vaimennetun alueen loppuun). Sen jälkeen kaikki on vaimentamatta
vain koska kukaan ei ole vielä katsonut.
"""

from __future__ import annotations

import numpy as np
import pytest

from podcastmagic import nhsx
from podcastmagic.silence import calibrate
from podcastmagic.silence.detect import AudioCache, dominant_words, speech_intervals
from podcastmagic.silence.presets import Settings

RATE = 16000


def dbfs(amplitude: float) -> float:
    return 20 * np.log10(amplitude)


def word(start: float, length: float = 0.5) -> str:
    return f'<w s="{start:.3f}" l="{length:.3f}" sp="UU">sana</w>'


def audio(spans: list[tuple[float, float, float]], base: float = 0.001,
          seconds: int = 60) -> np.ndarray:
    out = np.full(RATE * seconds, base, np.float32)
    for start, end, amplitude in spans:
        out[int(start * RATE): int(end * RATE)] = amplitude
    return (out * 32768).astype(np.int16)


def session_xml(olli_words, panu_words) -> str:
    """Olli vaimennettu 0–10, Panu vaimennettu 16–20: muokattu aika on 20 s."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Name="sidechain">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription><p>{"".join(word(t) for t in olli_words)}</p></Transcription>
    </File>
    <File Id="2" Name="panu.wav" Path="panu.wav">
      <Transcription><p>{"".join(word(t) for t in panu_words)}</p></Transcription>
    </File>
  </AudioPool>
  <Tracks>
    <Track Name="Olli">
      <Region Ref="1" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>
      <Region Ref="1" Start="10.000" Length="50.000" Offset="10.000"/>
    </Track>
    <Track Name="Panu">
      <Region Ref="2" Start="0.000" Length="16.000" Offset="0.000"/>
      <Region Ref="2" Start="16.000" Length="4.000" Offset="16.000" Muted="True"/>
      <Region Ref="2" Start="20.000" Length="40.000" Offset="20.000"/>
    </Track>
  </Tracks>
</Session>
"""


def make(tmp_path, monkeypatch, olli_spans, panu_spans, olli_words, panu_words):
    path = tmp_path / "sidechain.nhsx"
    path.write_text(session_xml(olli_words, panu_words), encoding="utf-8")
    (tmp_path / "olli.wav").write_bytes(b"")
    (tmp_path / "panu.wav").write_bytes(b"")
    data = {str(tmp_path / "olli.wav"): audio(olli_spans),
            str(tmp_path / "panu.wav"): audio(panu_spans)}
    monkeypatch.setattr(
        "podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: data[str(p)])
    return path


# Panu puhuu kovaa (0,30 = −10,5 dBFS) Ollin vaimennetulla ajalla. Olli vuotaa
# silloin 0,03:lla (−30,5): vuodon ero 20 dB. Yhtä aikaa puhuessaan Olli on
# 3,5–6 dB Panua hiljaisempi: puheen ero.
PANU = [(2.0, 2.5, 0.30), (3.0, 3.5, 0.30), (4.0, 4.5, 0.30),
        (11.0, 11.5, 0.30), (12.0, 12.5, 0.30), (14.0, 14.5, 0.30), (30.0, 30.5, 0.30),
        (40.0, 40.5, 0.30), (45.0, 45.5, 0.30)]
PANU_WORDS = [s for s, _e, _a in PANU]


@pytest.fixture
def separable(tmp_path, monkeypatch):
    olli = [(2.0, 2.5, 0.03), (3.0, 3.5, 0.03), (4.0, 4.5, 0.03),
            (11.0, 11.5, 0.20), (12.0, 12.5, 0.20), (14.0, 14.5, 0.15),
            (30.0, 30.5, 0.20), (40.0, 40.5, 0.05), (45.0, 45.5, 0.10)]
    return make(tmp_path, monkeypatch, olli, PANU,
                [11.0, 12.0, 14.0, 30.0, 40.0, 45.0], PANU_WORDS)


def test_the_edited_time_ends_at_the_last_muted_region(separable):
    assert calibrate.horizon(nhsx.read(separable)) == pytest.approx(20.0)


def test_the_gap_between_bleed_and_speech_is_learned(separable):
    """Vuodon ero 20 dB, yhtäaikaisen puheen ero ≤ 6 dB: raja on niiden välissä."""
    found = calibrate.calibrate(nhsx.read(separable), AudioCache())["Olli"]
    assert found.dominance is not None, found.reason
    assert 9.0 < found.dominance < 17.0
    assert found.bleed_gap == pytest.approx(20.0, abs=1.0)
    assert found.speech_gap < found.dominance < found.bleed_gap


def test_a_word_that_is_bleed_by_the_learned_gap_is_dropped_and_overlap_survives(separable):
    """Panu 40 s: Olli −26 dBFS (ero 15,6 dB) on vuotoa. Panu 45 s: Olli
    −20 dBFS (ero 9,5 dB) on päällekkäistä puhetta ja jää. Molemmat ovat
    absoluuttisen kynnyksen yläpuolella, joten vain ero ratkaisee."""
    session = nhsx.read(separable)
    cache = AudioCache()
    found = calibrate.calibrate(session, cache)
    settings = Settings(rms=True, learn=True)
    margins = {name: c.dominance for name, c in found.items() if c.dominance is not None}
    keep = dominant_words(session, settings, cache, margins=margins)["Olli"]
    olli_words = [11.0, 12.0, 14.0, 30.0, 40.0, 45.0]
    kept = {t for t, k in zip(olli_words, keep, strict=True) if k}
    assert 40.0 not in kept, "vuoto jäi kuuluviin"
    assert {11.0, 12.0, 14.0, 45.0} <= kept, "päällekkäinen puhe vaimeni"


def test_without_the_learned_gap_the_default_margin_decides(separable):
    """Oletuskaista on 6 dB: 45 s sana (ero 9,5 dB) putoaisi, vaikka käyttäjä
    ei ole sitä vaimentanut. Ero oppimiseen on juuri tämä."""
    session = nhsx.read(separable)
    keep = dominant_words(session, Settings(rms=True), AudioCache())["Olli"]
    olli_words = [11.0, 12.0, 14.0, 30.0, 40.0, 45.0]
    assert 45.0 not in {t for t, k in zip(olli_words, keep, strict=True) if k}


def test_rare_bleed_still_sets_the_threshold(tmp_path, monkeypatch):
    """Vuoto on vain 0,5 s Ollin 10 s vaimennetusta ajasta (alle 10 %), joten
    pelkkä persentiili koko ajasta jää kohinan tasolle (−60 dBFS). Kun toinen
    kanava puhuu ja tämä on vaimennettu, taso on vuotoa, ja se otetaan mukaan."""
    olli = [(2.0, 2.5, 0.03), (12.0, 12.5, 0.20), (30.0, 30.5, 0.20)]
    path = make(tmp_path, monkeypatch, olli, PANU[:1] + PANU[3:],
                [12.0, 30.0], [2.0, 11.0, 12.0, 14.0, 30.0, 40.0, 45.0])
    found = calibrate.calibrate(nhsx.read(path), AudioCache())["Olli"]
    assert found.threshold is not None, found.reason
    assert abs(found.threshold - (dbfs(0.03) + calibrate.MARGIN_DB)) < 1.5
    assert found.threshold > -45


def test_a_quiet_word_the_user_left_unmuted_must_be_kept(tmp_path, monkeypatch):
    """Käyttäjä jätti vaimentamatta sanan jonka taso (−34 dBFS) on vuodon
    (−30,5) alapuolella, joten kynnys ei saa olla sen yläpuolella: päästettävä
    tulee päästää. Kynnys laskee juuri sen alle."""
    olli = [(2.0, 2.5, 0.03), (3.0, 3.5, 0.03), (4.0, 4.5, 0.03),
            (12.0, 12.5, 0.20), (14.0, 14.5, 0.20), (15.0, 15.5, 0.02),
            (30.0, 30.5, 0.20), (50.0, 50.5, 0.20)]
    path = make(tmp_path, monkeypatch, olli, PANU,
                [12.0, 14.0, 15.0, 30.0, 50.0], PANU_WORDS)
    session = nhsx.read(path)
    cache = AudioCache()
    found = calibrate.calibrate(session, cache)["Olli"]
    assert found.threshold is not None, found.reason
    assert found.threshold < dbfs(0.02), "kynnys vaientaisi sanan jonka käyttäjä piti"
    result = speech_intervals(session, session.tracks[0],
                              Settings(rms=True, learn=True, dominance=0.0), cache,
                              calibration=found)
    assert 15 in [round(a) for a, _b in result.intervals]


def test_speech_gaps_wider_than_bleed_gaps_protect_the_speech(tmp_path, monkeypatch):
    """Kun yhtäaikainen puhe on vuotoa kauempana (ero 22 dB) kuin vuoto (20 dB),
    eroa ei voi erottaa: raja asetetaan puheen yläpuolelle, koska liikaa
    vaimennettu on pahempi virhe, ja syy kirjoitetaan."""
    olli = [(2.0, 2.5, 0.03), (3.0, 3.5, 0.03), (4.0, 4.5, 0.03),
            (11.0, 11.5, 0.024), (12.0, 12.5, 0.024), (14.0, 14.5, 0.024),
            (30.0, 30.5, 0.20)]
    path = make(tmp_path, monkeypatch, olli, PANU, [11.0, 12.0, 14.0, 30.0], PANU_WORDS)
    found = calibrate.calibrate(nhsx.read(path), AudioCache())["Olli"]
    assert found.dominance is not None
    assert found.dominance > found.speech_gap
    assert "erotu" in found.gap_note


def test_with_no_other_speaker_there_is_no_gap_to_learn(separable):
    """Panulla ei ole mitään jonka rinnalla mitata (Olli ei puhu hänen
    vaimennetulla ajallaan, ja muokattu aika on lyhyt): eroa ei opita eikä
    se ole virhe."""
    found = calibrate.calibrate(nhsx.read(separable), AudioCache())["Panu"]
    assert found.dominance is None


def test_the_run_drops_bleed_by_the_learned_gap_and_says_so(separable):
    """Koko ajo: vuotosana (Olli 40 s) on vaiti, päällekkäinen puhe (45 s)
    kuuluu, ja lokista näkee opitun ero-rajan."""
    from podcastmagic.jobs import Job, Progress
    from podcastmagic.silence import run as runner

    job = Job(id=0, module="s", label="t")
    settings = Settings(tail=0.0, gap=0.0, rms=True, learn=True)
    result = runner.run(str(separable), settings, Progress(job))
    written = nhsx.read(result["written"])
    olli = next(t for t in written.tracks if t.name == "Olli")

    def audible(second: float) -> bool:
        return any(r.start <= second < r.end and r.elem.get("Muted") is None
                   for r in olli.regions)

    assert not audible(40.2), "vuoto jäi kuuluviin"
    assert audible(45.2), "päällekkäinen puhe vaimeni"
    assert audible(12.2) and audible(30.2)
    assert any("ero-raja" in line for line in job.log)
