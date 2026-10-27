"""Pipeline skriptin yksikkötestit — testataan erillisinä funktioina.

Huom: pipeline.py on Colabissa ajettava resurssi, mutta sen funktiot
ovat testattavissa erillään ilman Colabia.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from colabtranscribe.colab.pipeline import (
    merge_intervals_with_gap,
    run_transcription,
    seconds_to_time,
    time_to_seconds,
)


def test_install_dependencies_uses_photon_for_parakeet_ultra(monkeypatch):
    from colabtranscribe.colab import pipeline

    calls = []
    monkeypatch.setattr(pipeline.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))
    monkeypatch.setattr(pipeline, "configure_cuda_libs", lambda: None)

    pipeline.install_dependencies()

    pip = next(cmd for cmd in calls if cmd[:2] == ["pip", "install"])
    assert "moondream==2.4.1" in pip
    assert not any("nemo" in package.lower() for package in pip)


def test_transcribe_file_uses_photon_ultra_word_timestamps(monkeypatch, tmp_path):
    import sys
    import types

    from colabtranscribe.colab import pipeline

    seen = []

    class FakeModel:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def transcribe(self, **kwargs):
            seen.append(kwargs)
            return {
                "text": "Öö, tämä toimii.",
                "language": None,
                "segments": [{
                    "start": 0.1,
                    "end": 1.5,
                    "text": "Öö, tämä toimii.",
                    "words": [
                        {"word": "Öö,", "start": 0.1, "end": 0.5},
                        {"word": "tämä", "start": 0.6, "end": 0.9},
                        {"word": "toimii.", "start": 1.0, "end": 1.5},
                    ],
                }],
            }

    def photon(model_id, **kwargs):
        seen.append({"model_id": model_id, **kwargs})
        return FakeModel()

    monkeypatch.setitem(sys.modules, "moondream", types.SimpleNamespace(photon=photon))
    monkeypatch.setattr(pipeline, "_ULTRA", None)
    raw = pipeline.transcribe_file(str(tmp_path / "puhe.wav"))

    assert seen[0] == {"model_id": "moondream/parakeet-ultra", "device": "cuda"}
    assert seen[1] == {"audio": str(tmp_path / "puhe.wav"), "timestamps": "word"}
    assert raw["segments"][0]["words"][1] == {
        "word": "tämä", "start": 0.6, "end": 0.9,
    }


def test_transcribe_file_converts_aiff_before_photon(monkeypatch, tmp_path):
    import sys
    import types

    from colabtranscribe.colab import pipeline

    source = tmp_path / "puhe.aiff"
    source.write_bytes(b"AIFF")
    seen = {}

    def ffmpeg(command, **kwargs):
        assert command[:5] == ["ffmpeg", "-nostdin", "-v", "error", "-i"]
        Path(command[-1]).write_bytes(b"WAVE")

    class FakeModel:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def transcribe(self, **kwargs):
            seen.update(kwargs)
            assert Path(kwargs["audio"]).suffix == ".wav"
            assert Path(kwargs["audio"]).is_file()
            return {"text": "Moi", "segments": [{
                "words": [{"word": "Moi", "start": 0.0, "end": 0.4}],
            }]}

    monkeypatch.setattr(pipeline.subprocess, "run", ffmpeg)
    monkeypatch.setitem(
        sys.modules,
        "moondream",
        types.SimpleNamespace(photon=lambda *args, **kwargs: FakeModel()),
    )
    monkeypatch.setattr(pipeline, "_ULTRA", None)
    monkeypatch.setattr(pipeline, "_ULTRA_STACK", None)

    pipeline.transcribe_file(str(source))

    assert seen["timestamps"] == "word"
    assert seen["audio"] != str(source)


def test_time_to_seconds_valid_formats():
    assert time_to_seconds("0") == 0.0
    assert time_to_seconds("1.5") == 1.5
    assert time_to_seconds("1:30") == 90.0
    assert time_to_seconds("0:01:30") == 90.0
    assert time_to_seconds("1:23:45") == 5025.0
    assert time_to_seconds("0:00:00.5") == 0.5


def test_time_to_seconds_invalid_raises():
    # Virheelliset muodot eivät saa palauttaa 0.0 hiljaa — se piilottaa bugeja.
    # time_to_seconds palauttaa 0.0 virheessä, mikä on vaarallista (ks. CLAUDE.md).
    # Testi vaatii, että virheellisestä syötteestä nousee poikkeus.
    with pytest.raises(ValueError):
        time_to_seconds("invalid")
    with pytest.raises(ValueError):
        time_to_seconds("1:2:3:4")  # liian monta osaa
    with pytest.raises(ValueError):
        time_to_seconds("")  # tyhjä


def test_time_to_seconds_omitted_start_is_zero():
    """Hindenburg jättää ``Start``in pois kun alue alkaa nollasta.

    ``region.get("Start")`` on silloin None, ei tyhjä merkkijono. Tyhjä
    merkkijono on virhe; puuttuva attribuutti on mitattu nolla.
    """
    assert time_to_seconds(None) == 0.0


def test_auto_silence_reads_a_region_with_no_start(tmp_path):
    """Ensimmäinen alue h-test A:ssa on ``Length`` ilman ``Start``ia."""
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session>
      <AudioPool Path="">
        <File Id="1" Name="a.wav" Path="a.wav">
          <Transcription><p><w s="0.5" l="0.2" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1" Length="5.000" Offset="0.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = tree.find(".//Track")
    intervals = get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35)
    assert intervals == [(0.5, 0.7)]


def test_seconds_to_time():
    assert seconds_to_time(0) == "0.000"
    assert seconds_to_time(1.5) == "1.500"
    assert seconds_to_time(90) == "90.000"


def test_merge_intervals_with_gap():
    intervals = [(1.0, 2.0), (3.0, 4.0)]
    # gap 0 -> ei yhdistä
    assert merge_intervals_with_gap(intervals, 0.0) == [(1.0, 2.0), (3.0, 4.0)]
    # gap 1.5 -> yhdistää (1.0, 2.0) ja (3.0, 4.0) kun gap 1.5 >= 1.0
    assert merge_intervals_with_gap(intervals, 1.5) == [(1.0, 4.0)]
    # tyhjä lista
    assert merge_intervals_with_gap([], 1.0) == []


def test_merge_intervals_does_not_modify_input():
    intervals = [(3.0, 4.0), (1.0, 2.0)]
    original = list(intervals)
    merge_intervals_with_gap(intervals, 0.0)
    assert intervals == original  # ei muokkaa alkuperäistä


def test_inject_replaces_only_the_audio_suffix(tmp_path):
    """Pääte vaihdetaan kirjainkoosta riippumatta, eikä keskeltä nimeä.

    ``replace(".wav", ".json")`` jättää ``A.WAV`` ennalleen ja tekee
    ``take.wav.wav``:sta ``take.json.json``.
    """
    from xml.etree import ElementTree

    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    (outbox / "transcripts" / "take.wav.json").write_text(
        '{"segments":[{"words":[{"start":0.1,"end":0.3,"word":"hei"}]}]}',
        encoding="utf-8",
    )
    (inbox / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
      <AudioPool><File Id="1" Name="take.wav.WAV" Path="take.wav.WAV"/></AudioPool>
    </Session>""",
        encoding="utf-8",
    )
    inject_transcriptions_to_nhsx(str(inbox), str(outbox))
    written = next(outbox.glob("*litteroitu*"))
    tree = ElementTree.parse(written)
    words = [w.text for w in tree.findall(".//w")]
    assert words == ["hei"]


