"""``nhsx-render``: istunto sisään, ohjelma ulos — ilman Hindenburgia.

Tämä on se puoli josta on hyötyä vasta myöhemmin. Istuntotiedosto on XML ja
äänipooli on WAV-tiedostoja levyllä; niin kauan kuin jokin osaa lukea nämä
kaksi, istunto on kuunneltavissa, vaikka sitä ohjelmaa jolla se tehtiin ei
enää olisi eikä sen lisenssiä saisi.

Kolme tapaa käyttää:

* ``nhsx-render jakso.nhsx`` — renderöi ohjelman WAViksi istunnon viereen.
* ``nhsx-render jakso.nhsx --plan`` — kertoo mitä kuuluisi, avaamatta ääntä.
  ``--json`` sama koneelle: juuri se mitä esikatselu lukee.
* ``nhsx-render jakso.nhsx --inspect`` — kartoittaa formaatin, ks.
  ``prospect.py``.

``--plan`` ja ``--json`` eivät koske äänitiedostoihin lainkaan. Tunnin
istunnon suunnitelma on XML:n lukemisen verran työtä eli millisekunteja, ja
juuri siksi esikatselu voi olla nopea: se ei renderöi mitään vaan sijoittaa
lähteet aikajanalle ja antaa käyttöjärjestelmän soittaa ne.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from . import mix, prospect, render
from .read import NhsxError, read
from .write import next_free_path


def _version() -> str:
    """Paketin versio, myös paketoituna."""
    from .. import __version__

    return __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nhsx-render",
        description="Renderöi Hindenburgin istunto WAViksi ilman Hindenburgia.",
    )
    # Paketoidusta binääristä ei näe versiota mistään muualta: `.app`illa on
    # `CFBundleVersion`, yksittäisellä binäärillä ei mitään. Numero tulee
    # paketista eikä ole oma kopionsa.
    parser.add_argument(
        "--version", action="version", version=f"nhsx-render {_version()}"
    )
    parser.add_argument("session", help="istuntotiedosto (.nhsx)")
    parser.add_argument("-o", "--output", help="kohdetiedosto (oletus: istunnon viereen)")
    parser.add_argument("--audio-dir", default="", help="mistä äänipoolia etsitään lisäksi")
    parser.add_argument("--rate", type=int, default=render.SAMPLE_RATE, help="näytetaajuus")
    parser.add_argument("--bits", type=int, default=24, choices=(16, 24), help="bittisyvyys")
    parser.add_argument("--plan", action="store_true", help="kerro mitä kuuluisi, älä renderöi")
    parser.add_argument("--json", action="store_true", help="sama koneluettavana")
    parser.add_argument("--inspect", action="store_true", help="kartoita formaatti")
    parser.add_argument(
        "--conformance",
        action="store_true",
        help="suunnitelma ilman koneen omia polkuja — kahden toteutuksen yhteinen muoto",
    )
    return parser


# Suunnitelman muoto. Nostetaan kun kenttä katoaa tai vaihtaa merkitystä —
# ei kun uusi kenttä ilmestyy, sillä lukija saa jättää tuntemattoman
# huomiotta. QuickLook-esikatselu kieltäytyy versiosta jota se ei tunne
# mieluummin kuin lukee sen väärin.
PLAN_VERSION = 1

# Montako desimaalia konetarkistettavassa suunnitelmassa. Kuudella kaksi eri
# kielellä laskettua `10 ** (dB / 20)` on varmasti sama luku; ilman
# pyöristystä vertailu olisi liukulukujen viimeisen bitin varassa.
CONFORMANCE_DIGITS = 6


def _plan_as_dict(mixdown: mix.Mix) -> dict:
    return {
        "version": PLAN_VERSION,
        "duration": mixdown.duration,
        "muted": mixdown.muted,
        "missing": mixdown.missing,
        "unknown": mixdown.unknown,
        "speakers": mixdown.speakers,
        "clips": [
            {
                "path": clip.path,
                # Poolin nimi polun rinnalla: polku on koneen oma, nimi on
                # istunnon. Esikatselu paikantaa tiedostot itse.
                "file": Path(clip.path).name,
                "speaker": clip.speaker,
                "start": clip.start,
                "length": clip.length,
                "file_offset": clip.file_offset,
                "gain": clip.gain,
                "pan": clip.pan,
                "ramps": [
                    {"start": r.start, "length": r.length, "gain": r.gain}
                    for r in clip.ramps
                ],
            }
            for clip in mixdown.clips
        ],
    }


def conformance_dict(mixdown: mix.Mix) -> dict:
    """Suunnitelma ilman mitään koneen omaa, pyöristettynä.

    Tämä on se muoto, jonka **molempien** toteutusten on tuotettava samasta
    istunnosta: tämä ja QuickLook-esikatselun Swift-jäsennin. Ne eivät jaa
    riviäkään koodia, joten ainoa tapa pitää ne samaa mieltä on istunto,
    jonka vastaus on kirjoitettu muistiin ja jota molemmat testaavat itseään
    vasten. Sama sääntö kuin työtilan jäsenillä, kielirajan yli.

    Poluista jää nimi: absoluuttinen polku on sen koneen oma jolla testi
    ajettiin, eikä se kuulu yhteiseen totuuteen. `missing` jää pois samasta
    syystä — se kertoo levystä, ei istunnosta.
    """
    digits = CONFORMANCE_DIGITS
    return {
        "version": PLAN_VERSION,
        "duration": round(mixdown.duration, digits),
        "muted": mixdown.muted,
        "unknown": mixdown.unknown,
        "speakers": mixdown.speakers,
        "clips": [
            {
                "file": Path(clip.path).name,
                "speaker": clip.speaker,
                "start": round(clip.start, digits),
                "length": round(clip.length, digits),
                "file_offset": round(clip.file_offset, digits),
                "gain": round(clip.gain, digits),
                "pan": round(clip.pan, digits),
                # Kanavakertoimet eikä vain panoroinnin luku. Pelkkä `pan`
                # on sama molemmilla toteutuksilla myös silloin kun ne
                # soveltavat eri lakia, eli juuri se ero jota tämä tiedosto
                # on olemassa estämään ei näkyisi. Laki on mitattu; nyt
                # myös yhteinen vastaus sanoo mihin se johtaa.
                "left": round(mix.pan_gains(clip.pan)[0], digits),
                "right": round(mix.pan_gains(clip.pan)[1], digits),
                "ramps": [
                    {
                        "start": round(r.start, digits),
                        "length": round(r.length, digits),
                        "gain": round(r.gain, digits),
                    }
                    for r in clip.ramps
                ],
            }
            for clip in mixdown.clips
        ],
    }


def _warn_about_the_unknown(mixdown: mix.Mix) -> None:
    """Ohitettu attribuutti kerrotaan, koska sen jälki on hiljainen.

    Miksaus jossa faderi jäi lukematta on kelvollinen WAV väärällä tasolla.
    Ilman tätä riviä se näyttäisi onnistuneelta.
    """
    if not mixdown.unknown:
        return
    names = ", ".join(sorted(mixdown.unknown))
    print(
        f"Huom: istunnossa on attribuutteja joita tämä ei lue: {names}. "
        "Jos joukossa on taso, panorointi tai häivytys, miksaus on niiltä "
        "osin väärä — `--inspect` kertoo arvot.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None, decode: Callable[..., object] | None = None) -> int:
    """Palauttaa 0 kun ohjelma syntyi, 1 kun se syntyi vaillinaisena, 2 kun ei lainkaan.

    ``decode`` on testien sauma: summaus on testattavissa ilman ffmpegiä.
    """
    args = build_parser().parse_args(argv)

    try:
        session = read(args.session)
    except NhsxError as exc:
        print(f"{Path(args.session).name}: {exc}", file=sys.stderr)
        return 2

    if args.inspect:
        print(prospect.text(prospect.survey(args.session)))
        return 0

    mixdown = mix.plan(session, args.audio_dir)

    if args.conformance:
        print(json.dumps(conformance_dict(mixdown), indent=2, ensure_ascii=False))
        return 0

    if args.json:
        print(json.dumps(_plan_as_dict(mixdown), indent=2, ensure_ascii=False))
        return 0

    if args.plan:
        print(f"{Path(args.session).name}: {mixdown.duration:.1f} s")
        print(f"  {len(mixdown.clips)} leikettä, {mixdown.muted} vaimennettu")
        for speaker in mixdown.speakers:
            count = sum(1 for c in mixdown.clips if c.speaker == speaker)
            heard = sum(c.length for c in mixdown.clips if c.speaker == speaker)
            print(f"  {speaker}: {count} leikettä, {heard:.1f} s")
        _warn_about_the_unknown(mixdown)
        return 0

    if mixdown.missing:
        print(
            "Äänipoolin tiedostoja ei löytynyt levyltä: "
            + ", ".join(mixdown.missing)
            + ". Kokeile --audio-dir.",
            file=sys.stderr,
        )
        return 1

    target = Path(args.output) if args.output else next_free_path(
        Path(args.session).with_suffix(".wav")
    )
    _warn_about_the_unknown(mixdown)

    report = render.to_wav(
        mixdown, target, sample_rate=args.rate, bit_depth=args.bits, decode=decode
    )

    print(f"{target.name}: {report.duration:.1f} s, huippu {report.peak_dbfs:.1f} dBFS")
    if report.clipped:
        print(f"  {report.clipped} näytettä rajautui — miksaus on liian kuuma.")
    if report.unreadable:
        print("  ei auennut: " + ", ".join(Path(p).name for p in report.unreadable))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
