"""RMS-verhokäyrä ja sen välimuisti.

Purku on kirjaston, välimuistin **paikka** ei: kolme sovellusta säilövät
omissa hakemistoissaan, ja kirjasto joka valitsee itse hakemiston
käyttäjän kotihakemistosta on kirjasto joka kirjoittaa kutsumatta. Siksi
``cache_dir`` on parametri eikä oletus, ja ``None`` tarkoittaa «älä säilö».
"""

import numpy as np
import pytest
from speechmix import rms as envelope


@pytest.fixture
def decoded(monkeypatch):
    """Purku korvattuna: laskettu käyrä ja laskuri montako kertaa se ajettiin."""
    calls = []

    def fake_decode(path, progress=None):
        calls.append(path)
        return np.arange(10, dtype=np.float32) - 60.0

    monkeypatch.setattr(envelope, "_decode_rms", fake_decode)
    monkeypatch.setattr(envelope, "require_ffmpeg", lambda: None)
    return calls


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "puhe.wav"
    path.write_bytes(b"ei oikeaa aanta, purku on korvattu")
    return str(path)


def test_without_a_cache_dir_nothing_is_written(decoded, source, tmp_path):
    """``cache_dir=None``: laske joka kerta, älä jätä jälkiä."""
    before = set(tmp_path.iterdir())

    first = envelope.envelope_for(source)
    second = envelope.envelope_for(source)

    assert np.array_equal(first, second)
    assert len(decoded) == 2
    assert set(tmp_path.iterdir()) == before


def test_the_cache_is_used_on_the_second_call(decoded, source, tmp_path):
    """Säilötty käyrä luetaan levyltä eikä ääntä pureta uudestaan.

    Tämä on ollut rikki kerran hiljaa: ``np.save`` sai polun eikä kahvaa,
    kirjoitti ``<avain>.npy.tmp.npy``:n ja nimesi uudelleen tiedoston jota
    ei ollut. Nostettu ``FileNotFoundError`` on ``OSError``, jonka
    kirjoituksen ``except`` nielaisi — levylle jäi 1212 orpoa tiedostoa ja
    jokainen lataus purki äänen uudestaan. Testi laskee purut, ei riviä.
    """
    cache = tmp_path / "cache"
    cache.mkdir()

    first = envelope.envelope_for(source, cache_dir=cache)
    second = envelope.envelope_for(source, cache_dir=cache)

    assert np.array_equal(first, second)
    assert len(decoded) == 1
    assert [p.name for p in cache.iterdir()] == [f"{envelope.cache_key(source)}.npy"]


def test_a_changed_file_misses_the_cache(decoded, source, tmp_path):
    """Avaimessa on koko ja muokkausaika: korvattu tiedosto ei osu vanhaan."""
    cache = tmp_path / "cache"
    cache.mkdir()

    envelope.envelope_for(source, cache_dir=cache)
    with open(source, "ab") as handle:
        handle.write(b" lisaa")
    envelope.envelope_for(source, cache_dir=cache)

    assert len(decoded) == 2


def test_a_corrupt_cache_entry_is_recomputed(decoded, source, tmp_path):
    """Vioittunut .npy poistetaan ja lasketaan uudestaan, ei nosteta."""
    cache = tmp_path / "cache"
    cache.mkdir()

    envelope.envelope_for(source, cache_dir=cache)
    (cache / f"{envelope.cache_key(source)}.npy").write_bytes(b"roskaa")

    again = envelope.envelope_for(source, cache_dir=cache)
    assert len(decoded) == 2
    assert again.size == 10


def test_a_missing_source_says_so(decoded, tmp_path):
    with pytest.raises(envelope.EnvelopeError, match=r"ei-ole\.wav"):
        envelope.envelope_for(str(tmp_path / "ei-ole.wav"))


def test_a_missing_ffmpeg_is_an_envelope_error(monkeypatch, source):
    """Puuttuva työkalu tulee ulos ``EnvelopeError``ina, ei OSErrorina.

    Kutsuja on analyysisilmukka, joka näyttää tämän käyttäjälle. Se nappaa
    ``EnvelopeError``in; paljas ``FileNotFoundError`` menisi sen ohi.
    """
    from speechmix import binaries

    def missing(_name):
        raise binaries.MissingBinary("ffmpeg puuttuu")

    monkeypatch.setattr(binaries, "get_binary_path", missing)
    with pytest.raises(envelope.EnvelopeError, match="ffmpeg"):
        envelope.envelope_for(source)
