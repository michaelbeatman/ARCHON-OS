# -*- coding: utf-8 -*-
"""Welle W5-B — Regressionstests für D10-H1, D10-M1 und D10-M2.

Alle Tests fahren den Produktivpfad (Produzent -> Konsument -> Effekt ->
Verifikation): Chaos-Tester misst die echte SLA bis /livez 200, liest die
Watchdog-Liveness-Datei, der Restore-Tester ruft `litestream restore` in der
Sandbox auf. Kein PostgreSQL, kein Coroutine-Replay, keine Secrets, keine
fremden Dateien.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _FakeDockerClient:
    """Zeichnet den echten stop?t/start-Pfad auf, ohne Docker zu beruehren."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float | None]] = []

    def request(self, method: str, path: str, timeout: float | None = None) -> bytes:
        self.calls.append((method, path, timeout))
        return b""

    def restart_container(self, name: str) -> bytes:
        self.calls.append(("POST", f"/containers/{name}/restart", None))
        return b""

    def container_json(self, name: str) -> bytes:
        return json.dumps({"State": {"Status": "running"}}).encode("utf-8")


def _install_fake_docker(monkeypatch, fake: _FakeDockerClient) -> None:
    import utils.docker_client as docker_client

    monkeypatch.setattr(docker_client, "DockerAdminClient", lambda: fake)


# ---------------------------------------------------------------------------
# D10-H1 — Restart-SLA end-to-end, Dry-Run als Gate, Autoheal-Budget
# ---------------------------------------------------------------------------


def test_d10_h1_dry_run_is_skipped_and_breaks_exit_gate(monkeypatch):
    """Ein Dry-Run darf niemals 'passed' melden und muss exit 1 liefern."""
    import scripts.chaos_tester as ct

    result = ct.ArchonChaosTester(dry_run=True).test_simulated_container_restart("test-proxy")
    assert result["status"] == "skipped", result
    assert result["reason"] == "dry_run_sla_not_measurable"

    def _run_all(self):
        self.results["tests_skipped"] = 1  # Dry-Run wurde nicht gemessen
        return self.results

    monkeypatch.setattr(ct.ArchonChaosTester, "run_all", _run_all)
    monkeypatch.setattr(sys, "argv", ["chaos_tester.py"])
    with pytest.raises(SystemExit) as exc:
        ct.main()
    assert exc.value.code == 1, "skipped darf nicht als Exit 0 durchgehen"


def test_d10_h1_sla_is_measured_from_failure_to_livez_200(monkeypatch):
    """t_fail liegt vor dem Restart, t_recovered beim ersten /livez-200."""
    import scripts.chaos_tester as ct

    fake = _FakeDockerClient()
    _install_fake_docker(monkeypatch, fake)
    # clock(): t_fail, wait_for_livez deadline, t_recovered
    clocks = iter([100.0, 100.0, 110.0])

    result = ct.ArchonChaosTester(dry_run=False).test_simulated_container_restart(
        "test-proxy", clock=lambda: next(clocks), probe=lambda: True
    )

    assert result["status"] == "passed", result
    assert result["t_fail"] == 100.0
    assert result["t_recovered"] == 110.0
    assert result["recovery_time_sec"] == 10.0
    assert result["sla_violation"] is False
    assert result["measured_from"] == "simulated_failure_to_livez_200"
    assert fake.calls[0][1].startswith("/containers/test-proxy/stop?t=")
    assert fake.calls[1][1] == "/containers/test-proxy/start"


def test_d10_h1_late_livez_200_is_sla_violation(monkeypatch):
    """Auch ein erfolgreicher Restart ist FAILED, wenn /livez zu spaet kommt."""
    import scripts.chaos_tester as ct

    fake = _FakeDockerClient()
    _install_fake_docker(monkeypatch, fake)
    clocks = iter([100.0, 100.0, 120.0])

    result = ct.ArchonChaosTester(dry_run=False).test_simulated_container_restart(
        "test-proxy", clock=lambda: next(clocks), probe=lambda: True
    )

    assert result["status"] == "failed", result
    assert result["sla_violation"] is True
    assert result["recovery_time_sec"] == 20.0
    assert "restart_sla_exceeded" in result["reason"]


