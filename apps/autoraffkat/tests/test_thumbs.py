"""Pikkukuvat. Puolivälistä tiedostoa, välimuistiin, epäonnistuminen sallittu."""

import os
from pathlib import Path

from conftest import needs_ffmpeg

from autoraffkat import thumbs


def test_missing_file_is_not_an_error(tmp_path):
    """Pikkukuva on mukavuus: sen puuttuminen ei saa estää roolitusta."""
    assert thumbs.thumbnail(str(tmp_path / "ei-ole.mp4"), 100.0) is None
    assert thumbs.thumbnail("", 100.0) is None


def test_zero_duration_is_refused(tmp_path):
    path = tmp_path / "tyhja.mp4"
    path.write_bytes(b"")
    assert thumbs.thumbnail(str(path), 0.0) is None


def test_cache_path_follows_the_file(tmp_path):
    """Korvattu tiedosto ei osu vanhaan pikkukuvaan."""
    path = tmp_path / "a.mp4"
    path.write_bytes(b"x" * 10)
    first = thumbs.cache_path(str(path), 50.0)
    path.write_bytes(b"x" * 20)
    os.utime(path, (10**9, 10**9))
    assert thumbs.cache_path(str(path), 50.0) != first
    # Eri kohta samasta tiedostosta on eri pikkukuva.
    assert thumbs.cache_path(str(path), 60.0) != thumbs.cache_path(str(path), 50.0)


def test_audio_only_media_has_no_thumbnail(fixture_dir):
    from autoraffkat.finalcut.read import read_fcpxml

    timeline = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    mic = timeline.media_by_key()["host a Track1.wav"]
    assert thumbs.for_item(mic) is None


class _Done:
    returncode = 0


def _fake_ffmpeg(writes):
    """Vale-ffmpeg: kirjoittaa tuloskuvan kuten oikea, ja tallentaa
    käytetyt tmp-nimet. ``writes`` on jaettu lista tmp-polkuja varten."""

    def run(args, **kw):
        tmp = Path(args[-1])
        writes.append(tmp)
        tmp.write_bytes(b"jpeg")
        return _Done()

    return run


def test_concurrent_calls_use_separate_tmp_files(tmp_path, monkeypatch):
    """Kaksi pyyntöä samasta klipistä yhtä aikaa: kummallakin on oma
    tmp-tiedostonsa, eikä kumpikaan kaadu toisen siirtäessä omansa."""
    import threading

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x" * 10)
    monkeypatch.setattr(thumbs, "cache_dir", lambda: tmp_path)
    barrier = threading.Barrier(2)
    writes = []

    def run(args, **kw):
        tmp = Path(args[-1])
        writes.append(tmp)
        barrier.wait(timeout=10)   # molemmat purkavat yhtä aikaa
        tmp.write_bytes(b"jpeg")
        return _Done()

    monkeypatch.setattr(thumbs.subprocess, "run", run)
    results, errors = [], []

    def call():
        try:
            results.append(thumbs.thumbnail(str(video), 100.0))
        except Exception as e:  # haluamme nähdä virheen, ei kaataa säiettä
            errors.append(e)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(set(writes)) == 2, "tmp-nimien pitää erota"
    assert results[0] == results[1] and results[0] is not None


def test_a_lost_tmp_race_is_not_an_error(tmp_path, monkeypatch):
    """Toinen pyyntö ehti siirtää saman kuvan maaliin: oma tmp on poissa,
    mutta maali on olemassa, joten palautetaan maali kaatumatta."""

    video = tmp_path / "b.mp4"
    video.write_bytes(b"x" * 10)
    monkeypatch.setattr(thumbs, "cache_dir", lambda: tmp_path)
    def run(args, **kw):
        tmp = Path(args[-1])
        tmp.write_bytes(b"jpeg")
        # "Voittaja": maali ilmestyy purun aikana (välimuistiosumaa ei
        # ollut vielä kutsun alussa).
        thumbs.cache_path(str(video), 50.0).write_bytes(b"voittajan kuva")
        return _Done()

    monkeypatch.setattr(thumbs.subprocess, "run", run)
    # ...ja hävisijän tmp on poissa siirtohetkellä.
    def gone(self, dst):
        raise FileNotFoundError(str(self))

    monkeypatch.setattr(Path, "replace", gone)
    target = thumbs.cache_path(str(video), 50.0)
    assert thumbs.thumbnail(str(video), 100.0) == str(target)


@needs_ffmpeg
def test_thumbnail_is_taken_from_the_middle(fixture_dir):
    """Alku on asettelua ja loppu pakkaamista; puoliväli on kuvausta."""
    from autoraffkat.finalcut.read import read_fcpxml

    timeline = read_fcpxml(str(fixture_dir / "multicam.fcpxml"))
    item = timeline.media_by_key()["WIDE 01.mp4"]
    if not os.path.exists(item.path):
        import pytest

        pytest.skip("fixturen mediaa ei ole")
    path = thumbs.for_item(item)
    assert path and os.path.getsize(path) > 0
    assert f"-{int(float(item.asset_duration) / 2)}.jpg" in path
    # Toinen kutsu tulee välimuistista.
    assert thumbs.for_item(item) == path
