"""Kynnys opitaan käsin vaimennetuista alueista.

Käyttäjä muokkaa istunnon alkua Hindenburgissa ja vaimentaa kohdat joissa
kukaan ei puhu. Niiden taso on kynnys: sen alle jäävä sana ei ole puhetta.
Alueissa on myös yskäisyjä ja muuta, eikä niitä saa ottaa kynnykseksi.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from podcastmagic import nhsx
from podcastmagic.silence import calibrate
from podcastmagic.silence.detect import AudioCache, speech_intervals
from podcastmagic.silence.presets import PRESETS, Settings

RATE = 16000


def dbfs(amplitude: float) -> float:
    return 20 * np.log10(amplitude)


def session_xml(regions: str, words: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Name="opittu">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription><p>{words}</p></Transcription>
    </File>
  </AudioPool>
  <Tracks><Track Name="Olli">{regions}</Track></Tracks>
</Session>
"""


def word(start: float, length: float = 0.5) -> str:
    return f'<w s="{start:.3f}" l="{length:.3f}" sp="UU">sana</w>'


def audio(spans: list[tuple[float, float, float]], seconds: int = 60,
          base: float = 0.001) -> np.ndarray:
    """Taustakohina ``base`` ja päälle annetut jaksot annetulla amplitudilla."""
    out = np.full(RATE * seconds, base, np.float32)
    for start, end, amplitude in spans:
        out[int(start * RATE): int(end * RATE)] = amplitude
    return (out * 32768).astype(np.int16)


@pytest.fixture
def edited(tmp_path, monkeypatch):
    """Istunto jonka alun 10 s käyttäjä on vaimentanut.

    Vaimennetussa alueessa: taustakohina −60 dBFS, vuoto 0,03 (−30,5 dBFS)
    sekunneilla 1–5 eli 40 % alueesta, ja yskäisy 0,4 (−8 dBFS) 0,4 s eli
    4 %. Alueen jälkeen puhetta (0,2 = −14 dBFS) ja yksi hiljaisempi sana
    (0,02 = −34 dBFS) joka on vuotoa, ei puhetta.
    """
    words = "".join(word(t) for t in (12.0, 14.0, 20.0, 30.0)) + word(40.0)
    path = tmp_path / "opittu.nhsx"
    path.write_text(session_xml(
        '<Region Ref="1" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="10.000" Length="50.000" Offset="10.000"/>',
        words,
    ), encoding="utf-8")
    (tmp_path / "olli.wav").write_bytes(b"")
    samples = audio([
        (1.0, 5.0, 0.03), (7.0, 7.4, 0.4),
        (12.0, 12.5, 0.2), (14.0, 14.5, 0.2), (20.0, 20.5, 0.2), (30.0, 30.5, 0.2),
        (40.0, 40.5, 0.02),
    ])
    monkeypatch.setattr(
        "podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: samples
    )
    return path


def test_the_threshold_is_the_level_of_the_muted_clips_not_of_the_cough(edited):
    """Vaimennetun alueen tyypillinen taso on vuoto (−30,5 dBFS). Yskäisy on
    4 % alueesta, ja kynnys joka seuraisi sitä olisi −8 dBFS ja vaientaisi
    puheen."""
    session = nhsx.read(edited)
    found = calibrate.calibrate(session, AudioCache())["Olli"]
    assert found.threshold is not None, found.reason
    assert abs(found.threshold - (dbfs(0.03) + calibrate.MARGIN_DB)) < 1.0
    assert found.threshold < dbfs(0.4) - 15          # ei yskäisyn tasolla
    assert found.muted_seconds == pytest.approx(10.0)


