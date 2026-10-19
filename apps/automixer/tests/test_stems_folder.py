"""Kansio stemejä ja ``tracks.json`` levypohjaisen reitin kautta.

kuulas vie jokaisen raidan omaksi WAViksi ja luettelon (``tracks.json``)
kansioon. Ennen tätä automixer luki sellaiset muistiin (``Mixer``), ja sama
koodikommentti joka vei Hindenburgin istunnon levypohjaiselle reitille kertoo
miksi se ei kelpaa: 47 minuutin jakso ei mahtunut 32 GB:n koneeseen. Nyt
kansio kulkee saman ``stems_mix``-putken kautta kuin ``.nhsx``.
"""

from __future__ import annotations

import json

import numpy as np
import pyloudnorm as pyln
import pytest
import soundfile as sf

from automixer import cli_mix, stems_mix
from speechmix import stems

RATE = 48000


def _speaker(seconds, turns, hz, rng):
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    voice = 0.25 * np.sin(2 * np.pi * hz * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 4 * t))
    on = np.zeros(n, dtype=bool)
    for a, b in turns:
        on[int(a * RATE) : int(b * RATE)] = True
    return (np.where(on, voice, 0.0) + rng.normal(0, 2e-4, n)).astype(np.float32)


def _folder(tmp_path, seconds=40.0, speakers=2, bed=True, gains=None, subtype="PCM_24"):
    """Kansio kuten kuulas sen vie: yksi WAV raitaa kohti, kaikki saman mittaisia."""
    rng = np.random.default_rng(7)
    folder = tmp_path / "Pääeditio 2026-10-19 v1"
    folder.mkdir()
    n = int(seconds * RATE)
    tracks = []
    for i in range(speakers):
        turns = [
            (a, a + 3.0)
            for a in np.arange(3.0 * i, seconds, 3.0 * speakers)
            if not (20.0 <= a < 28.0)
        ]
        name = f"Pääeditio – P{i}.wav"
        sf.write(
            folder / name,
            _speaker(seconds, turns, 140 + 50 * i, rng),
            RATE,
            subtype=subtype,
        )
        tracks.append(
            {
                "id": f"t{i}",
                "name": f"P{i}",
                "kind": "speech",
                "speaker": "",
                "channels": 1,
                "file": name,
                "audible": True,
                "gain_db": (gains or {}).get(f"P{i}", 0.0),
                "pan": 0.0,
            }
        )
    if bed:
        music = np.zeros((n, 2), dtype=np.float32)
        music[int(18 * RATE) : int(30 * RATE)] = rng.normal(0, 0.1, (12 * RATE, 2))
        # Pehmeä alku ja loppu, kuten kuulaksen vienti jättää ne.
        for a, b in ((18, 20), (28, 30)):
            ramp = np.linspace(0, 1, 2 * RATE, dtype=np.float32)
            seg = slice(int(a * RATE), int(b * RATE))
            music[seg] *= (ramp if a == 18 else ramp[::-1])[:, None]
        name = "Pääeditio – musiikit MUSIC.wav"
        sf.write(folder / name, music, RATE, subtype=subtype)
        tracks.append(
            {
                "id": "tm",
                "name": "musiikit",
                "kind": "music",
                "speaker": "",
                "channels": 2,
                "file": name,
                "audible": True,
                "gain_db": 0.0,
                "pan": 0.0,
            }
        )
    manifest = {
        "edit": "Pääeditio",
        "project": "p",
        "version": 1,
        "rate": RATE,
        "start_frame": 0,
        "frames": n,
        "processing": "dry",
        "format": "wav",
        "bit_depth": 24,
        "tracks": tracks,
    }
    (folder / "tracks.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return folder


def _edit(folder, change):
    path = folder / "tracks.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _mix(folder, out, **kwargs):
    stems_mix.mix_folder(str(folder), str(out), target_lufs=-16.0, **kwargs)
    audio, rate = sf.read(out, always_2d=True)
    assert rate == RATE
    return audio


def test_a_folder_of_stems_is_mixed_to_the_target_through_stems(tmp_path):
    folder = _folder(tmp_path)
    out = tmp_path / "out.wav"
    mix = _mix(folder, out)

    assert mix.shape[1] == 2 and abs(len(mix) - 40 * RATE) <= 1
    lufs = pyln.Meter(RATE).integrated_loudness(mix[int(30 * RATE) :])
    assert abs(lufs - -16.0) < 0.6, lufs
    # Pohja soi tauolla stereona: kanavat eivät ole sama signaali.
    gap = mix[int(22.5 * RATE) : int(25.5 * RATE)]
    assert 20 * np.log10(np.sqrt(np.mean(gap**2))) > -40
    assert np.corrcoef(gap[:, 0], gap[:, 1])[0, 1] < 0.5
    assert not list(tmp_path.glob("automixer-*"))
    assert not list(folder.glob("automixer-*"))


def test_the_mix_is_the_one_the_session_route_gives(tmp_path):
    """Sama puhe samoilla paikoilla: levypohjainen kansio ja ``.nhsx`` antavat
    saman miksauksen. Puhe käy kummassakin saman ``stems_mix``-rungon läpi."""
    folder = _folder(tmp_path, bed=False)
    session = tmp_path / "jakso.nhsx"
    files, tracks = [], []
    for i in range(2):
        name = f"Pääeditio – P{i}.wav"
        files.append(f'<File Id="{i + 1}" Name="{name}"/>')
        tracks.append(
            f'<Track Name="P{i}"><Region Ref="{i + 1}" Length="40.000" '
            f'IsMusic="False"/></Track>'
        )
    session.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Samplerate="48000">
  <AudioPool Path="" Location="{folder}">{"".join(files)}</AudioPool>
  <Tracks>{"".join(tracks)}</Tracks>
</Session>""",
        encoding="utf-8",
    )

    from_folder = _mix(folder, tmp_path / "a.wav")
    stems_mix.mix(str(session), str(tmp_path / "b.wav"), target_lufs=-16.0)
    from_session, _ = sf.read(tmp_path / "b.wav", always_2d=True)

    assert from_folder.shape == from_session.shape
    # 24-bittinen stemi vs. FLOAT-stemi: sama signaali kvantisointiin asti.
    diff = 20 * np.log10(np.sqrt(np.mean((from_folder - from_session) ** 2)) + 1e-12)
    ref = 20 * np.log10(np.sqrt(np.mean(from_session**2)))
    assert diff < ref - 50, (diff, ref)


def test_the_track_gain_is_not_applied_as_in_a_session(tmp_path):
    """``gain_db`` on raidan fader, ei otto: ``.nhsx``-reitti jättää sen pois
    (``clip.gain / clip.track_gain``) ja puhe tasataan joka tapauksessa."""
    a = _mix(
        _folder(tmp_path / "a" if (tmp_path / "a").mkdir() is None else tmp_path),
        tmp_path / "a.wav",
    )
    b_dir = tmp_path / "b"
    b_dir.mkdir()
    b = _mix(_folder(b_dir, gains={"P0": 6.0, "P1": -6.8}), tmp_path / "b.wav")
    np.testing.assert_array_equal(a, b)


def test_a_track_that_is_not_audible_is_left_out(tmp_path):
    """Hiljennetty raita ei soi eikä vaikuta muiden tasoon tai puheruudukkoon:
    sama kuin jos sitä ei olisi luettelossa lainkaan."""
    folder = _folder(tmp_path, speakers=3, bed=False)
    _edit(folder, lambda d: d["tracks"][2].update(audible=False))
    muted = _mix(folder, tmp_path / "a.wav")
    _edit(folder, lambda d: d["tracks"].pop(2))
    removed = _mix(folder, tmp_path / "b.wav")
    assert muted.shape == removed.shape
    np.testing.assert_array_equal(muted, removed)


# --- Kieltäytymiset: yksikään ei putoa nimiarvaukseen eikä korjaa hiljaa -----

REFUSALS = {
    "version": (lambda d: d.update(version=2), "version"),
    "rate": (lambda d: d.update(rate=44100), "44100"),
    "start": (lambda d: d.update(start_frame=480), "start_frame"),
    "processed": (lambda d: d.update(processing="compressed"), "dry"),
    "speech-mix": (lambda d: d["tracks"][0].update(kind="speech-mix"), "speech-mix"),
    "kind": (lambda d: d["tracks"][0].update(kind="video"), "video"),
    "frames": (lambda d: d.update(frames=d["frames"] + 5), "frames"),
    "missing": (lambda d: d["tracks"][1].update(file="puuttuu.wav"), "puuttuu.wav"),
    "channels": (lambda d: d["tracks"][0].update(channels=2), "P0"),
    "duplicate": (lambda d: d["tracks"][1].update(name="P0"), "P0"),
    "no-field": (lambda d: d["tracks"][0].pop("file"), "file"),
    "nothing-to-mix": (
        lambda d: [t.update(audible=False) for t in d["tracks"]],
        "audible",
    ),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_a_manifest_that_cannot_be_trusted_is_refused_by_name(tmp_path, case):
    change, word = REFUSALS[case]
    folder = _folder(tmp_path)
    _edit(folder, change)
    with pytest.raises(stems.StemError) as caught:
        stems_mix.mix_folder(str(folder), str(tmp_path / "out.wav"))
    assert word in str(caught.value)
    assert not (tmp_path / "out.wav").exists()
    assert not list(tmp_path.glob("automixer-*"))


def test_a_stem_whose_length_differs_from_the_manifest_is_refused(tmp_path):
    folder = _folder(tmp_path)
    name = "Pääeditio – P1.wav"
    audio, _ = sf.read(folder / name)
    sf.write(folder / name, audio[: len(audio) - RATE], RATE, subtype="PCM_24")
    with pytest.raises(stems.StemError) as caught:
        stems_mix.mix_folder(str(folder), str(tmp_path / "out.wav"))
    assert "P1" in str(caught.value) and "frames" in str(caught.value)


def test_a_stem_at_another_sample_rate_is_refused_even_with_the_same_frame_count(
    tmp_path,
):
    folder = _folder(tmp_path)
    name = "Pääeditio – P1.wav"
    audio, _ = sf.read(folder / name)
    # Sama kehysmäärä, eri taajuus: kehysten vertailu ei huomaa tätä.
    sf.write(folder / name, audio, 44100, subtype="PCM_24")
    with pytest.raises(stems.StemError) as caught:
        stems_mix.mix_folder(str(folder), str(tmp_path / "out.wav"))
    assert "P1" in str(caught.value) and "44100 Hz" in str(caught.value)


def test_a_speech_bus_is_refused_with_the_reason_and_the_way_out(tmp_path):
    folder = _folder(tmp_path)
    _edit(folder, lambda d: d["tracks"][0].update(kind="speech-mix"))
    with pytest.raises(stems.StemError) as caught:
        stems_mix.mix_folder(str(folder), str(tmp_path / "out.wav"))
    message = str(caught.value)
    assert "P0" in message and "several speakers" in message
    assert "separate" in message


def test_a_mono_music_stem_is_refused_not_guessed(tmp_path):
    folder = _folder(tmp_path)
    name = "Pääeditio – musiikit MUSIC.wav"
    audio, _ = sf.read(folder / name)
    sf.write(folder / name, audio[:, 0], RATE, subtype="PCM_24")
    _edit(folder, lambda d: d["tracks"][-1].update(channels=1))
    with pytest.raises(stems.StemError) as caught:
        stems_mix.mix_folder(str(folder), str(tmp_path / "out.wav"))
    assert "musiikit" in str(caught.value) and "stereo" in str(caught.value)


def test_a_manifest_that_is_not_json_is_refused(tmp_path):
    folder = _folder(tmp_path)
    (folder / "tracks.json").write_text("{ ei json", encoding="utf-8")
    with pytest.raises(stems.StemError) as caught:
        stems_mix.mix_folder(str(folder), str(tmp_path / "out.wav"))
    assert "tracks.json" in str(caught.value)


# --- Komentorivi ------------------------------------------------------------


def _run(monkeypatch, *argv):
    monkeypatch.setattr("sys.argv", ["automixer", *argv])
    return cli_mix.main()


def test_the_command_line_takes_a_folder_and_does_not_use_the_memory_route(
    tmp_path, monkeypatch
):
    folder = _folder(tmp_path)
    monkeypatch.setattr(cli_mix, "Mixer", lambda config: pytest.fail("memory route"))
    out = tmp_path / "ulos.wav"
    _run(monkeypatch, str(folder) + "/", "-o", str(out))
    assert out.exists()


def test_the_command_line_takes_the_manifest_file_itself(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    out = tmp_path / "ulos.wav"
    _run(monkeypatch, str(folder / "tracks.json"), "-o", str(out))
    assert out.exists()


def test_the_default_output_is_named_for_the_edit_and_lies_in_the_folder(
    tmp_path, monkeypatch
):
    folder = _folder(tmp_path)
    _run(monkeypatch, str(folder))
    assert (folder / "Pääeditio automixer.wav").exists()


def test_flags_only_on_a_folder_writes_the_list_without_a_mix(tmp_path, monkeypatch):
    folder = _folder(tmp_path)
    out = tmp_path / "ulos.wav"
    _run(monkeypatch, str(folder), "-o", str(out), "--flags-only")
    assert (tmp_path / "ulos flags.txt").exists()
    assert not out.exists()


def test_a_folder_is_mixed_on_its_own(tmp_path, monkeypatch, capsys):
    folder = _folder(tmp_path)
    other = tmp_path / "x.wav"
    sf.write(other, np.zeros(RATE, dtype=np.float32), RATE)
    for argv in ([str(folder), str(other)], [str(folder), "--speech", str(other)]):
        with pytest.raises(SystemExit) as caught:
            _run(monkeypatch, *argv, "-o", str(tmp_path / "ulos.wav"))
        assert caught.value.code not in (0, None)
        assert "on its own" in capsys.readouterr().out
        assert not (tmp_path / "ulos.wav").exists()


def test_a_folder_without_a_manifest_says_so_instead_of_a_format_error(
    tmp_path, monkeypatch, capsys
):
    folder = tmp_path / "tyhjä"
    folder.mkdir()
    with pytest.raises(SystemExit) as caught:
        _run(monkeypatch, str(folder), "-o", str(tmp_path / "ulos.wav"))
    assert caught.value.code not in (0, None)
    assert "tracks.json" in capsys.readouterr().out


def test_a_bad_manifest_on_the_command_line_exits_non_zero_with_the_reason(
    tmp_path, monkeypatch, capsys
):
    folder = _folder(tmp_path)
    _edit(folder, lambda d: d["tracks"][0].update(kind="speech-mix"))
    with pytest.raises(SystemExit) as caught:
        _run(monkeypatch, str(folder), "-o", str(tmp_path / "ulos.wav"))
    assert caught.value.code not in (0, None)
    assert "speech-mix" in capsys.readouterr().out


# --- Edistyminen ja poistumiskoodi kuulakselle ---------------------------------


def test_progress_is_reported_as_rising_percentages_ending_at_100(tmp_path):
    folder = _folder(tmp_path)
    seen = []
    stems_mix.mix_folder(
        str(folder),
        str(tmp_path / "out.wav"),
        progress=lambda pct, msg: seen.append((pct, msg)),
    )
    percents = [p for p, _ in seen]
    assert percents == sorted(percents)
    assert percents[-1] == 100 and 0 < percents[0] < 20
    assert all(isinstance(p, int) and isinstance(m, str) and m for p, m in seen)
    # Yksi päivitys per puhestemi, ja niiden prosentit nousevat tiukasti
    # lohkotarkistuksen (15) ja masteroinnin (80) välissä.
    steps = [p for p, m in seen if m.startswith("P")]
    assert len(steps) == 2
    assert 15 < steps[0] < steps[1] < 80, steps


def test_the_progress_flag_prints_one_parsable_line_per_update(
    tmp_path, monkeypatch, capsys
):
    import re

    folder = _folder(tmp_path)
    _run(monkeypatch, str(folder), "-o", str(tmp_path / "out.wav"), "--progress")
    lines = [
        ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("PROGRESS")
    ]
    assert lines and all(re.fullmatch(r"PROGRESS \d{1,3} \S.*", ln) for ln in lines)
    assert lines[-1].startswith("PROGRESS 100 ")


def test_without_the_flag_no_progress_lines_are_printed(tmp_path, monkeypatch, capsys):
    folder = _folder(tmp_path)
    _run(monkeypatch, str(folder), "-o", str(tmp_path / "out.wav"))
    assert "PROGRESS" not in capsys.readouterr().out


def test_no_tracks_exits_with_one_not_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as caught:
        _run(monkeypatch)
    assert caught.value.code == 1
    assert "No tracks" in capsys.readouterr().out


# --- Peruutus --------------------------------------------------------------


def test_sigterm_cancels_the_mix_and_removes_the_work_folder(tmp_path):
    """kuulas peruuttaa ``SIGTERM``illä. Työhakemisto (käsitellyt stemit levyllä,
    jakson kokoiset) ei saa jäädä tulostiedoston viereen."""
    import os
    import signal
    import subprocess
    import sys
    import time

    folder = _folder(tmp_path, seconds=120.0)
    out_dir = tmp_path / "ulos"
    out_dir.mkdir()
    out = out_dir / "out.wav"
    code = (
        "import sys; from automixer import cli_mix; "
        "sys.argv = ['automixer', sys.argv[1], '-o', sys.argv[2]]; cli_mix.main()"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(folder), str(out)],
        env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 60
        while not list(out_dir.glob("automixer-*")):
            assert proc.poll() is None, "the mix ended before it could be cancelled"
            assert time.time() < deadline, "no work folder appeared"
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        status = proc.wait(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert status != 0
    assert not list(out_dir.glob("automixer-*"))
    assert not out.exists()
