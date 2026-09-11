"""Käynnistys: TUI ilman argumentteja, täysin skriptattava ajo valitsimilla.

Kaksi tapaa, yksi totuus: molemmat kulkevat `plan_commands`in kautta, joten
mitä ruudulla pyytää, se myös komentorivi ajaa — ja `--dry-run` tulostaa
komennot varmistettavaksi ennen kuin mitään läheteään pilveen.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from . import __version__, driver
from .onboarding import check_environment
from .options import DEFAULT_PROMPT, GPUS, PRESETS, TRANSFERS, RunOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="colab-transcribe",
        description="Litterointi ja Auto-Silence Colabin näytönohjaimella.",
    )
    parser.add_argument("--input", help="syötekansio (.nhsx + äänet). Ilman tätä avataan TUI.")
    parser.add_argument("--output", default="output", help="tulostekansio (oletus: output)")
    parser.add_argument("--session", default="vst-pipeline", help="Colab-istunnon nimi")
    parser.add_argument("--gpu", choices=GPUS, default="T4", help="Colabin GPU (oletus: T4)")
    parser.add_argument("--preset", choices=PRESETS, default="remote", help="leikkauksen esiasetus")
    parser.add_argument(
        "--transfer",
        choices=TRANSFERS,
        default="drive",
        help="siirtotapa: drive (nopea Google Drive) tai direct (hidas Colab-lataus)",
    )
    parser.add_argument(
        "--no-drive",
        action="store_true",
        help="älä käytä Google Drivea vaan suoraa Colab-latausta",
    )
    parser.add_argument("--rms", action="store_true", help="RMS-tarkistus Auto-Silencelle")
    parser.add_argument("--thr", type=int, default=-35, help="RMS-kynnys desibeleinä (oletus: -35)")
    parser.add_argument("--tail", type=float, default=1.0, help="häntä sekunteina (oletus: 1.0)")
    parser.add_argument("--gap", type=float, default=1.0, help="minimitauko sekunteina (oletus: 1.0)")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Whisperin täytesanat")
    parser.add_argument("--tui", action="store_true", help="avaa TUI myös valitsimien kanssa")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="tulosta ajettavat komennot äläkä aja mitään",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="tarkista apuohjelmat ja ympäristömuuttujat",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def options_from_args(args: argparse.Namespace) -> RunOptions:
    env_opts = RunOptions.from_env()
    transfer = "direct" if args.no_drive else (
        args.transfer if args.transfer != "drive" else env_opts.transfer
    )
    return RunOptions(
        session=args.session if args.session != "vst-pipeline" else env_opts.session,
        gpu=args.gpu if args.gpu != "T4" else env_opts.gpu,
        input_dir=args.input or env_opts.input_dir,
        output_dir=args.output if args.output != "output" else env_opts.output_dir,
        preset=args.preset if args.preset != "remote" else env_opts.preset,
        transfer=transfer,
        rms=args.rms or env_opts.rms,
        thr=args.thr if args.thr != -35 else env_opts.thr,
        tail=args.tail if args.tail != 1.0 else env_opts.tail,
        gap=args.gap if args.gap != 1.0 else env_opts.gap,
        prompt=args.prompt if args.prompt != DEFAULT_PROMPT else env_opts.prompt,
    )


def run_headless(options: RunOptions, dry_run: bool) -> int:
    """Skriptattava ajo: suunnitelma, joko tulosteena tai totuutena."""
    input_dir = Path(options.input_dir)
    if not input_dir.is_dir():
        print(f"Syötekansio ei ole hakemisto: {options.input_dir}", file=sys.stderr)
        return 1

    files = driver.list_input_files(input_dir)
    commands = driver.plan_commands(options, files)

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

    code = driver.run(commands, log, timeout=driver.COMMAND_TIMEOUT)
    if code == 0:
        generated = driver.parse_generated("\n".join(lines))
        print(f"\nValmiit istunnot ({len(generated)}):")
        for path in generated:
            print(f"  {path}")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.check:
        report = check_environment()
        print(report.summary())
        return 0 if report.is_ready else 1

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