def test_d10_h1_never_healthy_is_failed_not_passed(monkeypatch):
    """Kein /livez-200 im Fenster ist ein harter Fehler."""
    import scripts.chaos_tester as ct

    fake = _FakeDockerClient()
    _install_fake_docker(monkeypatch, fake)
    monkeypatch.setattr(ct.time, "sleep", lambda _s: None)
    clocks = iter([100.0, 100.0, 200.0, 200.0])

    result = ct.ArchonChaosTester(dry_run=False).test_simulated_container_restart(
        "test-proxy", clock=lambda: next(clocks), probe=lambda: False
    )

    assert result["status"] == "failed", result
    assert result["t_recovered"] is None
    assert result["sla_violation"] is True
    assert "livez_not_recovered" in result["reason"]


def test_d10_h1_autoheal_detection_budget_and_fast_stop(monkeypatch):
    """Erkennung <= 15 s und kurzes SIGTERM-Fenster statt 90-s-Health-Gate."""
    import scripts.archon_autoheal as autoheal

    detection_budget = autoheal.INTERVAL * autoheal.FAILURES + autoheal.PROBE_TIMEOUT
    assert detection_budget <= 15.0, (autoheal.INTERVAL, autoheal.FAILURES, autoheal.PROBE_TIMEOUT)
    assert autoheal.HEALTH_GATE is False, "Docker-Health-Gate wuerde die SLA brechen"

    calls: list[tuple[str, str]] = []

    def _docker_request(method: str, path: str, payload=None) -> dict:
        calls.append((method, path))
        return {}

    monkeypatch.setattr(autoheal, "docker_request", _docker_request)
    assert autoheal._do_restart() is True
    assert calls[0] == ("POST", f"/containers/{autoheal.CONTAINER}/stop?t={autoheal.STOP_GRACE_S}")
    assert calls[1] == ("POST", f"/containers/{autoheal.CONTAINER}/start")


# ---------------------------------------------------------------------------
# D10-M1 — Watchdog-Responsiveness ueber watchdog_liveness.json
# ---------------------------------------------------------------------------


def _write_liveness(path: Path, loop_count: int, last_seen: float, *, alive: bool = True) -> None:
    path.write_text(
        json.dumps({
            "last_seen": last_seen,
            "loop_count": loop_count,
            "pid": 4242,
            "alive": alive,
        }),
        encoding="utf-8",
    )


def test_d10_m1_watchdog_uses_liveness_file_not_legacy_log():
    """Statischer Gate: der nie geschriebene Logpfad darf nicht mehr vorkommen."""
    src = (ROOT / "scripts" / "chaos_tester.py").read_text(encoding="utf-8")
    assert "watchdog_liveness.json" in src
    assert "no_watchdog_log_evidence" not in src
    assert "loop_advanced" in src


def test_d10_m1_advancing_loop_count_and_fresh_timestamp_passes(tmp_path, monkeypatch):
    """Zwei Proben: loop_count erhoeht, last_seen frisch -> passed."""
    import scripts.chaos_tester as ct

    liveness = tmp_path / "watchdog_liveness.json"
    now = time.time()
    _write_liveness(liveness, 5, now)
    monkeypatch.setattr(ct, "WATCHDOG_LIVENESS_CANDIDATES", (str(liveness),))

    def _advance_during_wait(_seconds):
        _write_liveness(liveness, 6, now + 31.0)

    monkeypatch.setattr(ct.time, "sleep", _advance_during_wait)
    result = ct.ArchonChaosTester(dry_run=True).test_watchdog_supervisor_responsiveness(
        sample_interval_s=0.0, clock=lambda: now + 31.0
    )
    assert result["status"] == "passed", result
    assert result["evidence_file"] == "watchdog_liveness.json"
    assert result["loop_advanced"] is True
    assert result["last_seen_advanced"] is True