def test_a_word_below_the_learned_threshold_is_muted_and_speech_survives(edited):
    session = nhsx.read(edited)
    settings = Settings(rms=True, learn=True, dominance=0.0)
    cache = AudioCache()
    found = calibrate.calibrate(session, cache)
    result = speech_intervals(session, session.tracks[0], settings, cache,
                              calibration=found["Olli"])
    kept = [round(a) for a, _b in result.intervals]
    assert 40 not in kept, "vuotosana (−34 dBFS) jäi kuuluviin"
    assert {12, 14, 20, 30} <= set(kept), "puhe vaimeni"
    assert result.words_quiet == 1


def test_without_learning_the_same_word_passes(edited):
    """Sama istunto ilman oppimista: pohja + 12 dB on −42, ja −34 päästetään
    läpi. Ero edelliseen on se mitä oppiminen tuo."""
    session = nhsx.read(edited)
    result = speech_intervals(session, session.tracks[0],
                              Settings(rms=True, dominance=0.0), AudioCache())
    assert 40 in [round(a) for a, _b in result.intervals]


def test_every_file_is_decoded_once_however_many_tracks_there_are(tmp_path, monkeypatch):
    """Kynnys vertaa jokaisen ikkunan kohdalla myös muita raitoja. Välimuistin
    kahden tiedoston katto purkaisi kolmella raidalla joka haun uudestaan:
    neljä tiedostoa kiertää kahden paikan läpi eikä yksikään osu.

    Raita ``a`` vaimennettu alku, muut puhuvat sen aikana vaimentamattomina."""
    regions = {
        "a": ('<Region Ref="1" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>'
              '<Region Ref="1" Start="10.000" Length="50.000" Offset="10.000"/>'),
    }
    for number, name in enumerate(("b", "c", "d"), 2):
        regions[name] = f'<Region Ref="{number}" Start="0.000" Length="60.000" Offset="0.000"/>'
    tracks, files, arrays = "", "", {}
    for number, name in enumerate(("a", "b", "c", "d"), 1):
        tracks += f'<Track Name="{name}">{regions[name]}</Track>'
        words = word(2.0, 1.0) + word(5.0, 1.0) + word(20.0 + number)
        files += (f'<File Id="{number}" Name="{name}.wav" Path="{name}.wav">'
                  f"<Transcription><p>{words}</p></Transcription></File>")
        arrays[f"{name}.wav"] = audio([(1.0, 8.0, 0.02), (2.0, 3.0, 0.2), (5.0, 6.0, 0.2)])
        (tmp_path / f"{name}.wav").write_bytes(b"")
    path = tmp_path / "monta.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Name="monta"><AudioPool Path="">{files}</AudioPool><Tracks>{tracks}</Tracks></Session>""",
                    encoding="utf-8")
    calls = []

    def counting(file_path):
        name = Path(file_path).name
        calls.append(name)
        return arrays[name]

    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm", counting)
    calibrate.calibrate(nhsx.read(path), AudioCache())
    assert sorted(calls) == ["a.wav", "b.wav", "c.wav", "d.wav"], calls


def test_a_hand_muted_region_stays_muted_even_where_words_were_heard(tmp_path, monkeypatch):
    """Käyttäjän oma vaimennus on tosi: sanat sen sisällä eivät avaa sitä."""
    path = tmp_path / "kasin.nhsx"
    path.write_text(session_xml(
        '<Region Ref="1" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="10.000" Length="50.000" Offset="10.000"/>',
        word(3.0) + word(20.0),
    ), encoding="utf-8")
    (tmp_path / "olli.wav").write_bytes(b"")
    samples = audio([(3.0, 3.5, 0.2), (20.0, 20.5, 0.2)])
    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: samples)
    session = nhsx.read(path)
    result = speech_intervals(session, session.tracks[0],
                              Settings(rms=True, learn=True, dominance=0.0), AudioCache())
    assert [round(a) for a, _b in result.intervals] == [20]
    assert result.words_hand_muted == 1


