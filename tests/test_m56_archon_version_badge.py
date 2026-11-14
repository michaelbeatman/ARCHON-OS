"""
tests/test_m56_archon_version_badge.py
======================================
Tests für M56: Archon OS Versions- & GitHub-Update-Badge unten links in der Sidebar
inkl. Semver-Vergleich gegen `origin/main:config/version.json` und 1-Klick Settings-Sprung.
"""

import json
import os
import unittest
from unittest.mock import patch


class TestM56ArchonVersionBadge(unittest.TestCase):
    def test_01_semver_tuple_parsing(self):
        from backend.system_updater import _parse_version_tuple

        self.assertGreater(_parse_version_tuple("v0.5.3"), _parse_version_tuple("v0.5.2.3"))
        self.assertGreater(_parse_version_tuple("v0.5.2.4"), _parse_version_tuple("v0.5.2.3"))
        self.assertEqual(_parse_version_tuple("v0.5.2.1"), _parse_version_tuple("0.5.2.1"))

    def test_02_update_status_detects_newer_remote_github_version(self):
        from backend import system_updater

        system_updater.invalidate(system_updater.get_update_status)

        def fake_run_git(args, timeout=60):
            cmd = " ".join(args)
            if "rev-parse --short HEAD" in cmd:
                return {"success": True, "stdout": "abc1234", "stderr": "", "returncode": 0}
            if cmd.startswith("log -1"):
                return {"success": True, "stdout": "2026-11-14 · Local HEAD", "stderr": "", "returncode": 0}
            if "status --porcelain" in cmd:
                return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
            if "fetch origin main" in cmd:
                return {"success": True, "stdout": "", "stderr": "", "returncode": 0}
            if "rev-list --count HEAD..origin/main" in cmd:
                return {"success": True, "stdout": "2", "stderr": "", "returncode": 0}
            if "log HEAD..origin/main" in cmd:
                return {"success": True, "stdout": "def5678 Release v0.5.3\n9876543 Feat X", "stderr": "", "returncode": 0}
            if "rev-parse --short origin/main" in cmd:
                return {"success": True, "stdout": "def5678", "stderr": "", "returncode": 0}
            if "show origin/main:config/version.json" in cmd:
                return {
                    "success": True,
                    "stdout": json.dumps({"version": "v0.5.3", "codename": "Next"}),
                    "stderr": "",
                    "returncode": 0,
                }
            return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

        with patch.object(system_updater, "_run_git", side_effect=fake_run_git), \
             patch.object(system_updater, "get_system_version_info", return_value={"version": "v0.5.2.3", "codename": "Global"}):
            res = system_updater.get_update_status()

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["version"], "v0.5.2.3")
        self.assertEqual(res["remote_version"], "v0.5.3")
        self.assertTrue(res["version_newer"])
        self.assertTrue(res["update_available"])
        self.assertEqual(res["commits_behind"], 2)
        system_updater.invalidate(system_updater.get_update_status)

    def test_03_sidebar_badge_script_wired_in_index_html(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(repo_root, "static", "js", "archon_version_badge.js")
        html_path = os.path.join(repo_root, "static", "index.html")

        self.assertTrue(os.path.isfile(js_path))
        with open(js_path, "r", encoding="utf-8") as fh:
            js_src = fh.read()
        self.assertIn('openSystemSettingsModal("update")', js_src)
        self.assertIn("/api/v1/system/update/check", js_src)

        with open(html_path, "r", encoding="utf-8") as fh:
            html_src = fh.read()
        self.assertIn('/static/js/archon_version_badge.js', html_src)
