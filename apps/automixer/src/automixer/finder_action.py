"""Install autovideo as a Finder Quick Action (right-click → Quick Actions).

    uv run python -m automixer.finder_action

writes ``~/Library/Services/<NAME>.workflow``. The workflow holds one line
that runs ``autovideo_finder.sh`` from this checkout, so a ``git pull`` changes
what the action does without reinstalling; moving the checkout needs a
reinstall.

The dxRevive state is read from ``~/Library/Application Support/autovideo``
rather than the repo: the first install copies the repo's ``dx.state`` there,
and later installs leave the copy alone so a model chosen with ``--edit`` is
not overwritten.
"""

from __future__ import annotations

import argparse
import plistlib
import shutil
import uuid
from pathlib import Path

RUNNER = Path(__file__).with_name("autovideo_finder.sh").resolve()
PROJECT = RUNNER.parents[2]
# The bundle's file name is what Finder lists, so it says what the action does.
NAME = "Restore & Level Video Audio (dxRevive, -16 LUFS)"
# Names earlier installs used; removed so the menu does not list the action twice.
OLD_NAMES = ("autovideo",)
SERVICES = Path.home() / "Library" / "Services"
STATE = Path.home() / "Library" / "Application Support" / "autovideo" / "dx.state"
REPO_STATE = PROJECT.parents[1] / "dx.state"

SHELL_ACTION = "/System/Library/Automator/Run Shell Script.action"
# Automator's "Pass input: as arguments". 0 is "to stdin", which leaves "$@"
# empty and the action silently does nothing.
AS_ARGUMENTS = 1


def command() -> str:
    return f'exec /bin/bash "{RUNNER}" "$@"'


def _info() -> dict:
    return {
        "NSServices": [{
            "NSMenuItem": {"default": NAME},
            "NSMessage": "runWorkflowAsService",
            "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
            "NSSendFileTypes": ["public.movie"],
            "NSIconName": "NSActionTemplate",
        }],
    }


def _document() -> dict:
    """The smallest ``document.wflow`` Automator runs: one Run Shell Script
    step, keys as Automator 2.10 saves them."""
    finder = "/System/Library/CoreServices/Finder.app"
    step = {
        "AMAccepts": {"Container": "List", "Optional": True,
                      "Types": ["com.apple.cocoa.string"]},
        "AMActionVersion": "2.0.3",
        "AMApplication": ["Automator"],
        "AMProvides": {"Container": "List", "Types": ["com.apple.cocoa.string"]},
        "ActionBundlePath": SHELL_ACTION,
        "ActionName": "Run Shell Script",
        "ActionParameters": {
            "COMMAND_STRING": command(),
            "CheckedForUserDefaultShell": True,
            "inputMethod": AS_ARGUMENTS,
            "shell": "/bin/bash",
            "source": "",
        },
        "BundleIdentifier": "com.apple.RunShellScript",
        "CFBundleVersion": "2.0.3",
        "CanShowSelectedItemsWhenRun": False,
        "CanShowWhenRun": True,
        "Category": ["AMCategoryUtilities"],
        "Class Name": "RunShellScriptAction",
        "InputUUID": str(uuid.uuid4()).upper(),
        "OutputUUID": str(uuid.uuid4()).upper(),
        "UUID": str(uuid.uuid4()).upper(),
        "UnlocalizedApplications": ["Automator"],
        "isViewVisible": True,
    }
    return {
        "AMApplicationBuild": "523.1",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [{"action": step, "isViewVisible": True}],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleID": "com.apple.finder",
            "applicationPath": finder,
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject.movie",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 15,
            "processesInput": False,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": finder,
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject.movie",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": False,
            "systemImageName": "NSActionTemplate",
            "useAutomaticInputType": False,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def write_workflow(bundle: Path) -> Path:
    """Write the ``.workflow`` bundle, replacing whatever was there."""
    if bundle.exists():
        shutil.rmtree(bundle)
    contents = bundle / "Contents"
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(plistlib.dumps(_info()))
    (contents / "document.wflow").write_bytes(plistlib.dumps(_document()))
    return bundle


def install(services: Path = SERVICES, repo_state: Path = REPO_STATE,
            state: Path = STATE) -> Path:
    for old in OLD_NAMES:
        shutil.rmtree(services / f"{old}.workflow", ignore_errors=True)
    bundle = write_workflow(services / f"{NAME}.workflow")
    if not state.exists() and repo_state.exists():
        state.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo_state, state)
    return bundle


def main() -> None:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    bundle = install()
    print(f"Installed {bundle}")
    if STATE.exists():
        print(f"dxRevive state: {STATE}")
    else:
        print(f"No dxRevive state yet; the action refuses to run until you choose "
              f'the model:\n  autovideo <clip> --edit --state "{STATE}"')


if __name__ == "__main__":
    main()