def test_clips_as_loud_as_the_speech_are_not_a_threshold(tmp_path, monkeypatch):
    """Käyttäjä vaimensi vahingossa puhetta: taso on puheen tasolla, ja siitä
    tehty kynnys vaientaisi kaiken. Silloin ei opita mitään ja sanotaan miksi."""
    path = tmp_path / "vaara.nhsx"
    path.write_text(session_xml(
        '<Region Ref="1" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="10.000" Length="50.000" Offset="10.000"/>',
        "".join(word(t) for t in (12.0, 14.0, 20.0, 30.0)),
    ), encoding="utf-8")
    (tmp_path / "olli.wav").write_bytes(b"")
    samples = audio([(0.0, 10.0, 0.2), (12.0, 12.5, 0.2), (14.0, 14.5, 0.2),
                     (20.0, 20.5, 0.2), (30.0, 30.5, 0.2)])
    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: samples)
    found = calibrate.calibrate(nhsx.read(path), AudioCache())["Olli"]
    assert found.threshold is None
    assert "puheen" in found.reason


def test_a_track_with_too_little_muted_audio_is_not_calibrated(tmp_path, monkeypatch):
    path = tmp_path / "lyhyt.nhsx"
    path.write_text(session_xml(
        '<Region Ref="1" Start="0.000" Length="1.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="1.000" Length="59.000" Offset="1.000"/>',
        word(20.0),
    ), encoding="utf-8")
    (tmp_path / "olli.wav").write_bytes(b"")
    samples = audio([(20.0, 20.5, 0.2)])
    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: samples)
    found = calibrate.calibrate(nhsx.read(path), AudioCache())["Olli"]
    assert found.threshold is None and found.muted_seconds == pytest.approx(1.0)
    assert "vähän" in found.reason


def test_a_session_nobody_has_muted_anything_in_says_so(tmp_path, monkeypatch):
    from podcastmagic.jobs import Job, Progress
    from podcastmagic.silence import run as runner

    path = tmp_path / "puhdas.nhsx"
    path.write_text(session_xml(
        '<Region Ref="1" Start="0.000" Length="60.000" Offset="0.000"/>', word(20.0)),
        encoding="utf-8")
    (tmp_path / "olli.wav").write_bytes(b"")
    samples = audio([(20.0, 20.5, 0.2)])
    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: samples)
    with pytest.raises(RuntimeError, match="vaimennettua"):
        runner.run(str(path), PRESETS["learned"],
                   Progress(Job(id=0, module="s", label="t")))
    assert not list(tmp_path.glob("* vaimennettu*"))


def test_the_run_uses_the_learned_threshold_and_keeps_the_hand_edit(edited):
    from podcastmagic.jobs import Job, Progress
    from podcastmagic.silence import run as runner

    settings = Settings(tail=0.0, gap=0.0, rms=True, learn=True, dominance=0.0)
    result = runner.run(str(edited), settings, Progress(Job(id=0, module="s", label="t")))
    written = nhsx.read(result["written"])
    muted = [(r.start, r.end) for r in written.tracks[0].regions
             if r.elem.get("Muted") is not None]
    # Käsin vaimennettu alku ja vuotosana (40 s) ovat vaiti.
    assert any(a == pytest.approx(0.0) and b >= 10.0 for a, b in muted)
    assert any(a <= 40.0 and b >= 40.5 for a, b in muted)
    heard = [(r.start, r.end) for r in written.tracks[0].regions
             if r.elem.get("Muted") is None]
    assert any(a <= 12.0 and b >= 12.5 for a, b in heard), "puhe vaimeni"


def test_the_learned_preset_and_old_settings():
    """``learn`` on uusi kenttä: levylle tallennetussa asetuksessa sitä ei ole,
    ja sen pitää tarkoittaa pois — muuten vanha «bleed» ei enää täsmäisi."""
    assert PRESETS["learned"].learn is True and PRESETS["learned"].rms is True
    assert PRESETS["bleed"].learn is False and PRESETS["remote"].learn is False
    old = Settings.from_dict({"tail": 0.4, "gap": 0.4, "rms": True})
    assert old.learn is False


