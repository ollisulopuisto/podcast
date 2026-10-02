"""Koko ketju: litterointi, vaimennus ja miksaus yhdellä napilla.

Vaiheet korvataan jäljittäjillä. Testattava on se mitä ketju päättää —
mikä tiedosto kulkee mihinkin vaiheeseen, mitä ei ajeta ja mitä tarkistetaan
ennen kuin tunnin litterointi on tehty — ei se mitä vaiheet itse tekevät.
Ne on testattu omissa tiedostoissaan.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from podcastmagic.chain import mixer
from podcastmagic.chain import run as chain
from podcastmagic.jobs import Cancelled, Job, Progress
from podcastmagic.server.app import create_app
from podcastmagic.silence.presets import Settings
from podcastmagic.transcribe.options import Options


def _progress() -> Progress:
    return Progress(Job(id=1, module="chain", label="t"))


@pytest.fixture
def stages(monkeypatch, tmp_path):
    """Jäljittäjät kolmelle vaiheelle. ``calls`` kertoo mitä ajettiin ja millä."""
    calls: list[tuple[str, str]] = []

    def transcribe(session, options, progress, audio_dir="", force=False):
        calls.append(("transcribe", session))
        return {"written": str(tmp_path / "jakso litteroitu.nhsx"), "files": 2, "words": 9}

    def silence(session, settings, progress, extra_dir=""):
        calls.append(("silence", session))
        return {"written": str(tmp_path / "jakso litteroitu vaimennettu.nhsx"), "tracks": []}

    def mix(session, target_lufs, progress):
        calls.append(("mix", session))
        return str(tmp_path / "jakso litteroitu vaimennettu automixer.wav")

    monkeypatch.setattr(chain.transcribe_run, "run", transcribe)
    monkeypatch.setattr(chain.silence_run, "run", silence)
    monkeypatch.setattr(chain.mixer, "run", mix)
    monkeypatch.setattr(chain.mixer, "command", lambda: ["automixer"])
    return calls


def _go(session, steps, **kw):
    return chain.run(
        str(session), steps, Options(), Settings(), _progress(), **kw
    )


def test_each_stage_reads_what_the_previous_one_wrote(stages, session_file, tmp_path):
    result = _go(session_file, chain.Steps(transcribe=True, silence=True, mix=True))

    assert stages == [
        ("transcribe", str(session_file)),
        ("silence", str(tmp_path / "jakso litteroitu.nhsx")),
        ("mix", str(tmp_path / "jakso litteroitu vaimennettu.nhsx")),
    ]
    assert result["written"].endswith("automixer.wav")
    assert [s["stage"] for s in result["stages"]] == ["transcribe", "silence", "mix"]


def test_a_stage_that_is_not_chosen_is_not_run(stages, session_file, tmp_path):
    """«Ei aina»: valmiiksi litteroidusta istunnosta alkaa vaimennuksesta."""
    _go(session_file, chain.Steps(transcribe=False, silence=True, mix=True))

    assert [name for name, _ in stages] == ["silence", "mix"]
    assert stages[0][1] == str(session_file)


def test_mixing_alone_takes_the_session_as_it_is(stages, session_file):
    _go(session_file, chain.Steps(transcribe=False, silence=False, mix=True))

    assert stages == [("mix", str(session_file))]


def test_a_transcription_that_had_nothing_to_do_hands_the_session_on(
    stages, session_file, monkeypatch
):
    """Kaikki poolin tiedostot oli jo litteroitu: ``written`` on tyhjä.

    Seuraava vaihe saa silloin alkuperäisen istunnon. Tyhjä polku
    vaimennukselle olisi virhe, ja pahempi: «ei tehty mitään» ei saa
    pysäyttää ketjua jonka jäljellä olevat vaiheet ovat täysin tehtävissä.
    """
    monkeypatch.setattr(
        chain.transcribe_run, "run",
        lambda session, *a, **k: stages.append(("transcribe", session))
        or {"written": "", "files": 0, "words": 0},
    )
    _go(session_file, chain.Steps(transcribe=True, silence=True, mix=False))

    assert stages == [("transcribe", str(session_file)), ("silence", str(session_file))]


def test_missing_mixer_stops_the_chain_before_anything_is_run(
    stages, session_file, monkeypatch
):
    """Litterointi kestää tunnin. Miksausta ei saa huomata puuttuvaksi sen jälkeen."""
    monkeypatch.setattr(chain.mixer, "command", lambda: None)

    with pytest.raises(RuntimeError, match="automixer"):
        _go(session_file, chain.Steps(transcribe=True, silence=True, mix=True))

    assert stages == []


def test_a_missing_mixer_does_not_matter_when_mixing_is_not_chosen(
    stages, session_file, monkeypatch
):
    monkeypatch.setattr(chain.mixer, "command", lambda: None)

    _go(session_file, chain.Steps(transcribe=True, silence=True, mix=False))

    assert [name for name, _ in stages] == ["transcribe", "silence"]


def test_choosing_nothing_is_a_stated_error(stages, session_file):
    with pytest.raises(RuntimeError, match="vaihe"):
        _go(session_file, chain.Steps(transcribe=False, silence=False, mix=False))


def test_a_cancel_between_stages_stops_the_next_one(stages, session_file, monkeypatch):
    progress = _progress()

    def transcribe(session, options, progress_, audio_dir="", force=False):
        stages.append(("transcribe", session))
        progress._job.cancel_requested = True
        return {"written": "x.nhsx"}

    monkeypatch.setattr(chain.transcribe_run, "run", transcribe)

    with pytest.raises(Cancelled):
        chain.run(
            str(session_file), chain.Steps(True, True, True), Options(), Settings(), progress
        )
    assert [name for name, _ in stages] == ["transcribe"]


def test_inner_progress_is_scaled_to_the_stage(session_file):
    """Vaiheen sisäinen «2/5» ei saa kirjoittaa koko ketjun «1/3»:n päälle."""
    progress = _progress()
    stage = chain.StageProgress(progress, "litterointi", index=1, total=3)

    stage.step("olli.wav", done=1, total=4)
    stage.fraction(0.5)

    job = progress._job
    assert (job.steps_done, job.steps_total) == (1, 3)
    assert job.step_label.startswith("litterointi")
    # Kolmannes ketjusta on tehty; vaiheesta puolitoista neljäsosaa 4:stä.
    assert job.fraction == pytest.approx((1 + 0.5) / 4)


# ---- miksaus ------------------------------------------------------------


def test_mixer_command_prefers_the_installed_script(monkeypatch):
    monkeypatch.setattr(mixer.shutil, "which", lambda name: "/usr/local/bin/automixer")

    assert mixer.command() == ["/usr/local/bin/automixer"]


def test_mixer_command_falls_back_to_the_module_in_this_environment(monkeypatch):
    monkeypatch.setattr(mixer.shutil, "which", lambda name: None)
    monkeypatch.setattr(mixer, "_importable", lambda name: True)
    monkeypatch.setattr(mixer.sys, "frozen", False, raising=False)

    assert mixer.command() == [sys.executable, "-m", "automixer.cli_mix"]


def test_a_packaged_app_cannot_borrow_its_own_interpreter(monkeypatch):
    """Paketissa ``sys.executable`` on sovellus itse: ``-m`` käynnistäisi toisen ikkunan."""
    monkeypatch.setattr(mixer.shutil, "which", lambda name: None)
    monkeypatch.setattr(mixer, "_importable", lambda name: True)
    monkeypatch.setattr(mixer.sys, "frozen", True, raising=False)

    assert mixer.command() is None


def test_no_mixer_anywhere_is_none(monkeypatch):
    monkeypatch.setattr(mixer.shutil, "which", lambda name: None)
    monkeypatch.setattr(mixer, "_importable", lambda name: False)

    assert mixer.command() is None


def test_mixer_output_is_a_new_file_beside_the_session(tmp_path):
    session = tmp_path / "jakso.nhsx"
    session.write_text("<Session/>")

    assert mixer.output_path(str(session)) == tmp_path / "jakso automixer.wav"
    (tmp_path / "jakso automixer.wav").write_bytes(b"")
    assert mixer.output_path(str(session)) == tmp_path / "jakso automixer v2.wav"


def test_the_mixer_is_called_with_session_output_and_loudness(
    monkeypatch, tmp_path
):
    session = tmp_path / "jakso.nhsx"
    session.write_text("<Session/>")
    seen: dict = {}

    class Fake:
        stdout = iter(["Detected Track Roles:\n", "  MIX: valmis\n"])

        def __init__(self, argv, **kw):
            seen["argv"] = argv

        def wait(self, timeout=None):
            # Automixer on kirjoittanut tiedoston kun se on valmis.
            Path(seen["argv"][3]).write_bytes(b"RIFF")
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(mixer, "command", lambda: ["automixer"])
    monkeypatch.setattr(mixer.subprocess, "Popen", Fake)
    progress = _progress()

    written = mixer.run(str(session), -18.0, progress)

    assert written == str(tmp_path / "jakso automixer.wav")
    assert seen["argv"] == [
        "automixer", str(session), "--output", written, "--target-lufs", "-18.0",
    ]
    # Automixerin oma tuloste näkyy työn lokissa. Pitkä ajo, jonka ainoa
    # merkki elämästä on pyörivä palkki, näyttää jumiutuneelta.
    assert any("MIX: valmis" in line for line in progress._job.log)


def test_a_failed_mixer_is_an_error_not_a_written_path(tmp_path):
    session = tmp_path / "jakso.nhsx"
    session.write_text("<Session/>")
    script = tmp_path / "fail.py"
    script.write_text("import sys; print('no tracks'); sys.exit(3)")

    original = mixer.command
    mixer.command = lambda: [sys.executable, str(script)]
    try:
        with pytest.raises(RuntimeError, match="3"):
            mixer.run(str(session), -16.0, _progress())
    finally:
        mixer.command = original


def test_automixer_returning_without_a_file_is_an_error(tmp_path):
    """Automixer palaa nollalla myös silloin kun raitoja ei löytynyt.

    Se tulostaa «No tracks found» ja lopettaa siististi. Ilman levyltä
    tehtävää tarkistusta ketju ilmoittaisi tiedostosta jota ei ole.
    """
    session = tmp_path / "jakso.nhsx"
    session.write_text("<Session/>")
    script = tmp_path / "quiet.py"
    script.write_text("print('No tracks found or specified.')")

    original = mixer.command
    mixer.command = lambda: [sys.executable, str(script)]
    try:
        with pytest.raises(RuntimeError, match="ei kirjoittanut"):
            mixer.run(str(session), -16.0, _progress())
    finally:
        mixer.command = original


def test_cancelling_stops_the_mixer_process(tmp_path):
    session = tmp_path / "jakso.nhsx"
    session.write_text("<Session/>")
    script = tmp_path / "slow.py"
    script.write_text("import time\nprint('start', flush=True)\ntime.sleep(60)")
    progress = _progress()
    progress._job.cancel_requested = True

    original = mixer.command
    mixer.command = lambda: [sys.executable, str(script)]
    try:
        with pytest.raises(Cancelled):
            mixer.run(str(session), -16.0, progress)
    finally:
        mixer.command = original


# ---- rajapinta ----------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("podcastmagic.settings.state_dir", lambda: tmp_path / "state")
    (tmp_path / "state").mkdir()
    return TestClient(create_app(start_dir=str(tmp_path)))


def test_info_says_whether_the_mixer_is_there(client, monkeypatch):
    monkeypatch.setattr(mixer, "command", lambda: None)
    info = client.get("/api/chain/info").json()

    assert info["mixer"]["available"] is False
    assert info["mixer"]["install"]
    assert info["steps"] == {"transcribe": True, "silence": True, "mix": True}
    assert info["targetLufs"] == -16.0


def test_choosing_nothing_is_a_400(client, session_file):
    response = client.post(
        "/api/chain/run",
        json={"session": str(session_file),
              "steps": {"transcribe": False, "silence": False, "mix": False}},
    )
    assert response.status_code == 400
    assert "vaihe" in response.json()["detail"]


def test_mix_without_a_mixer_is_refused_at_the_door(client, session_file, monkeypatch):
    """409 tai 400 heti, ei työ joka kuolee: käyttäjä näkee syyn ilman lokia."""
    monkeypatch.setattr(mixer, "command", lambda: None)
    response = client.post(
        "/api/chain/run",
        json={"session": str(session_file),
              "steps": {"transcribe": True, "silence": True, "mix": True}},
    )
    assert response.status_code == 400
    assert "automixer" in response.json()["detail"]


def test_the_chosen_steps_are_remembered(client, session_file, monkeypatch):
    from podcastmagic import settings as saved
    from podcastmagic.jobs import RUNNER

    monkeypatch.setattr(RUNNER, "start", lambda module, label, work: Job(
        id=1, module=module, label=label))
    client.post(
        "/api/chain/run",
        json={"session": str(session_file), "targetLufs": -18,
              "steps": {"transcribe": False, "silence": True, "mix": False}},
    )

    assert saved.section("chain") == {
        "steps": {"transcribe": False, "silence": True, "mix": False},
        "targetLufs": -18.0,
    }


def test_the_chain_is_a_module_with_its_script():
    from podcastmagic.modules import MODULES
    from podcastmagic.paths import get_resource_path

    keys = [m.key for m in MODULES]
    assert "chain" in keys
    assert (get_resource_path("server/static") / "mod_chain.js").is_file()


def test_the_mixer_is_not_a_dependency_of_this_app():
    """Miksain ajetaan komentona eikä tuoda.

    Se vetäisi mukanaan mlx:n, pedalboardin ja textualin, ja pakattu
    sovellus kasvaisi niiden verran vaikka ketjun miksausvaihe jäisi
    käyttämättä. Jos tämä joskus muuttuu, muutos tehdään tahallaan.
    """
    import tomllib

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    deps = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    assert not any(d.split("[")[0].strip().lower().startswith("automixer") for d in deps)


# ---- komentorivi --------------------------------------------------------


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Komentorivin ajo ilman oikeita vaiheita; ``seen`` kertoo mitä ketju sai."""
    from podcastmagic import __main__ as entry
    from podcastmagic.chain import cli as chain_cli

    monkeypatch.setattr("podcastmagic.settings.state_dir", lambda: tmp_path / "state")
    (tmp_path / "state").mkdir()
    seen: dict = {}

    def fake(session, steps, options, settings, progress, **kw):
        seen.update(session=session, steps=steps, kw=kw)
        return {"written": str(tmp_path / "ulos.wav"), "stages": []}

    monkeypatch.setattr(chain_cli.runner, "run", fake)
    return entry.main, seen