def test_inject_does_not_read_a_name_outside_transcripts(tmp_path):
    """File/@Name on käyttäjän XML:ä, ei polku transcripts-kansioon."""
    from xml.etree import ElementTree

    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    secret = tmp_path / "secret.json"
    secret.write_text(
        '{"segments":[{"words":[{"start":0,"end":1,"word":"LEAK"}]}]}',
        encoding="utf-8",
    )
    (inbox / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
      <AudioPool><File Id="1" Name="../../secret.wav" Path="a.wav"/></AudioPool>
    </Session>""",
        encoding="utf-8",
    )
    inject_transcriptions_to_nhsx(str(inbox), str(outbox))
    written = next(outbox.glob("*litteroitu*"))
    text = ElementTree.parse(written).find(".//w")
    assert text is None or (text.text or "") != "LEAK"


def test_inject_writes_utf8(tmp_path):
    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    (outbox / "transcripts" / "a.json").write_text(
        '{"segments":[{"words":[{"start":0.1,"end":0.3,"word":"ää"}]}]}',
        encoding="utf-8",
    )
    (inbox / "s.nhsx").write_text(
        """<?xml version="1.0"?><Session>
      <AudioPool><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>
    </Session>""",
        encoding="utf-8",
    )
    inject_transcriptions_to_nhsx(str(inbox), str(outbox))
    raw = next(outbox.glob("*litteroitu*")).read_bytes()
    assert "ää".encode() in raw
    assert raw.startswith(b"<?xml")


def test_quoted_region_ref_does_not_crash_auto_silence(tmp_path):
    """Ref menee XPath-predikaattiin lainausmerkeissä: `'` kaataa lxml:n."""
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session>
      <AudioPool>
        <File Id="1" Name="a.wav">
          <Transcription><p><w s="0.5" l="0.2" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1'" Length="5.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = tree.find(".//Track")
    assert get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35) == []


def test_auto_silence_reads_namespaced_sessions(tmp_path):
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session xmlns="urn:hindenburg">
      <AudioPool>
        <File Id="1" Name="a.wav">
          <Transcription><p><w s="0.5" l="0.2" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1" Length="5.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = next(e for e in tree.iter() if e.tag.endswith("Track"))
    assert get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35) == [
        (0.5, 0.7)
    ]


def test_auto_silence_handles_colon_word_times(tmp_path):
    """Sanan ``s`` voi olla muodossa ``MM:SS`` vanhemmissa istunnoissa.

    ``float("01:30")`` kaataisi koko Auto-Silencen. Jäsennin käyttää
    ``time_to_seconds``ia kuten muutkin toteutukset — sama aika, sama
    muoto, sama tulos.
    """
    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    tree = etree.fromstring(
        """<Session>
      <AudioPool Path="">
        <File Id="1" Name="a.wav" Path="a.wav">
          <Transcription><p><w s="01:30" l="0.5" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1" Start="0.000" Length="120.000" Offset="0.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = tree.find(".//Track")
    intervals = get_speech_intervals_for_track(tree, track, str(tmp_path), False, -35)
    assert intervals == [(90.0, 90.5)]


def test_inject_rejects_a_doctype(tmp_path):
    """Istunto ei saa julistaa DTD:tä.

    ``<!DOCTYPE>`` avaisi ovi entiteettejä: tiedostojen luku (XXE) ja
    laajennus. Kelvollinen ``.nhsx`` ei koskaan julista DTD:tä, joten
    julistava tiedosto hylätään eikä käsitellä.
    """
    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox = tmp_path / "in"
    outbox = tmp_path / "out"
    inbox.mkdir()
    (outbox / "transcripts").mkdir(parents=True)
    (inbox / "evil.nhsx").write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE Session [<!ENTITY name "a.wav">]>\n'
        '<Session><AudioPool><File Id="1" Name="a.wav" Path="a.wav"/></AudioPool>'
        '<Tracks><Track Name="t"><Region Ref="1" Start="0" Length="1"/></Track></Tracks></Session>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        inject_transcriptions_to_nhsx(str(inbox), str(outbox))


def test_install_dependencies_does_not_require_libcublas11(monkeypatch):
    from colabtranscribe.colab.pipeline import install_dependencies

    commands = []

    def mock_run(cmd, *args, **kwargs):
        commands.append(cmd)

    monkeypatch.setattr("subprocess.run", mock_run)
    install_dependencies()

    assert any(cmd[:2] == ["apt-get", "update"] for cmd in commands)
    apt_installs = [cmd for cmd in commands if cmd[:2] == ["apt-get", "install"]]
    assert apt_installs
    for cmd in apt_installs:
        assert "libcublas11" not in cmd
        assert "ffmpeg" in cmd


def test_install_dependencies_pins_locked_versions(monkeypatch):
    """Riippuvuudet on lukittu toimiviin versioihin eikä käytetä -U -valitsinta."""
    from colabtranscribe.colab.pipeline import install_dependencies

    commands = []

    def mock_run(cmd, *args, **kwargs):
        commands.append(cmd)

    monkeypatch.setattr("subprocess.run", mock_run)
    install_dependencies()

    pip_installs = [cmd for cmd in commands if cmd[:2] == ["pip", "install"]]
    assert pip_installs
    pip_cmd = pip_installs[0]
    assert "-U" not in pip_cmd
    assert "moondream==2.4.1" in pip_cmd
    assert not any("nemo" in str(arg).lower() for arg in pip_cmd)
    assert not any("whisper" in str(arg).lower() for arg in pip_cmd)


def test_configure_cuda_libs(tmp_path, monkeypatch):
    from colabtranscribe.colab.pipeline import configure_cuda_libs

    fake_nvidia_lib = (
        tmp_path
        / "usr"
        / "local"
        / "lib"
        / "python3.13"
        / "dist-packages"
        / "nvidia"
        / "cublas"
        / "lib"
    )
    fake_nvidia_lib.mkdir(parents=True)
    fake_ld_conf = tmp_path / "00-nvidia-pip.conf"

    monkeypatch.setattr(
        "glob.glob",
        lambda pat: [str(fake_nvidia_lib)] if "nvidia" in pat else [],
    )
    commands = []

    def mock_run(cmd, *args, **kwargs):
        commands.append(cmd)

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/old/path")
    monkeypatch.setattr(
        "colabtranscribe.colab.pipeline.LD_SO_CONF_PATH",
        str(fake_ld_conf),
        raising=False,
    )

    configure_cuda_libs()
    assert str(fake_nvidia_lib) in os.environ.get("LD_LIBRARY_PATH", "")
    assert ["ldconfig"] in commands
    assert fake_ld_conf.is_file()
    assert str(fake_nvidia_lib) in fake_ld_conf.read_text()


def test_run_auto_silence_processes_all_tracks(tmp_path):
    """Auto-Silence käsittelee kaikki istunnon raidat, ei vain ensimmäistä.

    lxml:n puun muokkaaminen silmukan aikana rikkoi aiemmin iteraattorin,
    jolloin vain raita 1 pilkottiin ja loput raidat jäivät koskemattomiksi.
    """
    from lxml import etree

    from colabtranscribe.colab.pipeline import run_auto_silence

    nhsx_path = tmp_path / "multi.nhsx"
    nhsx_path.write_text(
        """<Session>
  <AudioPool Path="">
    <File Id="1" Name="a.wav" Path="a.wav">
      <Transcription><p><w s="1.0" l="1.0" sp="UU">eka</w></p></Transcription>
    </File>
    <File Id="2" Name="b.wav" Path="b.wav">
      <Transcription><p><w s="2.0" l="1.0" sp="UU">toka</w></p></Transcription>
    </File>
    <File Id="3" Name="c.wav" Path="c.wav">
      <Transcription><p><w s="3.0" l="1.0" sp="UU">kolmas</w></p></Transcription>
    </File>
  </AudioPool>
  <Tracks>
    <Track Name="Raita1">
      <Region Ref="1" Start="0.000" Length="10.000" Offset="0.000"/>
    </Track>
    <Track Name="Raita2">
      <Region Ref="2" Start="0.000" Length="10.000" Offset="0.000"/>
    </Track>
    <Track Name="Raita3">
      <Region Ref="3" Start="0.000" Length="10.000" Offset="0.000"/>
    </Track>
  </Tracks>
</Session>""",
        encoding="utf-8",
    )

    run_auto_silence(
        str(nhsx_path), str(tmp_path), rms_enabled=False, threshold=-35, tail=0.5, gap=0.5
    )

    processed_path = tmp_path / "multi_processed.nhsx"
    assert processed_path.is_file()

    tree = etree.parse(str(processed_path))
    tracks = tree.findall(".//Track")
    assert len(tracks) == 3

    for track in tracks:
        regions = track.findall("Region")
        # Jokaisessa raidassa pitäisi olla vähintään 2 aluetta (ääni + vaimennettu),
        # koska 1s puhetta 10s leikkeessä tail=0.5 jakaa leikkeen osiin.
        assert len(regions) > 1, (
            f"Raita {track.get('Name')} jäi leikkaamatta (vain {len(regions)} aluetta)"
        )


def test_auto_silence_rms_finds_audio_with_name_and_pool_path(tmp_path, monkeypatch):
    """RMS-tarkistus löytää äänitiedoston Name-attribuutilla ja AudioPool-polusta."""
    import sys
    from unittest.mock import MagicMock

    from lxml import etree

    from colabtranscribe.colab.pipeline import get_speech_intervals_for_track

    mock_pydub = MagicMock()
    mock_audio = MagicMock()
    mock_chunk = MagicMock()
    mock_chunk.dBFS = -20
    mock_audio.__getitem__.return_value = mock_chunk
    mock_pydub.AudioSegment.from_file.return_value = mock_audio
    monkeypatch.setitem(sys.modules, "pydub", mock_pydub)

    subfolder = tmp_path / "SubFiles"
    subfolder.mkdir()
    audio_file = subfolder / "test_audio.wav"
    audio_file.write_bytes(b"dummy")

    tree = etree.fromstring(
        """<Session>
      <AudioPool Path="SubFiles">
        <File Id="1" Name="test_audio.wav">
          <Transcription><p><w s="1.0" l="0.5" sp="UU">hei</w></p></Transcription>
        </File>
      </AudioPool>
      <Tracks>
        <Track Name="A">
          <Region Ref="1" Start="0.000" Length="10.000"/>
        </Track>
      </Tracks>
    </Session>"""
    )
    track = tree.find(".//Track")
    intervals = get_speech_intervals_for_track(
        tree, track, str(tmp_path), rms_enabled=True, threshold=-35
    )
    assert intervals == [(1.0, 1.5)]
    mock_pydub.AudioSegment.from_file.assert_called_once_with(str(audio_file))


def test_run_transcription_logs_litterointi_luotu(tmp_path, capsys, monkeypatch):
    in_dir = tmp_path / "in"
    in_dir.mkdir()

    (in_dir / "haastattelu.wav").write_bytes(b"data")
    out_dir = tmp_path / "out"

    def fake_transcribe(path, model, language, prompt):
        return {"segments": [{"words": [{"word": "Moi", "start": 0.1, "end": 0.3}]}]}

    monkeypatch.setattr("colabtranscribe.colab.pipeline.transcribe_file", fake_transcribe)
    run_transcription(str(in_dir), str(out_dir), "prompt")

    captured = capsys.readouterr().out
    assert "Litterointi luotu:" in captured
    assert "haastattelu.json" in captured
    assert "ei tue Whisperin promptia" in captured
    written = json.loads((out_dir / "transcripts" / "haastattelu.json").read_text())
    assert written["segments"][0]["words"][0]["word"] == "Moi"


@pytest.mark.parametrize(("argv", "silenced"), [([], True), (["--no-silence"], False)])
def test_no_silence_skips_auto_silence(monkeypatch, argv, silenced):
    """``--no-silence``: litteroitu istunto tehdään, Auto-Silence jää pois."""
    import sys

    from colabtranscribe.colab import pipeline

    ran = []
    monkeypatch.setattr(sys, "argv", ["pipeline.py", *argv])
    monkeypatch.setattr(pipeline.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "install_dependencies", lambda: None)
    monkeypatch.setattr(pipeline, "run_transcription", lambda *a: None)
    monkeypatch.setattr(pipeline, "inject_transcriptions_to_nhsx", lambda *a, **k: ["/c/x.nhsx"])
    monkeypatch.setattr(pipeline, "run_auto_silence", lambda *a: ran.append(a[0]))
    scripted = []
    monkeypatch.setattr(pipeline, "write_script", lambda p, **k: scripted.append(p))
    pipeline.main()
    assert ran == (["/c/x.nhsx"] if silenced else [])
    # Käsikirjoitus tehdään valmiista istunnosta, ei aina samasta.
    assert scripted == (["/c/x_processed.nhsx"] if silenced else ["/c/x.nhsx"])


# ------------------------------------------------------------------ käsikirjoitus

TURNS_SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="vuorot">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription><p>
        <w s="1.000" l="0.400" sp="UU">Ensin</w>
        <w s="6.000" l="0.400" sp="UU">sitten</w>
        <w s="20.000" l="0.400" sp="UU">lopuksi</w>
        <w s="50.000" l="0.400" sp="UU">hukassa</w>
      </p></Transcription>
    </File>
    <File Id="2" Name="panu.wav" Path="panu.wav">
      <Transcription><p><w s="11.000" l="0.300" sp="UU">Joo</w></p></Transcription>
    </File>
    <File Id="3" Name="musa.wav" Path="musa.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Olli">
      <Region Ref="1" Start="0.000" Length="3.000" Offset="0.000"/>
      <Region Ref="1" Start="5.000" Length="3.000" Offset="5.000" Muted="True"/>
      <Region Ref="1" Start="19.000" Length="3.000" Offset="19.000"/>
    </Track>
    <Track Name="Panu">
      <Region Ref="2" Start="10.000" Length="3.000" Offset="10.000"/>
    </Track>
    <Track Name="Musiikki">
      <Region Ref="3" Length="30.000"/>
    </Track>
  </Tracks>
</Session>"""


def test_write_script_makes_speaker_turns_next_to_the_session(tmp_path):
    """Valmis istunto saa viereensä ``.md``:n: raidan nimi puhujana,
    peräkkäiset alueet yhtenä vuorona, sanat alueen ikkunan sisältä."""
    from colabtranscribe.colab.pipeline import write_script

    session = tmp_path / "jakso litteroitu_processed.nhsx"
    session.write_text(TURNS_SESSION, encoding="utf-8")
    written = write_script(str(session))
    assert written == str(tmp_path / "jakso litteroitu_processed.md")
    assert open(written, encoding="utf-8").read() == (
        "[00:00] **Olli:** Ensin sitten\n"
        "\n"
        "[00:10] **Panu:** Joo\n"
        "\n"
        "[00:19] **Olli:** lopuksi\n"
    )


def test_the_snapshot_script_matches_podcast_magics(tmp_path):
    """Snapshot ei seuraa muutoksia itsestään (ks. CLAUDE.md), joten sen
    ero ``podcastmagic.script``ista on testi eikä arvaus: sama istunto,
    täsmälleen sama teksti."""
    from colabtranscribe.colab.pipeline import write_script
    from podcastmagic.script import core

    session = tmp_path / "vuorot.nhsx"
    session.write_text(TURNS_SESSION, encoding="utf-8")
    written = write_script(str(session))
    assert open(written, encoding="utf-8").read() == core.script(core.read(str(session)))


def test_write_script_rejects_a_doctype(tmp_path):
    from colabtranscribe.colab.pipeline import write_script

    session = tmp_path / "paha.nhsx"
    session.write_text(
        '<?xml version="1.0"?><!DOCTYPE Session [<!ENTITY x "y">]><Session/>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        write_script(str(session))
    assert not (tmp_path / "paha.md").exists()


def test_run_auto_silence_returns_the_file_it_wrote(tmp_path):
    from colabtranscribe.colab.pipeline import run_auto_silence

    session = tmp_path / "jakso.nhsx"
    session.write_text(TURNS_SESSION, encoding="utf-8")
    out = run_auto_silence(str(session), str(tmp_path), False, -35, 1.0, 1.0)
    assert out == str(tmp_path / "jakso_processed.nhsx")


# ------------------------------------------------------------------ downmix

def _downmix_session(tmp_path, tracks_xml):
    for name in ("a.wav", "b.wav"):
        (tmp_path / name).write_bytes(b"")
    session = tmp_path / "jakso.nhsx"
    session.write_text(
        '<?xml version="1.0"?><Session><AudioPool>'
        '<File Id="1" Name="a.wav" Path="a.wav"/>'
        '<File Id="2" Name="b.wav" Path="b.wav"/>'
        f"</AudioPool><Tracks>{tracks_xml}</Tracks></Session>",
        encoding="utf-8",
    )
    return session


def _ones(path, offset, length, rate):
    return [1.0] * int(round(length * rate))


def _mixed(tmp_path, tracks_xml, decode=_ones, rate=10):
    from colabtranscribe.colab.pipeline import gain_mix, read_mix

    session = _downmix_session(tmp_path, tracks_xml)
    clips, duration, missing = read_mix(str(session), str(tmp_path))
    assert missing == []
    return list(gain_mix(clips, duration, rate, decode))


def test_main_downmix_skips_the_track_chain(monkeypatch):
    """``--source downmix``: yksi litterointi koko miksauksesta, ei raitoja."""
    import sys

    from colabtranscribe.colab import pipeline

    def boom(*a, **k):
        raise AssertionError("raitaketju ajettiin")

    called = []
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "--source", "downmix"])
    monkeypatch.setattr(pipeline.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "install_dependencies", lambda: None)
    monkeypatch.setattr(pipeline, "run_downmix", lambda *a: called.append(a))
    for name in ("run_transcription", "inject_transcriptions_to_nhsx", "run_auto_silence", "write_script"):
        monkeypatch.setattr(pipeline, name, boom)
    pipeline.main()
    assert len(called) == 1
    assert called[0][:2] == ("/content/input", "/content/output")


def test_gain_mix_clip_gain_wins_over_gain(tmp_path):
    out = _mixed(
        tmp_path,
        '<Track Name="A"><Region Ref="1" Start="0" Length="1" Offset="0"'
        ' Gain="-20" ClipGain="0"/></Track>',
    )
    assert out == pytest.approx([1.0] * 10)


def test_gain_mix_multiplies_track_volume_and_region_gain(tmp_path):
    out = _mixed(
        tmp_path,
        '<Track Name="A" Volume="-20"><Region Ref="1" Start="0" Length="1"'
        ' Offset="0" Gain="-20"/></Track>',
    )
    assert out == pytest.approx([0.01] * 10)


def test_gain_mix_skips_muted_tracks_and_regions(tmp_path):
    out = _mixed(
        tmp_path,
        '<Track Name="A" Muted="true"><Region Ref="1" Start="0" Length="1"/></Track>'
        '<Track Name="B"><Region Ref="2" Start="0" Length="1" Muted="true"/>'
        '<Region Ref="2" Start="1" Length="1"/></Track>',
    )
    # Mykistetyt alueet laskevat silti kestoon: miksaus on 2 s.
    assert out == pytest.approx([0.0] * 10 + [1.0] * 10)


def test_gain_mix_places_by_start_and_reads_from_offset(tmp_path):
    seen = []

    def decode(path, offset, length, rate):
        seen.append((os.path.basename(path), offset, length, rate))
        return [1.0] * int(round(length * rate))

    out = _mixed(
        tmp_path,
        '<Track Name="A"><Region Ref="1" Start="1" Length="0.5" Offset="3"/></Track>',
        decode,
    )
    assert seen == [("a.wav", 3.0, 0.5, 10)]
    assert out == pytest.approx([0.0] * 10 + [1.0] * 5)


def test_gain_mix_pads_a_short_source_with_silence(tmp_path):
    out = _mixed(
        tmp_path,
        '<Track Name="A"><Region Ref="1" Start="0" Length="1"/></Track>',
        lambda *a: [1.0] * 4,
    )
    assert out == pytest.approx([1.0] * 4 + [0.0] * 6)


def test_read_mix_lists_missing_files_and_run_downmix_refuses(tmp_path):
    from colabtranscribe.colab.pipeline import read_mix, run_downmix

    session = _downmix_session(tmp_path, '<Track Name="A"><Region Ref="1" Length="1"/></Track>')
    (tmp_path / "a.wav").unlink()
    _, _, missing = read_mix(str(session), str(tmp_path))
    assert missing == ["a.wav"]
    with pytest.raises(RuntimeError, match=r"a\.wav"):
        run_downmix(str(tmp_path), str(tmp_path / "out"), "")


def test_read_mix_rejects_a_doctype(tmp_path):
    from colabtranscribe.colab.pipeline import read_mix

    session = tmp_path / "paha.nhsx"
    session.write_text(
        '<?xml version="1.0"?><!DOCTYPE Session [<!ENTITY x "y">]><Session/>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        read_mix(str(session), str(tmp_path))


def test_downmix_text_matches_podcast_magics():
    """Snapshot ei seuraa muutoksia itsestään (ks. CLAUDE.md): sama sanalista,
    täsmälleen sama teksti kuin ``podcastmagic.transcribe.downmix``."""
    from colabtranscribe.colab import pipeline
    from nhsx.read import Word
    from podcastmagic.transcribe import downmix

    raw = [
        ("Hei", 0.0, 0.4), (" maailma", 0.5, 0.4), ("tauon", 3.0, 0.4), ("jälkeen", 3.45, 0.5),
        ("pitkä", 75.2, 0.3), ("tauko", 80.0, 0.3),
    ]
    mine = pipeline.paragraph_lines([pipeline._Word(t, s, s + n) for t, s, n in raw])
    theirs = downmix.paragraph_lines([Word(t, s, n) for t, s, n in raw])
    assert mine == theirs
    assert pipeline.paragraph_lines([]) == ""


def test_run_downmix_writes_text_and_marker(tmp_path, monkeypatch, capsys):
    from colabtranscribe.colab import pipeline

    _downmix_session(tmp_path, '<Track Name="A"><Region Ref="1" Start="0" Length="1"/></Track>')
    out = tmp_path / "out"
    monkeypatch.setattr(pipeline, "decode_mono", _ones)
    monkeypatch.setattr(
        pipeline, "transcribe_samples",
        lambda samples, rate, prompt: [pipeline._Word("moi", 0.0, 0.3)],
    )
    pipeline.run_downmix(str(tmp_path), str(out), "")
    assert (out / "jakso downmix.md").read_text(encoding="utf-8") == "[00:00] moi\n"
    assert "Käsikirjoitus luotu:" in capsys.readouterr().out


def test_run_downmix_without_words_writes_nothing(tmp_path, monkeypatch, capsys):
    from colabtranscribe.colab import pipeline

    _downmix_session(tmp_path, '<Track Name="A"><Region Ref="1" Start="0" Length="1"/></Track>')
    out = tmp_path / "out"
    monkeypatch.setattr(pipeline, "decode_mono", _ones)
    monkeypatch.setattr(pipeline, "transcribe_samples", lambda *a: [])
    pipeline.run_downmix(str(tmp_path), str(out), "")
    assert list(out.glob("*.md")) == []
    assert "VAROITUS" in capsys.readouterr().out


def test_run_downmix_without_a_session_fails_loudly(tmp_path):
    from colabtranscribe.colab.pipeline import run_downmix

    (tmp_path / "a.wav").write_bytes(b"")
    with pytest.raises(RuntimeError, match=r"\.nhsx"):
        run_downmix(str(tmp_path), str(tmp_path / "out"), "")


def test_run_downmix_falls_back_to_a_processed_session(tmp_path, monkeypatch):
    from colabtranscribe.colab import pipeline

    seen = []
    (tmp_path / "x_processed.nhsx").write_text("<Session/>", encoding="utf-8")
    monkeypatch.setattr(
        pipeline, "read_mix", lambda path, d: seen.append(path) or ([], 0.0, [])
    )
    monkeypatch.setattr(pipeline, "transcribe_samples", lambda *a: [])
    pipeline.run_downmix(str(tmp_path), str(tmp_path / "out"), "")
    assert seen == [str(tmp_path / "x_processed.nhsx")]


INTERJECTION_SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="huudahdus">
  <AudioPool Path="">
    <File Id="1" Name="haastattelija.wav" Path="haastattelija.wav">
      <Transcription><p>
        <w s="0.000" l="0.400" sp="UU">alku</w>
        <w s="2.000" l="0.400" sp="UU">keskikohta</w>
        <w s="4.000" l="0.400" sp="UU">loppu</w>
      </p></Transcription>
    </File>
    <File Id="2" Name="vieras.wav" Path="vieras.wav">
      <Transcription><p>
        <w s="0.000" l="0.400" sp="UU">Joo</w>
        <w s="30.000" l="0.400" sp="UU">kauempana</w>
      </p></Transcription>
    </File>
  </AudioPool>
  <Tracks>
    <Track Name="Haastattelija">
      <Region Ref="1" Start="0.000" Length="6.000" Offset="0.000"/>
    </Track>
    <Track Name="Vieras">
      <Region Ref="2" Start="2.500" Length="1.000" Offset="0.000"/>
      <Region Ref="2" Start="10.000" Length="1.000" Offset="30.000"/>
    </Track>
  </Tracks>
</Session>"""


def test_a_short_remark_breaks_up_the_long_turn_in_the_snapshot_too(tmp_path):
    """Sama keskeytyssääntö kuin podcast-magicin ``script.core``issa, ja
    sama istunto antaa täsmälleen saman tekstin."""
    from colabtranscribe.colab.pipeline import write_script
    from podcastmagic.script import core

    session = tmp_path / "huudahdus.nhsx"
    session.write_text(INTERJECTION_SESSION, encoding="utf-8")
    text = open(write_script(str(session)), encoding="utf-8").read()
    assert text == (
        "[00:00] **Haastattelija:** alku keskikohta\n"
        "\n"
        "[00:02] **Vieras:** Joo\n"
        "\n"
        "[00:04] **Haastattelija:** loppu\n"
        "\n"
        "[00:10] **Vieras:** kauempana\n"
    )
    assert text == core.script(core.read(str(session)))


def test_identical_audio_is_transcribed_once_and_the_others_get_a_copy(
    tmp_path, monkeypatch
):
    """Sama äänitys kahdella nimellä (kopio, ``_D``-versio, ``.TAKE``): sisältö
    tunnistetaan tarkistussummasta, Orukeet ajetaan kerran ja muiden nimille
    kopioidaan tulos, jotta istunnon jokainen tiedosto saa litteroinnin."""
    in_dir = tmp_path / "in"
    (in_dir / "alikansio").mkdir(parents=True)
    (in_dir / "a.wav").write_bytes(b"sama sisalto")
    (in_dir / "alikansio" / "b.wav").write_bytes(b"sama sisalto")
    (in_dir / "c.wav").write_bytes(b"eri sisalto")
    out_dir = tmp_path / "out"
    ran: list[str] = []

    def fake_transcribe(path, model, language, prompt):
        src = Path(path)
        ran.append(src.name)
        return {"segments": [{"text": src.name, "words": [
            {"word": "moi", "start": 0.1, "end": 0.3}
        ]}]}

    monkeypatch.setattr("colabtranscribe.colab.pipeline.transcribe_file", fake_transcribe)
    run_transcription(str(in_dir), str(out_dir), "prompt")

    assert len(ran) == 2 and "c.wav" in ran
    t = out_dir / "transcripts"
    assert (t / "a.json").read_text() == (t / "b.json").read_text()
    assert (t / "a.json").exists() and (t / "b.json").exists() and (t / "c.json").exists()


RATE = 16000


def _bleed_session(tmp_path, monkeypatch, bleed=-27.0, own_b=-26.0):
    """Kaksi mikkiä, kumpikin kuulee molemmat. Aame puhuu 0-2 s, Antto 2-4 s,
    molemmat 4-5 s. Whisper litteroi vuodon kummallakin raidalla."""
    import numpy as np

    from colabtranscribe.colab import pipeline

    rng = np.random.default_rng(3)

    def level(db, seconds):
        return rng.standard_normal(int(RATE * seconds)) * 10 ** (db / 20)

    own_a = -20.0  # Antto on oletuksena 6 dB hiljaisempi omalla mikillään
    a = np.concatenate([level(own_a, 2), level(own_b + bleed, 2), level(own_a, 1)])
    b = np.concatenate([level(own_a + bleed, 2), level(own_b, 2), level(own_b, 1)])
    pcm = {"aame.wav": (a * 32767).astype("int16"), "antto.wav": (b * 32767).astype("int16")}
    monkeypatch.setattr(pipeline, "_decode_pcm16", lambda path: pcm[os.path.basename(path)])
    for name in pcm:
        (tmp_path / name).write_bytes(b"x")
    words_a = [(0.2, "aamen"), (2.2, "vuototanttoa"), (4.2, "yhtaikaa")]
    words_b = [(0.2, "vuotoaamea"), (2.2, "antton"), (4.2, "myos")]

    def file_xml(i, name, words):
        w = "".join(f'<w s="{s}" l="0.6">{t}</w>' for s, t in words)
        return (f'<File Id="{i}" Name="{name}" Path="{name}">'
                f"<Transcription><p>{w}</p></Transcription></File>")

    session = tmp_path / "jakso.nhsx"
    session.write_text(
        '<?xml version="1.0"?><Session><AudioPool>'
        + file_xml(1, "aame.wav", words_a) + file_xml(2, "antto.wav", words_b)
        + '</AudioPool><Tracks><Track Name="Aame"><Region Ref="1" Start="0" Length="5" Offset="0"/></Track>'
        '<Track Name="Antto"><Region Ref="2" Start="0" Length="5" Offset="0"/></Track></Tracks></Session>',
        encoding="utf-8",
    )
    return session


def test_bleed_words_are_dropped_from_the_script_and_overlap_is_kept(tmp_path, monkeypatch):
    """Molemmat mikit kuulevat molemmat: ilman suodatusta jokainen sana on
    kahdesti ja skripti näkee yhden pitkän keskeytyksen. Sana kuuluu raidalle
    jonka taso omaan puhetasoon nähden on kovempi; päällekkäinen puhe säilyy."""
    from colabtranscribe.colab.pipeline import write_script

    session = _bleed_session(tmp_path, monkeypatch)
    text = open(write_script(str(session), audio_dirs=[str(tmp_path)]), encoding="utf-8").read()
    for kept in ("aamen", "antton", "yhtaikaa", "myos"):
        assert kept in text
    assert "vuototanttoa" not in text and "vuotoaamea" not in text


def test_without_audio_the_script_is_unfiltered(tmp_path, monkeypatch):
    from colabtranscribe.colab.pipeline import write_script

    session = _bleed_session(tmp_path, monkeypatch)
    text = open(write_script(str(session)), encoding="utf-8").read()
    assert "vuototanttoa" in text and "vuotoaamea" in text


def test_one_track_is_never_filtered(tmp_path, monkeypatch):
    """Yksi raita ei voi vuotaa itselleen: sanoja ei pudoteta."""
    from colabtranscribe.colab.pipeline import write_script

    session = _bleed_session(tmp_path, monkeypatch)
    raw = session.read_text(encoding="utf-8")
    solo = raw[: raw.index('<Track Name="Antto">')] + "</Tracks></Session>"
    session.write_text(solo, encoding="utf-8")
    text = open(write_script(str(session), audio_dirs=[str(tmp_path)]), encoding="utf-8").read()
    assert "vuototanttoa" in text


def _bleed_inputs(tmp_path, monkeypatch):
    """Sama tilanne kuin skriptitestissä, mutta litteroinnit ovat vielä JSONeina
    eikä istunnossa: injektio päättää mitkä sanat kirjoitetaan Hindenburgiin."""
    import json

    session = _bleed_session(tmp_path, monkeypatch)
    raw = session.read_text(encoding="utf-8")
    import re

    # pois valmiit litteroinnit: injektio kirjoittaa ne itse
    session.write_text(re.sub(r"<Transcription>.*?</Transcription>", "", raw), encoding="utf-8")
    out = tmp_path / "out"
    (out / "transcripts").mkdir(parents=True)
    words = {
        "aame": [(0.2, "aamen"), (2.2, "vuototanttoa"), (4.2, "yhtaikaa")],
        "antto": [(0.2, "vuotoaamea"), (2.2, "antton"), (4.2, "myos")],
    }
    for name, ws in words.items():
        seg = {"segments": [{"words": [
            {"word": t, "start": s, "end": s + 0.6} for s, t in ws]}]}
        (out / "transcripts" / f"{name}.json").write_text(json.dumps(seg), encoding="utf-8")
    return out


def _injected_words(out, name):
    from lxml import etree

    tree = etree.parse(str(next(out.glob("*litteroitu.nhsx"))))
    for f in tree.iter("File"):
        if f.get("Name") == name:
            return [w.text for w in f.iter("w")]
    raise AssertionError(name)


def test_injection_leaves_bleed_out_of_each_speakers_file(tmp_path, monkeypatch):
    """Hindenburgissa jokaisella tiedostolla on oma litterointinsa: sama puhe
    jokaisen puhujan ja jokaisen tiedoston alla ei ole käyttökelpoista."""
    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    out = _bleed_inputs(tmp_path, monkeypatch)
    inject_transcriptions_to_nhsx(str(tmp_path), str(out))
    assert _injected_words(out, "aame.wav") == ["aamen", "yhtaikaa"]
    assert _injected_words(out, "antto.wav") == ["antton", "myos"]


def test_injection_keeps_everything_when_the_filter_is_off(tmp_path, monkeypatch):
    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    out = _bleed_inputs(tmp_path, monkeypatch)
    inject_transcriptions_to_nhsx(str(tmp_path), str(out), bleed_filter=False)
    assert _injected_words(out, "aame.wav") == ["aamen", "vuototanttoa", "yhtaikaa"]


def test_the_script_flag_turns_the_injection_filter_off(monkeypatch):
    import sys

    from colabtranscribe.colab import pipeline

    seen = []
    monkeypatch.setattr(sys, "argv", ["pipeline.py", "--no-bleed-filter"])
    monkeypatch.setattr(pipeline.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "install_dependencies", lambda: None)
    monkeypatch.setattr(pipeline, "run_transcription", lambda *a: None)
    monkeypatch.setattr(
        pipeline, "inject_transcriptions_to_nhsx",
        lambda i, o, bleed_filter=True: seen.append(bleed_filter) or [],
    )
    monkeypatch.setattr(pipeline, "write_script", lambda *a, **k: None)
    pipeline.main()
    assert seen == [False]


def test_the_margin_follows_how_deep_the_bleed_is(tmp_path, monkeypatch, capsys):
    """Raja ei ole kiinteä: se on neljäsosa siitä kuinka paljon omat sanat ovat
    kovempia kuin vuoto, 3-12 dB:n väliin rajattuna. Vuoto vain 5 dB alempana
    jäisi kiinteällä 6 dB:llä kokonaan, mutta puhujat erottuvat silti."""
    from colabtranscribe.colab.pipeline import write_script

    session = _bleed_session(tmp_path, monkeypatch, bleed=-5.0, own_b=-20.0)
    text = open(write_script(str(session), audio_dirs=[str(tmp_path)]), encoding="utf-8").read()
    assert "vuototanttoa" not in text and "vuotoaamea" not in text
    assert "aamen" in text and "antton" in text
    assert "Vuodon raja" in capsys.readouterr().out


WHOLE_FILE_SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session><AudioPool Path="">
  <File Id="1" Name="kysyja.wav" Path="kysyja.wav"><Transcription><p>
    <w s="1.000" l="0.500">Kysymys</w><w s="1.600" l="0.500">yksi</w>
    <w s="20.000" l="0.500">Kysymys</w><w s="20.600" l="0.500">kaksi</w>
  </p></Transcription></File>
  <File Id="2" Name="vieras.wav" Path="vieras.wav"><Transcription><p>
    <w s="5.000" l="0.500">Vastaus</w><w s="5.600" l="0.500">yksi</w><w s="6.200" l="0.500">jatkuu</w>
  </p></Transcription></File>
</AudioPool><Tracks>
  <Track Name="Kysyjä"><Region Ref="1" Start="0.000" Length="60.000" Offset="0.000"/></Track>
  <Track Name="Vieras"><Region Ref="2" Start="0.000" Length="60.000" Offset="0.000"/></Track>
</Tracks></Session>"""


def test_a_whole_file_region_still_gives_one_turn_per_burst_of_speech(tmp_path):
    """Ilman Auto-Silenceä jokaisella raidalla on yksi koko jakson mittainen
    alue: ennen kaikki yhden puhujan puhe oli yksi kappale aikaleimalla 00:00.
    Puhe pilkotaan tauoista, ja järjestys tulee sanojen ajoista."""
    from colabtranscribe.colab.pipeline import write_script

    session = tmp_path / "jakso.nhsx"
    session.write_text(WHOLE_FILE_SESSION, encoding="utf-8")
    text = open(write_script(str(session)), encoding="utf-8").read()
    assert text == (
        "[00:00] **Kysyjä:** Kysymys yksi\n"
        "\n"
        "[00:05] **Vieras:** Vastaus yksi jatkuu\n"
        "\n"
        "[00:20] **Kysyjä:** Kysymys kaksi\n"
    )


def test_the_snapshot_script_matches_podcast_magics_on_whole_file_regions(tmp_path):
    from colabtranscribe.colab.pipeline import write_script
    from podcastmagic.script import core

    session = tmp_path / "jakso.nhsx"
    session.write_text(WHOLE_FILE_SESSION, encoding="utf-8")
    written = write_script(str(session))
    assert open(written, encoding="utf-8").read() == core.script(core.read(str(session)))


def test_orukeet_repetitions_are_preserved_in_the_session(tmp_path):
    """Podcastin aitoja toistoja ei siivota litteroinnin jälkikäsittelyssä."""
    import json

    from colabtranscribe.colab.pipeline import inject_transcriptions_to_nhsx

    inbox, out = tmp_path / "in", tmp_path / "out"
    (out / "transcripts").mkdir(parents=True)
    inbox.mkdir()
    (inbox / "j.nhsx").write_text(
        '<?xml version="1.0"?><Session><AudioPool><File Id="1" Name="a.wav"/></AudioPool>'
        '<Tracks><Track Name="A"><Region Ref="1" Start="0" Length="100" Offset="0"/></Track></Tracks></Session>',
        encoding="utf-8",
    )
    words = [("niin" if 1 <= i <= 9 else w, i * 0.5) for i, w in enumerate(["ensin"] + ["x"] * 9 + ["sitten", "niin", "niin"])]
    seg = {"segments": [{"words": [{"word": t, "start": s, "end": s + 0.4} for t, s in words]}]}
    (out / "transcripts" / "a.json").write_text(json.dumps(seg), encoding="utf-8")
    inject_transcriptions_to_nhsx(str(inbox), str(out), bleed_filter=False)
    from lxml import etree

    tree = etree.parse(str(next(out.glob("*litteroitu.nhsx"))))
    assert [w.text for w in tree.iter("w")] == [
        "ensin", *["niin"] * 9, "sitten", "niin", "niin"
    ]


def test_script_turns_use_the_same_gap_as_auto_silence():
    """Yksi määritelmä puhejaksolle: sanat yhdistyvät ``merge_intervals_with_gap``illa
    ja presetin ``gap`` määrää rajan, joten skripti ja Auto-Silence eivät ole eri mieltä."""
    from colabtranscribe.colab.pipeline import _split_bursts

    words = [(0.0, 0.5, "a"), (1.2, 1.7, "b")]  # tauko 0,7 s
    one = _split_bursts([(0.0, "X", words)], gap=1.0)
    two = _split_bursts([(0.0, "X", words)], gap=0.4)
    assert [len(w) for _, _, w in one] == [2]
    assert [len(w) for _, _, w in two] == [1, 1]
    assert [s for s, _, _ in two] == [0.0, 1.2]


@pytest.mark.parametrize(("argv", "gap"), [([], 1.0), (["--preset", "intra-mic"], 0.4), (["--gap", "2.5"], 2.5)])
def test_the_script_gets_the_runs_gap(monkeypatch, argv, gap):
    import sys

    from colabtranscribe.colab import pipeline

    seen = []
    monkeypatch.setattr(sys, "argv", ["pipeline.py", *argv])
    monkeypatch.setattr(pipeline.os, "makedirs", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "install_dependencies", lambda: None)
    monkeypatch.setattr(pipeline, "run_transcription", lambda *a: None)
    monkeypatch.setattr(pipeline, "inject_transcriptions_to_nhsx", lambda *a, **k: ["/c/x.nhsx"])
    monkeypatch.setattr(pipeline, "run_auto_silence", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "write_script", lambda path, **k: seen.append(k.get("gap")))
    pipeline.main()
    assert seen == [gap]


def _remark_entries():
    """Haastattelija jatkaa virkettä, vieras sanoo «niin» keskellä."""
    return [
        (0.0, "Haastattelija", [(0.0, 0.4, "No"), (0.5, 0.9, "pörssiyhtiö,"),
                                 (3.0, 3.4, "puhutte"), (3.5, 3.9, "paljon")]),
        (1.5, "Vieras", [(1.5, 1.8, "niin")]),
    ]


def test_a_short_remark_breaks_the_paragraph_by_default():
    from colabtranscribe.colab.pipeline import _script_lines

    assert _script_lines(_remark_entries()) == [
        "[00:00] **Haastattelija:** No pörssiyhtiö,",
        "[00:01] **Vieras:** niin",
        "[00:03] **Haastattelija:** puhutte paljon",
    ]


def test_inline_remarks_keep_the_paragraph_whole_when_asked():
    from colabtranscribe.colab.pipeline import _script_lines

    assert _script_lines(_remark_entries(), inline_remarks=True) == [
        "[00:00] **Haastattelija:** No pörssiyhtiö, (Vieras: niin) puhutte paljon",
    ]


def test_a_longer_reply_is_never_folded_into_the_paragraph():
    from colabtranscribe.colab.pipeline import _script_lines

    entries = _remark_entries()
    entries[1] = (1.5, "Vieras", [(1.5, 1.8, "ei"), (1.9, 2.2, "ihan"), (2.3, 2.6, "noin")])
    lines = _script_lines(entries, inline_remarks=True)
    assert len(lines) == 3


def test_the_inline_remarks_flag_reaches_the_script_and_is_off_by_default(monkeypatch):
    import sys

    from colabtranscribe.colab import pipeline
    from colabtranscribe.options import RunOptions, pipeline_args

    assert "--inline-remarks" not in pipeline_args(RunOptions())
    assert "--inline-remarks" in pipeline_args(RunOptions(inline_remarks=True))
    seen = []
    for argv, want in (([], False), (["--inline-remarks"], True)):
        monkeypatch.setattr(sys, "argv", ["pipeline.py", *argv])
        monkeypatch.setattr(pipeline.os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(pipeline, "install_dependencies", lambda: None)
        monkeypatch.setattr(pipeline, "run_transcription", lambda *a: None)
        monkeypatch.setattr(pipeline, "inject_transcriptions_to_nhsx", lambda *a, **k: ["/c/x.nhsx"])
        monkeypatch.setattr(pipeline, "run_auto_silence", lambda *a, **k: None)
        monkeypatch.setattr(pipeline, "write_script", lambda p, **k: seen.append(k.get("inline_remarks")))
        pipeline.main()
        assert seen[-1] is want
