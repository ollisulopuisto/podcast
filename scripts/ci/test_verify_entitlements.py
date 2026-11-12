import os
import plistlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import verify_entitlements as v


class Guard(unittest.TestCase):
    def test_missing_entitlement_fails(self):
        info = {"NSAppleEventsUsageDescription": "x"}
        self.assertEqual(
            v.missing(info, {"com.apple.security.network.client": True}),
            [("NSAppleEventsUsageDescription", "com.apple.security.automation.apple-events")],
        )

    def test_present_entitlement_passes(self):
        info = {"NSMicrophoneUsageDescription": "x"}
        self.assertEqual(v.missing(info, {"com.apple.security.device.audio-input": True}), [])

    def test_false_value_fails(self):
        info = {"NSCameraUsageDescription": "x"}
        self.assertEqual(len(v.missing(info, {"com.apple.security.device.camera": False})), 1)

    def test_no_usage_strings_passes(self):
        self.assertEqual(v.missing({}, {}), [])

    def test_cli_source_mode(self):
        with tempfile.TemporaryDirectory() as d:
            i, e = os.path.join(d, "i.plist"), os.path.join(d, "e.plist")
            plistlib.dump({"NSContactsUsageDescription": "x"}, open(i, "wb"))
            plistlib.dump({}, open(e, "wb"))
            self.assertEqual(v.main(["--info", i, "--entitlements", e]), 1)


if __name__ == "__main__":
    unittest.main()
