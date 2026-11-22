"""Regressionstests fuer Batch A/1: Config-SSOT + CI-Drift-Check.

Prueft per Source-Text-Assertions (Stil wie test_p1_profile_ssot.py), dass die
Strict-Flag, die CI-Kommandos und die --allow-missing-hermes-Option verdrahtet
sind, sowie das Drift-Verhalten bei fehlendem .hermes/profiles direkt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

VALIDATE_SCRIPT = REPO_ROOT / "scripts" / "validate_config.py"
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync_profile_ssot.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_validate_config_exposes_strict_flag():
    """validate_config.py muss --strict an validate_all durchreichen."""
    src = VALIDATE_SCRIPT.read_text(encoding="utf-8")
    assert '"--strict"' in src
    assert "strict=args.strict" in src


def test_ci_runs_strict_validation_and_ssot_drift_check():
    """Job 1 muss beide neuen Kommandos ausfuehren."""
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/validate_config.py --strict" in ci
    assert "Profil-SSOT Drift-Check" in ci
    assert "python scripts/sync_profile_ssot.py --check --allow-missing-hermes --json" in ci


def test_sync_supports_allow_missing_hermes_flag():
    """sync_profile_ssot.py muss --allow-missing-hermes definieren und nutzen."""
    src = SYNC_SCRIPT.read_text(encoding="utf-8")
    assert '"--allow-missing-hermes"' in src
    assert "allow_missing_hermes" in src


def _prepare_workspace(tmp_path, monkeypatch, roles):
    """Temporaere SSOT und Rollen-Projektion setzen, Hermes-Pfad fehlt."""
    import scripts.sync_profile_ssot as ssot

    ssot_json = tmp_path / "agent_profiles.json"
    roles_json = tmp_path / "roles.json"
    ssot_json.write_text(json.dumps([{"id": "alpha"}, {"id": "beta"}]), encoding="utf-8")
    roles_json.write_text(json.dumps(roles), encoding="utf-8")

    monkeypatch.setattr(ssot, "PROFILES_JSON", str(ssot_json))
    monkeypatch.setattr(ssot, "ROLES_JSON", str(roles_json))
    monkeypatch.setattr(ssot, "HERMES_PROFILES", str(tmp_path / "does-not-exist"))
    return ssot


def test_detect_drift_missing_dir_only_with_flag(tmp_path, monkeypatch):
    """Ohne Flag bleibt Drift hart, mit Flag wird er ignoriert."""
    ssot = _prepare_workspace(
        tmp_path, monkeypatch, [{"id": "alpha"}, {"id": "beta"}]
    )

    strict = ssot.detect_drift()
    assert strict["drift"] is True
    assert set(strict["missing_dirs"]) == {"alpha", "beta"}
    assert strict["disk_skipped"] is False

    relaxed = ssot.detect_drift(allow_missing_hermes=True)
    assert relaxed["drift"] is False
    assert relaxed["disk_skipped"] is True
    # Report-Felder bleiben auch im relaxierten Modus intact.
    assert set(relaxed["missing_dirs"]) == {"alpha", "beta"}
    assert relaxed["counts"] == strict["counts"]


def test_detect_drift_still_enforces_roles(tmp_path, monkeypatch):
    """Rollen-Drift bleibt trotz fehlendem Hermes-Ordner ein Fehler."""
    ssot = _prepare_workspace(tmp_path, monkeypatch, [{"id": "alpha"}])

    report = ssot.detect_drift(allow_missing_hermes=True)
    assert report["drift"] is True
    assert report["missing_roles"] == ["beta"]
    assert report["disk_skipped"] is True


def test_detect_drift_existing_dir_behavior_unchanged(tmp_path, monkeypatch):
    """Wenn .hermes/profiles existiert, darf sich nichts aendern."""
    ssot = _prepare_workspace(
        tmp_path, monkeypatch, [{"id": "alpha"}, {"id": "beta"}]
    )
    profiles_dir = tmp_path / "does-not-exist"
    profiles_dir.mkdir()
    (profiles_dir / "alpha").mkdir()
    (profiles_dir / "ghost").mkdir()

    default = ssot.detect_drift()
    allowed = ssot.detect_drift(allow_missing_hermes=True)

    assert default["drift"] is True
    assert default["missing_dirs"] == ["beta"]
    assert default["orphan_dirs"] == ["ghost"]
    assert default["disk_skipped"] is False
    # Beide Aufrufe liefern bis auf das neue Infofeld identische Reports.
    assert {k: v for k, v in default.items() if k != "disk_skipped"} == {
        k: v for k, v in allowed.items() if k != "disk_skipped"
    }
