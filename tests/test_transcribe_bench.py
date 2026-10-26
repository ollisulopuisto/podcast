"""Litteroinnin mittari: kellotettu ajo ja sanojen alkujen vertailu käsin merkittyihin.

Mittari ei aja mallia: komento rakennetaan funktiolla ja vertailu on puhdasta
laskentaa, joten kaikki todistetaan täällä ilman Macia, MLX:ää tai Colabia.
Mitä mittari sanoo oikealla äänellä, kertoo vasta oikea ajo.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "transcribe_bench", ROOT / "scripts" / "ab" / "transcribe_bench.py"
)
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)


def words(*rows):
    return {"version": 1, "timing": "test", "language": "fi",
            "words": [{"w": w, "s": s, "e": s + 0.2} for w, s in rows]}


MARKS = """
TAUON JÄLKEEN
12.000 Terve 12.400
31.500 Jatketaan 31.900
SISÄLLÄ
50.000 niin 50.100
"""


def test_the_command_runs_the_cli_in_audio_mode_for_each_backend(tmp_path):
    for backend in ("colab", "parakeet", "orukeet"):
        cmd = tb.command(tmp_path / "a.wav", tmp_path / "ulos", backend)
        assert cmd[:4] == ["uv", "run", "--package", "colab-transcribe"]
        assert cmd[cmd.index("--audio") + 1] == str(tmp_path / "a.wav")
        assert cmd[cmd.index("--json") + 1] == str(tmp_path / "ulos")
        assert cmd[cmd.index("--backend") + 1] == backend


def test_an_unknown_backend_is_refused_before_anything_runs(tmp_path):
    with pytest.raises(ValueError, match="backend"):
        tb.command(tmp_path / "a.wav", tmp_path / "ulos", "whispercpp")


def test_the_real_time_factor_is_audio_seconds_over_wall_seconds():
    assert tb.realtime_factor(3600.0, 60.0) == pytest.approx(60.0)
    assert tb.realtime_factor(10.0, 0.0) is None  # kello ei saa antaa «ääretöntä»
    assert tb.realtime_factor(0.0, 5.0) is None


def test_a_mark_is_matched_by_text_to_the_word_nearest_its_own_time():
    rows = words(("terve", 11.8), ("Terve,", 40.0), ("jatketaan.", 31.4), ("niin", 50.3))
    table = tb.compare(tb.parse_marks(MARKS), rows)
    by_word = {t["word"]: t for t in table}
    # Välimerkit ja kirjainkoko eivät ratkaise; lähin oma aika voittaa kaksoiskappaleen.
    assert by_word["Terve"]["estimate"] == pytest.approx(11.8)
    assert by_word["Jatketaan"]["estimate"] == pytest.approx(31.4)
    assert by_word["niin"]["estimate"] == pytest.approx(50.3)


def test_among_duplicates_inside_the_window_the_nearest_to_my_time_wins():
    """Sama sana kahdesti ikkunassa: ensimmäinen listassa ei saa voittaa vain järjestyksensä vuoksi."""
    rows = words(("terve", 11.0), ("terve", 12.3))
    table = tb.compare(tb.parse_marks(MARKS), rows)
    assert next(t for t in table if t["word"] == "Terve")["estimate"] == pytest.approx(12.3)


def test_the_error_is_mine_minus_the_estimate_so_plus_means_the_estimate_is_early():
    table = tb.compare(tb.parse_marks(MARKS), words(("Terve", 12.100)))
    entry = next(t for t in table if t["word"] == "Terve")
    assert entry["error"] == pytest.approx(0.300)


def test_a_word_outside_the_window_or_with_other_text_is_unmatched_not_guessed():
    rows = words(("Terve", 12.0 + tb.WINDOW_S + 0.5), ("jatkoa", 31.5))
    table = tb.compare(tb.parse_marks(MARKS), rows)
    assert [t["estimate"] for t in table] == [None, None, None]
    assert all(t["error"] is None for t in table)
    summary = tb.summarize(table)["kaikki"]
    assert summary["n"] == 3 and summary["matched"] == 0 and summary["median"] is None


def test_the_summary_counts_hits_within_30_ms_and_reports_the_median():
    rows = words(("Terve", 12.380), ("Jatketaan", 31.300), ("niin", 50.100))
    summary = tb.summarize(tb.compare(tb.parse_marks(MARKS), rows))
    total = summary["kaikki"]
    assert total["n"] == 3 and total["matched"] == 3
    assert total["hits"] == 2  # +20 ms ja 0 ms; Jatketaan on +600 ms
    assert total["median"] == pytest.approx(0.020)
    assert summary["tauon jälkeen"]["n"] == 2
    assert summary["sisällä"]["n"] == 1


def test_two_transcripts_are_reported_side_by_side_with_the_same_marks():
    new = words(("Terve", 12.400), ("Jatketaan", 31.900), ("niin", 50.100))
    old = words(("Terve", 11.900), ("Jatketaan", 31.000), ("niin", 49.900))
    text = tb.report(tb.parse_marks(MARKS), {"uusi": new, "vanha": old})
    assert "uusi" in text and "vanha" in text
    assert "Jatketaan" in text
    # Mittari sanoo itse mitä se ei todista.
    assert "yksi puhuja" in text.lower()


def test_a_words_file_without_words_is_refused_with_the_reason(tmp_path):
    bad = tmp_path / "x.words.json"
    bad.write_text(json.dumps({"version": 1}), encoding="utf-8")
    with pytest.raises(SystemExit, match="words"):
        tb.load_words(bad)
    ok = tmp_path / "y.words.json"
    ok.write_text(json.dumps(words(("Terve", 1.0))), encoding="utf-8")
    assert tb.load_words(ok)["words"][0]["w"] == "Terve"


def test_the_compare_command_prints_a_report_from_files(tmp_path, capsys):
    marks = tmp_path / "merkinnat.txt"
    marks.write_text(MARKS, encoding="utf-8")
    new = tmp_path / "uusi.words.json"
    new.write_text(json.dumps(words(("Terve", 12.39), ("Jatketaan", 31.9))), encoding="utf-8")
    code = tb.main(["compare", str(new), "--marks", str(marks)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Terve" in out and "mediaani" in out


def test_the_run_command_times_the_process_and_writes_the_bench_file(tmp_path, monkeypatch):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"x")
    out = tmp_path / "ulos"
    clock = iter([100.0, 160.0])
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        out.mkdir()
        (out / "jakso.words.json").write_text(json.dumps(words(("Terve", 1.0))), encoding="utf-8")

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(tb.subprocess, "run", fake_run)
    code = tb.main(["run", str(audio), "--out", str(out), "--backend", "parakeet",
                    "--seconds", "3600"], clock=lambda: next(clock))
    assert code == 0
    bench = json.loads((out / "jakso.bench.json").read_text(encoding="utf-8"))
    assert bench["wall_s"] == pytest.approx(60.0)
    assert bench["audio_s"] == pytest.approx(3600.0)
    assert bench["realtime_factor"] == pytest.approx(60.0)
    assert bench["backend"] == "parakeet" and bench["words"] == 1
    assert seen["cmd"][seen["cmd"].index("--backend") + 1] == "parakeet"


def test_a_failed_run_does_not_write_a_bench_file(tmp_path, monkeypatch):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"x")
    out = tmp_path / "ulos"

    class Failed:
        returncode = 1

    def fail_after_writing(cmd, **kwargs):
        # Tulostiedosto on olemassa, mutta ajo kertoo epäonnistuneensa: vain
        # poistumiskoodi voi pysäyttää tämän, ei tiedoston puuttuminen.
        out.mkdir()
        (out / "jakso.words.json").write_text(json.dumps(words(("Terve", 1.0))), encoding="utf-8")
        return Failed()

    monkeypatch.setattr(tb.subprocess, "run", fail_after_writing)
    code = tb.main(["run", str(audio), "--out", str(out), "--backend", "colab",
                    "--seconds", "10"], clock=lambda: 0.0)
    assert code == 1
    assert not (out / "jakso.bench.json").exists()


def test_a_run_whose_words_file_is_missing_is_a_failure_even_if_the_exit_was_zero(
    tmp_path, monkeypatch
):
    """Exit 0 ilman tulostiedostoa ei ole onnistuminen: sama hiljainen vika kuin aina."""
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"x")

    class Done:
        returncode = 0

    monkeypatch.setattr(tb.subprocess, "run", lambda cmd, **kw: Done())
    code = tb.main(["run", str(audio), "--out", str(tmp_path / "ulos"), "--backend",
                    "orukeet", "--seconds", "10"], clock=lambda: 0.0)
    assert code == 1


def test_an_old_words_file_does_not_stand_in_for_a_run_that_wrote_nothing(tmp_path, monkeypatch):
    audio = tmp_path / "jakso.wav"
    audio.write_bytes(b"x")
    out = tmp_path / "ulos"
    out.mkdir()
    (out / "jakso.words.json").write_text(json.dumps(words(("Vanha", 1.0))), encoding="utf-8")

    class Done:
        returncode = 0

    monkeypatch.setattr(tb.subprocess, "run", lambda cmd, **kw: Done())
    code = tb.main(["run", str(audio), "--out", str(out), "--backend", "parakeet",
                    "--seconds", "10"], clock=lambda: 0.0)
    assert code == 1
    assert not (out / "jakso.bench.json").exists()
