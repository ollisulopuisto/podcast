"""Vuoto: kuka on äänessä, kun jokainen mikki kuulee jokaisen puhujan.

Hiljaisessa studiossa hyvillä mikeillä vuoto ei ole hiljaista. Se on
*hiljaisempaa*, ja vain suhteessa siihen mikkiin jonka edessä puhuja on.
Absoluuttinen kynnys ei siksi erota niitä: autoraffkatissa mitattuna
molemmat mikit ylittävät kynnyksen **41 % ajasta**, mutta vuoto on
mediaanissa **12,8 dB** hiljempaa kuin sama puhe omalla mikillä.

Näiden testien äänet ovat kumpikin reilusti kynnyksen yläpuolella. Sana
jonka kynnys päästää läpi molemmilla raidoilla on juuri se tapaus jota
kynnys ei osaa ratkaista.
"""

from __future__ import annotations

import numpy as np
import pytest
from podcastmagic import nhsx
from podcastmagic.silence.detect import AudioCache, dominant_words, speech_intervals
from podcastmagic.silence.presets import PRESETS, Settings

# Molemmilla raidoilla sama litterointi, koska juuri niin vuoto näkyy:
# Whisper kuulee naapurin puheen tästäkin mikistä ja kirjoittaa sen ylös.
SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="vuoto">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription><p>
        <w s="1.000" l="0.500" sp="UU">Terve</w>
        <w s="5.000" l="0.500" sp="UU">samoin</w>
      </p></Transcription>
    </File>
    <File Id="2" Name="panu.wav" Path="panu.wav">
      <Transcription><p>
        <w s="1.000" l="0.500" sp="UU">Terve</w>
        <w s="5.000" l="0.500" sp="UU">samoin</w>
      </p></Transcription>
    </File>
  </AudioPool>
  <Tracks>
    <Track Name="Olli"><Region Ref="1" Start="0.000" Length="10.000" Offset="0.000"/></Track>
    <Track Name="Panu"><Region Ref="2" Start="0.000" Length="10.000" Offset="0.000"/></Track>
  </Tracks>
