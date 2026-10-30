"""Opittu kynnys Colabissa: ``silencelearn``-kirjasto ja tämän skriptin sovitin.

Laskenta on kirjastossa, jonka myös podcast-magic tuo; täällä testataan sovitinta,
joka antaa kirjastolle lxml-puusta sanat ja ffmpeg-tasot. Koska sovittimia on
kaksi (tämä ja podcast-magicin), ``test_the_learned_threshold_matches_podcast_
magics`` ajaa molemmat samalle istunnolle ja äänelle ja vaatii saman luvun.

Ääni annetaan valmiina taulukkona, ei levyltä: testi mittaa laskentaa eikä
ffmpegiä.
"""

from __future__ import annotations

import numpy as np
import pytest
from lxml import etree

import silencelearn
from colabtranscribe.colab import pipeline

RATE = 16000


def word(start: float, length: float = 0.5) -> str:
    return f'<w s="{start:.3f}" l="{length:.3f}" sp="UU">sana</w>'


def session_xml(tracks: str, files: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Name="opittu">
  <AudioPool Path="">{files}</AudioPool>
  <Tracks>{tracks}</Tracks>
</Session>
"""


def file_xml(file_id: int, name: str, words: str) -> str:
    return (f'<File Id="{file_id}" Name="{name}" Path="{name}">'
            f"<Transcription><p>{words}</p></Transcription></File>")


def audio(spans: list[tuple[float, float, float]], seconds: int = 60,
          base: float = 0.001) -> np.ndarray:
    """Taustakohina ``base`` ja päälle annetut jaksot annetulla amplitudilla."""
    out = np.full(RATE * seconds, base, np.float32)
    for start, end, amplitude in spans:
        out[int(start * RATE): int(end * RATE)] = amplitude
    return (out * 32768).astype(np.int16)


MUTED_HEAD = (
    '<Region Ref="{ref}" Start="0.000" Length="10.000" Offset="0.000" Muted="True"/>'
    '<Region Ref="{ref}" Start="10.000" Length="50.000" Offset="10.000"/>'
)

# Vaimennetussa alussa: taustakohina −60 dBFS, vuoto 0,03 (−30,5 dBFS) sekunneilla
# 1–5 eli 40 %, ja yskäisy 0,4 (−8 dBFS) 0,4 s eli 4 %. Sen jälkeen puhetta
# (0,2 = −14 dBFS) ja yksi hiljaisempi sana (0,02 = −34 dBFS) joka on vuotoa.
OLLI_SPEECH = (12.0, 14.0, 20.0, 30.0)
OLLI_AUDIO = audio([
    (1.0, 5.0, 0.03), (7.0, 7.4, 0.4),
    (12.0, 12.5, 0.2), (14.0, 14.5, 0.2), (20.0, 20.5, 0.2), (30.0, 30.5, 0.2),
    (40.0, 40.5, 0.02),
])


def write_session(tmp_path, tracks: str, files: str, name="opittu.nhsx"):
    import re

    path = tmp_path / name
    path.write_text(session_xml(tracks, files), encoding="utf-8")
    # Skripti etsii tiedoston levyltä ennen purkua; sisältö tulee korvatusta purusta.
    for audio_name in re.findall(r'Name="([^"]+\.wav)"', files):
        (tmp_path / audio_name).write_bytes(b"")
    return path


def tree_of(path):
    return etree.parse(str(path))


def olli(tmp_path):
    words = "".join(word(t) for t in OLLI_SPEECH) + word(40.0)
    return write_session(
        tmp_path,
        f'<Track Name="Olli">{MUTED_HEAD.format(ref=1)}</Track>',
        file_xml(1, "olli.wav", words),
    )


def decoding(monkeypatch, by_name: dict[str, np.ndarray]):
    """Korvaa ffmpeg-purun: tiedoston nimi -> valmis taulukko."""
    import os

    monkeypatch.setattr(pipeline, "_decode_pcm16",
                        lambda path: by_name[os.path.basename(path)])


def calibrate(path, monkeypatch, by_name):
    decoding(monkeypatch, by_name)
    return pipeline.calibrate_tree(tree_of(path), [str(path.parent)])


def test_the_threshold_is_the_level_of_the_muted_clips_not_of_the_cough(
        tmp_path, monkeypatch):
    found = calibrate(olli(tmp_path), monkeypatch, {"olli.wav": OLLI_AUDIO})["Olli"]
    assert found.threshold is not None, found.reason
    leak = 20 * np.log10(0.03)
    assert abs(found.threshold - (leak + silencelearn.MARGIN_DB)) < 1.0
    assert found.threshold < 20 * np.log10(0.4) - 15       # ei yskäisyn tasolla
    assert found.muted_seconds == pytest.approx(10.0)


def test_a_track_with_too_little_muted_audio_is_not_calibrated(tmp_path, monkeypatch):
    path = write_session(
        tmp_path,
        '<Track Name="Olli">'
        '<Region Ref="1" Start="0.000" Length="1.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="1.000" Length="59.000" Offset="1.000"/></Track>',
        file_xml(1, "olli.wav", word(20.0)),
    )
    found = calibrate(path, monkeypatch,
                      {"olli.wav": audio([(20.0, 20.5, 0.2)])})["Olli"]
    assert found.threshold is None
    assert found.muted_seconds == pytest.approx(1.0)
    assert "vähän" in found.reason


def test_clips_as_loud_as_the_speech_are_not_a_threshold(tmp_path, monkeypatch):
    """Vahingossa vaimennettu puhe: siitä tehty kynnys vaientaisi kaiken."""
    path = write_session(
        tmp_path,
        f'<Track Name="Olli">{MUTED_HEAD.format(ref=1)}</Track>',
        file_xml(1, "olli.wav", "".join(word(t) for t in OLLI_SPEECH)),
    )
    loud = audio([(0.0, 10.0, 0.2), (12.0, 12.5, 0.2), (14.0, 14.5, 0.2),
                  (20.0, 20.5, 0.2), (30.0, 30.5, 0.2)])
    found = calibrate(path, monkeypatch, {"olli.wav": loud})["Olli"]
    assert found.threshold is None
    assert "puheen" in found.reason


def test_a_word_left_unmuted_is_never_below_the_threshold(tmp_path, monkeypatch):
    """Muokatulla ajalla vaimentamatta jätetty sana on käyttäjän päätös."""
    words = word(12.0) + word(14.0) + word(20.0) + word(24.0)
    path = write_session(
        tmp_path,
        f'<Track Name="Olli">{MUTED_HEAD.format(ref=1)}'
        '<Region Ref="1" Start="60.000" Length="5.000" Offset="60.000" Muted="True"/>'
        "</Track>",
        file_xml(1, "olli.wav", words),
    )
    # Vuoto −24 dBFS vaimennetussa alussa, ja sana 24 s:ssa vain −27 dBFS:ssä.
    samples = audio([(1.0, 9.0, 0.063), (12.0, 12.5, 0.4), (14.0, 14.5, 0.4),
                     (20.0, 20.5, 0.4), (24.0, 24.5, 0.045)], seconds=70)
    found = calibrate(path, monkeypatch, {"olli.wav": samples})["Olli"]
    assert found.threshold is not None, found.reason
    assert found.threshold <= 20 * np.log10(0.045) - silencelearn.KEEP_MARGIN_DB + 0.01
    assert found.clamp_note


def test_leak_from_another_track_raises_the_threshold(tmp_path, monkeypatch):
    """Panun puhuessa Ollin vaimennettu mikki kuulee hänet: harvinainen vuoto
    ei näy koko vaimennetun ajan persentiilissä, mutta kynnyksen pitää estää se."""
    olli_words = "".join(word(t) for t in OLLI_SPEECH)
    panu_words = word(2.0, 1.0) + word(3.5, 1.0) + word(5.5, 1.0) + word(7.5, 1.0)
    path = write_session(
        tmp_path,
        f'<Track Name="Olli">{MUTED_HEAD.format(ref=1)}</Track>'
        f'<Track Name="Panu">{MUTED_HEAD.format(ref=2)}</Track>',
        file_xml(1, "olli.wav", olli_words) + file_xml(2, "panu.wav", panu_words),
    )
    # Ollin mikki: hiljainen pohja, ja vuoto 0,01 (−40 dBFS) vain Panun sanojen
    # aikana. Panun mikki on silloin kovalla.
    olli_audio = audio([(2.0, 3.0, 0.01), (3.5, 4.5, 0.01), (5.5, 6.5, 0.01),
                        (7.5, 8.5, 0.01), *[(t, t + 0.5, 0.2) for t in OLLI_SPEECH]])
    panu_audio = audio([(2.0, 3.0, 0.2), (3.5, 4.5, 0.2), (5.5, 6.5, 0.2),
                        (7.5, 8.5, 0.2)])
    found = calibrate(path, monkeypatch,
                      {"olli.wav": olli_audio, "panu.wav": panu_audio})["Olli"]
    assert found.threshold is not None, found.reason
    assert found.threshold >= 20 * np.log10(0.01) + silencelearn.MARGIN_DB - 0.5


def test_the_learned_threshold_matches_podcast_magics(tmp_path, monkeypatch):
    """Kirjasto on yhteinen, mutta sovittimia on kaksi: sanojen luku, alueiden
    poiminta ja ``dbfs`` ovat kummassakin omansa. Sama istunto, sama ääni, sama
    kynnys molemmista."""
    from podcastmagic import nhsx
    from podcastmagic.silence import calibrate as original
    from podcastmagic.silence.detect import AudioCache

    olli_words = "".join(word(t) for t in OLLI_SPEECH) + word(40.0)
    panu_words = word(2.0, 1.0) + word(3.5, 1.0) + word(12.5, 1.0) + word(20.5, 1.0)
    path = write_session(
        tmp_path,
        f'<Track Name="Olli">{MUTED_HEAD.format(ref=1)}</Track>'
        f'<Track Name="Panu">{MUTED_HEAD.format(ref=2)}</Track>'
        f'<Track Name="Kolmas">{MUTED_HEAD.format(ref=3)}</Track>',
        file_xml(1, "olli.wav", olli_words) + file_xml(2, "panu.wav", panu_words)
        + file_xml(3, "kolmas.wav", word(45.0)),
    )
    def graded(low: float, high: float, spans):
        """Vaimennettu alku nousevana ramppina: persentiili ei saa osua samaan
        lukuun kaikilla arvoilla, tai testi ei huomaisi sen muuttuvan."""
        out = audio(spans).astype(np.float32) / 32768.0
        out[: RATE * 10] = np.linspace(low, high, RATE * 10)
        return (out * 32768).astype(np.int16)

    arrays = {
        "olli.wav": graded(0.002, 0.05, [(t, t + 0.5, 0.2) for t in OLLI_SPEECH]
                           + [(40.0, 40.5, 0.02)]),
        "panu.wav": graded(0.001, 0.03, [(2.0, 3.0, 0.2), (3.5, 4.5, 0.2),
                                         (12.5, 13.5, 0.15), (20.5, 21.5, 0.15)]),
        "kolmas.wav": graded(0.001, 0.01, [(45.0, 45.5, 0.1)]),
    }
    for name in arrays:
        (tmp_path / name).write_bytes(b"")
    monkeypatch.setattr("podcastmagic.silence.detect.audio_io.decode_pcm",
                        lambda p: arrays[p.rsplit("/", 1)[-1]])
    want = original.calibrate(nhsx.read(path), AudioCache())
    got = calibrate(path, monkeypatch, arrays)
    assert set(got) == set(want)
    # Pelkkä «ei opittu» kummallakin olisi tyhjä vertailu.
    assert sum(e.threshold is not None for e in want.values()) >= 2
    for name, expected in want.items():
        if expected.threshold is None:
            assert got[name].threshold is None, name
        else:
            assert got[name].threshold == pytest.approx(expected.threshold, abs=1e-6), name
        assert got[name].muted_seconds == pytest.approx(expected.muted_seconds), name


def test_every_track_is_decoded_once_however_many_tracks_there_are(
        tmp_path, monkeypatch):
    """Kynnys vertaa jokaisen ikkunan kohdalla muita raitoja. Kahden tiedoston
    katto purkaisi kolmella raidalla joka haun uudestaan."""
    tracks, files, arrays = "", "", {}
    for number, name in enumerate(("a", "b", "c", "d"), 1):
        tracks += f'<Track Name="{name}">{MUTED_HEAD.format(ref=number)}</Track>'
        files += file_xml(number, f"{name}.wav", word(20.0 + number))
        arrays[f"{name}.wav"] = audio([(1.0, 8.0, 0.02), (20.0 + number, 20.5 + number, 0.2)])
    path = write_session(tmp_path, tracks, files)
    calls = []

    def counting(file_path):
        import os

        calls.append(os.path.basename(file_path))
        return arrays[os.path.basename(file_path)]

    monkeypatch.setattr(pipeline, "_decode_pcm16", counting)
    pipeline.calibrate_tree(tree_of(path), [str(tmp_path)])
    assert sorted(calls) == ["a.wav", "b.wav", "c.wav", "d.wav"]


# ------------------------------------------------------------------ ajo

def test_a_hand_muted_region_stays_muted_even_where_words_were_heard(
        tmp_path, monkeypatch):
    path = write_session(
        tmp_path,
        f'<Track Name="Olli">{MUTED_HEAD.format(ref=1)}</Track>',
        file_xml(1, "olli.wav", word(3.0) + word(20.0)),
    )
    decoding(monkeypatch, {"olli.wav": audio([(3.0, 3.5, 0.2), (20.0, 20.5, 0.2)])})
    tree = tree_of(path)
    track = next(iter(tree.getroot().iter("Track")))
    intervals = pipeline.get_speech_intervals_for_track(
        tree, track, str(tmp_path), True, -35, learn=True)
    assert [round(a) for a, _b in intervals] == [20]


def test_a_word_below_the_learned_threshold_is_muted_and_speech_survives(
        tmp_path, monkeypatch):
    path = olli(tmp_path)
    decoding(monkeypatch, {"olli.wav": OLLI_AUDIO})
    tree = tree_of(path)
    calibrations = pipeline.calibrate_tree(tree, [str(tmp_path)])
    track = next(iter(tree.getroot().iter("Track")))
    intervals = pipeline.get_speech_intervals_for_track(
        tree, track, str(tmp_path), True, -35,
        learn=True, calibration=calibrations["Olli"], audio_dirs=[str(tmp_path)])
    kept = [round(a) for a, _b in intervals]
    assert 40 not in kept, "vuotosana (−34 dBFS) jäi kuuluviin"
    assert {12, 14, 20, 30} <= set(kept), "puhe vaimeni"


def test_without_learning_the_same_word_is_judged_by_the_fixed_threshold(
        tmp_path, monkeypatch):
    """Sama istunto ilman oppimista: −34 dBFS on kiinteän −35:n yläpuolella ja
    päästetään läpi. Ero edelliseen on se mitä oppiminen tuo."""
    from unittest.mock import MagicMock

    path = olli(tmp_path)
    chunk = MagicMock()
    chunk.dBFS = -34.0
    audio_segment = MagicMock()
    audio_segment.__getitem__.return_value = chunk
    fake = MagicMock()
    fake.AudioSegment.from_file.return_value = audio_segment
    monkeypatch.setitem(__import__("sys").modules, "pydub", fake)
    (tmp_path / "olli.wav").write_bytes(b"")
    tree = tree_of(path)
    track = next(iter(tree.getroot().iter("Track")))
    intervals = pipeline.get_speech_intervals_for_track(
        tree, track, str(tmp_path), True, -35)
    assert 40 in [round(a) for a, _b in intervals]


def test_a_session_nobody_has_muted_anything_in_says_so(tmp_path, monkeypatch):
    path = write_session(
        tmp_path,
        '<Track Name="Olli"><Region Ref="1" Start="0.000" Length="60.000" '
        'Offset="0.000"/></Track>',
        file_xml(1, "olli.wav", word(20.0)),
    )
    decoding(monkeypatch, {"olli.wav": audio([(20.0, 20.5, 0.2)])})
    with pytest.raises(RuntimeError, match="vaimennettua"):
        pipeline.run_auto_silence(str(path), str(tmp_path), True, -35, 0.4, 0.4,
                                  learn=True)
    assert not list(tmp_path.glob("*_processed.nhsx"))


def test_the_run_uses_the_learned_threshold_and_keeps_the_hand_edit(
        tmp_path, monkeypatch):
    path = olli(tmp_path)
    decoding(monkeypatch, {"olli.wav": OLLI_AUDIO})
    written = pipeline.run_auto_silence(str(path), str(tmp_path), True, -35, 0.0, 0.0,
                                        learn=True)
    root = etree.parse(written).getroot()
    regions = [(pipeline.time_to_seconds(r.get("Start")),
                pipeline.time_to_seconds(r.get("Start"))
                + pipeline.time_to_seconds(r.get("Length")),
                r.get("Muted") is not None) for r in root.iter("Region")]
    muted = [(a, b) for a, b, is_muted in regions if is_muted]
    heard = [(a, b) for a, b, is_muted in regions if not is_muted]
    # Käsin vaimennettu alku ja vuotosana (40 s) ovat vaiti.
    assert any(a == pytest.approx(0.0) and b >= 10.0 for a, b in muted)
    assert any(a <= 40.0 and b >= 40.5 for a, b in muted)
    assert any(a <= 12.0 and b >= 12.5 for a, b in heard), "puhe vaimeni"


def test_a_track_without_a_learned_threshold_falls_back_to_the_fixed_one(
        tmp_path, monkeypatch, capsys):
    """Liian vähän vaimennettua ääntä: raita ajetaan tavallisella säännöllä, ja
    siitä kerrotaan lokissa."""
    from unittest.mock import MagicMock

    path = write_session(
        tmp_path,
        '<Track Name="Olli">'
        '<Region Ref="1" Start="0.000" Length="1.000" Offset="0.000" Muted="True"/>'
        '<Region Ref="1" Start="1.000" Length="59.000" Offset="1.000"/></Track>'
        '<Track Name="Panu">' + MUTED_HEAD.format(ref=2) + "</Track>",
        file_xml(1, "olli.wav", word(20.0)) + file_xml(2, "panu.wav", word(20.0)),
    )
    decoding(monkeypatch, {"olli.wav": audio([(20.0, 20.5, 0.2)]),
                           "panu.wav": audio([(1.0, 9.0, 0.02), (20.0, 20.5, 0.2)])})
    chunk = MagicMock()
    chunk.dBFS = -14.0
    segment = MagicMock()
    segment.__getitem__.return_value = chunk
    fake = MagicMock()
    fake.AudioSegment.from_file.return_value = segment
    monkeypatch.setitem(__import__("sys").modules, "pydub", fake)
    (tmp_path / "olli.wav").write_bytes(b"")
    pipeline.run_auto_silence(str(path), str(tmp_path), True, -35, 0.4, 0.4, learn=True)
    out = capsys.readouterr().out
    assert "kynnystä ei opittu" in out


# ------------------------------------------------------------------ esiasetus

def test_the_learned_preset_is_offered_and_turns_the_flags_on():
    from colabtranscribe.options import PRESETS

    assert "learned" in PRESETS


def test_the_script_accepts_the_learned_preset(monkeypatch, tmp_path):
    """``--preset learned`` laittaa RMS:n ja oppimisen päälle, häntä ja tauko 0,4."""
    seen = {}
    monkeypatch.setattr(pipeline, "install_dependencies", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "run_transcription", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "inject_transcriptions_to_nhsx",
                        lambda *a, **k: ["/x/jakso.nhsx"])
    monkeypatch.setattr(pipeline, "write_script", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "run_auto_silence",
                        lambda *args, **kwargs: seen.update(args=args, kwargs=kwargs))
    monkeypatch.setattr(pipeline.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr("sys.argv", ["pipeline.py", "--preset", "learned"])
    pipeline.main()
    _nhsx_path, _audio, rms, _thr, tail, gap = seen["args"]
    assert rms is True and tail == 0.4 and gap == 0.4
    assert seen["kwargs"].get("learn") is True
