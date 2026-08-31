"""RunOptions: mitä kenttää pilvessä ajettavalle skriptille kerrotaan.

Nämä testit määrittävät rajapinnan ennen toteutusta. Ajettava skripti
(``colabtranscribe/colab/pipeline.py``) lukee argumenttinsa komennot-
merkkijonosta, joten argumenttilistan muoto on sopimus: jos se muuttuu,
muuttuu myös mitä pilvessä oikeasti ajetaan.
"""

from __future__ import annotations

import pytest

from colabtranscribe.options import GPUS, PRESETS, RunOptions, pipeline_args


def test_defaults_are_the_remote_preset():
    options = RunOptions()
    assert options.preset == "remote"
    assert options.gpu == "T4"
    assert options.rms is False
    assert options.thr == -35
    assert options.tail == 1.0
    assert options.gap == 1.0
    assert options.prompt  # täytesanoissa ei ole tyhjää


def test_gpu_choices():
    assert "T4" in GPUS and "A100" in GPUS


def test_preset_choices():
    assert set(PRESETS) == {"remote", "intra-mic"}


def test_unknown_gpu_is_rejected():
    with pytest.raises(ValueError, match="T9"):
        RunOptions(gpu="T9")


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="studio"):
        RunOptions(preset="studio")


def test_args_carry_every_setting():
    options = RunOptions(preset="intra-mic", rms=True, thr=-40, tail=0.5, gap=0.6)
    args = pipeline_args(options)
    assert "--preset" in args and "intra-mic" in args
    assert "--thr" in args and "-40" in args
    assert "--tail" in args and "0.5" in args
    assert "--gap" in args and "0.6" in args
    assert "--rms" in args


def test_rms_off_writes_no_flag():
    # --rms on store_true: poissa oleva lippu on poissa oleva asetus, ja se
    # on oikein — tyhjä arvo kertoisi jotain muuta.
    assert "--rms" not in pipeline_args(RunOptions())


def test_prompt_is_passed_on():
    options = RunOptions(prompt="öö, tota")
    args = pipeline_args(options)
    i = args.index("--prompt")
    assert args[i + 1] == "öö, tota"


def test_tail_and_gap_must_be_positive():
    with pytest.raises(ValueError, match="tail"):
        RunOptions(tail=-1.0)
    with pytest.raises(ValueError, match="gap"):
        RunOptions(gap=0.0)
