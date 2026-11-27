# -*- coding: utf-8 -*-
"""M71 — Tests zur Eval-Attestierung.

Alle Konfigurationsquellen und die Audit-DB liegen unter ``tmp_path``. Es wird
bewusst keine produktive SQLite-DB beschrieben.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend import eval_attestation as attestation_module  # noqa: E402
from backend.eval_attestation import (  # noqa: E402
    EvalAttestationError,
    attest_eval_run,
    attest_eval_run_sync,
    build_config_fingerprint,
    verify_attestation,
)


@pytest.fixture
def config_root(tmp_path: Path) -> Path:
    """Minimale, vollständige Konfigurationswelt unter tmp_path."""
    root = tmp_path / "workspace"
    (root / "config").mkdir(parents=True)
    (root / "souls" / "default").mkdir(parents=True)
    (root / ".agents" / "skills" / "demo").mkdir(parents=True)

    payloads: Dict[str, Dict[str, Any]] = {
        "agent_profiles.json": {
            "profiles": [{"id": "default", "name": "Default", "model": "modell-a"}],
        },
        "roles.json": {"roles": ["admin", "operator"]},
        "config/org_hierarchy.json": {
            "updated_at": "2026-01-01T00:00:00",
            "nodes": [{"id": "default", "model": "modell-a"}],
        },
        "config/permission_gates.json": {"gates": []},
        "config/passkey_hitl.json": {"users": {}},
        "config/approval_policy.yaml": {"policy_version": "v1"},
        "settings.json": {
            "routing": {"default": "modell-a"},
            "last_run": "2026-01-01T00:00:00",
        },
    }
    for name, payload in payloads.items():
        (root / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    # write_bytes verhindert auf Windows die automatische \n -> \r\n-Umsetzung;
    # die CRLF-Variante ist hier bewusst der Ausgangszustand.
    (root / "souls" / "default" / "SOUL.md").write_bytes(
        "# Default\r\n\r\nAntworte knapp.   \r\n".encode("utf-8")
    )
    (root / ".agents" / "skills" / "demo" / "SOUL.md").write_bytes(
        b"# Demo\nPrompt A\n"
    )
    return root


@pytest.fixture
def tmp_audit_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Tuple[Path, Any]:
    """Echte Hashkette, aber ausschließlich in einer temporären DB."""
    monkeypatch.setenv("ARCHON_DATA_DIR", str(tmp_path / "isolated_data"))
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "test-only-" + "b" * 64)
    monkeypatch.setenv("ARCHON_AUDIT_ANCHOR_PATH", "")
    from backend.audit_log import ChainedAuditLog

    db_path = tmp_path / "audit.db"
    log = ChainedAuditLog(db_path=str(db_path), start_anchor=False)
    monkeypatch.setattr(attestation_module, "_AUDIT_LOG", log)
    return db_path, log


def test_fingerprint_stable_for_order_whitespace_and_runtime_timestamps(
    config_root: Path,
) -> None:
    first = build_config_fingerprint(config_root)
    assert len(first.sha256) == 64

    # JSON: andere Key-Reihenfolge, andere Einrückung, neue Laufzustände.
    (config_root / "settings.json").write_text(
        json.dumps(
            {"last_run": "2099-12-31T23:59:59", "routing": {"default": "modell-a"}},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    (config_root / "config" / "org_hierarchy.json").write_text(
        json.dumps(
            {
                "nodes": [{"model": "modell-a", "id": "default"}],
                "updated_at": "2099-12-31T23:59:59",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    # Markdown: CRLF -> LF, keine trailing spaces.
    (config_root / "souls" / "default" / "SOUL.md").write_bytes(
        b"# Default\n\nAntworte knapp.\n"
    )

    second = build_config_fingerprint(config_root)
    assert second == first
    assert second.sha256 == first.sha256


def test_real_config_change_changes_fingerprint(config_root: Path) -> None:
    before = build_config_fingerprint(config_root)
    (config_root / "config" / "org_hierarchy.json").write_text(
        json.dumps(
            {
                "updated_at": "2026-01-01T00:00:00",
                "nodes": [{"id": "default", "model": "modell-b"}],
            }
        ),
        encoding="utf-8",
    )
    assert build_config_fingerprint(config_root).sha256 != before.sha256


def test_missing_required_file_fails_closed(config_root: Path) -> None:
    (config_root / "roles.json").unlink()
    with pytest.raises(EvalAttestationError, match="roles.json"):
        build_config_fingerprint(config_root)


def test_missing_soul_directory_fails_closed(config_root: Path) -> None:
    import shutil

    shutil.rmtree(config_root / "souls")
    with pytest.raises(EvalAttestationError, match="souls"):
        build_config_fingerprint(config_root)


def test_verify_attestation_reports_changed_file(config_root: Path) -> None:
    fingerprint = build_config_fingerprint(config_root)
    result = {
        "status": "success",
        "eval_id": "eval-m71-1",
        "attestation": fingerprint.to_dict(),
    }
    assert verify_attestation(result, root=config_root)["valid"] is True

    (config_root / "roles.json").write_text(
        json.dumps({"roles": ["admin", "operator", "auditor"]}), encoding="utf-8"
    )
    report = verify_attestation(result, root=config_root)
    assert report["valid"] is False
    assert report["status"] == "drift"
    assert any(
        diff["path"] == "roles.json" and diff["kind"] == "changed"
        for diff in report["differences"]
    )
    assert report["stored_sha256"] != report["current_sha256"]


def test_verify_attestation_reports_added_and_removed_files(config_root: Path) -> None:
    fingerprint = build_config_fingerprint(config_root)
    result = {"attestation": fingerprint.to_dict()}

    (config_root / "souls" / "default" / "SOUL.md").unlink()
    (config_root / "souls" / "other").mkdir()
    (config_root / "souls" / "other" / "SOUL.md").write_text(
        "# Other\nNeuer Prompt\n", encoding="utf-8"
    )
    report = verify_attestation(result, root=config_root)
    kinds = {(diff["path"], diff["kind"]) for diff in report["differences"]}
    assert ("souls/default/SOUL.md", "removed") in kinds
    assert ("souls/other/SOUL.md", "added") in kinds
    assert report["valid"] is False


def test_verify_attestation_without_attestation_is_invalid(config_root: Path) -> None:
    report = verify_attestation({"status": "success"}, root=config_root)
    assert report["valid"] is False
    assert report["status"] == "invalid_attestation"
    assert report["differences"] == []


def test_async_attest_eval_run_attaches_fingerprint_before_run(
    config_root: Path, tmp_audit_log: Tuple[Path, Any]
) -> None:
    calls: list[str] = []
    expected = build_config_fingerprint(config_root)

    async def runner() -> Dict[str, Any]:
        calls.append("started")
        # Änderung während des Laufs darf den vorab gebildeten Hash nicht ändern.
        (config_root / "roles.json").write_text('{"roles": ["admin"]}', encoding="utf-8")
        return {"status": "success", "eval_id": "eval-m71-2", "target_id": "default"}

    result = asyncio.run(attest_eval_run(runner, root=config_root, agent_id="qa"))
    assert calls == ["started"]
    assert result["status"] == "success"
    assert result["eval_id"] == "eval-m71-2"
    assert result["attestation"]["sha256"] == expected.sha256
    assert len(result["attestation"]["files"]) >= 8
    assert verify_attestation(result, root=config_root)["valid"] is False


def test_audit_event_goes_only_to_temporary_db(
    config_root: Path, tmp_audit_log: Tuple[Path, Any]
) -> None:
    db_path, injected_log = tmp_audit_log

    def runner() -> Dict[str, Any]:
        return {"status": "success", "eval_id": "eval-m71-3", "target_type": "profile"}

    result = attest_eval_run_sync(runner, root=config_root, agent_id="qa")
    assert str(injected_log.db_path) == str(db_path)
    assert attestation_module._AUDIT_LOG is injected_log

    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT category, action, agent_id, payload_json FROM audit_log"
        ).fetchall()
    assert len(rows) == 1
    category, action, agent_id, payload_json = rows[0]
    assert category == "eval"
    assert action == "eval_run_attested"
    assert agent_id == "qa"
    payload = json.loads(payload_json)
    assert payload["fingerprint_sha256"] == result["attestation"]["sha256"]
    assert payload["eval_id"] == "eval-m71-3"
    assert payload["target_type"] == "profile"
    # Kein Dateiinhalt, nur Pfade und Digests.
    assert all("sha256" in entry and "path" in entry for entry in payload["files"])


def test_eval_gates_wrapper_is_additive(
    config_root: Path, tmp_audit_log: Tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend import eval_gates

    async def fake_run(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        return {"status": "success", "eval_id": "eval-wrap", "target_id": args[1]}

    monkeypatch.setattr(eval_gates, "run_evaluation", fake_run)
    result = asyncio.run(
        eval_gates.run_attested_evaluation(
            "profile", "default", attestation_root=str(config_root)
        )
    )
    assert result["target_id"] == "default"
    assert result["attestation"]["sha256"] == build_config_fingerprint(config_root).sha256