def _setup(tmp_path, monkeypatch, regions, words, spans, seconds=70):
    path = tmp_path / "s.nhsx"
    path.write_text(session_xml(regions, words), encoding="utf-8")
    (tmp_path / "olli.wav").write_bytes(b"")
    samples = audio(spans, seconds=seconds)
    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm", lambda p: samples)
    return nhsx.read(path)


def test_speech_level_is_taken_from_words_the_user_left_unmuted(tmp_path, monkeypatch):
    """Käyttäjän muokkaama aika kertoo mikä on puhetta: sen vaimentamatta
    jättämät sanat. Muokatun ajan jälkeen litteroidut sanat voivat olla
    kanavan kohinaa (Perttu, 07 uutiset: sanat 1.–3. minuutilla −49 dBFS,
    puhe −25…−31), eivätkä ne saa laskea 'puheen tasoa' kohinan tasolle ja
    saada oikeaa kynnystä hylätyksi."""
    regions = (
        '<Region Ref="1" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="10.000" Length="10.000" Offset="10.000"/>'
        '<Region Ref="1" Start="20.000" Length="5.000" Offset="20.000" Muted="True"/>'
        '<Region Ref="1" Start="25.000" Length="45.000" Offset="25.000"/>'
    )
    vetted = [12.0, 14.0, 16.0]
    noise = [26.0 + 1.2 * i for i in range(30)]          # kohinaa, -60 dBFS
    session = _setup(tmp_path, monkeypatch, regions,
                     "".join(word(t) for t in vetted + noise),
                     [(1.0, 5.0, 0.03)] + [(t, t + 0.5, 0.2) for t in vetted])
    found = calibrate.calibrate(session, AudioCache())["Olli"]
    assert found.threshold is not None, found.reason
    assert found.speech_level == pytest.approx(dbfs(0.2), abs=0.5)


def test_without_vetted_words_the_speech_level_is_not_the_quiet_end(tmp_path, monkeypatch):
    """Ei yhtään vaimentamatta jätettyä sanaa muokatulla ajalla: puhetaso
    mitataan litteroiduista sanoista, mutta niiden hiljaisin neljännes on
    usein kohinaa. 15 kohinasanaa + 25 puhesanaa: p25 olisi −60 dBFS."""
    regions = (
        '<Region Ref="1" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="10.000" Length="60.000" Offset="10.000"/>'
    )
    starts = [12.0 + 1.4 * i for i in range(40)]
    loud = starts[15:]
    session = _setup(tmp_path, monkeypatch, regions,
                     "".join(word(t) for t in starts),
                     [(1.0, 5.0, 0.03)] + [(t, t + 0.5, 0.2) for t in loud])
    found = calibrate.calibrate(session, AudioCache())["Olli"]
    assert found.threshold is not None, found.reason


def test_a_turn_cut_into_many_pieces_is_one_block(tmp_path, monkeypatch):
    """Yksi puheenvuoro voi olla pätkitty moneen alueeseen. 125 palaa à
    0,08 s on alle ikkunan (ja alle 0,1 s), joten kukin pala yksin ei anna
    yhtään mittausta; yhtenä lohkona ne ovat 10 s."""
    pieces = "".join(
        f'<Region Ref="1" Start="{i * 0.08:.3f}" Length="0.080" '
        f'Offset="{i * 0.08:.3f}" Muted="True"/>' for i in range(125))
    regions = pieces + '<Region Ref="1" Start="10.000" Length="50.000" Offset="10.000"/>'
    session = _setup(tmp_path, monkeypatch, regions,
                     "".join(word(t) for t in (12.0, 14.0, 20.0, 30.0)),
                     [(1.0, 5.0, 0.03)] + [(t, t + 0.5, 0.2) for t in (12.0, 14.0, 20.0, 30.0)])
    found = calibrate.calibrate(session, AudioCache())["Olli"]
    assert found.threshold is not None, found.reason
    assert found.muted_seconds == pytest.approx(10.0)
    assert found.frames > 30
