"""Regressionstests fuer K-4 (Profil-SSOT: 73 / 72 / 59 bereinigt)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _ids(path: Path) -> set:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("roles", [])
    return {str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")}


def test_p1_profile_ssot_is_consistent():
    """SSOT = 73; abgeleitete Artefakte muessen likewise 73 sein."""
    ssot = _ids(REPO_ROOT / "agent_profiles.json")
    roles = _ids(REPO_ROOT / "roles.json")
    disk = {
        p.name for p in (REPO_ROOT / ".hermes" / "profiles").iterdir()
        if p.is_dir() and not p.name.startswith(".")
    }
    assert len(ssot) == 73
    assert roles == ssot
    assert disk == ssot
    # Die zuvor veralteten IDs duerfen nicht wieder auftauchen.
    assert "agility_story" not in roles
    assert "analyze_claims" not in roles
    # Das zuvor fehlende Profil ist jetzt vorhanden.
    assert "linkedin_social_media_specialist" in disk


def test_p1_validator_reports_ssot_drift(tmp_path):
    """Der Pre-Flight-Validator muss Drift als Fehler melden."""
    from backend.config_validator import ConfigValidator

    work = tmp_path / "workspace"
    work.mkdir()
    # Minimale, aber vollstaendige SSOT-Struktur kopieren.
    shutil.copy(REPO_ROOT / "agent_profiles.json", work / "agent_profiles.json")
    shutil.copy(REPO_ROOT / "roles.json", work / "roles.json")
    (work / ".hermes").mkdir()
    shutil.copytree(REPO_ROOT / ".hermes" / "profiles", work / ".hermes" / "profiles")

    validator = ConfigValidator(str(work))
    errors, warnings, stats = validator.validate_profile_ssot(
        {str(p["id"]) for p in json.loads((work / "agent_profiles.json").read_text(encoding="utf-8"))}
    )
    assert errors == []
    assert stats["ssot_profiles"] == 73

    # Drift simulieren: eine Rolle entfernen.
    roles = json.loads((work / "roles.json").read_text(encoding="utf-8"))
    roles = [r for r in roles if r["id"] != "linkedin_social_media_specialist"]
    (work / "roles.json").write_text(json.dumps(roles), encoding="utf-8")
    errors, _, _ = validator.validate_profile_ssot(
        {str(p["id"]) for p in json.loads((work / "agent_profiles.json").read_text(encoding="utf-8"))}
    )
    assert any("fehlen" in e for e in errors)


def test_p1_sync_script_check_detects_and_syncs(tmp_path):
    """--check meldet Drift, ein Sync behebt ihn."""
    import subprocess

    py = sys.executable
    script = REPO_ROOT / "scripts" / "sync_profile_ssot.py"
    result = subprocess.run(
        [py, str(script), "--check", "--json"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    report = json.loads(result.stdout)
    assert report["drift"] is False
    assert result.returncode == 0
