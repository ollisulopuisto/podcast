"""Hindenburgin istunto stemeinä levyllä: autoraffkatin putki automixerissa.

47 minuutin jakso ei mahtunut 32 GB:n koneeseen (vst s13e03, 2026-10-06):
automixer piti jokaisen raidan ja summan muistissa kokonaisena. Nyt raita
käsitellään kerrallaan levylle ja ohjelma virtaa paloittain
(``speechmix.stems``), kuten autoraffkatissa.
"""

from __future__ import annotations

import tracemalloc

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy import signal

from automixer import stems_mix

RATE = 48000


def _speaker(seconds, turns, hz, rng):
    """Puheen kaltainen raita: vuorot, tavujen rytmi, pohjakohina."""
    n = int(seconds * RATE)
    t = np.arange(n) / RATE
    voice = 0.25 * np.sin(2 * np.pi * hz * t) * (0.55 + 0.45 * np.sin(2 * np.pi * 4 * t))
    on = np.zeros(n, dtype=bool)
    for a, b in turns:
        on[int(a * RATE):int(b * RATE)] = True
    x = np.where(on, voice, 0.0) + rng.normal(0, 2e-4, n)
    return x.astype(np.float32)


def _session(tmp_path, seconds=40.0, speakers=2, bed=True):
    rng = np.random.default_rng(7)
    files, tracks = [], []
    for i in range(speakers):
        # Vuorotellen 3 s kukin, tauko 20–28 s pohjaa varten.
        turns = [(a, a + 3.0) for a in np.arange(3.0 * i, seconds, 3.0 * speakers)
                 if not (20.0 <= a < 28.0)]
        name = f"p{i}.wav"
        sf.write(tmp_path / name, _speaker(seconds, turns, 140 + 50 * i, rng), RATE)
        files.append(f'<File Id="{i + 1}" Name="{name}"/>')
        tracks.append(
            f'<Track Name="P{i}"><Region Ref="{i + 1}" Length="{seconds:.3f}" '
            f'IsMusic="False"/></Track>'
        )
    if bed:
        music = rng.normal(0, 0.1, (int(12 * RATE), 2)).astype(np.float32)
        sf.write(tmp_path / "bed.wav", music, RATE)
        files.append(f'<File Id="{speakers + 1}" Name="bed.wav" Channels="2"/>')
        tracks.append(
            f'<Track Name="musa"><Region Ref="{speakers + 1}" Start="18.000" '
            f'Length="12.000" FadeIn="0.200"><Fade Start="0.000" Length="2.000" '
            f'Gain="-12"/><Fade Start="2.500" Length="1.500" Gain="0"/>'
            f'<Fade Start="8.000" Length="2.000" Gain="-60"/></Region></Track>'
        )
    path = tmp_path / "jakso.nhsx"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<Session Samplerate="48000">
  <AudioPool Path="" Location="{tmp_path}">{''.join(files)}</AudioPool>
  <Tracks>{''.join(tracks)}</Tracks>
