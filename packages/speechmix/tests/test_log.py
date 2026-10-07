"""Tarkempi loki: mitä pitkän vaiheen sisällä tapahtuu, vain pyydettäessä.

Käyttäjä 2026-10-07: «dynamics 506 s» ei kerro mikä siitä vei ajan.
"""

from __future__ import annotations

import logging

import numpy as np

from speechmix import chain, log

RATE = 48000


def _speech(seconds=20.0):
    rng = np.random.default_rng(0)
    t = np.arange(int(seconds * RATE)) / RATE
    x = 0.1 * np.sin(2 * np.pi * 150 * t) * (rng.random(t.size) > 0.3)
    return x.astype(np.float32)[None, :]


class _Settings:
    high_pass_hz = 80.0
    peak_threshold_db = -18.0
    leveler_threshold_db = -24.0
    declick = True
    declick_sensitivity = 0.5
    rider = True


def test_verbose_names_the_steps_inside_dynamics(caplog):
    caplog.set_level(logging.DEBUG, logger="speechmix")
    chain.process(_speech(), RATE, _Settings(), 0.0, True, -16.0, None)
    steps = " ".join(r.getMessage() for r in caplog.records if r.name.startswith("speechmix"))
    for name in ("declick", "deess", "multiband", "leveler", "limiter"):
        assert name in steps, (name, steps)


def test_quiet_unless_asked(capsys):
    log.disable()
    chain.process(_speech(5.0), RATE, _Settings(), 0.0, True, -16.0, None)
    assert "deess" not in capsys.readouterr().out