def test_d10_m1_missing_liveness_evidence_is_failed(tmp_path, monkeypatch):
    """Fehlende Evidenz ist ein Fehler, kein skipped und kein Exit 0."""
    import scripts.chaos_tester as ct

    monkeypatch.setattr(
        ct, "WATCHDOG_LIVENESS_CANDIDATES", (str(tmp_path / "does_not_exist.json"),)
    )
    result = ct.ArchonChaosTester(dry_run=True).test_watchdog_supervisor_responsiveness(
        sample_interval_s=0.0
    )
    assert result["status"] == "failed", result
    assert result["reason"] == "watchdog_liveness_evidence_missing"


def test_d10_m1_stalled_or_stale_watchdog_is_failed(tmp_path, monkeypatch):
    """Gleicher loop_count oder altes last_seen -> failed."""
    import scripts.chaos_tester as ct

    liveness = tmp_path / "watchdog_liveness.json"
    now = time.time()
    _write_liveness(liveness, 5, now - 300.0)
    monkeypatch.setattr(ct, "WATCHDOG_LIVENESS_CANDIDATES", (str(liveness),))

    result = ct.ArchonChaosTester(dry_run=True).test_watchdog_supervisor_responsiveness(
        sample_interval_s=0.0, clock=lambda: now
    )
    assert result["status"] == "failed", result
    assert result["loop_advanced"] is False
    assert result["last_seen_age_s"] >= 300.0


