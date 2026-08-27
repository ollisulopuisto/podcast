"""Ohjelmatason katto ja trimmi.

Katto on kanavatietoinen ja saa monikanavaisen lohkon; trimmi mittaa
äänekkyyttä ja on monoa. Ero on tarkoituksellinen, ei epäjohdonmukaisuus.

Molemmat korjaavat saman virheen: ketju takaa katon ja tason jokaiselle
tiedostolle erikseen, mutta isäntä soittaa niiden summan. Testit pitävät
kiinni kahdesta säännöstä joita on helppo rikkoa vahingossa — käyrä lasketaan
summasta ja on jokaiselle stemille sama, ja trimmi on rajattu eikä koskaan
nosta.
"""

import numpy as np
import pytest

from speechmix import programme

RATE = 48000


def _stem(seed, seconds=6.0, peak_db=-1.5):
    """Puheenkaltaista, huiput painettuna kattoon kuten ketju ne jättää."""
    rng = np.random.default_rng(seed)
    n = int(RATE * seconds)
    t = np.arange(n) / RATE
    body = sum(np.sin(2 * np.pi * (110 + 47 * seed) * k * t) / k for k in range(1, 10))
    gate = (np.sin(2 * np.pi * 0.8 * t + seed) > -0.25).astype(float)
    audio = body * gate * (0.6 + 0.4 * np.sin(2 * np.pi * 0.27 * t))
    audio += rng.normal(0, 1e-3, n)
    audio = audio / np.max(np.abs(audio)) * 10 ** (peak_db / 20)
    return audio[None, :]


def test_two_stems_at_the_ceiling_still_clip_when_summed():
    """Lähtökohta. Ilman tätä koko moduulilla ei ole korjattavaa."""
    a, b = _stem(1), _stem(2)
    assert np.max(np.abs(a)) <= 10 ** (-1.5 / 20) + 1e-9
    assert np.max(np.abs(b)) <= 10 ** (-1.5 / 20) + 1e-9
    assert np.max(np.abs(a + b)) > 1.0


def test_the_sum_obeys_the_ceiling():
    a, b = _stem(1), _stem(2)
    gain = programme.shared_gain([a, b], RATE)
    summed = a * gain + b * gain
    assert np.max(np.abs(summed)) <= 1.0
    assert programme.reduction_db(gain) < -0.01


def test_the_balance_between_speakers_cannot_move():
    """Sama kerroin jokaiseen stemiin, joten suhde säilyy näyte näytteeltä."""
    a, b = _stem(1), _stem(2)
    gain = programme.shared_gain([a, b], RATE)
    loud = np.abs(b[0]) > 1e-3
    before = a[0][loud] / b[0][loud]
    after = (a * gain)[0][loud] / (b * gain)[0][loud]
    np.testing.assert_allclose(after, before, rtol=1e-9)


def test_the_pass_is_idempotent():
    """Käyrä on min(1, katto/huippu), joten toinen ajo ei tee mitään.

    Siksi tämän saa ajaa joka kierroksella, myös kun osa tiedostoista
    ohitettiin ajan tasalla olevina.
    """
    a, b = _stem(1), _stem(2)
    gain = programme.shared_gain([a, b], RATE)
    again = programme.shared_gain([a * gain, b * gain], RATE)
    assert programme.reduction_db(again) == pytest.approx(0.0, abs=1e-6)
    np.testing.assert_allclose(again, np.ones_like(again), atol=1e-9)


def test_a_sum_already_under_the_ceiling_is_untouched():
    quiet = _stem(3, peak_db=-20.0)
    gain = programme.shared_gain([quiet, quiet], RATE)
    assert programme.reduction_db(gain) == pytest.approx(0.0, abs=1e-9)


def test_no_stems_is_an_error_not_a_silent_unity_curve():
    with pytest.raises(ValueError):
        programme.shared_gain([], RATE)


def test_the_trim_never_lifts_and_is_bounded():
    """Trimmi on korjaus päällekkäisyyteen, ei toinen normalisointi."""
    loud = _stem(4, seconds=20.0, peak_db=-1.0)[0]
    trim = programme.trim_to_target(loud * 4, RATE, -30.0)
    assert trim == -programme.MAX_PROGRAM_TRIM

    quiet = _stem(5, seconds=20.0, peak_db=-40.0)[0]
    assert programme.trim_to_target(quiet, RATE, -14.0) == 0.0, "trimmi ei saa nostaa"


def test_the_trim_measures_the_sum():
    """Kaksi tavoitteessa olevaa mikkiä eivät summaudu tavoitteeseen."""
    a = programme.at_target(_stem(6, seconds=20.0)[0], RATE, -20.0)
    b = programme.at_target(_stem(7, seconds=20.0)[0], RATE, -20.0)
    assert a is not None and b is not None

    trim = programme.trim_to_target(a + b, RATE, -20.0)
    assert trim < 0.0, "summa on tavoitteen yli, joten trimmin on oltava negatiivinen"
    assert trim == round(trim, 2)


def test_a_microphone_that_is_silent_in_the_window_is_not_an_error():
    """Toisen osan tiedosto tai hiljainen kohta: ei virhe, ei lisäystä summaan."""
    assert programme.at_target(np.zeros(RATE * 5), RATE, -14.0) is None


def test_the_backoff_is_shared_so_the_balance_cannot_move():
    """Eniten tarvitseva sanelee, ja kaikki seuraavat.

    Budjetti lasketaan stemikohtaisesti, koska crest on puhujakohtainen.
    Sellaisenaan sovellettuna se siirtää puhujien tasapainoa: mitattuna
    77 minuutin jaksolla 1,1 dB:n ero kasvoi 5,9 dB:iin, eli ohjelman
    kovempi puhuja jäi yhtä tiivistetyksi ja hiljaisempi vain vaimeni.
    """
    extra = programme.shared_backoff({"a": -5.9, "b": 0.0})
    assert extra["a"] == 0.0, "syvimmin peruuttanut ei saa lisää"
    assert extra["b"] == -5.9, "toinen ei seurannut, eli tasapaino siirtyi"
    # Ero säilyy: -5,9 + 0,0 vs 0,0 + -5,9.
    assert (-5.9 + extra["a"]) == (0.0 + extra["b"])


def test_no_backoff_means_no_change():
    assert programme.shared_backoff({}) == {}
    assert programme.shared_backoff({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}
