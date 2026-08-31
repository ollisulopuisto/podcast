"""Ajurin komentojen muoto: mitä `colab`-komentoa mikinäkii ajetaan.

`plan_commands` on puhdas funktio: se ei aja mitään, joten koko ajoa ei
tarvitse Colabia testaamaan. Järjestys on sopimus — uusi istunto, hakemistot,
skripti ylös, äänet ylös, ajo alas, tulokset alas, istunto kiinni.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from colabtranscribe import driver
from colabtranscribe.options import RunOptions


def test_pipeline_script_ships_with_the_package():
    # Ladattava skripti on paketin sisällä, ei sovellushakemistossa: vain
    # näin ajuri voi löytää sen myös asennettuna.
    script = driver.PIPELINE_SCRIPT
    assert script.is_file()
    assert script.name == "pipeline.py"
    assert "whisper-ctranslate2" in script.read_text(encoding="utf-8")


def test_plan_sequence(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), output_dir=str(tmp_path / "out"))
    commands = driver.plan_commands(options, ["pool/a.wav"])

    heads = [c[:3] for c in commands]
    assert heads[0] == ["colab", "new", "-s"]
    assert "--gpu" in commands[0] and "T4" in commands[0]
    assert heads[1] == ["colab", "exec", "-s"]
    assert "/content/input" in commands[1][-1]
    assert heads[2] == ["colab", "upload", "-s"]
    assert str(driver.PIPELINE_SCRIPT) in commands[2]
    assert commands[2][-1] == "/content/pipeline.py"
    # alipolku tehdään ennen kuin siihen ladataan
    assert heads[3] == ["colab", "exec", "-s"]
    assert "/content/input/pool" in commands[3][-1]
    assert heads[4] == ["colab", "upload", "-s"]
    # lähde on absoluuttinen: aliprosessi ei peri TUI:n työhakemistoa eikä
    # kannata arvata mistä se käynnistettiin
    assert commands[4][4] == str(tmp_path / "pool/a.wav")
    assert commands[4][-1] == "/content/input/pool/a.wav"
    assert heads[-2] == ["colab", "download", "-s"]
    assert heads[-1] == ["colab", "stop", "-s"]
    assert options.session in commands[0] and options.session in commands[-1]


def test_pipeline_args_land_in_the_exec_call(tmp_path: Path):
    options = RunOptions(
        input_dir=str(tmp_path), preset="intra-mic", thr=-42, tail=0.4
    )
    commands = driver.plan_commands(options, [])
    exec_cmd = next(c for c in commands if c[1] == "exec" and "pipeline.py" in c[-1])
    remote = exec_cmd[-1]
    assert remote.startswith("python3 /content/pipeline.py")
    for token in ("--preset", "intra-mic", "--thr", "-42", "--tail", "0.4"):
        assert token in remote


def test_prompt_with_spaces_is_quoted(tmp_path: Path):
    options = RunOptions(input_dir=str(tmp_path), prompt="öö, tota, niinku")
    commands = driver.plan_commands(options, [])
    exec_cmd = next(c for c in commands if c[1] == "exec" and "pipeline.py" in c[-1])
    remote = exec_cmd[-1]
    # purettuna takaisin argumenteiksi prompt on yksi argumentti, ei kolme
    args = shlex.split(remote)
    i = args.index("--prompt")
    assert args[i + 1] == "öö, tota, niinku"


def test_list_input_files_lists_everything_relative(tmp_path: Path):
    # Ei suodateta: skripti tarvitsee myös .nhsx-istunnot, ja sen tarvitsema
    # se itse. Polut ovat suhteellisia, sillä pilvipää antaa /content/inputin.
    (tmp_path / "puhe.wav").write_bytes(b"")
    (tmp_path / "jakso.nhsx").write_text("<x/>", encoding="utf-8")
    (tmp_path / "kuva.png").write_bytes(b"")
    (tmp_path / "ala").mkdir()
    (tmp_path / "ala" / "toinen.m4a").write_bytes(b"")

    assert driver.list_input_files(tmp_path) == [
        "ala/toinen.m4a",
        "jakso.nhsx",
        "kuva.png",
        "puhe.wav",
    ]


def test_parse_generated_reads_the_script_output():
    out = "Litteroidaan tiedostoa: /content/input/a.wav\n" "Litteroitu .nhsx luotu: /content/output/jakso litteroitu.nhsx\n"
    assert driver.parse_generated(out) == ["/content/output/jakso litteroitu.nhsx"]


def test_parse_generated_empty_when_nothing():
    assert driver.parse_generated("Koko putki suoritettu onnistuneesti.") == []
