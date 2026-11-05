#!/usr/bin/env python3
"""Stdlib-only tests for tools/ios-service-audit.py; no Apple assets required."""
from __future__ import annotations

import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AUDITOR = Path(__file__).resolve().parents[1] / "ios-service-audit.py"


def write_plist(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        plistlib.dump(data, stream, fmt=plistlib.FMT_BINARY)


class IosServiceAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "iosroot"
        (self.root / "System/Library").mkdir(parents=True)

    def run_audit(self, *args):
        return subprocess.run(
            [sys.executable, str(AUDITOR), str(self.root), *args],
            capture_output=True, text=True, check=False,
        )

    def test_bundle_and_cache_jobs(self):
        write_plist(
            self.root / "Applications/AppStore.app/Info.plist",
            {"CFBundleIdentifier": "com.apple.AppStore", "CFBundleExecutable": "AppStore"},
        )
        write_plist(
            self.root / "System/Library/xpc/launchd.plist",
            {"LaunchDaemons": {
                "job_appstore": {"Label": "com.apple.appstored",
                                 "ProgramArguments": ["/usr/libexec/appstored"]},
                "job_download": {"Label": "com.apple.nsurlsessiond",
                                 "Program": "/usr/libexec/nsurlsessiond"},
            }},
        )
        result = self.run_audit("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["app_store_bundles"][0]["bundle_id"], "com.apple.AppStore")
        self.assertEqual(data["service_jobs"]["appstored"][0]["program"], "/usr/libexec/appstored")
        self.assertEqual(len(data["service_jobs"]["nsurlsessiond"]), 1)
        self.assertIn("akd", data["service_hints_not_found"])

    def test_jobs_in_loose_plists_and_missing_app(self):
        write_plist(
            self.root / "System/Library/LaunchDaemons/com.apple.apsd.plist",
            {"Label": "com.apple.apsd", "Program": "/usr/libexec/apsd", "Disabled": True},
        )
        result = self.run_audit("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["app_store_bundles"], [])
        self.assertTrue(data["service_jobs"]["apsd"][0]["disabled_in_definition"])

    def test_bad_root_rejected(self):
        self.root = Path(self.temp.name) / "missing"
        result = self.run_audit("--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("System/Library not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
