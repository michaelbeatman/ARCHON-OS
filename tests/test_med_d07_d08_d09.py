"""Regressionstests fuer MED-Funde aus D07/D08/D09 (Stage-1-Reaudit).

Abgedeckt:
  D07  backend/durable_execution_kernel.py — schliessende SQLite-Verbindungen,
        korruptes state_json/payload_json nicht als leerer State.
  D08  backend/async_write_batcher.py — Retention + materialisierter Zaehler,
        frontend/src — AbortController und Template-Fensterung.
  D09  frontend/src/components/AuthModal.tsx — Dialog-Semantik/Fokus-Trap,
        Dockerfile / requirements.lock.txt — reproduzierbare pip-Basis.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import inspect
from contextlib import closing
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------- D07 / Kernel

def test_d07_connect_closes_connection_on_with_exit(tmp_path):
    from backend import durable_execution_kernel as kernel_mod

    conn = kernel_mod._connect(str(tmp_path / "conn.db"))
    assert isinstance(conn, kernel_mod._ArchonClosingConn)
    with conn as active:
        active.execute("CREATE TABLE ping (id INTEGER)")
    # sqlite3.Connection hat kein .closed-Attribut — eine geschlossene
    # Verbindung verweigert jeden weiteren Execute.
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_d07_all_kernel_connections_are_closed(tmp_path, monkeypatch):
    from backend import durable_execution_kernel as kernel_mod

    created = []
    original = kernel_mod.sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = original(*args, **kwargs)
        created.append(conn)
        return conn

    monkeypatch.setattr(kernel_mod.sqlite3, "connect", tracking_connect)

    kernel = kernel_mod.DurableExecutionKernel(db_path=str(tmp_path / "kernel.db"))
    claim = kernel.claim("fd-run")
    token = claim["fencing_token"]
    for _ in range(25):
        kernel.renew("fd-run", token)
        kernel.get_state("fd-run")
        kernel.command_log("fd-run")

    assert len(created) > 25
    for conn in created:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def _corrupt_field(db_path: Path, table: str, column: str, run_id: str) -> None:
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.execute(f"UPDATE {table} SET {column} = '{{kaputt' WHERE run_id = ?", (run_id,))
        conn.commit()


def test_d07_corrupt_state_json_blocks_resume_instead_of_false_success(tmp_path):
    from backend.durable_execution_kernel import (
        DurableExecutionKernel, SUSPENDED,
    )

    db_path = tmp_path / "corrupt.db"
    kernel = DurableExecutionKernel(db_path=str(db_path))
    token = kernel.claim("corrupt-run")["fencing_token"]
    kernel.suspend("corrupt-run", token, 2, {"step": "research"}, reason="hitl")
    _corrupt_field(db_path, "durable_executions", "state_json", "corrupt-run")

    state = kernel.get_state("corrupt-run")
    assert state["state_data"] is None
    assert state["checkpoint_error"] == "corrupt_state_json"
    assert state["resume_blocked"] is True

    ctx = kernel.resume_context("corrupt-run")
    assert ctx["checkpoint_error"] == "corrupt_state_json"
    assert ctx["resume_blocked"] is True

    resumed = kernel.resume_suspended("corrupt-run", ctx["fencing_token"])
    assert resumed["status"] == "resume_blocked"
    assert resumed["resume_blocked"] is True
    assert resumed["checkpoint_error"] == "corrupt_state_json"

    # Keine Transition, kein Event-Replay: der Run bleibt SUSPENDED.
    with closing(sqlite3.connect(str(db_path))) as conn:
        row = conn.execute(
            "SELECT state FROM durable_executions WHERE run_id = ?", ("corrupt-run",)
        ).fetchone()
        commands = conn.execute(
            "SELECT command_type FROM durable_commands WHERE run_id = ?", ("corrupt-run",)
        ).fetchall()
    assert row[0] == SUSPENDED
    assert [c[0] for c in commands].count("resume") == 0


def test_d07_corrupt_payload_json_is_marked(tmp_path):
    from backend.durable_execution_kernel import DurableExecutionKernel

    db_path = tmp_path / "payload.db"
    kernel = DurableExecutionKernel(db_path=str(db_path))
    token = kernel.claim("payload-run")["fencing_token"]
    kernel.append_command("payload-run", "note", {"ok": True}, token)
    _corrupt_field(db_path, "durable_commands", "payload_json", "payload-run")

    commands = kernel.command_log("payload-run")
    assert commands
    assert commands[0]["payload"] is None
    assert commands[0]["payload_error"] == "corrupt_payload_json"


# ------------------------------------------------------------- D08 / Batcher

def test_d08_telemetry_retention_and_bounded_stats(tmp_path, monkeypatch):
    from backend import async_write_batcher as batcher_mod

    db_path = tmp_path / "telemetry.db"
    monkeypatch.setattr(batcher_mod, "DB_PATH", str(db_path))
    monkeypatch.setattr(batcher_mod, "_get_cfg", lambda: {
        "enabled": True,
        "batch_size": 1000,
        "flush_interval_seconds": 999.0,
        "max_queue_size": 1000,
        "retention_max_rows": 7,
    })

    batcher = batcher_mod.AsyncWriteBatcher()
    for i in range(30):
        batcher.enqueue("evt", "test", {"i": i})
        result = batcher.flush()
        assert result["flushed_count"] == 1

    stats = batcher.get_stats()
    assert stats["persisted_in_db"] <= 7
    assert stats["total_flushed_events"] == 30

    with closing(sqlite3.connect(str(db_path))) as conn:
        count = conn.execute("SELECT COUNT(*) FROM batched_telemetry_events").fetchone()[0]
        newest = conn.execute(
            "SELECT payload_json FROM batched_telemetry_events ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    assert count <= 7
    assert json.loads(newest) == {"i": 29}

    # Statistik darf keinen unbegrenzten COUNT(*)-Full-Scan mehr ausfuehren.
    assert "COUNT(*)" not in inspect.getsource(batcher_mod.AsyncWriteBatcher.get_stats)


# --------------------------------------------------------------- D08 / Frontend

def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_d08_frontend_abort_controllers_and_template_window():
    cockpit = _read("frontend/src/components/WorkflowCockpit.tsx")
    panel = _read("frontend/src/components/UnifiedAgentControlPanel.tsx")
    gateway = _read("frontend/src/components/GatewayManagerModal.tsx")
    api = _read("frontend/src/lib/archon-api.ts")

    assert "new AbortController()" in cockpit
    assert "return () => controller.abort();" in cockpit
    assert "templates.slice(0, tplVisibleCount)" in cockpit
    assert "new AbortController()" in panel
    assert "sendAbortRef.current?.abort()" in panel
    assert "new AbortController()" in gateway
    assert "function withSignal" in api


# --------------------------------------------------------------- D09 / Frontend

def test_d09_auth_modal_has_dialog_semantics_and_focus_trap():
    src = _read("frontend/src/components/AuthModal.tsx")
    assert 'role="dialog"' in src
    assert 'aria-modal="true"' in src
    assert 'aria-labelledby="auth-modal-title"' in src
    assert "document.addEventListener('keydown', onKeyDown)" in src
    assert "event.key === 'Escape'" in src
    assert "previousFocus?.focus()" in src
    # useRef/useEffect muessen vor dem `if (!isOpen) return null` stehen.
    assert src.index("useRef<HTMLDivElement>") < src.index("if (!isOpen) return null;")


# ------------------------------------------------------- D09 / Reproduzierbarkeit

def test_d09_dockerfile_has_no_unpinned_pip_upgrade():
    dockerfile = _read("Dockerfile")
    # Nur echte RUN-Zeilen zählen — der Erklärungskommentar darf den Begriff
    # „--upgrade pip" enthalten.
    run_lines = [line for line in dockerfile.splitlines() if line.strip().startswith("RUN ")]
    assert not any("--upgrade pip" in line for line in run_lines)
    assert "--require-hashes --no-deps -r requirements.lock.txt" in dockerfile


def test_d09_lockfile_header_has_no_stale_ci_line_references():
    header = "\n".join(_read("requirements.lock.txt").splitlines()[:12])
    assert "ci.yml:94" not in header
    assert "ci.yml:166" not in header
    assert "--require-hashes" in header


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
