"""Litteroinnista luettava käsikirjoitus — ``nhsx-to-script.py``:n perillinen.

Sama työ, lyhyempänä: ``nhsx/read.py`` osaa sanat ja niiden ajat jo, joten
tässä on jäljellä vain aikajanaan sijoitus ja markdown. Vanha versio
jäsenti istuntonsa uudestaan suorilla tageilla ja kaatui nimiavaruudelliseen
tiedostoon ja pelkkiä sekunteja sisältävään aikaan — molemmat menevät nyt
``read.py``:n läpi.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from podcastmagic.script import core
from podcastmagic.server.app import create_app


def session_with(tmp_path: Path, name: str = "jakso.nhsx") -> Path:
    """Kaksi puhujaa, offset ja yksi sana regionin ulkopuolella."""
    (tmp_path / name).write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="jakso">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription>
        <p>
          <w s="10.000" l="0.400" sp="UU">Moikka</w>
          <w s="10.500" l="0.300" sp="UU">kaikille</w>
          <w s="50.000" l="0.400" sp="UU">hukassa</w>
        </p>
      </Transcription>
    </File>
    <File Id="2" Name="panu.wav" Path="panu.wav">
      <Transcription><p><w s="0.100" l="0.300" sp="UU">Hei</w></p></Transcription>
    </File>
    <File Id="3" Name="hiljaista.wav" Path="hiljaista.wav"/>
  </AudioPool>
  <Tracks>
    <Track Name="Panu">
      <Region Ref="2" Start="0.000" Length="4.000" Offset="0.000"/>
    </Track>
    <Track Name="Olli">
      <Region Ref="1" Start="120.000" Length="2.000" Offset="9.500"/>
    </Track>
    <Track Name="Musiikki">
      <Region Ref="3" Start="4.000" Length="116.000" Offset="0.000"/>
    </Track>
  </Tracks>
</Session>""",
        encoding="utf-8",
    )
    return tmp_path / name


def test_lines_carry_speaker_and_timeline_time(tmp_path):
    """Aikaleima on regionin paikka aikajanalla, sana on tiedoston aikaa.

    Region 2.000–2.000 sekuntia aikajanaan, offset 9,5 — sanat 10,0 ja
    10,5 osuvat ikkunaan [9,5; 11,5), sana 50,0 ei. Aikaleima on 02:00,
    ei 00:10: se on missä jakso puhuu, missä nauhoite.
    """
    text = core.script(core.read(str(session_with(tmp_path))))
    assert "[00:00] **Panu:** Hei" in text
    assert "[02:00] **Olli:** Moikka kaikille" in text
    assert "hukassa" not in text


def test_speaker_change_starts_a_new_paragraph(tmp_path):
    text = core.script(core.read(str(session_with(tmp_path))))
    lines = text.splitlines()
    assert lines.index("") == 1  # Panu: yksi rivi, sitten tyhjä rivi
    assert lines[2].startswith("[02:00] **Olli:**")


def test_the_timeline_orders_the_lines_not_the_tracks(tmp_path):
    text = core.script(core.read(str(session_with(tmp_path))))
    assert text.index("Panu") < text.index("Olli")


def test_a_region_without_words_is_not_a_line(tmp_path):
    """Musiikkiraita ja litteroimaton tiedosto eivät ole käsikirjoitusta.

    Vanha versio tulosti niille tyhjiä rivejä — deduppi piti niistä yhtä
    kopiota, ja sekin hävisi heti kun kaksi tyhjää oli eri kohdassa.
    """
    text = core.script(core.read(str(session_with(tmp_path))))
    assert "Musiikki" not in text
    assert "**Panu:** \n" not in text


def test_namespaced_sessions_read_the_same(tmp_path):
    path = session_with(tmp_path)
    raw = path.read_text(encoding="utf-8")
    namespaced = tmp_path / "avaruus.nhsx"
    namespaced.write_text(
        raw.replace("<Session ", '<Session xmlns="urn:hi" '), encoding="utf-8"
    )
    assert core.script(core.read(str(namespaced))) == core.script(core.read(str(path)))


def wait_for_job(client) -> dict:
    """Ajo on taustasäie: kysytään kunnes se on valmis."""
    import time

    for _ in range(200):
        job = client.get("/api/job").json()
        if job and not job.get("running"):
            return job
        time.sleep(0.02)
    raise AssertionError("Työ ei valmistunut.")


def test_run_writes_markdown_next_to_the_session(tmp_path):
    path = session_with(tmp_path)
    client = TestClient(create_app(start_dir=str(tmp_path)))

    preview = client.post("/api/script/preview", json={"session": str(path)})
    assert preview.status_code == 200
    assert "Moikka kaikille" in preview.json()["markdown"]

    client.post("/api/script/run", json={"session": str(path)})
    job = wait_for_job(client)
    written = Path(job["result"]["written"])
    assert written.suffix == ".md"
    assert "Moikka kaikille" in written.read_text(encoding="utf-8")


def test_the_output_never_overwrites(tmp_path):
    path = session_with(tmp_path)
    client = TestClient(create_app(start_dir=str(tmp_path)))
    client.post("/api/script/run", json={"session": str(path)})
    first = wait_for_job(client)
    client.post("/api/script/run", json={"session": str(path)})
    second = wait_for_job(client)
    assert first["result"]["written"] != second["result"]["written"]


