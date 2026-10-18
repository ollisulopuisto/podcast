"""Sanaleimojen mittari: kuinka kaukana Whisperin sanan alku on äänen nousevasta reunasta.

Oikeat jaksot ovat vain käyttäjän koneella, joten täällä todistetaan, että mittari
löytää tunnetut reunat tunnetusta aineistosta ja että sen kolme rehellisyyttä
pitävät: reunaa ei keksitä sanalle, jonka lähellä ei ole mitään; hidas
sisäänajo ei ole reuna; ja tauon jälkeiset sanat raportoidaan erikseen.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "word_onsets", ROOT / "scripts" / "ab" / "word_onsets.py"
)
wo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wo)

RATE = 16000


def _audio(
    bursts, seconds, floor_db=-70.0, level_db=-20.0, rise_s=0.010, db_ramp=False, seed=3
):
    """Kohinaa, jossa on purskeita ``(alku, kesto)`` sekunteina.

    Purskeen amplitudi nousee ``rise_s`` sekunnissa, joten alku on tunnettu
    ja terävä. ``db_ramp`` nostaa tasoa desibeleinä tasaisesti (hidas
    sisäänajo), ei lineaarisesti: lineaarinen nousu on desibeleinä jyrkkä
    juuri alussa.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    x = rng.standard_normal(n) * 10 ** (floor_db / 20)
    for start, length in bursts:
        a, b = int(start * RATE), int((start + length) * RATE)
        env = np.ones(b - a)
        r = max(1, int(rise_s * RATE))
        if db_ramp:
            env[:r] = 10 ** (np.linspace(-50, 0, r) / 20)
        else:
            env[:r] = np.linspace(0, 1, r)
        x[a:b] += rng.standard_normal(b - a) * 10 ** (level_db / 20) * env
    return x.astype(np.float32)


def _words(starts, length=0.3):
    return [
        {"word": f"w{i}", "start": s, "end": s + length} for i, s in enumerate(starts)
    ]


def test_onsets_are_found_where_the_bursts_start():
    x = _audio([(1.0, 0.4), (2.5, 0.4), (4.0, 0.4)], 6.0)
    found = wo.onset_times(x, RATE)
    assert len(found) == 3
    for truth, got in zip([1.0, 2.5, 4.0], found):
        assert abs(got - truth) < 0.003


def test_a_slow_fade_in_is_not_an_onset():
    x = _audio([(1.0, 1.5)], 4.0, rise_s=0.9, db_ramp=True)
    assert wo.onset_times(x, RATE) == []


def test_silence_has_no_onsets():
    assert wo.onset_times(_audio([], 3.0), RATE) == []


def test_offset_is_onset_minus_whisper_start():
    x = _audio([(1.0, 0.4), (2.5, 0.4), (4.0, 0.4)], 6.0)
    # Whisper on 80 ms liian aikaisin kaikissa.
    offsets = wo.word_offsets(_words([0.92, 2.42, 3.92]), wo.onset_times(x, RATE))
    assert [o is not None for o in offsets] == [True, True, True]
    for o in offsets:
        assert abs(o - 0.08) < 0.02


def test_a_word_with_no_onset_nearby_is_unmatched_not_zero():
    x = _audio([(1.0, 0.4)], 6.0)
    onsets = wo.onset_times(x, RATE)
    assert len(onsets) == 1
    # Yksin: reuna on vapaa, mutta kolme sekuntia kauempana kuin ikkuna sallii.
    assert wo.word_offsets(_words([4.0]), onsets) == [None]
    assert wo.word_offsets(_words([1.0]), onsets)[0] is not None


