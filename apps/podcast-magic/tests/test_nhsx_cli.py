"""``nhsx-render``: istunto sisään, WAV tai kartoitus ulos."""

from __future__ import annotations

import json
import wave

import numpy as np
import pytest

from podcastmagic.nhsx import cli

SESSION = """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="testi">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav"/>
    <File Id="2" Name="panu.wav" Path="panu.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Olli"><Region Ref="1" Start="0" Length="2" Offset="0"/></Track>
    <Track Name="Panu"><Region Ref="2" Start="1" Length="2" Offset="5" Muted="True"/></Track>
  </Tracks>
</Session>
"""


def fake_decode(path, start, length, sample_rate):
    n = int(round(length * sample_rate))
    return np.full((n, 1), 0.25, dtype=np.float32)


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "jakso.nhsx"
    path.write_text(SESSION, encoding="utf-8")
    for name in ("olli.wav", "panu.wav"):
        (tmp_path / name).write_bytes(b"")
    return path


def test_it_renders_a_wav_next_to_the_session(session, capsys):
    assert cli.main([str(session), "--rate", "1000"], decode=fake_decode) == 0
    out = session.with_suffix(".wav")
    assert out.exists()
    with wave.open(str(out)) as w:
        assert w.getnframes() == 3000  # aikajana on 3 s, myös vaimennettu osa
        assert w.getnchannels() == 2
    assert "jakso.wav" in capsys.readouterr().out


def test_it_never_writes_over_an_earlier_render(session):
    existing = session.with_suffix(".wav")
    existing.write_bytes(b"vanha")
    cli.main([str(session), "--rate", "1000"], decode=fake_decode)
    assert existing.read_bytes() == b"vanha"
    assert session.with_name("jakso v2.wav").exists()


def test_an_explicit_output_name_is_used_as_given(session, tmp_path):
    target = tmp_path / "ohjelma.wav"
    cli.main([str(session), "-o", str(target), "--rate", "1000"], decode=fake_decode)
    assert target.exists()


def test_the_plan_says_what_would_be_heard_without_reading_any_audio(session, capsys):
    assert cli.main([str(session), "--plan"]) == 0
    out = capsys.readouterr().out
    assert "Olli" in out
    assert "3.0" in out or "3,0" in out
    # Vaimennettu leike ei ole miksauksessa, mutta se lasketaan.
    assert "1" in out


def test_the_plan_as_json_is_what_a_previewer_would_read(session, capsys):
    assert cli.main([str(session), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["duration"] == pytest.approx(3.0)
    assert data["muted"] == 1
    assert data["speakers"] == ["Olli"]
    clip = data["clips"][0]
    assert clip["speaker"] == "Olli"
    assert clip["start"] == pytest.approx(0.0)
    assert clip["length"] == pytest.approx(2.0)
    assert clip["file_offset"] == pytest.approx(0.0)
    assert clip["path"].endswith("olli.wav")
    assert clip["gain"] == pytest.approx(1.0)


def test_inspect_reports_the_format_rather_than_rendering(session, capsys, tmp_path):
    assert cli.main([str(session), "--inspect"]) == 0
    assert "Region" in capsys.readouterr().out
    assert not (tmp_path / "jakso.wav").exists()


def test_an_unreadable_session_is_an_error_with_a_message(tmp_path, capsys):
    bad = tmp_path / "rikki.nhsx"
    bad.write_text("<Session><ei suljettu>", encoding="utf-8")
    assert cli.main([str(bad)]) == 2
    assert "rikki.nhsx" in capsys.readouterr().err


def test_a_session_whose_audio_is_missing_says_which_file(tmp_path, capsys):
    path = tmp_path / "jakso.nhsx"
    path.write_text(SESSION, encoding="utf-8")  # yhtään .wav:ia ei ole levyllä
    assert cli.main([str(path), "--rate", "1000"], decode=fake_decode) == 1
    assert "olli.wav" in capsys.readouterr().err


def test_an_unknown_attribute_is_warned_about_not_swallowed(tmp_path, capsys):
    """Miksaus, joka ohitti tason, ei saa näyttää onnistuneelta ilman muuta."""
    path = tmp_path / "jakso.nhsx"
    path.write_text(
        SESSION.replace('Start="0" Length="2" Offset="0"', 'Start="0" Length="2" Volume="0.5"'),
        encoding="utf-8",
    )
    for name in ("olli.wav", "panu.wav"):
        (tmp_path / name).write_bytes(b"")
    assert cli.main([str(path), "--rate", "1000"], decode=fake_decode) == 0
    err = capsys.readouterr().err
    assert "Volume" in err
    assert "--inspect" in err


def test_the_peak_is_reported_so_a_hot_mix_is_visible(session, capsys):
    cli.main([str(session), "--rate", "1000"], decode=fake_decode)
    assert "dBFS" in capsys.readouterr().out


def test_sixteen_bit_is_available_for_publishing(session):
    cli.main([str(session), "--rate", "1000", "--bits", "16"], decode=fake_decode)
    with wave.open(str(session.with_suffix(".wav"))) as w:
        assert w.getsampwidth() == 2


def test_it_says_which_version_it_is(capsys):
    """Paketoidusta binääristä ei näe versiota mistään muualta.

    `.app`illa on `CFBundleVersion`, jonka Finder näyttää; yksittäisellä
    binäärillä ei ole mitään vastaavaa. Ilman tätä lippua käyttäjän
    lataamasta tiedostosta ei voi kertoa mikä se on — eikä siis myöskään
    sitä, selittääkö vanha versio jonkin oudon tuloksen.

    Numero tulee paketista eikä ole oma kopionsa: `nhsx-render` on
    `podcast-magic`in sisällä, ja yksi versio riittää.
    """
    from podcastmagic import __version__

    with pytest.raises(SystemExit) as exit_code:
        cli.main(["--version"])
    assert exit_code.value.code == 0
    assert __version__ in capsys.readouterr().out
