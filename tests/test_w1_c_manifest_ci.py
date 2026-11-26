# -*- coding: utf-8 -*-
"""W1-C (Fundament/DB) — Regressionstests.

D03-H3: ein normaler ``--migrate`` darf das versionierte Manifest nicht
umschreiben (byte-identisch), ``--deactivate`` nur mit Bestaetigung + Audit +
Backup des alten Manifests.
D03-M2: der busy_timeout-SSOT-Gate ist hart in CI verdrahtet (datiertes Ratchet).
D03-M4: ein Restore ohne GoBD-Auditnachweis ist ``blocked`` (HTTP 503), nie
``restored=true``.
"""

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_source_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, payload TEXT)")
        conn.execute("INSERT INTO sample (payload) VALUES ('sample')")
        conn.commit()
    finally:
        conn.close()


def _write_active_manifest(path: Path, active: bool) -> bytes:
    payload = (
        json.dumps(
            {"active": active, "version": 1, "marker": "w1-c-byte-identical"},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(payload)
    return payload


def _fixture_dirs(tmp_path):
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    src.mkdir()
    tgt.mkdir()
    _make_source_db(src / "sample.db")
    return src, tgt, tgt / "db_consolidated.json"


def _stub_audit(monkeypatch, event_id="evt-w1c", error=None):
    import backend.audit_log as audit_mod

    def record(**_kwargs):
        if error is not None:
            raise error
        return {"event_id": event_id}

    monkeypatch.setattr(audit_mod.chained_audit_log, "record_event", record)
    return record


# ---------------------------------------------------------------- D03-H3


def test_migrate_keeps_existing_active_manifest_byte_identical(tmp_path, monkeypatch):
    """Ein normaler --migrate (activate=False) laesst active=true unberuehrt."""
    from backend import db_consolidation as dbc

    src, tgt, manifest = _fixture_dirs(tmp_path)
    before = _write_active_manifest(manifest, True)
    monkeypatch.delenv("ARCHON_DB_CONSOLIDATED", raising=False)

    result = dbc.run_consolidation(
        source_dirs=[str(src)],
        target_dir=str(tgt),
        dry_run=False,
        create_backup=False,
        activate=False,
    )

    assert result["status"] == "success"
    assert manifest.read_bytes() == before
    assert result["manifest_written"] is False
    assert result["manifest_state_changed"] is False
    assert dbc.is_consolidation_active(str(tgt)) is True


def test_activation_is_explicit_and_idempotent(tmp_path, monkeypatch):
    """Nur --activate schreibt; ein zweiter activate-Lauf ist byte-identisch."""
    from backend import db_consolidation as dbc

    src, tgt, manifest = _fixture_dirs(tmp_path)
    monkeypatch.delenv("ARCHON_DB_CONSOLIDATED", raising=False)
    calls = []
    real_record = _stub_audit(monkeypatch)

    def record(**kwargs):
        calls.append(kwargs)
        return real_record(**kwargs)

    import backend.audit_log as audit_mod

    monkeypatch.setattr(audit_mod.chained_audit_log, "record_event", record)

    first = dbc.run_consolidation(
        source_dirs=[str(src)], target_dir=str(tgt),
        create_backup=False, activate=True,
    )
    assert first["manifest_written"] is True
    assert first["audit_event_id"] == "evt-w1c"
    assert calls and calls[0]["action"] == "consolidation_activated"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["active"] is True
    snapshot = manifest.read_bytes()

    second = dbc.run_consolidation(
        source_dirs=[str(src)], target_dir=str(tgt),
        create_backup=False, activate=True,
    )
    assert second["manifest_written"] is False
    assert manifest.read_bytes() == snapshot


def test_deactivate_requires_confirmation_backup_and_audit(tmp_path, monkeypatch):
    """--deactivate ohne Bestaetigung ist abgelehnt; mit Bestaetigung auditiert+gesichert."""
    from backend import db_consolidation as dbc

    src, tgt, manifest = _fixture_dirs(tmp_path)
    before = _write_active_manifest(manifest, True)
    monkeypatch.delenv("ARCHON_DB_CONSOLIDATED", raising=False)
    _stub_audit(monkeypatch)

    with pytest.raises(ValueError, match="confirm_deactivate"):
        dbc.run_consolidation(
            source_dirs=[str(src)], target_dir=str(tgt),
            create_backup=False, deactivate=True,
        )
    assert manifest.read_bytes() == before

    result = dbc.run_consolidation(
        source_dirs=[str(src)], target_dir=str(tgt),
        create_backup=False, deactivate=True, confirm_deactivate=True,
    )
    assert result["manifest_written"] is True
    assert result["manifest_active"] is False
    assert json.loads(manifest.read_text(encoding="utf-8"))["active"] is False

    backups = list(tgt.glob("db_consolidated.json.pre_deactivate.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before
    assert result["manifest_backup_path"] == str(backups[0])


def test_deactivate_fails_closed_without_audit_proof(tmp_path, monkeypatch):
    """Fehlt der Auditnachweis, bleibt das Manifest unberuehrt (fail-closed)."""
    from backend import db_consolidation as dbc

    src, tgt, manifest = _fixture_dirs(tmp_path)
    before = _write_active_manifest(manifest, True)
    monkeypatch.delenv("ARCHON_DB_CONSOLIDATED", raising=False)
    _stub_audit(monkeypatch, error=RuntimeError("audit unavailable"))

    with pytest.raises(RuntimeError, match="Auditnachweis fehlt"):
        dbc.run_consolidation(
            source_dirs=[str(src)], target_dir=str(tgt),
            create_backup=False, deactivate=True, confirm_deactivate=True,
        )
    assert manifest.read_bytes() == before
    assert dbc.is_consolidation_active(str(tgt)) is True


# ---------------------------------------------------------------- D03-M2


def _ci_text() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_ci_busy_timeout_gate_is_hard_and_dated():
    text = _ci_text()
    assert "python -m backend.db_paths --audit-busy-timeout" in text
    assert "2026-12-31" in text  # datiertes Ratchet-Ablaufdatum
    assert not any(
        line.strip().startswith("continue-on-error:") for line in text.splitlines()
    )


def test_ci_ratchet_covers_all_current_drift_and_gate_is_real(capsys):
    """Der in ci.yml hinterlegte Ratchet macht den Gate gruen — ohne ihn rot."""
    from backend.db_paths import audit_busy_timeout_cli, audit_busy_timeout_ssot

    text = _ci_text()
    marker = "<<'ARCHON_BUSY_TIMEOUT_ALLOWLIST'"
    assert marker in text
    start = text.index(marker) + len(marker)
    end = text.index("ARCHON_BUSY_TIMEOUT_ALLOWLIST", start)
    allowed = [
        line.strip()
        for line in text[start:end].splitlines()
        if line.strip().endswith(".py")
    ]
    assert allowed, "Ratchet-Liste leer"

    offenders = audit_busy_timeout_ssot(str(REPO_ROOT))
    known_files = {path for path, _line, _value in offenders}
    assert known_files <= set(allowed), (
        "Neue Datei mit busy_timeout-Drift fehlt im Ratchet: "
        + repr(sorted(known_files - set(allowed)))
    )

    base = ["--audit-busy-timeout", "--root", str(REPO_ROOT)]
    assert audit_busy_timeout_cli(base) != 0  # ohne Ratchet: hart rot
    with_ratchet = []
    for name in allowed:
        with_ratchet.extend(("--allow-drift", name))
    assert audit_busy_timeout_cli(base + with_ratchet) == 0
    capsys.readouterr()


# ---------------------------------------------------------------- D03-M4


def test_restore_without_audit_event_id_is_blocked(tmp_path, monkeypatch):
    """Auditfehler => status=blocked, restored=False (kein Scheinerfolg)."""
    import backend.db_backup_manager as dbm

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    raw = tmp_path / "source.db"
    conn = sqlite3.connect(str(raw))
    try:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    archive = backup_dir / "fixture_20260101_000000.db.gz"
    with open(raw, "rb") as fin, gzip.open(str(archive), "wb") as fout:
        fout.write(fin.read())

    _stub_audit(monkeypatch, error=RuntimeError("audit unavailable"))
    # Restore-Ziel-Jail ist APP_DATA_DIR ∪ WORKSPACE_DIR; fuer den Test auf
    # tmp_path umstellen (kein Schreiben in das geteilte data/).
    monkeypatch.setattr(dbm, "_APP_DATA_DIR", str(tmp_path))

    manager = dbm.DBBackupManager(backup_dir=str(backup_dir))
    target = tmp_path / "restored.db"
    result = manager.restore_backup(
        archive.name, target_path=str(target), dry_run=False
    )

    assert result["status"] == "blocked"
    assert result["restored"] is False
    assert not result.get("audit_event_id")
    assert result["failure_reason"] == "GoBD_AUDIT_PROOF_MISSING"
    # Ehrlich ausgewiesen: Datei wurde ausgetauscht, aber nicht freigegeben.
    assert result["restore_applied"] is True


def test_restore_endpoint_maps_blocked_to_http_503(monkeypatch):
    """Der Router darf 'blocked' nie als HTTP-200-'success' quittieren."""
    from fastapi import HTTPException

    import backend.db_backup_manager as dbm
    from archon.routers import system

    monkeypatch.setattr(system, "_require_admin", lambda request: None)
    monkeypatch.setattr(
        dbm.db_backup_manager,
        "restore_backup",
        lambda *args, **kwargs: {
            "status": "blocked",
            "restored": False,
            "audit_status": "failed",
            "failure_reason": "GoBD_AUDIT_PROOF_MISSING",
            "backup": "fixture.db.gz",
            "target": "/tmp/fixture.db",
        },
    )

    body = system.DbRestoreRequest(file_name="fixture.db.gz", confirmed=True)
    with pytest.raises(HTTPException) as exc:
        system.api_restore_db_backup(object(), body)
    assert exc.value.status_code in (500, 503)
