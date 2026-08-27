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
    parser.add_argument("--debug", action="store_true", help="kehitystyökalut käyttöön")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    # Pakattuna sovelluksena oletus on ikkuna, kehityksessä selain: .app:llä ei
    # ole terminaalia johon osoite tulostettaisiin.
    use_gui = args.gui if args.gui is not None else getattr(sys, "frozen", False)

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
