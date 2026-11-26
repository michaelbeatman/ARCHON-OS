"""W1-B / D03-H2 — Mandantenisoliertes DAG-Ledger (workflow_runs / node_states).

Regression für den HIGH-Befund: ``workflow_dags.db`` lag in der globalen
``ops.db``, ``workflow_runs``/``workflow_node_states`` hatten keine
``tenant_id``. Zwei Mandanten mit identischer ``run_id`` überschrieben sich
und fremde ``gate_approvals_json`` / ``output_json`` wurden gelesen.

Alle Tests nutzen explizite tmp_path-DBs und den tenant_context-ContextVar —
keine Produktiv-DB wird berührt. Kein PostgreSQL, kein Replay (NEVER_DO_LIST).
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TENANT_A = "tenant_a"
TENANT_B = "tenant_b"
SHARED_RUN = "wfrun-identical"
SHARED_NODE = "gate-1"


def _pk_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall() if r[5]]


# ---------------------------------------------------------------------------
# DB-Pfad-Auflösung (D03-H2.1): resolve_active_db("ops.db"), hart fail-closed
# ---------------------------------------------------------------------------


def test_dag_db_path_uses_tenant_ops_db_and_fails_closed(monkeypatch):
    import backend.workflow_dag_runner as dag
    from backend import tenant_context as tc

    assert dag.DEFAULT_DB_PATH == dag._INITIAL_DEFAULT_DB_PATH

    seen: list[str] = []
    expected = str(REPO_ROOT / "data" / "tenants" / TENANT_A / "ops.db")

    def _resolve(filename: str) -> str:
        seen.append(filename)
        return expected

    monkeypatch.setattr(tc.tenant_context, "resolve_active_db", _resolve)
    assert dag._resolve_dag_db_path() == expected
    assert seen == ["ops.db"], "DAG-Ledger muss ueber ops.db aufgeloest werden"

    def _broken(filename: str) -> str:
        raise RuntimeError("tenant resolver unavailable")

    monkeypatch.setattr(tc.tenant_context, "resolve_active_db", _broken)
    with pytest.raises(RuntimeError, match="Tenant-DB-Aufl"):
        dag._resolve_dag_db_path()
    # Kein stiller Fallback auf die globale DEFAULT_DB_PATH.

    monkeypatch.setattr(tc.tenant_context, "resolve_active_db", _broken)
    assert dag._resolve_dag_db_path("/tmp/explicit-ops.db") == "/tmp/explicit-ops.db"


def test_missing_tenant_context_aborts_ledger_access(monkeypatch, tmp_path):
    import backend.workflow_dag_runner as dag
    from backend import tenant_context as tc

    def _broken() -> str:
        raise RuntimeError("no active company")

    monkeypatch.setattr(tc.tenant_context, "get_active_tenant_id", _broken)
    with pytest.raises(RuntimeError, match="Tenant-Kontext"):
        dag._persist_run_status_sync(
            str(tmp_path / "dag.db"), "r1", "wf", "running", "{}", time.time()
        )


# ---------------------------------------------------------------------------
# Schema (D03-H2.2): tenant_id NOT NULL + PK (tenant_id, run_id[, node_id])
# ---------------------------------------------------------------------------


def test_tenant_scoped_schema(tmp_path):
    import backend.workflow_dag_runner as dag

    db = str(tmp_path / "schema.db")
    with dag._connect(db, tenant_id=TENANT_A) as conn:
        assert _pk_columns(conn, "workflow_runs") == ["tenant_id", "run_id"]
        assert _pk_columns(conn, "workflow_node_states") == [
            "tenant_id", "run_id", "node_id"
        ]
        cols = {str(r[1]): r for r in conn.execute("PRAGMA table_info(workflow_runs)")}
        assert int(cols["tenant_id"][3]) == 1, "tenant_id muss NOT NULL sein"
        node_cols = {
            str(r[1]): r for r in conn.execute("PRAGMA table_info(workflow_node_states)")
        }
        assert int(node_cols["tenant_id"][3]) == 1


def test_legacy_schema_migration_assigns_primary_tenant(tmp_path):
    import backend.workflow_dag_runner as dag
    from backend import tenant_context as tc

    primary = tc.sanitize_tenant_id(tc.tenant_context.get_active_tenant_id())
    db = str(tmp_path / "legacy.db")
    with sqlite3.connect(db) as conn:
        conn.execute("""
            CREATE TABLE workflow_runs (
                run_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                status TEXT NOT NULL,
                dag_json TEXT DEFAULT '{}',
                gate_approvals_json TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE workflow_node_states (
                run_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                output_json TEXT DEFAULT '{}',
                updated_at REAL NOT NULL,
                PRIMARY KEY (run_id, node_id)
            )
        """)
        conn.execute(
            "INSERT INTO workflow_runs VALUES (?,?,?,?,?,?,?)",
            ("legacy-run", "wf", "completed", "{}", '{"gate":true}', 1.0, 2.0),
        )
        conn.execute(
            "INSERT INTO workflow_node_states VALUES (?,?,?,?,?,?)",
            ("legacy-run", "n1", "fp", "completed", '{"content":"legacy"}', 2.0),
        )
        conn.commit()

    # Migration laeuft additiv beim ersten Ledger-Zugriff.
    with dag._connect(db, tenant_id=TENANT_B) as conn:
        assert _pk_columns(conn, "workflow_runs") == ["tenant_id", "run_id"]
        assert _pk_columns(conn, "workflow_node_states") == [
            "tenant_id", "run_id", "node_id"
        ]
        migrated = conn.execute(
            "SELECT tenant_id, run_id FROM workflow_runs"
        ).fetchall()
        assert [(r["tenant_id"], r["run_id"]) for r in migrated] == [(primary, "legacy-run")]
        node = conn.execute(
            "SELECT tenant_id, output_json FROM workflow_node_states"
        ).fetchone()
        assert node[0] == primary and "legacy" in node[1]

    # Identische run_id des zweiten Mandanten kollidiert nicht mehr.
    dag._persist_run_status_sync(
        db, "legacy-run", "wf", "running", "{}", time.time(), tenant_id=TENANT_B
    )
    with sqlite3.connect(db) as conn:
        rows = {
            tuple(r) for r in conn.execute(
                "SELECT tenant_id, run_id FROM workflow_runs"
            ).fetchall()
        }
    assert rows == {(primary, "legacy-run"), (TENANT_B, "legacy-run")}


# ---------------------------------------------------------------------------
# Zwei-Tenant-Regression (D03-H2.4)
# ---------------------------------------------------------------------------


def test_two_tenants_same_run_id_are_isolated(tmp_path):
    import backend.workflow_dag_runner as dag

    db = str(tmp_path / "shared_ops.db")
    now = time.time()

    # A: Run + Gate-Freigabe + Node-Output
    gate_a = dag._load_run_gate_state_sync(
        db, SHARED_RUN, "wf", {"gate-1": True}, now, '{"id":"wf"}',
        tenant_id=TENANT_A,
    )
    assert gate_a["approvals"] == {"gate-1": True}
    dag._persist_node_state_sync(
        db, SHARED_RUN, SHARED_NODE, "fp-a", "completed",
        '{"content":"A","cost_usd":1.0,"input_tokens":10,"output_tokens":0}',
        now, tenant_id=TENANT_A,
    )

    # B: identische run_id / node_id — darf A weder ueberschreiben noch lesen
    gate_b = dag._load_run_gate_state_sync(
        db, SHARED_RUN, "wf", {"gate-1": False}, now, '{"id":"wf"}',
        tenant_id=TENANT_B,
    )
    assert gate_b["approvals"] == {"gate-1": False}
    dag._persist_node_state_sync(
        db, SHARED_RUN, SHARED_NODE, "fp-b", "completed",
        '{"content":"B","cost_usd":2.0,"input_tokens":20,"output_tokens":0}',
        now, tenant_id=TENANT_B,
    )

    with sqlite3.connect(db) as conn:
        runs = conn.execute(
            "SELECT tenant_id, status FROM workflow_runs "
            "WHERE run_id = ? ORDER BY tenant_id", (SHARED_RUN,)
        ).fetchall()
        nodes = conn.execute(
            "SELECT tenant_id, output_json FROM workflow_node_states "
            "WHERE run_id = ? AND node_id = ? ORDER BY tenant_id",
            (SHARED_RUN, SHARED_NODE),
        ).fetchall()
    assert runs == [(TENANT_A, "running"), (TENANT_B, "running")]
    assert len(nodes) == 2
    assert "content\":\"A" in nodes[0][1] and "content\":\"B" in nodes[1][1]

    # Keine gegenseitige Sichtbarkeit über die öffentlichen APIs.
    seen_a = dag.get_workflow_run(SHARED_RUN, db_path=db, tenant_id=TENANT_A)
    seen_b = dag.get_workflow_run(SHARED_RUN, db_path=db, tenant_id=TENANT_B)
    assert seen_a["tenant_id"] == TENANT_A and seen_b["tenant_id"] == TENANT_B
    assert seen_a["nodes"][SHARED_NODE]["output"]["content"] == "A"
    assert seen_b["nodes"][SHARED_NODE]["output"]["content"] == "B"
    assert dag.get_workflow_run(SHARED_RUN, db_path=db, tenant_id="unknown") is None

    assert {r["tenant_id"] for r in dag.list_workflow_runs(db_path=db, tenant_id=TENANT_A)} == {TENANT_A}
    assert {r["tenant_id"] for r in dag.list_workflow_runs(db_path=db, tenant_id=TENANT_B)} == {TENANT_B}

    # Cancel-Persistenz trifft nur den eigenen Mandanten.
    assert dag._persist_run_cancelled_sync(db, SHARED_RUN, tenant_id=TENANT_A)["updated"] is True
    assert dag.get_workflow_run(SHARED_RUN, db_path=db, tenant_id=TENANT_A)["status"] == "cancelled"
    assert dag.get_workflow_run(SHARED_RUN, db_path=db, tenant_id=TENANT_B)["status"] == "running"

    # Verify/Kostenaggregation (finalize) liest nur eigene output_json.
    dag._finalize_run_sync(
        db, SHARED_RUN, "wf", "completed", None, "traj-a", {}, tenant_id=TENANT_A
    )
    with sqlite3.connect(db) as conn:
        costs = dict(conn.execute(
            "SELECT tenant_id, total_cost_usd FROM workflow_runs WHERE run_id = ?",
            (SHARED_RUN,),
        ).fetchall())
    assert costs[TENANT_A] == pytest.approx(1.0)
    assert costs[TENANT_B] == 0.0


def test_contextvar_tenant_is_used_without_explicit_param(tmp_path):
    """Produktivpfad: Request-ContextVar liefert die tenant_id (kein Parameter noetig)."""
    import backend.workflow_dag_runner as dag
    from backend import tenant_context as tc

    db = str(tmp_path / "ctx.db")
    token = tc._REQUEST_TENANT_VAR.set(tc.sanitize_tenant_id(TENANT_A))
    try:
        dag._persist_run_status_sync(db, "ctx-run", "wf", "running", "{}", time.time())
    finally:
        tc._REQUEST_TENANT_VAR.reset(token)

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT tenant_id FROM workflow_runs WHERE run_id = 'ctx-run'"
        ).fetchall()
    assert rows == [(TENANT_A,)]
