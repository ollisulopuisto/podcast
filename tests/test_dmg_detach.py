"""DMG detach must use the attach device and remain fail-closed on real errors."""

import importlib.util
import plistlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "dmg_restyle_detach", ROOT / "packaging/dmg/restyle.py"
)
restyle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restyle)


def test_restyle_detaches_device_even_when_mount_path_disappears(tmp_path):
    image = tmp_path / "test.dmg"
    image.write_bytes(b"original")
    background = tmp_path / "welcome.png"
    background.write_bytes(b"png")
    commands = []

    def run(*args):
        commands.append(args)
        if args[:2] == ("hdiutil", "attach"):
            mounted = Path(args[args.index("-mountpoint") + 1])
            (mounted / "Test.app").mkdir()
            (mounted / ".DS_Store").write_bytes(b"layout")
            return plistlib.dumps(
                {
                    "system-entities": [
                        {"dev-entry": "/dev/disk42"},
                        {"dev-entry": "/dev/disk42s1", "mount-point": str(mounted)},
                    ]
                }
            )
        if args[:2] == ("hdiutil", "convert"):
            Path(args[args.index("-o") + 1]).write_bytes(b"styled")
        if args[:2] == ("hdiutil", "detach"):
            if args[2] != "/dev/disk42":
                raise subprocess.CalledProcessError(
                    1, args, output=b"No such file or directory"
                )
        return b""

    with (
        patch.object(restyle.sys, "platform", "darwin"),
        patch.object(restyle, "run", run),
    ):
        restyle.restyle(image, "Test.app", background)
    assert image.read_bytes() == b"styled"
    assert ("hdiutil", "detach", "/dev/disk42") in commands


def test_busy_detach_does_not_force_or_claim_success():
    commands = []

    def run(*args):
        commands.append(args)
        if args[1] == "info":
            return plistlib.dumps(
                {"images": [{"system-entities": [{"dev-entry": "/dev/disk42s1"}]}]}
            )
        raise subprocess.CalledProcessError(1, args, output=b"Resource busy")

    with patch.object(restyle, "run", run), pytest.raises(subprocess.CalledProcessError):
        restyle.detach_image("/dev/disk42")
    assert commands == [
        ("hdiutil", "detach", "/dev/disk42"),
        ("hdiutil", "info", "-plist"),
    ]


def test_already_detached_device_is_verified_absent():
    def run(*args):
        if args[1] == "detach":
            raise subprocess.CalledProcessError(
                1, args, output=b"No such file or directory"
            )
        return plistlib.dumps(
            {"images": [{"system-entities": [{"dev-entry": "/dev/disk99"}]}]}
        )

    with patch.object(restyle, "run", run):
        restyle.detach_image("/dev/disk42")


def test_failed_mount_info_never_turns_detach_green():
    with patch.object(
        restyle, "run", side_effect=subprocess.CalledProcessError(1, "info")
    ):
        with pytest.raises(subprocess.CalledProcessError):
            restyle.detach_image("/dev/disk42")


def test_unclassifiable_mount_info_never_turns_detach_green():
    def run(*args):
        if args[1] == "detach":
            raise subprocess.CalledProcessError(1, args)
        return plistlib.dumps({})

    with patch.object(restyle, "run", run), pytest.raises(RuntimeError):
        restyle.detach_image("/dev/disk42")
