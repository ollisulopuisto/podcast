"""Käynnistys: avaa ikkuna tai palvelin.

Ilman argumenttia istunto etsitään työhakemistosta. Työjärjestys on aina
sama — Hindenburg vie istunnon kansioon ja seuraava työkalu avataan siihen —
ja polun kirjoittaminen on kitkaa juuri siinä kohdassa.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import webbrowser

from . import __version__, pick

DEFAULT_PORT = 8741


def wants_window(flag: bool | None, frozen: bool, system: str) -> bool:
    """Avataanko ikkuna vai selain, kun käyttäjä ei sanonut kumpaa.

    Pakattuna oletus on ikkuna: `.app`illa ei ole terminaalia johon osoite
    tulostettaisiin. Poikkeus on Linux — siellä `pywebview` tarvitsee GTK:n ja
    WebKit2:n koneelta eikä paketista, ja niiden puuttuessa ohjelma ei avaisi
    mitään eikä kertoisi mitään. Selain on siellä se joka varmasti on.

    Pyydetty ikkuna avataan aina: `--gui` on käyttäjän päätös, ja jos
    kirjastot puuttuvat, virhe kuuluu näkyä.
    """
    if flag is not None:
        return flag
    if system.startswith("linux"):
        return False
    return bool(frozen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="podcast-magic",
        description="Hindenburg-jälkityöt: litterointi ja hiljaisten kohtien vaimennus.",
    )
    parser.add_argument(
        "session",
        nargs="?",
        help="Hindenburgin .nhsx-istunto tai kansio. Ilman tätä etsitään työhakemistosta.",
    )
    parser.add_argument("--gui", action="store_true", default=None,
                        help="avaa natiivi työpöytäikkuna")
    parser.add_argument("--no-gui", "--headless", dest="gui", action="store_false",
                        help="aja taustapalvelimena ilman ikkunaa")
    parser.add_argument("--no-browser", action="store_true",
                        help="älä avaa selainta (vain ilman ikkunaa)")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="tulosta litteroinnin tarkistus ja lopeta (ei avaa ikkunaa)",
    )
    parser.add_argument(
        "--chain",
        action="store_true",
        help="aja litterointi, vaimennus ja miksaus yhdellä komennolla ja lopeta",
    )
    parser.add_argument(
        "--steps",
        default="transcribe,silence,mix",
        help="ketjun vaiheet pilkulla erotettuna (oletus: kaikki kolme)",
    )
    parser.add_argument("--lufs", type=float, default=None,
                        help="miksauksen voimakkuus, LUFS (oletus: -16)")
    parser.add_argument("--audio-dir", default="",
                        help="kansio josta ääni haetaan, jos polut eivät löydy")
    parser.add_argument("--force", action="store_true",
                        help="litteroi uudestaan myös valmiit tiedostot")
    parser.add_argument("--debug", action="store_true", help="kehitystyökalut käyttöön")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    use_gui = wants_window(args.gui, frozen=getattr(sys, "frozen", False),
                           system=sys.platform)

    here = os.getcwd()
    session = ""
    if args.session:
        session = pick.resolve(args.session)
        if not session or not os.path.isfile(session):
            print(f"Istuntoa ei löydy: {args.session}", file=sys.stderr)
            return 1
    else:
        session = pick.newest(here)
        if session:
            print(f"Istunto: {os.path.basename(session)}")

    if args.inspect:
        from . import nhsx
        from .nhsx import verify

        if not session:
            print("Anna istuntotiedosto: podcast-magic --inspect jakso.nhsx", file=sys.stderr)
            return 1
        print(verify.as_text(verify.inspect(nhsx.read(session))))
        return 0

    if args.chain:
        from .chain import cli as chain_cli

        if not session:
            print("Anna istuntotiedosto: podcast-magic jakso.nhsx --chain", file=sys.stderr)
            return 1
        try:
            steps = chain_cli.parse_steps(args.steps)
        except ValueError as exc:
            parser.error(str(exc))
        extra = {} if args.lufs is None else {"target_lufs": args.lufs}
        return chain_cli.execute(
            session, steps, audio_dir=args.audio_dir, force=args.force, **extra
        )

    if use_gui:
        from .gui import launch

        launch(session=session, start_dir=here, host=args.host, port=args.port,
               debug=args.debug)
        return 0

    from .server.app import create_app

    app = create_app(start_dir=here, session=session)
    url = f"http://{args.host}:{args.port}/"
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    print(f"Podcast Magic: {url}")

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
