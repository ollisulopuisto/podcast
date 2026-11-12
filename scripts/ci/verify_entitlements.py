#!/usr/bin/env python3
"""Fail when an Info.plist usage string has no matching hardened-runtime entitlement.

With --options runtime (Developer ID), a protected resource without its
entitlement is denied silently: no prompt, no error. This guard catches that.

Usage:
  verify_entitlements.py path/to/App.app          # packaged app (needs codesign)
  verify_entitlements.py --info Info.plist --entitlements App.entitlements   # source check
"""
import argparse
import plistlib
import subprocess
import sys

# Info.plist usage key -> entitlement that hardened runtime needs for it.
REQUIRED = {
    "NSMicrophoneUsageDescription": "com.apple.security.device.audio-input",
    "NSCameraUsageDescription": "com.apple.security.device.camera",
    "NSAppleEventsUsageDescription": "com.apple.security.automation.apple-events",
    "NSContactsUsageDescription": "com.apple.security.personal-information.addressbook",
    "NSCalendarsUsageDescription": "com.apple.security.personal-information.calendars",
    "NSCalendarsFullAccessUsageDescription": "com.apple.security.personal-information.calendars",
    "NSRemindersUsageDescription": "com.apple.security.personal-information.calendars",
    "NSLocationUsageDescription": "com.apple.security.personal-information.location",
    "NSLocationWhenInUseUsageDescription": "com.apple.security.personal-information.location",
    "NSPhotoLibraryUsageDescription": "com.apple.security.personal-information.photos-library",
}


def missing(info, ents):
    out = []
    for key, ent in REQUIRED.items():
        if info.get(key) and ents.get(ent) is not True:
            out.append((key, ent))
    return out


def load_app(app):
    with open(f"{app}/Contents/Info.plist", "rb") as f:
        info = plistlib.load(f)
    raw = subprocess.run(
        ["codesign", "-d", "--entitlements", ":-", app],
        capture_output=True, check=False,
    ).stdout
    ents = plistlib.loads(raw) if raw.strip() else {}
    return info, ents


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("app", nargs="?")
    p.add_argument("--info")
    p.add_argument("--entitlements")
    a = p.parse_args(argv)
    if a.app:
        info, ents = load_app(a.app)
    elif a.info and a.entitlements:
        with open(a.info, "rb") as f:
            info = plistlib.load(f)
        with open(a.entitlements, "rb") as f:
            ents = plistlib.load(f)
    else:
        p.error("give an app path, or --info and --entitlements")
    bad = missing(info, ents)
    for key, ent in bad:
        print(f"::error::{key} is set but {ent} is not in the signed entitlements")
    if bad:
        return 1
    print("entitlement guard: every usage string has its entitlement")
    return 0


if __name__ == "__main__":
    sys.exit(main())