</Session>""", encoding="utf-8")
    return path


def _true_peak_db(x):
    up = signal.resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.abs(up).max())


def test_a_session_is_mixed_to_the_target_through_stems(tmp_path, capsys):
    path = _session(tmp_path)
    out = tmp_path / "jakso automixer.wav"
    stems_mix.mix(str(path), str(out), target_lufs=-16.0)

    mix, rate = sf.read(out, always_2d=True)
    assert rate == RATE and mix.shape[1] == 2
    assert abs(len(mix) - 40 * RATE) <= 1
    # Masterointi tähtää puheen äänekkyyteen (puheportti, kuten
    # autoraffkatissa): 40 sekunnin testissä 12 s pohjaa +7 dB puheen yllä
    # nostaa koko tiedoston lukemaa, 47 minuutin jaksossa ei (−16,27).
    lufs = pyln.Meter(RATE).integrated_loudness(mix[int(30 * RATE):])
    assert abs(lufs - -16.0) < 0.6, lufs
    assert _true_peak_db(mix) <= -1.0 + 0.1

    # Pohja soi tauolla, stereona: kanavat eivät ole sama signaali.
    gap = mix[int(22.5 * RATE):int(25.5 * RATE)]
    assert 20 * np.log10(np.sqrt(np.mean(gap ** 2))) > -40
    assert np.corrcoef(gap[:, 0], gap[:, 1])[0, 1] < 0.5
    # Häivytys hiljaisuuteen: pohjan lopussa ei ole musiikkia. Sivusignaali
    # (L−R) on musiikkia — puhe on lähes keskellä — joten se mitataan suoraan.
    # Mitattu: tauolla −18,9 dB, häivytyksen jälkeen −78,9.
    def side_db(a, b):
        seg = mix[int(a * RATE):int(b * RATE)]
        return 20 * np.log10(np.sqrt(np.mean(((seg[:, 0] - seg[:, 1]) / 2) ** 2)) + 1e-12)

    assert side_db(28.5, 29.5) < side_db(22.5, 25.5) - 40

    # Työhakemisto siivotaan.
    assert not list(tmp_path.glob("automixer-*"))


def test_memory_follows_one_stem_not_the_number_of_tracks(tmp_path):
    """Raita kerrallaan levylle: neljä puhujaa ei saa viedä kaksinkertaista
    muistia kahteen verrattuna. Muistissa koottu ohjelma kasvoi raitojen
    määrän mukana."""

    def peak(speakers):
        here = tmp_path / f"s{speakers}"
        here.mkdir()
        path = _session(here, seconds=60.0, speakers=speakers, bed=False)
        tracemalloc.start()
        stems_mix.mix(str(path), str(here / "out.wav"), target_lufs=-16.0)
        _, top = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return top

    two, four = peak(2), peak(4)
    assert four < 1.5 * two, (two, four)


def test_the_bed_is_no_louder_than_the_speech(tmp_path):
    """Pohjan tasanne puheen tasolla, ei yli: käyttäjä, 2026-10-07 — «music
    at most at −16 LUFS, the same as the speech». +7 dB (sovitettu
    Hindenburgin istunnosta, käsittelemätöntä puhetta vasten) teki
    valmiissa miksauksessa intropohjasta +7…+10 dB puhetta kovemman; käyttäjän
    oma master: +1,2. Taso asetetaan **käsitellystä** puheesta mitattuna."""
    path = _session(tmp_path, seconds=40.0)
    out = tmp_path / "mix.wav"
    stems_mix.mix(str(path), str(out), target_lufs=-16.0)
    mix, _ = sf.read(out, always_2d=True)
    meter = pyln.Meter(RATE)
    bed = meter.integrated_loudness(mix[int(21.0 * RATE):int(25.5 * RATE)])
    speech = meter.integrated_loudness(mix[int(30.0 * RATE):int(40.0 * RATE)])
    assert bed <= speech + 0.5, (bed, speech)
    assert abs((bed - speech) - stems_mix.BED_UNDER_SPEECH_DB) < 1.0, bed - speech


def test_a_hot_take_is_brought_to_the_speakers_level(tmp_path, capsys):
    """Ollin intro oli +8…+13 dB hänen tasonsa yllä (vst s13e03), ja
    käyttäjä laski sen alueen vahvistuksella. Sama automaattisesti:
    lohkotaso ennen ketjua (``speechmix.blocks``)."""
    path = _session(tmp_path, seconds=40.0, bed=False)
    p0, _ = sf.read(tmp_path / "p0.wav")
    p0[: int(9.5 * RATE)] *= 10 ** (10 / 20)      # kaksi ensimmäistä vuoroa +10 dB
    sf.write(tmp_path / "p0.wav", p0.astype(np.float32), RATE)

    out = tmp_path / "mix.wav"
    stems_mix.mix(str(path), str(out), target_lufs=-16.0)
    mix, _ = sf.read(out, always_2d=True)
    meter = pyln.Meter(RATE)

    def level(a, b):
        seg = mix[int(a * RATE):int(b * RATE)]
        return meter.integrated_loudness(seg)

    hot = level(0.5, 2.5)
    normal = level(30.5, 32.5)
    # Ilman lohkotasoa ketju (kuljettaja, kompressorit) jättää tällä
    # signaalilla +2,7 dB; lohkotaso ennen ketjua vie sen alle 1,5:n.
    assert abs(hot - normal) < 1.5, (hot, normal)
    assert "block" in capsys.readouterr().out


def _with_shout(tmp_path):
    path = _session(tmp_path, seconds=40.0, bed=False)
    p0, _ = sf.read(tmp_path / "p0.wav")
    # Pitkä vuoro 30–39 s (kuten Ollin 14 s:n lohko 36:41), huuto keskellä.
    p0[int(33 * RATE):int(36 * RATE)] = p0[int(30 * RATE):int(33 * RATE)]
    p0[int(33.5 * RATE):int(35.3 * RATE)] *= 10 ** (8 / 20)
    sf.write(tmp_path / "p0.wav", p0.astype(np.float32), RATE)
    return path


def test_a_loud_stretch_is_listed_for_listening_not_changed(tmp_path):
    path = _with_shout(tmp_path)
    out = tmp_path / "mix.wav"
    stems_mix.mix(str(path), str(out), target_lufs=-16.0)
    listing = (tmp_path / "mix flags.txt").read_text(encoding="utf-8")
    line = next(x for x in listing.splitlines() if "P0" in x and "loud" in x)
    assert line.startswith("0:33")


def test_flags_only_writes_the_list_without_a_mix(tmp_path, monkeypatch):
    from automixer import cli_mix

    path = _with_shout(tmp_path)
    monkeypatch.setattr("sys.argv", ["automixer", str(path), "--flags-only"])
    cli_mix.main()
    assert (tmp_path / "jakso automixer flags.txt").exists()
    assert not (tmp_path / "jakso automixer.wav").exists()
    assert not list(tmp_path.glob("automixer-*"))


def test_stems_in_parallel_give_the_same_mix(tmp_path, monkeypatch, capsys):
    """Kaksi stemiä kerrallaan kun muisti riittää — ja tulos on sama kuin
    yksi kerrallaan, bitilleen. Stemit eivät jaa tilaa keskenään."""
    path = _session(tmp_path, seconds=40.0)
    monkeypatch.setenv("SPEECHMIX_PARALLEL_STEMS", "1")
    stems_mix.mix(str(path), str(tmp_path / "one.wav"), target_lufs=-16.0)
    assert "stems at a time" not in capsys.readouterr().out

    monkeypatch.delenv("SPEECHMIX_PARALLEL_STEMS")
    stems_mix.mix(str(path), str(tmp_path / "two.wav"), target_lufs=-16.0)
    assert "2 stems at a time" in capsys.readouterr().out
    one, _ = sf.read(tmp_path / "one.wav")
    two, _ = sf.read(tmp_path / "two.wav")
    assert np.array_equal(one, two)