def test_an_edge_below_the_noise_floor_is_not_an_onset():
    # Kuusi sekuntia -70 dB:n kohinaa määrää lattian (20. persentiili; hiljaisuutta
    # on alle 20 %); sen jälkeen digitaalinen hiljaisuus ja -85 dB:n napsahdus,
    # joka nousee yli 15 dB mutta jää kohinalattian alapuolelle.
    rng = np.random.default_rng(5)
    noise = rng.standard_normal(6 * RATE) * 10 ** (-70 / 20)
    quiet = np.zeros(RATE)
    click = rng.standard_normal(int(0.2 * RATE)) * 10 ** (-85 / 20)
    quiet[RATE // 4 : RATE // 4 + click.size] = click
    x = np.concatenate([noise, quiet]).astype(np.float32)
    assert wo.onset_times(x, RATE) == []


def test_the_nearest_onset_wins_not_the_earlier_or_the_stronger():
    x = _audio([(1.00, 0.05), (1.15, 0.4)], 4.0)
    onsets = wo.onset_times(x, RATE)
    assert len(onsets) == 2
    # Sanan alku 1,12: toinen reuna (1,15) on lähempänä kuin ensimmäinen (1,00).
    (off,) = wo.word_offsets(_words([1.12]), onsets)
    assert abs(off - 0.03) < 0.02


def test_each_onset_is_claimed_by_one_word_only():
    x = _audio([(1.0, 0.4)], 4.0)
    offsets = wo.word_offsets(_words([0.95, 1.10]), wo.onset_times(x, RATE))
    # Kaksi sanaa ei voi alkaa samasta reunasta: lähempi saa sen.
    assert sum(o is not None for o in offsets) == 1
    assert offsets[0] is not None


def test_summary_splits_after_a_pause_from_inside_a_phrase():
    # Kolme sanaa tauon jälkeen (Whisper 150 ms aikaisin), kolme jatkona (20 ms).
    bursts = [(1.0, 0.2), (3.0, 0.2), (5.0, 0.2), (5.4, 0.2), (5.8, 0.2), (6.2, 0.2)]
    x = _audio(bursts, 8.0)
    words = _words([0.85, 2.85, 4.85, 5.38, 5.78, 6.18], length=0.38)
    summary = wo.summarize(words, wo.onset_times(x, RATE))
    assert summary["matched"] == 6
    assert summary["after_pause"]["n"] == 3
    assert summary["inside"]["n"] == 3
    assert abs(summary["after_pause"]["median"] - 0.15) < 0.02
    assert abs(summary["inside"]["median"] - 0.02) < 0.02


def test_verdict_names_a_constant_offset():
    offsets = [0.08, 0.075, 0.085, 0.082, 0.078, 0.081, 0.079, 0.083, 0.08, 0.08]
    assert wo.verdict(offsets).startswith("vakio")


def test_verdict_tells_which_way_to_move_the_stamps():
    early = [0.08, 0.075, 0.085, 0.082, 0.078, 0.081, 0.079, 0.083, 0.08, 0.08]
    assert "80 ms myöhemmäksi" in wo.verdict(early)
    late = [-o for o in early]
    assert "80 ms aikaisemmaksi" in wo.verdict(late)


def test_verdict_names_a_wide_spread():
    offsets = [-0.15, 0.2, 0.0, 0.12, -0.1, 0.18, -0.05, 0.1, -0.2, 0.15]
    assert wo.verdict(offsets).startswith("hajonta")


def test_verdict_says_nothing_to_fix_when_centred():
    offsets = [0.004, -0.006, 0.0, 0.003, -0.002, 0.005, -0.004, 0.001, 0.0, -0.001]
    assert wo.verdict(offsets).startswith("ei korjattavaa")


def test_verdict_refuses_on_too_few_words():
    assert wo.verdict([0.08, 0.08, 0.08]).startswith("liian vähän")


def test_load_words_reads_whisper_segments(tmp_path):
    data = {
        "segments": [
            {"words": [{"word": " Hei", "start": 1.0, "end": 1.3}]},
            {"words": [{"word": " maailma", "start": 2.0, "end": 2.6}]},
        ]
    }
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data))
    words = wo.load_words(p)
    assert [w["word"].strip() for w in words] == ["Hei", "maailma"]
    assert words[1]["start"] == 2.0


def test_load_words_reads_a_flat_list_and_skips_words_without_a_time(tmp_path):
    data = {"words": [{"word": "a", "start": 1.0, "end": 1.2}, {"word": "b"}]}
    p = tmp_path / "t.json"
    p.write_text(json.dumps(data))
    assert [w["word"] for w in wo.load_words(p)] == ["a"]


def test_load_words_refuses_a_file_without_words(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"segments": [{"text": "ei sanoja"}]}))
    with pytest.raises(SystemExit):
        wo.load_words(p)