# ---------------------------------------------------------------------------
# D10-M2 — echter Litestream-Restore in der Sandbox
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_restore(monkeypatch, tmp_path):
    """Isoliert Replikat-/Backup-/Historiepfade des Restore-Testers."""
    import scripts.automated_restore_test as rt

    replica_root = tmp_path / "replicas"
    replica_root.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(rt, "LITESTREAM_REPLICA_DIR", str(replica_root))
    monkeypatch.setattr(rt, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(rt, "HISTORY_FILE", str(tmp_path / "restore_history.json"))
    monkeypatch.setattr(rt, "_tenant_dbs_present", lambda: [])
    return rt, replica_root


def _fake_litestream(monkeypatch, rt, *, returncode: int = 0, calls: list | None = None):
    """Materialisiert beim 'litestream restore' eine echte SQLite-Datei."""

    def _run(cmd: list[str], **_kwargs):
        if calls is not None:
            calls.append(cmd)
        if returncode != 0:
            return subprocess.CompletedProcess(cmd, returncode, "", "restore_failed")
        dest = Path(cmd[cmd.index("-o") + 1])
        conn = sqlite3.connect(str(dest))
        try:
            conn.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
            conn.execute("INSERT INTO tasks (title) VALUES ('restore-ok')")
            conn.commit()
        finally:
            conn.close()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(rt.subprocess, "run", _run)


def test_d10_m2_replica_is_really_restored_and_verified(monkeypatch, isolated_restore):
    """Der echte CLI-Aufruf landet in der Sandbox und wird geprueft."""
    rt, replica_root = isolated_restore
    replica = replica_root / "ops.db"  # Litestream-Zielverzeichnis
    replica.mkdir()
    (replica / "wal_segment").write_bytes(b"x")  # Timestamp-Evidenz
    calls: list[list[str]] = []
    _fake_litestream(monkeypatch, rt, calls=calls)

    tester = rt.AutomatedRestoreTester()
    tester.dbs_to_test = []  # nur den Litestream-Pfad isoliert testen
    result = tester.run_restore_test(notify=False)

    detail = next(
        d for d in result["details"]
        if d["database"] == "LITESTREAM_RESTORE:ops.db"
    )
    assert detail["status"] == "PASSED", detail
    assert detail["restore_returncode"] == 0
    assert detail["integrity_check"] == "ok"
    assert detail["foreign_key_check"] == "OK"
    assert detail["record_count"] == 1
    assert result["litestream_replicas_found"] == 1
    assert result["overall_status"] == "PASSED", result
    assert len(calls) == 1
    assert calls[0][:2] == ["litestream", "restore"]
    assert "-o" in calls[0] and "-config" in calls[0]


def test_d10_m2_missing_replica_is_failed_not_skipped(monkeypatch, isolated_restore):
    """Kein Replikat-Artefakt ist FAILED — nicht SKIPPED, nicht gruen."""
    rt, _replica_root = isolated_restore
    tester = rt.AutomatedRestoreTester()
    tester.dbs_to_test = []
    result = tester.run_restore_test(notify=False)

    detail = next(d for d in result["details"] if d["database"] == "LITESTREAM_REPLICA_SOURCE")
    assert detail["status"] == "FAILED", detail
    assert result["databases_failed"] >= 1
    assert result["overall_status"] == "FAILED"


def test_d10_m2_stale_replica_is_failed(monkeypatch, isolated_restore):
    """Veraltetes Replikat verletzt das RPO-Fenster (sync-interval 5-10 s)."""
    rt, replica_root = isolated_restore
    replica = replica_root / "ops.db"
    replica.mkdir()
    segment = replica / "wal_segment"
    segment.write_bytes(b"x")
    old = time.time() - 3600.0
    os.utime(segment, (old, old))
    _fake_litestream(monkeypatch, rt)

    tester = rt.AutomatedRestoreTester()
    tester.dbs_to_test = []
    result = tester.run_restore_test(notify=False)

    detail = next(d for d in result["details"] if d["database"] == "LITESTREAM_RESTORE:ops.db")
    assert detail["status"] == "FAILED", detail
    assert "veraltet" in detail["error"]
    assert result["overall_status"] == "FAILED"


def test_d10_m2_restore_command_failure_is_failed(monkeypatch, isolated_restore):
    """Ein fehlgeschlagener `litestream restore` darf nie PASSED werden."""
    rt, replica_root = isolated_restore
    replica = replica_root / "ops.db"
    replica.mkdir()
    (replica / "wal_segment").write_bytes(b"x")
    _fake_litestream(monkeypatch, rt, returncode=1)

    tester = rt.AutomatedRestoreTester()
    tester.dbs_to_test = []
    result = tester.run_restore_test(notify=False)

    detail = next(d for d in result["details"] if d["database"] == "LITESTREAM_RESTORE:ops.db")
    assert detail["status"] == "FAILED", detail
    assert "exit 1" in detail["error"]
    assert result["overall_status"] == "FAILED"


def test_d10_m2_tenant_replication_needs_real_restore(monkeypatch, isolated_restore):
    """Config-Praesenz allein genuegt fuer TENANT_REPLICATION nicht mehr."""
    rt, replica_root = isolated_restore
    tenant_live = ROOT / "data" / "tenants" / "t-w5b" / "tenant.db"
    monkeypatch.setattr(rt, "_tenant_dbs_present", lambda: [str(tenant_live)])
    monkeypatch.setattr(rt, "_litestream_covers_tenants", lambda: True)

    tester = rt.AutomatedRestoreTester()
    tester.dbs_to_test = []

    # 1. Nur Config, kein Replikat -> FAILED
    result = tester.run_restore_test(notify=False)
    tenant = next(d for d in result["details"] if d["database"] == "TENANT_REPLICATION")
    assert tenant["status"] == "FAILED", tenant
    assert tenant["litestream_config_present"] is True
    assert tenant["litestream_restore_verified"] is False

    # 2. Echtes Tenant-Replikat restore-verifiziert -> PASSED
    tenant_replica = replica_root / "tenants" / "t-w5b" / "tenant.db"
    tenant_replica.parent.mkdir(parents=True)
    tenant_replica.write_bytes(b"replica-evidence")
    _fake_litestream(monkeypatch, rt)
    result = tester.run_restore_test(notify=False)
    tenant = next(d for d in result["details"] if d["database"] == "TENANT_REPLICATION")
    assert tenant["status"] == "PASSED", tenant
    assert tenant["litestream_restore_verified"] is True


def test_d10_m2_guide_and_alerts_are_honest():
    """Doku und Alert-Kommentar duerfen keinenScheinerfolg behaupten."""
    guide = (ROOT / "docs" / "system" / "AUTOMATED_RESTORE_TEST_GUIDE.md").read_text(
        encoding="utf-8"
    )
    assert "litestream restore" in guide
    assert "ARCHON_LITESTREAM_REPLICA_DIR" in guide
    assert "PASSED 5/5" not in guide
    assert "Konfigurationspräsenz" in guide or "Konfigurationspraesenz" in guide

    alerts = (ROOT / "config" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
    assert "tests_skipped" in alerts
    assert "nicht verdrahtet" in alerts.lower()
