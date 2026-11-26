"""W3-C (Orchestrierung) — Regressionstests fuer D07-H1/H2 und D11-H1/H2/H3 + M1/M2/M5.

Alle Tests laufen offline gegen temporaere SQLite-DBs und pruefen den
Produktivpfad (Signatur → Konsument → Gate → Dispatch), nicht nur Einzelfunktionen.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture()
def hmac_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARCHON_DELEGATION_HMAC_KEY", "w3c-delegation-key")
    monkeypatch.setenv("ARCHON_HANDOFF_HMAC_KEY", "w3c-handoff-key")
    monkeypatch.setenv("ARCHON_AUDIT_HMAC_KEY", "w3c-audit-key")
    monkeypatch.setenv("ARCHON_WARRANT_SECRET", "w3c-warrant-secret-0123456789abcdef")


def _kanban_db(path: Path, *, assignee: str = "worker", created: str = "") -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, body TEXT, "
            "assignee TEXT, status TEXT, priority TEXT, created_by TEXT, "
            "created_at TEXT, started_at TEXT, completed_at TEXT, result TEXT, "
            "model_override TEXT, provider_override TEXT, project_id TEXT, "
            "block_kind TEXT, token_budget INTEGER DEFAULT 0, "
            "proof_command TEXT DEFAULT '', consecutive_failures INTEGER DEFAULT 0, "
            "tenant_id TEXT DEFAULT 'default')"
        )
        conn.execute(
            "INSERT INTO tasks (id, title, body, assignee, status, priority, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("t-w3c", "Auftrag", "Body", assignee, "todo", "1", "2026-11-26"),
        )
        conn.execute(
            "CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "task_id TEXT, run_id INTEGER, kind TEXT, payload TEXT, created_at INTEGER)"
        )
        if created:
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?,?,?,?)",
                ("t-w3c", "created", created, 1),
            )
        conn.commit()
    finally:
        conn.close()


def _deps(db_path: Path, profiles: Dict[str, Any], loader: Any) -> Any:
    import backend.operations_execution as ops_exec

    def _conn(*_a: Any, **_kw: Any) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    return ops_exec.ExecutionDeps(
        get_active_kanban_db_path=lambda: str(db_path),
        get_kanban_connection=_conn,
        load_kanban_delegation_payload=loader,
        sync_to_memory_bridge=lambda *_a, **_kw: None,
        load_profiles_map=lambda: profiles,
        resolve_task_obsidian_rel=lambda _tid: "",
        load_kanban_meta=lambda: {},
    )


@pytest.fixture()
def worker_deps(monkeypatch: pytest.MonkeyPatch):
    import backend.operations_execution as ops_exec

    installed: Dict[str, Any] = {}

    def _install(deps: Any) -> None:
        ops_exec.register_execution_deps_provider(lambda: deps)
        installed["deps"] = deps

    previous = ops_exec._DEPS_PROVIDER
    try:
        yield _install
    finally:
        ops_exec._DEPS_PROVIDER = previous


def _signed_payload(**overrides: Any) -> Dict[str, Any]:
    from archon.core.delegation import HandoffDelegationPayload, sign_delegation_payload

    # Typkorrekte Defaults aus dem kanonischen Schema (keine leeren Strings
    # fuer bool/list/int-Felder).
    payload: Dict[str, Any] = HandoffDelegationPayload.model_validate({
        "ziel_agent": "worker", "auftrag": "A" * 400,
    }).model_dump()
    payload.update({
        "task_id": "t-w3c",
        "ziel_agent": "worker",
        "assignee": "worker",
        "auftrag": "A" * 400,  # voller Auftrag, nicht auftrag[:80]
        "delegation_chain": ["delegator", "worker"],
        "taint_status": "unknown",
        "soul_mode": "compact",
        "budget_remaining_tokens": None,
        "warrant_id": "war-w3c",
        "complexity_weight": 2.0,
        "budget_share_pct": 25.0,
        "token_budget": 5000,
        "trace_id": "trace-w3c",
        "correlation_id": "trace:trace-w3c",
        "extensions": {"marker": "keep-me"},
    })
    payload.update(overrides)
    payload["payload_signature"] = sign_delegation_payload(payload)
    return payload


# ---------------------------------------------------------------------------
# D07-H1 — Zombie-Reset fail-closed
# ---------------------------------------------------------------------------

def test_zombie_guard_import_error_never_resets_and_audits(tmp_path, monkeypatch):
    import backend.operations_api as ops_api

    db = tmp_path / "zombie.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE tasks (id TEXT, status TEXT, started_at REAL, created_at TEXT, "
        "claim_expires REAL, claim_lock INTEGER, pid INTEGER)"
    )
    conn.execute(
        "INSERT INTO tasks VALUES ('t-old', 'in_progress', ?, NULL, NULL, NULL, NULL)",
        (time.time() - 7 * 3600,),
    )
    conn.commit()
    monkeypatch.setattr(ops_api, "_ZOMBIE_RESET_LAST_RUN", {"ts": 0.0})
    monkeypatch.setitem(sys.modules, "backend.trajectory_budget", None)
    audits: list = []
    monkeypatch.setattr(
        "backend.audit_log._require_audit_event",
        lambda *a, **k: audits.append((a, k)) or {},  # type: ignore[func-returns-value]
    )

    assert ops_api._maybe_auto_reset_zombie_tasks(conn) == 0
    assert conn.execute("SELECT status FROM tasks WHERE id='t-old'").fetchone()[0] == "in_progress"
    assert any(a[1] == "zombie_guard_unavailable" for a, _ in audits)
    conn.close()


def test_zombie_reset_still_respects_active_lease(tmp_path, monkeypatch):
    import backend.operations_api as ops_api

    monkeypatch.delitem(sys.modules, "backend.trajectory_budget", raising=False)
    db = tmp_path / "zombie-live.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE tasks (id TEXT, status TEXT, started_at REAL, created_at TEXT, "
        "claim_expires REAL, claim_lock INTEGER, pid INTEGER)"
    )
    conn.execute(
        "INSERT INTO tasks VALUES ('t-live', 'in_progress', ?, NULL, ?, 1, 4242)",
        (time.time() - 7 * 3600, time.time() + 3600),
    )
    conn.commit()
    monkeypatch.setattr(ops_api, "_ZOMBIE_RESET_LAST_RUN", {"ts": 0.0})
    assert ops_api._maybe_auto_reset_zombie_tasks(conn) == 0
    assert conn.execute("SELECT status FROM tasks").fetchone()[0] == "in_progress"
    conn.close()


# ---------------------------------------------------------------------------
# D07-H2 — Lease-Fail-Open entfernt
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lease_fail_open_env_is_ignored(monkeypatch, hmac_env):
    import backend.operations_execution as ops_exec
    from backend.deadlock_supervisor import deadlock_supervisor

    monkeypatch.setenv("ARCHON_LEASE_FAIL_OPEN", "1")
    monkeypatch.setattr(
        deadlock_supervisor, "acquire_lease",
        lambda _tid: (_ for _ in ()).throw(RuntimeError("claim db down")),
    )
    dispatched: list = []

    async def _fake_inner(task_id: str, *, lease_token: str = "") -> Any:
        dispatched.append((task_id, lease_token))
        return {"ok": True}

    monkeypatch.setattr(ops_exec, "_execute_kanban_task_inner", _fake_inner)
    monkeypatch.setattr(
        "backend.audit_log._require_audit_event", lambda *a, **k: {}
    )
    result = await ops_exec._execute_kanban_task_async("t-w3c")
    assert result["skipped"] == "lease_unavailable"
    assert dispatched == []


@pytest.mark.asyncio
@pytest.mark.parametrize("claim", [
    {"acquired": False, "task_exists": False},
    {"acquired": True, "lease_token": ""},
])
async def test_no_dispatch_without_valid_lease_token(monkeypatch, hmac_env, claim):
    import backend.operations_execution as ops_exec
    from backend.deadlock_supervisor import deadlock_supervisor

    monkeypatch.setattr(deadlock_supervisor, "acquire_lease", lambda _tid: claim)
    dispatched: list = []

    async def _fake_inner(task_id: str, *, lease_token: str = "") -> Any:
        dispatched.append((task_id, lease_token))
        return {"ok": True}

    monkeypatch.setattr(ops_exec, "_execute_kanban_task_inner", _fake_inner)
    result = await ops_exec._execute_kanban_task_async("t-w3c")
    assert result["skipped"] == "lease_unavailable"
    assert dispatched == []


# ---------------------------------------------------------------------------
# D11-H1/H2 — Signatur vor Kanonisierung, EIN signiertes Payload
# ---------------------------------------------------------------------------

def test_tampered_created_payload_is_rejected_before_canonicalization(hmac_env):
    import backend.operations_api as ops_api
    from archon.core.delegation import canonicalize_delegation_payload

    good = canonicalize_delegation_payload(
        {"ziel_agent": "worker", "auftrag": "Originalauftrag"}, task_id="t-w3c"
    )
    tampered = dict(good, auftrag="Manipulierter Auftrag")
    assert ops_api._load_kanban_delegation_payload(
        json.dumps(tampered), task_id="t-w3c", require_signature=True
    ) is None
    loaded = ops_api._load_kanban_delegation_payload(
        json.dumps(good), task_id="t-w3c", require_signature=True
    )
    assert loaded is not None
    assert loaded.auftrag == "Originalauftrag"
    assert loaded.payload_signature == good["payload_signature"]


def test_canonicalize_requires_valid_incoming_signature(hmac_env):
    from archon.core.delegation import (
        canonicalize_delegation_payload,
        sign_delegation_payload,
    )

    payload = canonicalize_delegation_payload(
        {"ziel_agent": "worker", "auftrag": "Original"}, task_id="t-w3c"
    )
    payload["payload_signature"] = sign_delegation_payload(payload)
    assert canonicalize_delegation_payload(payload, require_signature=True)["auftrag"] == "Original"
    tampered = dict(payload, auftrag="Manipuliert")
    with pytest.raises(ValueError, match="Signatur"):
        canonicalize_delegation_payload(tampered, require_signature=True)
    unsigned = dict(payload, payload_signature="")
    with pytest.raises(ValueError, match="Signatur"):
        canonicalize_delegation_payload(unsigned, require_signature=True)


def test_producer_writes_single_signed_payload_and_envelope_before_dispatch():
    import inspect

    from archon.core import delegation

    src = inspect.getsource(delegation._execute_delegation)
    created = src.split('INSERT INTO task_events (task_id, kind, payload, created_at)', 1)[1]
    assert '"created", _handoff_json' in created
    assert src.index("create_handoff(") < src.index("_execute_kanban_task_async")
    assert "verify_payload_hash" in src


def test_worker_reads_full_signed_payload_unchanged(
    tmp_path, hmac_env, monkeypatch, worker_deps
):
    import backend.operations_api as ops_api
    import backend.operations_execution as ops_exec
    from backend.handoff_desk import HandoffDesk

    payload = _signed_payload()
    db = tmp_path / "kanban.db"
    _kanban_db(db, created=json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(
        "backend.handoff_desk.handoff_desk",
        HandoffDesk(db_path=str(tmp_path / "handoffs.db")),
    )
    worker_deps(_deps(db, {"worker": {"id": "worker"}}, ops_api._load_kanban_delegation_payload))

    task = ops_exec._kanban_load_task_sync("t-w3c")
    assert task is not None
    assert task["_delegation_signed"] is True
    assert task["_delegation_payload"]["auftrag"] == payload["auftrag"]
    assert task["_delegation_payload"]["extensions"] == {"marker": "keep-me"}
    assert task["_delegation_payload"]["payload_signature"] == payload["payload_signature"]


# ---------------------------------------------------------------------------
# D11-H3 — Envelope Pflicht vor Dispatch, 0 LLM-Calls
# ---------------------------------------------------------------------------

def test_handoff_gate_requires_envelope(tmp_path, monkeypatch):
    from backend.handoff_desk import HandoffDesk, require_accepted_handoff

    desk = HandoffDesk(db_path=str(tmp_path / "gate.db"))
    monkeypatch.setattr("backend.handoff_desk.handoff_desk", desk)
    assert require_accepted_handoff("t-w3c", "worker", require_envelope=True)["allowed"] is False
    created = desk.create_handoff(
        "t-w3c", "delegator", "worker", {"result": "ready", "status": "delegated"}, "Kriterium"
    )
    assert require_accepted_handoff("t-w3c", "worker", require_envelope=True)["allowed"] is True
    with desk._get_conn() as conn:
        conn.execute(
            "UPDATE agent_handoffs SET payload_hash='' WHERE id=?", (created["handoff_id"],)
        )
        conn.commit()
    assert require_accepted_handoff("t-w3c", "worker", require_envelope=True)["allowed"] is False


def _worker_setup(tmp_path, monkeypatch, worker_deps, *, assignee="worker", envelope=False):
    import backend.operations_api as ops_api
    import core_dispatcher
    from backend.handoff_desk import HandoffDesk

    payload = _signed_payload(ziel_agent=assignee, assignee=assignee)
    db = tmp_path / "worker.db"
    _kanban_db(db, assignee=assignee, created=json.dumps(payload, ensure_ascii=False))
    desk = HandoffDesk(db_path=str(tmp_path / "handoffs.db"))
    monkeypatch.setattr("backend.handoff_desk.handoff_desk", desk)
    if envelope:
        desk.create_handoff(
            "t-w3c", "delegator", assignee,
            {"result": payload["auftrag"], "status": "delegated"}, "Kriterium",
            trace_id="trace-w3c", session_id="sess-w3c",
        )
    worker_deps(_deps(
        db,
        {"worker": {"id": "worker", "prompt": "BASIS-PROMPT"}},
        ops_api._load_kanban_delegation_payload,
    ))

    class _Cancel:
        def register_task(self, *_a, **_k) -> None:
            pass

        def check(self) -> None:
            pass

        def cancel(self, *_a, **_k) -> None:
            pass

    monkeypatch.setattr("backend.cancellation.get_token", lambda _key: _Cancel())
    monkeypatch.setattr("backend.model_routing.autonomy_level", lambda _area: "autonomous")
    calls: list = []

    async def _dispatch(**kwargs: Any) -> Dict[str, Any]:
        calls.append(kwargs)
        return {"status": "success", "content": "erledigt", "total_tokens": 10}

    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", _dispatch)
    monkeypatch.setattr(
        "backend.kanban_verifier.verify_card_completion",
        lambda **_k: {"status": "done", "verified": True},
    )
    monkeypatch.setattr(
        "backend.post_task_pipeline.get_vault_dir", lambda: str(tmp_path / "vault")
    )
    return calls


@pytest.mark.asyncio
async def test_missing_envelope_means_zero_llm_calls(
    tmp_path, hmac_env, monkeypatch, worker_deps
):
    import backend.operations_execution as ops_exec

    calls = _worker_setup(tmp_path, monkeypatch, worker_deps, envelope=False)
    result = await ops_exec._execute_kanban_task_inner("t-w3c")
    assert result["blocked"] == "handoff_not_accepted"
    assert calls == []


@pytest.mark.asyncio
async def test_tampered_signature_means_zero_llm_calls(
    tmp_path, hmac_env, monkeypatch, worker_deps
):
    import backend.operations_api as ops_api
    import backend.operations_execution as ops_exec
    from backend.handoff_desk import HandoffDesk

    payload = _signed_payload()
    payload["auftrag"] = "TAMPERED"
    db = tmp_path / "tampered.db"
    _kanban_db(db, created=json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(
        "backend.handoff_desk.handoff_desk",
        HandoffDesk(db_path=str(tmp_path / "handoffs.db")),
    )
    worker_deps(_deps(
        db,
        {"worker": {"id": "worker", "prompt": "BASIS-PROMPT"}},
        ops_api._load_kanban_delegation_payload,
    ))
    import core_dispatcher

    dispatched: list = []

    async def _dispatch(**kwargs: Any) -> Dict[str, Any]:
        dispatched.append(kwargs)
        return {"status": "success", "content": "ok"}

    monkeypatch.setattr(core_dispatcher, "dispatch_to_omniroute_or_container", _dispatch)
    result = await ops_exec._execute_kanban_task_inner("t-w3c")
    assert result["blocked"] == "delegation_signature_invalid"
    assert dispatched == []


@pytest.mark.asyncio
async def test_unknown_agent_sentinel_is_blocked(
    tmp_path, hmac_env, monkeypatch, worker_deps
):
    import backend.operations_execution as ops_exec

    calls = _worker_setup(
        tmp_path, monkeypatch, worker_deps, assignee="ghost", envelope=False
    )
    result = await ops_exec._execute_kanban_task_inner("t-w3c")
    assert result["blocked"] == "UNKNOWN_AGENT_ID"
    assert calls == []


# ---------------------------------------------------------------------------
# W3-C/M1/M2/M5 — Child-Kontext vollstaendig hydrieren
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_child_prompt_carries_taint_soul_trace_warrant_and_budget(
    tmp_path, hmac_env, monkeypatch, worker_deps
):
    import backend.operations_execution as ops_exec

    monkeypatch.setattr(
        "archon.core.delegation.active_soul_tier_text",
        lambda _agent, mode: f"TIER-TEXT-{mode}",
    )
    calls = _worker_setup(tmp_path, monkeypatch, worker_deps, envelope=True)
    await ops_exec._execute_kanban_task_inner("t-w3c")
    assert len(calls) == 1
    prompt = calls[0]["system_prompt"]
    block = json.loads(
        prompt.split("[STRUKTURIERTE_DELEGATION_JSON]\n", 1)[1]
        .split("\n[/STRUKTURIERTE_DELEGATION_JSON]", 1)[0]
    )
    assert block["taint_status"] == "unknown"
    assert block["soul_mode"] == "compact"
    assert block["trace_id"] == "trace-w3c"
    assert block["warrant_id"] == "war-w3c"
    assert block["complexity_weight"] == 2.0
    assert block["budget_share_pct"] == 25.0
    assert block["token_budget"] == 5000
    assert block["auftrag"] == "A" * 400
    assert "[AKTIVER_SOUL_TIER: COMPACT]" in prompt
    assert "TIER-TEXT-compact" in prompt


# ---------------------------------------------------------------------------
# W3-C — Warrant-Vererbung an die Kind-Session
# ---------------------------------------------------------------------------

def test_warrant_is_inherited_to_child_session(monkeypatch, hmac_env):
    import backend.tool_warrants as warrants

    previous = dict(warrants._WARRANT_REGISTRY)
    try:
        warrants._WARRANT_REGISTRY.clear()
        parent = warrants.issue_warrant(
            "parent-sess", ["read_file"], {}, ttl_seconds=600
        )
        warrants.register_warrant(parent)
        wid = warrants.inherit_warrant_for_session(
            "parent-sess", "child-sess", allowed_tools=["read_file"]
        )
        assert wid and wid.startswith("war-")
        inherited = warrants.get_warrant_for_session("child-sess", "read_file")
        assert inherited is not None
        assert inherited["payload"]["warrant_id"] == wid
        assert inherited["payload"]["constraints"] == {}
        assert warrants.latest_warrant_payload_for_session("parent-sess") is not None
    finally:
        warrants._WARRANT_REGISTRY.clear()
        warrants._WARRANT_REGISTRY.update(previous)