def test_one_command_runs_the_whole_chain(cli, session_file):
    main, seen = cli

    assert main([str(session_file), "--chain"]) == 0

    assert seen["session"] == str(session_file)
    assert seen["steps"] == chain.Steps(True, True, True)


def test_the_command_line_picks_stages_by_name(cli, session_file):
    main, seen = cli

    assert main([str(session_file), "--chain", "--steps", "silence,mix"]) == 0

    assert seen["steps"] == chain.Steps(transcribe=False, silence=True, mix=True)


def test_the_command_line_takes_loudness_and_audio_folder(cli, session_file, tmp_path):
    main, seen = cli

    main([str(session_file), "--chain", "--lufs", "-18", "--audio-dir", str(tmp_path)])

    assert seen["kw"]["target_lufs"] == -18.0
    assert seen["kw"]["audio_dir"] == str(tmp_path)


def test_an_unknown_stage_name_is_refused_before_anything_runs(cli, session_file, capsys):
    main, seen = cli

    with pytest.raises(SystemExit) as stopped:
        main([str(session_file), "--chain", "--steps", "silence,masterointi"])

    assert stopped.value.code == 2
    assert "masterointi" in capsys.readouterr().err
    assert seen == {}


def test_a_failing_chain_is_exit_one_with_the_reason(cli, session_file, capsys, monkeypatch):
    from podcastmagic.chain import cli as chain_cli

    main, _ = cli

    def broken(*a, **k):
        raise RuntimeError("Istunnossa ei ole litterointia.")

    monkeypatch.setattr(chain_cli.runner, "run", broken)

    assert main([str(session_file), "--chain"]) == 1
    assert "litterointia" in capsys.readouterr().err


def test_the_chain_needs_a_session(cli, tmp_path, monkeypatch, capsys):
    main, seen = cli
    monkeypatch.chdir(tmp_path)

    assert main(["--chain"]) == 1
    assert seen == {}
    assert "istunto" in capsys.readouterr().err.lower()


def test_the_command_line_uses_the_settings_saved_in_the_tabs(cli, session_file, monkeypatch):
    """Sama sääntö kuin napilla: ketjulla ei ole omia asetuksia."""
    from podcastmagic import settings as saved
    from podcastmagic.chain import cli as chain_cli

    main, _ = cli
    saved.save("silence", {"tail": 1.5, "gap": 0.3, "rms": False})
    saved.save("transcribe", {"language": "sv"})
    got: dict = {}

    def capture(session, steps, options, settings, progress, **kw):
        got.update(options=options, settings=settings)
        return {"written": ""}

    monkeypatch.setattr(chain_cli.runner, "run", capture)
    main([str(session_file), "--chain"])

    assert got["settings"].tail == 1.5 and got["settings"].rms is False
    assert got["options"].language == "sv"
