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

    def test_empty_string_still_counts(self):
        self.assertEqual(len(v.missing({"NSMicrophoneUsageDescription": ""}, {})), 1)

    def test_modern_calendar_and_photo_keys(self):
        for k in ("NSCalendarsWriteOnlyAccessUsageDescription", "NSPhotoLibraryAddUsageDescription"):
            self.assertEqual(len(v.missing({k: "x"}, {})), 1)

    def test_reminders_need_only_the_documented_calendars_entitlement(self):
        for k in ("NSRemindersUsageDescription", "NSRemindersFullAccessUsageDescription"):
            self.assertEqual(v.missing({k: "x"}, {v.CAL: True}), [])
            self.assertEqual(v.missing({k: "x"}, {v.CAL: True, v.REM: True}), [])
            self.assertEqual(v.missing({k: "x"}, {v.REM: True}), [(k, v.CAL)])
            self.assertEqual(v.missing({k: "x"}, {}), [(k, v.CAL)])

    def test_localized_only_key_is_found(self):
        with tempfile.TemporaryDirectory() as d:
            lp = os.path.join(d, "A.app/Contents/Resources/en.lproj")
            os.makedirs(lp)
            with open(os.path.join(lp, "InfoPlist.strings"), "w") as f:
                f.write('"NSMicrophoneUsageDescription" = "Mic";\n')
            self.assertEqual(v.localized_keys(os.path.join(d, "A.app")), {"NSMicrophoneUsageDescription": ""})
            with open(os.path.join(lp, "InfoPlist.strings"), "wb") as f:
                plistlib.dump({"NSCameraUsageDescription": "Cam"}, f, fmt=plistlib.FMT_BINARY)
            self.assertIn("NSCameraUsageDescription", v.localized_keys(os.path.join(d, "A.app")))

    def test_strings_comments_are_ignored(self):
        text = (
            '/* "NSCameraUsageDescription" = "x"; */\n'
            '// "NSContactsUsageDescription" = "x";\n'
            '"NSMicrophoneUsageDescription" = "see /* not a comment */ here"; // real\n'
            'NSLocationUsageDescription = "y";\n'
        )
        self.assertEqual(
            v.strings_keys(text),
            ["NSMicrophoneUsageDescription", "NSLocationUsageDescription"],
        )

    def test_cr_only_line_endings_end_line_comments(self):
        text = '// old mac comment\rNSCameraUsageDescription = "x";\r'
        self.assertEqual(v.strings_keys(text), ["NSCameraUsageDescription"])

    def test_utf8_bom_does_not_hide_first_key(self):
        with tempfile.TemporaryDirectory() as d:
            lp = os.path.join(d, "A.app/Contents/Resources/en.lproj")
            os.makedirs(lp)
            with open(os.path.join(lp, "InfoPlist.strings"), "wb") as f:
                f.write(b'\xef\xbb\xbfNSCameraUsageDescription = "x";\n')
            self.assertIn("NSCameraUsageDescription", v.localized_keys(os.path.join(d, "A.app")))

    def test_cli_source_mode(self):
        with tempfile.TemporaryDirectory() as d:
            i, e = os.path.join(d, "i.plist"), os.path.join(d, "e.plist")
            with open(i, "wb") as f:
                plistlib.dump({"NSContactsUsageDescription": "x"}, f)
            with open(e, "wb") as f:
                plistlib.dump({}, f)
            self.assertEqual(v.main(["--info", i, "--entitlements", e]), 1)


if __name__ == "__main__":
    unittest.main()