</Session>
"""

RATE = 16000


def tone(spans: list[tuple[float, float, float]]) -> np.ndarray:
    """Kymmenen sekuntia hiljaisuutta, ja annetut jaksot annetulla tasolla."""
    out = np.zeros(RATE * 10, np.float32)
    for start, end, amplitude in spans:
        out[int(start * RATE) : int(end * RATE)] = amplitude
    return (out * 32768).astype(np.int16)


@pytest.fixture
def bleed_session(tmp_path, monkeypatch):
    """Olli puhuu sekunnissa 1, Panu sekunnissa 5. Molemmat kuuluvat molemmilla.

    0,30 on −10,5 dBFS ja 0,05 on −26 dBFS. Kumpikin on yli oletuskynnyksen
    −35, joten kynnys päästää kaikki neljä sanaa läpi; ero raitojen välillä
    on 15,6 dB eli selvästi yli 6 dB:n dominanssikaistan.
    """
    path = tmp_path / "vuoto.nhsx"
    path.write_text(SESSION, encoding="utf-8")
    for name in ("olli.wav", "panu.wav"):
        (tmp_path / name).write_bytes(b"")

    audio = {
        str(tmp_path / "olli.wav"): tone([(1.0, 1.5, 0.30), (5.0, 5.5, 0.05)]),
        str(tmp_path / "panu.wav"): tone([(1.0, 1.5, 0.05), (5.0, 5.5, 0.30)]),
    }
    monkeypatch.setattr(
        "podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: audio[str(p)]
    )
    return path


def test_the_threshold_alone_cannot_tell_bleed_from_speech(bleed_session):
    """Lähtökohta: kynnys päästää kaikki neljä sanaa läpi molemmilla raidoilla.

    Tämä ei ole toive vaan mittaus siitä mitä kynnys tekee. Jos tämä testi
    alkaa kaatua, kynnys on muuttunut eikä vuototesti alla enää mittaa sitä
    mitä se väittää mittaavansa.
    """
    session = nhsx.read(bleed_session)
    cache = AudioCache()
    for track in session.tracks:
        result = speech_intervals(session, track, Settings(rms=True), cache)
        assert result.words_seen == 2
        assert result.words_quiet == 0, "kynnys ei erota vuotoa — se on koko ongelma"


def test_the_loudest_microphone_keeps_the_word(bleed_session):
    """Kovin voittaa: sana jää sille raidalle jolla se on kovimmillaan."""
    session = nhsx.read(bleed_session)
    keep = dominant_words(session, Settings(rms=True), AudioCache())
    # Olli: oma puhe sekunnissa 1, vuotoa sekunnissa 5.
    assert list(keep["Olli"]) == [True, False]
    assert list(keep["Panu"]) == [False, True]


def test_bleed_is_dropped_and_own_speech_survives(bleed_session):
    """Ajon läpi: kummallekin raidalle jää vain oma puheenvuoro."""
    session = nhsx.read(bleed_session)
    cache = AudioCache()
    keep = dominant_words(session, Settings(rms=True), cache)
    for track in session.tracks:
        result = speech_intervals(
            session, track, Settings(rms=True), cache, dominance=keep[track.name]
        )
        assert result.words_seen == 2
        assert result.words_bled == 1
        assert len(result.intervals) == 1
    # Ja jäljelle jäävät jaksot ovat eri kohdissa: kumpikin omansa.
    olli = speech_intervals(
        session, session.tracks[0], Settings(rms=True), cache, dominance=keep["Olli"]
    )
    panu = speech_intervals(
        session, session.tracks[1], Settings(rms=True), cache, dominance=keep["Panu"]
    )
    assert round(olli.intervals[0][0]) == 1
    assert round(panu.intervals[0][0]) == 5


def test_real_overlap_inside_the_band_keeps_both(tmp_path, monkeypatch):
    """Kaista on olemassa juuri tätä varten: päällekkäinen puhe ei ole vuotoa.

    Kova sääntö «vain yksi kerrallaan» leikkaisi keskeytykset ja naurut,
    jotka ovat se mikä saa keskustelun kuulostamaan keskustelulta. 12,8 dB:n
    mitatusta erosta jää 6 dB:n kaistan jälkeen ~6,8 dB pelivaraa.
    """
    path = tmp_path / "vuoto.nhsx"
    path.write_text(SESSION, encoding="utf-8")
    for name in ("olli.wav", "panu.wav"):
        (tmp_path / name).write_bytes(b"")
    # 0,30 ja 0,20 ovat 3,5 dB:n päässä toisistaan — kaistan sisällä.
    audio = {
        str(tmp_path / "olli.wav"): tone([(1.0, 1.5, 0.30), (5.0, 5.5, 0.05)]),
        str(tmp_path / "panu.wav"): tone([(1.0, 1.5, 0.20), (5.0, 5.5, 0.30)]),
    }
    monkeypatch.setattr(
        "podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: audio[str(p)]
    )
    session = nhsx.read(path)
    keep = dominant_words(session, Settings(rms=True), AudioCache())
    assert list(keep["Olli"]) == [True, False]
    assert list(keep["Panu"]) == [True, True], "päällekkäinen puhe ei ole vuotoa"


def test_one_microphone_cannot_bleed_onto_itself(session_file):
    """Yhdellä raidalla ei ole mihin verrata, eikä sääntö saa keksiä mitään."""
    session = nhsx.read(session_file)
    one = [t for t in session.tracks if t.name == "Olli"]
    session.tracks = one
    assert dominant_words(session, Settings(rms=True), AudioCache()) == {}


def test_the_rule_is_off_unless_asked(bleed_session):
    """``dominance=0`` on pois päältä, ei nollan desibelin kaista.

    Nollan desibelin kaista olisi «vain tasan kovin», mikä leikkaisi kaiken
    päällekkäisen puheen. Se on eri asia kuin sääntö pois päältä.
    """
    session = nhsx.read(bleed_session)
    assert dominant_words(session, Settings(rms=True, dominance=0.0), AudioCache()) == {}


def test_missing_audio_keeps_every_word(tmp_path, monkeypatch):
    """Kun kenelläkään ei ole ääntä, vertailua ei ole eikä sanoja pudoteta.

    ``-inf`` on kovin vain siksi ettei kovempaa ole. Ilman tätä ehtoa
    ``level >= loudest - kaista`` olisi tosi kaikilla ja sattumalta oikein,
    mutta yhden raidan puuttuva tiedosto tekisi siitä epätoden: raita jolta
    ääni löytyy voittaisi, ja raita jolta ei löydy vaikenisi kokonaan.
    Liikaa vaimennettu jakso on pahempi virhe kuin liian vähän vaimennettu.
    """
    path = tmp_path / "vuoto.nhsx"
    path.write_text(SESSION, encoding="utf-8")
    for name in ("olli.wav", "panu.wav"):
        (tmp_path / name).write_bytes(b"")
    # Vain Ollin ääni on luettavissa; Panun tiedosto ei aukea.
    only_olli = tone([(1.0, 1.5, 0.30), (5.0, 5.5, 0.30)])

    def decode(p):
        if str(p).endswith("olli.wav"):
            return only_olli
        raise OSError("ei aukea")

    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm", decode)
    session = nhsx.read(path)
    keep = dominant_words(session, Settings(rms=True), AudioCache())
    assert list(keep["Panu"]) == [True, True], "ääntä ei ole, joten ei ole näyttöä vuodosta"


def test_the_run_writes_a_session_with_the_bleed_muted(bleed_session):
    """Koko ajo läpi: vuoto on vaiennettu tiedostossa, ei vain laskurissa.

    Sääntö voi olla oikein ja jäädä silti kytkemättä ajoon. Silloin loki
    kertoo vuodosta ja tiedostossa on kaikki auki.
    """
    from podcastmagic.jobs import Job, Progress
    from podcastmagic.silence import run as runner

    job = Job(id=0, module="silence", label="testi")
    result = runner.run(str(bleed_session), PRESETS["bleed"], Progress(job))

    assert [row["bled"] for row in result["tracks"]] == [1, 1]
    assert "Vuotovertailu päällä" in "\n".join(job.log)

    written = nhsx.read(result["written"])
    # Kummallakin raidalla yksi kuuluva pala, ja se on eri kohdassa.
    audible = {
        track.name: [r for r in track.regions if r.elem.get("Muted") is None]
        for track in written.tracks
    }
    assert len(audible["Olli"]) == 1
    assert len(audible["Panu"]) == 1
    assert audible["Olli"][0].start < audible["Panu"][0].start


def test_without_the_comparison_the_bleed_stays_audible(bleed_session):
    """Vertailu pois: sama istunto, ja molemmat raidat auki molemmissa kohdissa.

    Tämä on se lopputulos jonka pelkkä kynnys antaa — ja syy siihen että
    vertailu on olemassa.
    """
    from podcastmagic.jobs import Job, Progress
    from podcastmagic.silence import run as runner

    settings = Settings(tail=0.4, gap=0.4, rms=True, threshold=-35.0, dominance=0.0)
    result = runner.run(
        str(bleed_session), settings, Progress(Job(id=0, module="s", label="t"))
    )
    assert [row["bled"] for row in result["tracks"]] == [0, 0]
    written = nhsx.read(result["written"])
    for track in written.tracks:
        audible = [r for r in track.regions if r.elem.get("Muted") is None]
        assert len(audible) == 2, "kynnys jättää vuodon kuuluviin"


def test_settings_saved_before_this_change_still_match_their_preset():
    """Vanha tallennettu asetus ei saa muuttua «omaksi» uuden kentän takia.

    Levyllä olevassa asetuksessa ei ole `dominance`-kenttää lainkaan, joten
    `from_dict` antaa sille oletuksen. Jos oletus eroaa esivalinnan arvosta,
    esivalinta lakkaa täsmäämästä ja käyttöliittymä näyttää «oma» — mitään
    ei ole muuttunut paitsi se mitä ruudulla lukee, ja juuri sellaista
    hiljaista valhetta vastaan tämä repositorio on kirjoitettu.
    """
    saved = {
        "remote": {"tail": 1.0, "gap": 1.0, "rms": False, "threshold": -35.0},
        "bleed": {"tail": 0.4, "gap": 0.4, "rms": True, "threshold": -35.0},
    }
    for name, raw in saved.items():
        settings = Settings.from_dict(raw)
        preset = PRESETS[name]
        assert settings.dominance == preset.dominance, (
            f"«{name}» ei enää täsmää: tallennettu {settings.dominance}, "
            f"esivalinta {preset.dominance}"
        )
