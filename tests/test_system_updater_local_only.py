import os
import sys
from unittest.mock import patch

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def test_local_update_status_skips_fetch_and_status():
    from backend import system_updater

    called_cmds = []

    def fake_run_git(args, timeout=15):
        called_cmds.append(args[0] if args else "")
        if args and args[0] == "log":
            return {"success": True, "stdout": "2026-11-11 · Test commit", "stderr": ""}
        raise AssertionError(f"Unerwarteter Git-Aufruf im Fast-Path: {args}")

    with patch.object(system_updater, "_run_git", side_effect=fake_run_git), \
         patch.object(system_updater, "_read_git_head_native", return_value={"commit": "13b4c44bc033", "branch": "main"}), \
         patch.object(system_updater, "get_system_version_info", return_value={"version": "v0.5.1", "codename": "Archon Hardened"}):
        res = system_updater.get_local_update_status()

    assert res["status"] == "local_only"
    assert res["local_only"] is True
    assert res["version"] == "v0.5.1"
    assert res["version_codename"] == "Archon Hardened"
    assert res["next_version"] == "v0.5.1.1"
    assert res["version_steps"]["patch"] == "v0.5.2"
    assert res["current_commit"] == "13b4c44"
    assert res["branch"] == "main"
    assert "fetch" not in called_cmds
    assert "status" not in called_cmds


def test_version_fallback_no_stale_v036(tmp_path):
    from backend import system_updater

    with patch.object(system_updater, "WORKSPACE_DIR", str(tmp_path)):
        info = system_updater.get_system_version_info()

    assert info["version"] == "unbekannt"
    assert info["version"] != "v0.3.6"


def test_settings_modal_html_has_no_stale_version_placeholders():
    html_path = os.path.join("static", "views", "system_settings_modal.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "v0.3.6" not in html
    assert "v0.3.8" not in html
    assert "v0.3.9" not in html
    assert "v0.4.0" not in html
    assert "Lade..." in html
