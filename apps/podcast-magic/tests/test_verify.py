"""Litteroinnin tarkistus.

Tarkistus on olemassa yhtä vikaa varten: käsikirjoitusnäkymän toistokohdistin
jää alkuun, vaikka aikajananäkymässä sanat osuvat kohdalleen. Nämä testit
eivät väitä tietävänsä syytä. Ne pitävät huolen siitä, että jokainen epäilty
löytyy tiedostosta jossa se on — muuten tarkistus antaisi puhtaat paperit
tiedostolle joka oireilee, ja se on huonompi kuin ei tarkistusta lainkaan.
"""

from __future__ import annotations

from podcastmagic import nhsx
from podcastmagic.nhsx import verify
from podcastmagic.nhsx.write import paragraphs, set_transcription, tidy


def kinds(result, name="olli.wav"):
    """Vain viat. Huomiot ovat epäiltyjä, eivät mittaustuloksia."""
    report = next(r for r in result["files"] if r["name"] == name)
    return {f["kind"]: f["count"] for f in report["findings"] if f["severity"] == "vika"}


def notes(result, name="olli.wav"):
    report = next(r for r in result["files"] if r["name"] == name)
    return {f["kind"] for f in report["findings"] if f["severity"] == "huomio"}


def test_a_clean_transcription_has_nothing_to_report(session_file):
    session = nhsx.read(session_file)
    result = verify.inspect(session)
    assert kinds(result) == {}


def test_a_word_that_jumps_backwards_is_found(session_file):
    session = nhsx.read(session_file)
    words = session.file_by_id("1").words()
    # Kirjoitetaan ohi siivouksen, kuten Colab-muistikirja teki.
    _write_raw(session.file_by_id("1").elem, [
        ("yksi", 5.0, 0.3), ("kaksi", 2.0, 0.3), ("kolme", 6.0, 0.3),
    ])
    assert kinds(verify.inspect(nhsx.read(_saved(session, session_file))))["backwards"] == 1
    assert words  # alkuperäinen oli kunnossa


def test_overlapping_words_are_found(session_file):
    session = nhsx.read(session_file)
    _write_raw(session.file_by_id("1").elem, [
        ("yksi", 1.0, 2.0), ("kaksi", 1.5, 0.3),
    ])
    assert kinds(verify.inspect(nhsx.read(_saved(session, session_file))))["overlap"] == 1


def test_a_zero_length_word_is_found(session_file):
    session = nhsx.read(session_file)
    _write_raw(session.file_by_id("1").elem, [("yksi", 1.0, 0.0)])
    assert kinds(verify.inspect(nhsx.read(_saved(session, session_file))))["empty"] == 1


def test_words_outside_every_region_are_found(session_file):
    """Alun trimmaus jättää sanoja litterointiin mutta pois aikajanalta.

    Aikajananäkymä ei piirrä niitä lainkaan, joten se näyttää oikealta.
    Käsikirjoitusnäkymässä ne ovat dokumentissa, ja silloin kohdistin ja
    teksti eivät voi olla samassa kohdassa.
    """
    session = nhsx.read(session_file)
    region = session.tracks[0].regions[0].elem
    region.set("Offset", "5.000")   # alusta leikattu viisi sekuntia pois
    region.set("Length", "7.000")
    result = verify.inspect(nhsx.read(_saved(session, session_file)))
    # Kaksi ensimmäistä sanaa (1,0 s ja 1,5 s) jäävät alueen ulkopuolelle.
    assert kinds(result)["outside_regions"] == 2


def test_one_giant_paragraph_is_reported(session_file):
    session = nhsx.read(session_file)
    _write_raw(session.file_by_id("1").elem,
               [(f"sana{i}", float(i), 0.3) for i in range(300)])
    assert "one_paragraph" in notes(verify.inspect(nhsx.read(_saved(session, session_file))))


def test_the_report_names_where_the_file_sits_on_the_timeline(session_file):
    """Sijainti kuuluu raporttiin: se on puolet muunnoksesta.

    Ilman alueen Start- ja Offset-arvoja raportista ei voi päätellä mihin
    kohtaan aikajanaa sana kuuluisi, ja juuri se on kysymys.
    """
    result = verify.inspect(nhsx.read(session_file))
    placement = result["files"][0]["placements"][0]
    assert placement == {"track": "Olli", "start": 0.0, "offset": 0.0, "length": 12.0}


def test_the_writer_produces_nothing_the_check_complains_about():
    """Siivous ja tarkistus ovat sama sopimus kahdesta suunnasta."""
    from lxml import etree

    messy = [
        nhsx.Word("yksi", 5.0, 3.0),      # menee seuraavan päälle
        nhsx.Word("kaksi", 2.0, 0.3),     # taaksepäin
        nhsx.Word("kolme", 6.0, 0.0),     # nollapituinen
        nhsx.Word("neljä", 6.5, 0.3),
    ]
    file_elem = etree.Element("File", {"Id": "1", "Name": "a.wav"})
    report = set_transcription(file_elem, messy)
    assert report["reordered"] and report["shortened"]

    words = []
    for w in file_elem.iter("w"):
        words.append(nhsx.Word(w.text, float(w.get("s")), float(w.get("l"))))
    assert verify.check_order(words) == []


def test_tidy_keeps_the_start_times_it_is_given():
    """Alkuaika on se mihin toistokohdistin osuu, joten sitä ei siirretä.

    Päällekkäisyys korjataan lyhentämällä edellistä sanaa. Seuraavan
    siirtäminen myöhemmäksi kasaisi virheen eteenpäin koko tiedoston läpi.
    """
    words = [nhsx.Word("a", 1.0, 5.0), nhsx.Word("b", 2.0, 0.5)]
    out, moved, shortened = tidy(words)
    assert [w.start for w in out] == [1.0, 2.0]
    assert out[0].end == 2.0 and moved == 0 and shortened == 1


def test_paragraphs_break_on_pauses_and_on_length():
    speech = [nhsx.Word("a", 0.0, 0.3), nhsx.Word("b", 0.4, 0.3)]
    after_pause = [nhsx.Word("c", 5.0, 0.3)]
    assert len(paragraphs(speech + after_pause)) == 2
    # Tauoton monologi katkaistaan silti, muuten se on yksi muuri.
    monologue = [nhsx.Word(f"w{i}", i * 0.4, 0.3) for i in range(200)]
    assert len(paragraphs(monologue)) >= 2


def _write_raw(file_elem, triples):
    """Kirjoittaa sanat ohi siivouksen, kuten muistikirja teki."""
    from lxml import etree
    from podcastmagic.nhsx.read import localname

    for old in [c for c in file_elem if localname(c) == "Transcription"]:
        file_elem.remove(old)
    transcription = etree.SubElement(file_elem, "Transcription")
    paragraph = etree.SubElement(transcription, "p")
    for text, start, length in triples:
        elem = etree.SubElement(paragraph, "w")
        elem.set("s", f"{start:.3f}")
        elem.set("l", f"{length:.3f}")
        elem.set("sp", "UU")
        elem.text = text


def _saved(session, path):
    target = path.with_name("muokattu.nhsx")
    nhsx.write(session.tree, target)
    return target