def test_a_broken_session_is_a_stated_error(tmp_path):
    broken = tmp_path / "rikki.nhsx"
    broken.write_text("<Session>", encoding="utf-8")
    client = TestClient(create_app(start_dir=str(tmp_path)))
    response = client.post("/api/script/run", json={"session": str(broken)})
    assert response.status_code == 400


def two_regions_then_a_reply(tmp_path: Path) -> Path:
    """Olli puhuu kahdessa peräkkäisessä alueessa, sitten Panu, sitten Olli."""
    path = tmp_path / "vuorot.nhsx"
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Session Name="vuorot">
  <AudioPool Path="">
    <File Id="1" Name="olli.wav" Path="olli.wav">
      <Transcription><p>
        <w s="1.000" l="0.400" sp="UU">Ensin</w>
        <w s="6.000" l="0.400" sp="UU">sitten</w>
        <w s="20.000" l="0.400" sp="UU">lopuksi</w>
      </p></Transcription>
    </File>
    <File Id="2" Name="panu.wav" Path="panu.wav">
      <Transcription><p><w s="11.000" l="0.300" sp="UU">Joo</w></p></Transcription>
    </File>
  </AudioPool>
  <Tracks>
    <Track Name="Olli">
      <Region Ref="1" Start="0.000" Length="3.000" Offset="0.000"/>
      <Region Ref="1" Start="5.000" Length="3.000" Offset="5.000"/>
      <Region Ref="1" Start="19.000" Length="3.000" Offset="19.000"/>
    </Track>
    <Track Name="Panu">
      <Region Ref="2" Start="10.000" Length="3.000" Offset="10.000"/>
    </Track>
  </Tracks>
</Session>""",
        encoding="utf-8",
    )
    return path


def test_consecutive_regions_of_one_track_are_one_turn(tmp_path):
    """Puhuja on vuoro, ei joukko alueita: Hindenburg pilkkoo raidan
    hiljaisuuksista, ja joka palasta oma rivi toisti nimen kolmesti."""
    text = core.script(core.read(str(two_regions_then_a_reply(tmp_path))))
    assert text == (
        "[00:00] **Olli:** Ensin sitten\n"
        "\n"
        "[00:10] **Panu:** Joo\n"
        "\n"
        "[00:19] **Olli:** lopuksi\n"
    )


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


def test_a_short_remark_inside_a_long_turn_breaks_it_up(tmp_path):
    """Keskeytys jakaa vuoron ja vuoro jatkuu omalla aikaleimallaan.

    Hindenburgin alue ei katkea toisen puhujan kohdalla, joten alue
    alkaa 00:00 ja kestää yli vieraan «Joon» (00:02). Aluetasoinen
    järjestys pani koko haastattelijan kappaleen ensin ja huudahduksen
    sen perään; käyttäjän pyyntö 2026-10-13: huudahdus katkaisee kappaleen.
    """
    path = tmp_path / "huudahdus.nhsx"
    path.write_text(INTERJECTION_SESSION, encoding="utf-8")
    assert core.script(core.read(str(path))) == (
        "[00:00] **Haastattelija:** alku keskikohta\n"
        "\n"
        "[00:02] **Vieras:** Joo\n"
        "\n"
        "[00:04] **Haastattelija:** loppu\n"
        "\n"
        "[00:10] **Vieras:** kauempana\n"
    )


def test_a_reply_that_outlasts_the_turn_is_not_an_interjection(tmp_path):
    """Päällekkäin alkava mutta pidempään jatkuva puhe on vuoronvaihto.

    Haastattelijan puhe jaetaan sen omista tauoista, joten pitkä vastaus asettuu
    omaan kohtaansa ajassa ja haastattelijan loppu tulee sen jälkeen oman
    aikaleimansa kanssa (aiemmin koko kappale tuli ensin).
    """
    path = tmp_path / "huudahdus.nhsx"
    path.write_text(
        INTERJECTION_SESSION.replace('l="0.400" sp="UU">Joo', 'l="3.000" sp="UU">Joo'),
        encoding="utf-8",
    )
    text = core.script(core.read(str(path)))
    assert text.startswith(
        "[00:00] **Haastattelija:** alku keskikohta\n"
        "\n"
        "[00:02] **Vieras:** Joo\n"
        "\n"
        "[00:04] **Haastattelija:** loppu\n"
    )


def test_a_whole_file_region_gives_one_turn_per_burst_of_speech(tmp_path):
    """Istunto jota ei ole vaimennettu: yksi alue per raita, ja ennen kaikki
    yhden puhujan puhe oli yksi kappale aikaleimalla 00:00."""
    session = tmp_path / "jakso.nhsx"
    session.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
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
</Tracks></Session>""",
        encoding="utf-8",
    )
    assert core.script(core.read(str(session))) == (
        "[00:00] **Kysyjä:** Kysymys yksi\n"
        "\n"
        "[00:05] **Vieras:** Vastaus yksi jatkuu\n"
        "\n"
        "[00:20] **Kysyjä:** Kysymys kaksi\n"
    )
