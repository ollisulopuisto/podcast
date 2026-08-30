"""Litteroinnin siirto istunnosta toiseen — ``xml-merge.py``:n perillinen.

Leikkaus tehdään käsin editoituun istuntoon ja litterointi on
leikkaamattomassa. Ilman siirtoa toisen niistä tekee uudestaan. Vanha
versio korvasi kohdetiedoston litteroinnin katsomatta ja luotti siihen,
että nimellä löytyvä tiedosto on sama nauhoite — tässä molemmat ovat
omituisuuksia joita kertoo, ei hiljaisia oletuksia.
"""

from __future__ import annotations

import contextlib
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from podcastmagic.merge import core
from podcastmagic.server.app import create_app


def write_session(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>' + body, encoding="utf-8"
    )
    return path


def source_session(tmp_path: Path, name: str = "lahde.nhsx") -> Path:
    """Leikkaamaton istunto: litterointi kahdella tiedostolla ja yksi orpo."""
    return write_session(
        tmp_path / name,
        """<Session Name="lähde">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription>
        <p><w s="1.000" l="0.400" sp="UU">Terve</w><w s="1.500" l="0.300" sp="UU">vaan</w></p>
      </Transcription>
    </File>
    <File Id="2" Name="panu.wav" Path="panu.wav">
      <Transcription><p><w s="3.000" l="0.300" sp="UU">Moi</w></p></Transcription>
    </File>
    <File Id="3" Name="orpo.wav" Path="orpo.wav">
      <Transcription><p><w s="0.000" l="0.200" sp="UU">yksin</w></p></Transcription>
    </File>
  </AudioPool>
  <Tracks>
    <Track Name="Olli"><Region Ref="1" Start="0.000" Length="30.000" Offset="0.000"/></Track>
    <Track Name="Panu"><Region Ref="2" Start="0.000" Length="30.000" Offset="0.000"/></Track>
    <Track Name="Orpo"><Region Ref="3" Start="0.000" Length="30.000" Offset="0.000"/></Track>
  </Tracks>
</Session>""",
    )


def target_session(
    tmp_path: Path, name: str = "kohde.nhsx", with_old: bool = False
) -> Path:
    """Käsin editoitu istunto ilman litterointia — tai vanhan kanssa."""
    old = (
        "<Transcription><p><w s=\"2.000\" l=\"0.300\" sp=\"UU\">vanha</w></p></Transcription>"
        if with_old
        else ""
    )
    return write_session(
        tmp_path / name,
        f"""<Session Name="kohde">
  <AudioPool Path="">
    <File Id="7" Name="olli.wav" Path="olli.wav"/>
    <File Id="8" Name="panu.wav" Path="panu.wav">{old}</File>
  </AudioPool>
  <Tracks>
    <Track Name="Olli"><Region Ref="7" Start="0.000" Length="12.000" Offset="0.000"/></Track>
    <Track Name="Panu"><Region Ref="8" Start="0.000" Length="12.000" Offset="0.000"/></Track>
  </Tracks>
</Session>""",
    )


def write_wav(path: Path, seconds: float) -> None:
    """Aito WAV, jotta kesto on mitattu eikä arvattu."""
    with contextlib.closing(wave.open(str(path), "wb")) as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * int(8000 * seconds))


def words_of(session: Path, name: str) -> list[str]:
    from podcastmagic.nhsx.read import read

    parsed = read(session)
    info = parsed.file_by_name(name)
    return [w.text for w in info.words()]


def wait_for_job(client) -> dict:
    """Ajo on taustasäie: kysytään kunnes se on valmis."""
    import time

    for _ in range(200):
        job = client.get("/api/job").json()
        if job and not job.get("running"):
            return job
        time.sleep(0.02)
    raise AssertionError("Työ ei valmistunut.")


def test_words_move_from_the_uncut_session_into_the_edited_one(tmp_path):
    source = source_session(tmp_path)
    target = target_session(tmp_path)

    report = core.merge(source, target)
    written = Path(report["written"])

    # Sanat ovat nyt vietyssä istunnossa samalla tiedostolla, ja
    # tiedostoaika kulkee mukana muuttumattomana — litterointi on sama
    # nauhoite. Kohdetta ei kirjoiteta yli: leikkaus on käsin tehty.
    assert words_of(written, "olli.wav") == ["Terve", "vaan"]
    # Lähdettä ei kirjoiteta yli: vanha istunto jää silleen.
    assert words_of(source, "olli.wav") == ["Terve", "vaan"]
    assert words_of(target, "olli.wav") == []
    assert report["copied"] == ["olli.wav", "panu.wav"]


