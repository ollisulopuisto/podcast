"""Headless CLI commands for project inspection and automation."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import pick, project
from .finalcut.read import read_fcpxml
from .server.app import AppState, _track_json


def run_inspect(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="autoraffkat inspect",
        description="Inspect an FCPXML timeline and its tracks without launching a GUI or server.",
    )
    parser.add_argument("xml", help="Path to .fcpxml or .fcpxmld bundle")
    parser.add_argument("--json", action="store_true", help="Output details as JSON")
    args = parser.parse_args(argv)

    resolved = pick.resolve(args.xml)
    if not resolved or not os.path.exists(resolved):
        print(f"File not found: {args.xml}", file=sys.stderr)
        return 1

    try:
        timeline = read_fcpxml(resolved)
    except Exception as exc:
        print(f"Failed to read XML: {exc}", file=sys.stderr)
        return 1

    settings = project.load(resolved)
    state = AppState(xml_path=resolved, timeline=timeline, settings=settings)

    tracks = [_track_json(state, t) for t in timeline.tracks]
    data = {
        "xml_path": str(Path(resolved).resolve()),
        "name": timeline.name,
        "kind": timeline.kind,
        "fps": round(float(1 / timeline.frame_duration), 3) if timeline.frame_duration else None,
        "tracks": tracks,
        "settings": {
            "globals": settings.globals.to_json(),
            "audio": settings.audio.to_json(),
            "tracks": {k: v.to_json() for k, v in settings.tracks.items()},
        },
    }

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"Project: {timeline.name} ({timeline.kind}, {data['fps']} fps)")
        print(f"Source: {resolved}")
        print(f"Tracks ({len(tracks)}):")
        for tr in tracks:
            kind = "VIDEO" if tr["has_video"] else "AUDIO"
            cfg = tr.get("config") or {}
            role = cfg.get("role", "unused")
            print(f"  [{kind}] {tr['key']} -> role={role} (name: {tr['name']})")

    return 0


def _parse_override(arg: str) -> tuple[str, str, object]:
    """Parse 'section.field=val' into (section, field, parsed_val)."""
    if "=" not in arg or "." not in arg:
        raise ValueError(f"Invalid override format '{arg}'. Use section.field=value (e.g. globals.rhythm=mellow)")
    target, val_str = arg.split("=", 1)
    section, field = target.split(".", 1)
    val: object = val_str
    if val_str.lower() == "true":
        val = True
    elif val_str.lower() == "false":
        val = False
    else:
        try:
            val = float(val_str) if "." in val_str else int(val_str)
        except ValueError:
            val = val_str
    return section, field, val


def run_edit(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="autoraffkat edit",
        description="Automated headless cutting and export workflow for scripts and LLMs.",
    )
    parser.add_argument("xml", help="Path to .fcpxml or .fcpxmld bundle")
    parser.add_argument("--settings", help="Path to custom settings JSON file to load")
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        help="Inline override in format section.field=value (repeatable)",
    )
    parser.add_argument("--export", action="store_true", help="Export the cut timeline to FCPXML")
    parser.add_argument("--output", help="Explicit output path for exported FCPXML")
    parser.add_argument("--render", action="store_true", help="Render video MP4 beside the XML")
    parser.add_argument("--progress", action="store_true", help="Emit standard PROGRESS lines on stdout")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON result on stdout")
    args = parser.parse_args(argv)

    resolved = pick.resolve(args.xml)
    if not resolved or not os.path.exists(resolved):
        print(f"File not found: {args.xml}", file=sys.stderr)
        return 1

    if args.progress:
        print("PROGRESS 10 Loading project", flush=True)

    state = AppState(xml_path=resolved)
    state.load()

    # Wait for audio envelope analysis if needed
    while not state.progress.get("ready"):
        if state.load_error:
            print(f"Error loading project: {state.load_error}", file=sys.stderr)
            return 1
        import time
        time.sleep(0.05)

    if args.progress:
        print("PROGRESS 50 Analyzing timeline", flush=True)

    # Load custom settings if provided
    payload: dict = {}
    if args.settings:
        try:
            with open(args.settings, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:
            print(f"Failed to read settings file: {exc}", file=sys.stderr)
            return 1

    # Apply overrides
    for ov in args.overrides:
        try:
            sec, fld, val = _parse_override(ov)
            payload.setdefault(sec, {})[fld] = val
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    if payload:
        state.apply(payload)

    result = state.compute()
    if not result.get("ok"):
        problems = result.get("problems", [])
        print(f"Decision failed: {'; '.join(problems)}", file=sys.stderr)
        if args.json:
            print(json.dumps({"ok": False, "problems": problems}))
        return 1

    if args.progress:
        print("PROGRESS 80 Cuts computed", flush=True)

    export_path = None
    warnings = []
    if args.export:
        # Use export logic from AppState / server
        from fastapi.testclient import TestClient

        from .server.app import create_app

        client = TestClient(create_app(state))
        export_payload: dict = {"render": args.render}
        res = client.post("/api/v1/project/export", json=export_payload)
        if res.status_code != 200:
            err = res.json()
            print(f"Export failed: {err}", file=sys.stderr)
            return 1
        data = res.json()
        export_path = data.get("path")
        warnings = data.get("warnings", [])

        # If custom output path was requested, rename/move the exported file
        if args.output and export_path:
            out_p = Path(args.output).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.move(export_path, str(out_p))
            export_path = str(out_p)

    if args.progress:
        print("PROGRESS 100 Complete", flush=True)

    out_data = {
        "ok": True,
        "cuts": len(result.get("segments", [])),
        "path": export_path,
        "warnings": warnings,
        "segments": result.get("segments", []),
    }

    if args.json:
        print(json.dumps(out_data))
    else:
        print(f"Computed {out_data['cuts']} cuts.")
        if export_path:
            print(f"Exported to: {export_path}")
        for w in warnings:
            print(f"Warning: {w}")

    return 0
