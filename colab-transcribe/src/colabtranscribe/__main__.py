"""Käynnistys: TUI ilman argumentteja, täysin skriptattava ajo valitsimilla.

Kaksi tapaa, yksi totuus: molemmat kulkevat `plan_commands`in kautta, joten
mitä ruudulla pyytää, se myös komentorivi ajaa — ja `--dry-run` tulostaa
komennot varmistettavaksi ennen kuin mitään läheteään pilveen.
"""

from __future__ import annotations

import argparse
import contextlib
import shlex
import signal
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__, driver, session
from .onboarding import check_environment
from .options import DEFAULT_PROMPT, GPUS, PRESETS, SOURCES, TRANSFERS, RunOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="colab-transcribe",
        description="Litterointi ja Auto-Silence Colabin näytönohjaimella.",
    )
    parser.add_argument(
        "--input",
        help="syötekansio tai äänitiedosto (.nhsx + äänet tai pelkkä ääni). Ilman tätä avataan TUI.",
    )
    parser.add_argument(
        "--output", default="output", help="tulostekansio (oletus: output)"
    )
    parser.add_argument(
        "--audio",
        action="append",
        default=[],
        metavar="TIEDOSTO",
        help="pelkkä äänitiedosto, toistettavissa; sanat tulevat --json-kansioon "
        "<nimi>.words.json (ei .nhsx:ää, aina suora siirto)",
    )
    parser.add_argument(
        "--json", metavar="KANSIO", help="--audio-tilan tulostekansio"
    )
    parser.add_argument("--model", default=None, help="Whisper-malli (--audio, oletus: turbo)")
    parser.add_argument("--language", default=None, help="kieli (--audio, oletus: fi)")
    parser.add_argument(
        "--progress",
        action="store_true",
        help="--audio: kirjoita rivit 'PROGRESS <0-100> <viesti>' (prosentti ei laske)",
    )

    parser.add_argument("--session", default="whisper", help="Colab-istunnon nimi")
    parser.add_argument(
        "--gpu", choices=GPUS, default="T4", help="Colabin GPU (oletus: T4)"
    )
    parser.add_argument(
        "--preset", choices=PRESETS, default="remote", help="leikkauksen esiasetus"
    )
    parser.add_argument(
        "--transfer",
        choices=TRANSFERS,
        default=None,
        help="siirtotapa: direct (suora Colab-lataus, oletus) tai drive (nopeampi Google Drive, vaatii Drive API:n)",
    )
    parser.add_argument(
        "--inline-remarks",
        action="store_true",
        help="käsikirjoitus: lyhyet huomautukset kappaleen sisään (Nimi: teksti), ei omille riveilleen",
    )
    parser.add_argument(
        "--no-bleed-filter",
        action="store_true",
        help="kirjoita istuntoon myös toisen mikin vuoto (oletuksena vuoto jätetään pois)",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="älä pakkaa isoja WAVeja FLACiksi ennen suoraa siirtoa",
    )
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default=None,
        help="mitä litteroidaan: tracks (raidat, oletus) tai downmix (koko miksaus ilman puhujia)",
    )
    parser.add_argument(
        "--no-drive",
        action="store_true",
        help="älä käytä Google Drivea vaan suoraa Colab-latausta",
    )
    parser.add_argument(
        "--reset-session",
        action="store_true",
        help="sulje olemassa oleva istunto ennen uuden luomista",
    )
    parser.add_argument(
        "--keep-session",
        action="store_true",
        help="jätä Colab-istunto käyntiin ajon jälkeen",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="sulje aktiivinen Colab-istunto ja lopeta",
    )
    parser.add_argument(
        "--session-status",
        action="store_true",
        help="näytä Colab-istunnon tila",
    )
    parser.add_argument(
        "--rms", action="store_true", help="RMS-tarkistus Auto-Silencelle"
    )
    parser.add_argument(
        "--transcribe-only",
        action="store_true",
        help="vain litterointi, ei Auto-Silencea (tulos: <jakso> litteroitu.nhsx)",
    )
    parser.add_argument(
        "--thr", type=int, default=-35, help="RMS-kynnys desibeleinä (oletus: -35)"
    )
    parser.add_argument(
        "--tail", type=float, default=1.0, help="häntä sekunteina (oletus: 1.0)"
    )
    parser.add_argument(
        "--gap", type=float, default=1.0, help="minimitauko sekunteina (oletus: 1.0)"
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Whisperin täytesanat")
    parser.add_argument(
        "--tui", action="store_true", help="avaa TUI myös valitsimien kanssa"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="tulosta ajettavat komennot äläkä aja mitään",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="tarkista apuohjelmat ja ympäristömuuttujat",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="kirjaudu Googleen Colab CLI:n kautta (ensimmäisellä kerralla)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def options_from_args(args: argparse.Namespace) -> RunOptions:
    env_opts = RunOptions.from_env()
    transfer = (
        "direct"
        if args.no_drive
        else (args.transfer if args.transfer is not None else env_opts.transfer)
    )
    return RunOptions(
        session=args.session if args.session != "whisper" else env_opts.session,
        gpu=args.gpu if args.gpu != "T4" else env_opts.gpu,
        input_dir=args.input or env_opts.input_dir,
        output_dir=args.output if args.output != "output" else env_opts.output_dir,
        preset=args.preset if args.preset != "remote" else env_opts.preset,
        transfer=transfer,
        compress=not args.no_compress,
        bleed_filter=not args.no_bleed_filter,
        inline_remarks=args.inline_remarks,
        source=args.source if args.source is not None else env_opts.source,
        rms=args.rms or env_opts.rms,
        silence=not args.transcribe_only and env_opts.silence,
        thr=args.thr if args.thr != -35 else env_opts.thr,
        tail=args.tail if args.tail != 1.0 else env_opts.tail,
        gap=args.gap if args.gap != 1.0 else env_opts.gap,
        prompt=args.prompt if args.prompt != DEFAULT_PROMPT else env_opts.prompt,
        reset_session=args.reset_session or env_opts.reset_session,
        keep_session=args.keep_session or env_opts.keep_session,
    )


def _sigterm_as_interrupt(_signum, _frame):
    """SIGTERM kulkee samaa tietä kuin Ctrl+C, jotta Colab-istunto suljetaan."""
    raise KeyboardInterrupt


@contextlib.contextmanager
def _sigterm_cancels():
    previous = signal.signal(signal.SIGTERM, _sigterm_as_interrupt)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _refuse(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _audio_problem(args: argparse.Namespace) -> str | None:
    """Miksi ``--audio``-kutsu on virheellinen, tai None."""
    if not args.audio:
        return "--json vaatii vähintään yhden --audio-tiedoston." if args.json else None
    if not args.json:
        return "--audio vaatii tulostekansion: anna --json <kansio>."
    if args.input:
        return "--audio ja --input eivät mene yhteen: valitse toinen."
    if args.transfer == "drive":
        return "--audio käyttää aina suoraa siirtoa: Drive ei ole tässä tilassa käytössä."
    stems = {}
    for name in args.audio:
        path = Path(name)
        if not path.is_file():
            return f"Äänitiedostoa ei löydy: {name}"
        if path.suffix.lower() not in driver._AUDIO_EXT:
            return (
                f"Tiedostotyyppiä {path.suffix or '(ei päätettä)'} ei litteroida: {name}. "
                f"Tuetut: {', '.join(driver._AUDIO_EXT)}."
            )
        previous = stems.setdefault(path.stem, name)
        if previous != name:
            return (
                f"Kahdella tiedostolla on sama nimi ({path.stem}): {previous} ja {name}. "
                "Tulokset kirjoittaisivat toistensa päälle."
            )
    return None


def _progress_printer():
    """``PROGRESS <0-100> <viesti>``: kokonaisluku, joka ei laske eikä ylitä sataa."""
    shown = 0

    def report(percent: float, message: str) -> None:
        nonlocal shown
        shown = max(shown, min(100, int(percent)))
        print(f"PROGRESS {shown} {message}", flush=True)

    return report


def run_audio_mode(args: argparse.Namespace, dry_run: bool) -> int:
    """Pelkkä ääni sisään, ``<nimi>.words.json`` ulos (``docs/KUULAS-COLAB.md``)."""
    env_opts = RunOptions.from_env()
    audio = [str(Path(a).resolve()) for a in args.audio]
    options = RunOptions(
        session=args.session if args.session != "whisper" else env_opts.session,
        gpu=args.gpu if args.gpu != "T4" else env_opts.gpu,
        output_dir=args.json,
        transfer="direct",
        source="audio",
        prompt=args.prompt if args.prompt != DEFAULT_PROMPT else env_opts.prompt,
        reset_session=args.reset_session or env_opts.reset_session,
        keep_session=args.keep_session or env_opts.keep_session,
        model=args.model or "turbo",
        language=args.language or "fi",
    )
    reuse_session = False
    if session.is_session_alive(options.session):
        if options.reset_session:
            if not dry_run:
                print(f"Suljetaan olemassa oleva Colab-istunto '{options.session}'...")
                session.stop_session(options.session)
        else:
            reuse_session = True
            if not dry_run:
                print(f"Käytetään olemassa olevaa Colab-istuntoa '{options.session}'.")

    commands = driver.plan_audio_commands(options, audio, reuse_session=reuse_session)
    if dry_run:
        for command in commands:
            print(shlex.join(command))
        return 0

    report = check_environment()
    if not report.is_ready:
        print("Tarvittavat apuohjelmat tai tunnistetiedot puuttuvat:\n", file=sys.stderr)
        print(report.summary(), file=sys.stderr)
        return 1

    out_dir = options.resolved_output_dir()
    expected = [out_dir / f"{Path(a).stem}.words.json" for a in audio]
    # Vanha tiedosto ei saa mennä uuden ajon tuloksesta: puuttuva tulos olisi
    # muuten hiljaa «onnistunut».
    for path in expected:
        path.unlink(missing_ok=True)

    def log(line: str) -> None:
        print(line, flush=True)

    with _sigterm_cancels():
        code = driver.run(
            commands,
            log,
            timeout=driver.COMMAND_TIMEOUT,
            on_progress=_progress_printer() if args.progress else None,
        )
    if code == 130 and not options.keep_session:
        print(f"Suljetaan Colab-istunto '{options.session}'...")
        session.stop_session(options.session)
    if code != 0:
        return code
    missing = [p for p in expected if not p.is_file()]
    if missing:
        names = ", ".join(p.name for p in missing)
        return _refuse(
            f"Ajo päättyi, mutta sanatiedostot puuttuvat: {names}. "
            "Katso lokista, löysikö Whisper puhetta."
        )
    print(f"\nValmiit sanatiedostot ({len(expected)}):")
    for path in expected:
        print(f"  {path}")
    return 0


def run_headless(options: RunOptions, dry_run: bool) -> int:
    """Skriptattava ajo: suunnitelma, joko tulosteena tai totuutena."""
    input_path = Path(options.input_dir)
    if not input_path.exists():
        print(f"Syötepolkua ei löydy: {options.input_dir}", file=sys.stderr)
        return 1
    if not input_path.is_dir() and not input_path.is_file():
        print(
            f"Syöte ei ole tiedosto eikä hakemisto: {options.input_dir}",
            file=sys.stderr,
        )
        return 1

    # Syötteenä oleva .nhsx tarkoittaa sitä istuntoa omassa kansiossaan.
    input_path, only = driver.split_session(input_path)
    options = replace(options, input_dir=str(input_path))
    files = driver.list_input_files(input_path, exclude=options.resolved_output_dir())
    if only is None and input_path.is_dir():
        found = driver.nhsx_sessions(input_path)
        if len(found) > 1:
            print(
                f"Kansiossa on {len(found)} istuntoa ({', '.join(found)}): kaikki "
                "lähtevät mukaan. Valitse yksi antamalla --input <tiedosto>.nhsx."
            )
    files, skipped = driver.session_inputs(input_path, files, only=only)
    if skipped:
        print(driver.skipped_note(input_path, skipped))
    files, aliases = driver.dedupe_inputs(input_path, files)
    if aliases:
        print(f"{len(aliases)} tiedostoa on kopioita toisista: ladataan ja litteroidaan kerran.")

    reuse_session = False
    if session.is_session_alive(options.session):
        if options.reset_session:
            if not dry_run:
                print(f"Suljetaan olemassa oleva Colab-istunto '{options.session}'...")
                session.stop_session(options.session)
        else:
            reuse_session = True
            if not dry_run:
                print(f"Käytetään olemassa olevaa Colab-istuntoa '{options.session}'.")

    commands = driver.plan_commands(
        options, files, reuse_session=reuse_session, aliases=aliases
    )

    if dry_run:
        for command in commands:
            print(shlex.join(command))
        return 0

    report = check_environment()
    if not report.is_ready:
        print("Tarvittavat apuohjelmat tai tunnistetiedot puuttuvat:\n", file=sys.stderr)
        print(report.summary(), file=sys.stderr)
        return 1

    lines: list[str] = []

    def log(line: str) -> None:
        lines.append(line)
        print(line)

    code = driver.run(
        commands,
        log,
        timeout=driver.COMMAND_TIMEOUT,
        on_drive_failure=lambda: driver.direct_tail(options, files, aliases),
    )
    if code == 0:
        generated = driver.parse_generated("\n".join(lines))
        transcripts = driver.parse_generated_transcripts("\n".join(lines))
        if generated:
            print(f"\nValmiit istunnot ({len(generated)}):")
            for path in generated:
                print(f"  {path}")
        if transcripts:
            print(f"\nValmiit litteroinnit ({len(transcripts)}):")
            for path in transcripts:
                print(f"  {path}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.login:
        # ``colab`` kysyy tunnuksen itse: URL selaimeen, koodi takaisin
        # tähän terminaaliin. Sen token kelpaa Colabiin ja Driveen, joten
        # gcloudia ei tarvita. Mikä tahansa tunnistusta vaativa komento
        # käynnistää kirjautumisen; ``usage`` ei luo virtuaalikonetta.
        import subprocess

        from .onboarding import colab_env

        return subprocess.run(["colab", "usage"], check=False, env=colab_env()).returncode

    if args.stop:
        print(f"Suljetaan Colab-istunto '{args.session}'...")
        code = session.stop_session(args.session)
        print(f"Istunto '{args.session}' suljettu.")
        return code

    if args.session_status:
        alive = session.is_session_alive(args.session)
        info = session.get_session(args.session)
        if alive and info:
            hw = info.get("accelerator") or "CPU"
            var = info.get("variant") or ""
            print(
                f"Istunto '{args.session}': aktiivinen (Hardware: {hw}, Variant: {var})"
            )
        elif alive:
            print(f"Istunto '{args.session}': aktiivinen")
        else:
            print(f"Istunto '{args.session}': ei käynnissä")
        return 0

    if args.check:
        report = check_environment()
        print(report.summary())
        return 0 if report.is_ready else 1

    problem = _audio_problem(args)
    if problem:
        return _refuse(problem)
    if args.audio:
        return run_audio_mode(args, dry_run=args.dry_run)

    if not args.input or args.tui:
        from .tui import TranscribeApp

        TranscribeApp(options=options_from_args(args)).run()
        return 0

    try:
        return run_headless(options_from_args(args), dry_run=args.dry_run)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