def test_namespaced_and_plain_sessions_are_the_same_format(tmp_path):
    """Hindenburgin viennit ovat joskus nimiavaruudessa ja joskus eivät."""
    raw = (source_session(tmp_path)).read_text(encoding="utf-8")
    namespaced = tmp_path / "avaruus.nhsx"
    namespaced.write_text(raw.replace("<Session ", '<Session xmlns="urn:hi" '), encoding="utf-8")
    target = target_session(tmp_path)

    report = core.merge(namespaced, target)

    assert report["copied"] == ["olli.wav", "panu.wav"]
    assert words_of(Path(report["written"]), "olli.wav") == ["Terve", "vaan"]


def test_an_existing_transcription_is_kept_unless_overwrite_is_asked(tmp_path):
    source = source_session(tmp_path)
    target = target_session(tmp_path, with_old=True)

    report = core.merge(source, target)
    assert report["kept"] == ["panu.wav"]
    assert report["copied"] == ["olli.wav"]
    written = Path(report["written"])
    assert words_of(written, "panu.wav") == ["vanha"]

    report = core.merge(source, target, overwrite=True)
    written = Path(report["written"])
    assert report["overwritten"] == ["panu.wav"]
    assert words_of(written, "panu.wav") == ["Moi"]


def test_a_duration_mismatch_is_refused_not_written(tmp_path):
    """Väärään istuntoon ajettuna sanat olisivat väärissä kohdissa.

    Juuri se on tämän työkalun hiljainen vika: kelvollinen tiedosto, puhdas
    ajo, väärä litterointi. Nyt kestot mitataan WAV-otsikoista ja eri
    mittainen nauhoite jätetään pois ja sanotaan.
    """
    source_dir, target_dir = tmp_path / "a", tmp_path / "b"
    source = source_session(source_dir)
    target = target_session(target_dir)
    write_wav(source_dir / "olli.wav", 30.0)  # leikkaamaton pitkä nauhoite
    write_wav(target_dir / "olli.wav", 12.0)  # sama nimi, eri asia

    report = core.merge(source, target)

    assert report["mismatched"] == ["olli.wav"]
    assert report["copied"] == ["panu.wav"]
    assert words_of(target, "olli.wav") == []


def test_the_same_length_is_not_a_mismatch(tmp_path):
    source_dir, target_dir = tmp_path / "a", tmp_path / "b"
    source = source_session(source_dir)
    target = target_session(target_dir)
    write_wav(source_dir / "olli.wav", 30.0)
    write_wav(target_dir / "olli.wav", 30.0)

    report = core.merge(source, target)
    assert report["copied"] == ["olli.wav", "panu.wav"]
    assert report["mismatched"] == []


def test_an_unmeasurable_duration_is_reported_not_hidden(tmp_path):
    """Kesto mitataan vain kun molemmat nauhoitteet ovat levyltä.

    Istunto voi olla avattu muualta ilman äänipoolia — silloin ei mitata,
    mutta siitä kerrotaan eikä vaikenemista myydä varmuutena.
    """
    source = source_session(tmp_path)
    target = target_session(tmp_path)

    report = core.merge(source, target)
    assert report["copied"] == ["olli.wav", "panu.wav"]
    assert report["unverified"] == ["olli.wav", "panu.wav"]


def test_a_source_file_without_a_counterpart_is_reported(tmp_path):
    source = source_session(tmp_path)
    target = target_session(tmp_path)

    report = core.merge(source, target)
    assert report["missing"] == ["orpo.wav"]


def test_the_same_file_twice_is_an_error(tmp_path):
    source = target_session(tmp_path, name="sama.nhsx")
    with pytest.raises(RuntimeError, match="sama"):
        core.merge(source, source)


def test_the_api_runs_the_merge_and_reports(tmp_path):
    source = source_session(tmp_path)
    target = target_session(tmp_path)
    client = TestClient(create_app(start_dir=str(tmp_path)))

    preview = client.post(
        "/api/merge/preview",
        json={"session": str(target), "source": str(source)},
    )
    assert preview.status_code == 200
    assert preview.json()["copied"] == ["olli.wav", "panu.wav"]
    assert preview.json()["missing"] == ["orpo.wav"]

    client.post(
        "/api/merge/run",
        json={"session": str(target), "source": str(source)},
    )
    job = wait_for_job(client)
    assert job["result"]["copied"] == ["olli.wav", "panu.wav"]
    assert Path(job["result"]["written"]).is_file()


def test_the_api_states_what_is_missing(tmp_path):
    target = target_session(tmp_path)
    client = TestClient(create_app(start_dir=str(tmp_path)))
    response = client.post("/api/merge/run", json={"session": str(target)})
    assert response.status_code == 400
