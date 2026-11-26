"""D5-Cluster 3: Cache-Policy-/Gate- und Budget-/Usage-Helfer.

Ausgelagert aus ``core_dispatcher.py`` (INVARIANTS §3):
- ``_dispatch_cache_scope``
- ``_cache_policy_context``
- ``_validate_cache_hit_gate``
- ``_audit_dispatch_failure_with_lock``
- ``_reserve_trajectory_budget_sync``
- ``_DispClosingConn``
- ``_log_dispatcher_usage_sync``

``_AUDIT_WRITE_LOCK``, ``_PROMPT_VERSION_CTX`` und ``_STRUCTURED_OUTPUT_SCHEMA_CTX``
bleiben bewusst als Singletons auf ``core_dispatcher.py`` (Call-Time-Injection).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("core_dispatcher")


def _dispatch_cache_scope(
    agent_id: str = "",
    *,
    data_category: str = "",
    canary: bool = False,
    zero_egress_active: bool = False,
) -> str:
    """Tenant-/Policy-Scope fuer den semantischen Cache (kein Cross-Tenant-Leak)."""
    tenant = ""
    try:
        from backend import tenant_context as _tc
        tenant = str(_tc._REQUEST_TENANT_VAR.get() or "")
    except Exception as tc_exc:
        logger.debug("[Dispatcher] Tenant-Var nicht verfuegbar: %s", tc_exc)
    if not tenant:
        try:
            from backend.tenant_context import tenant_context
            tenant = str(tenant_context.get_active_tenant_id() or "")
        except Exception as tc_exc:
            logger.debug("[Dispatcher] Tenant-Context nicht verfuegbar: %s", tc_exc)
    policy_version = str(os.environ.get("ARCHON_POLICY_VERSION") or "")
    zero_egress = str(os.environ.get("ARCHON_ZERO_EGRESS_STRICT") or "").strip().lower()
    return (
        f"{tenant or 'default'}:{agent_id or 'default'}:{policy_version}:{zero_egress}"
        f":{data_category or 'general'}:{'canary' if canary else 'stable'}"
        f":{'zero_active' if zero_egress_active else 'egress_allowed'}"
    )


def _cache_policy_context(agent_id: str, role: str = "", prompt: str = "") -> Tuple[str, bool]:
    """Wirksame Datenkategorie / Zero-Egress fuer den Cache-Key (ohne Audit-Write)."""
    explicit_cat = ""
    try:
        from backend.data_classifier import DataClassifier
        if not DataClassifier.classify(prompt or "").get("cloud_llm_allowed", True):
            explicit_cat = "confidential"
    except Exception as exc:
        logger.warning("[Dispatcher] Cache-DataClassifier fehlgeschlagen (fail-closed): %s", exc)
        explicit_cat = "confidential"
    try:
        from backend.llm_egress_guard import infer_data_category
        from backend.privacy_router import get_privacy_config, is_sensitive_category
        cfg = get_privacy_config() or {}
        category = infer_data_category(agent_id=agent_id, role=role, explicit_category=explicit_cat)
        zero_active = bool(cfg.get("zero_egress_strict", False)) or (
            bool(cfg.get("sensitive_local_routing", False))
            and is_sensitive_category(category, cfg)
        )
        return str(category), bool(zero_active)
    except Exception as exc:
        logger.error("[Dispatcher] Cache-Policy-Kontext nicht verfuegbar (fail-closed): %s", exc)
        return "confidential", True


def _validate_cache_hit_gate(
    agent_id: str,
    provider: str,
    model: str,
    prompt: str,
    role: str = "",
    system_prompt: str = "",
) -> Dict[str, Any]:
    """D02/HIGH: Governance-Gate bei JEDEM Cache-Hit erneut auswerten (fail-closed)."""
    from backend.llm_egress_guard import (
        ZeroEgressBlockedError,
        evaluate_and_gate_llm_dispatch,
    )

    try:
        from backend.compliance_engine import compliance_engine
        chk = compliance_engine.check_activation_allowed(
            agent_id, system_prompt=system_prompt or prompt or ""
        )
        if not chk.get("allowed", True):
            raise ZeroEgressBlockedError(
                chk.get("reason") or f"Compliance Guardrail blockiert '{agent_id}'.",
                error_code=chk.get("error_code") or "COMPLIANCE_BLOCKED",
            )
    except ZeroEgressBlockedError:
        raise
    except Exception as exc:
        logger.error("[Dispatcher] Cache-Hit Compliance-Gate nicht verfuegbar — blockiert: %s", exc)
        raise ZeroEgressBlockedError(
            f"Compliance-Gate nicht verfuegbar: {exc}",
            error_code="COMPLIANCE_GATE_UNAVAILABLE",
        ) from exc

    explicit_cat = ""
    try:
        from backend.data_classifier import DataClassifier
        if not DataClassifier.classify(prompt or "").get("cloud_llm_allowed", True):
            explicit_cat = "confidential"
    except Exception as exc:
        logger.error("[Dispatcher] Cache-Hit DataClassifier fehlgeschlagen (fail-closed): %s", exc)
        explicit_cat = "confidential"

    gate: Dict[str, Any] = evaluate_and_gate_llm_dispatch(
        agent_id=agent_id,
        provider=provider or "omniroute",
        model=model,
        messages=[{"role": "user", "content": prompt}],
        role=role,
        explicit_category=explicit_cat,
    )
    if not gate.get("allowed", True):
        raise ZeroEgressBlockedError(
            "Dispatch-Gate verweigert den Cache-Hit (fail-closed).",
            error_code="LLM_DISPATCH_GATE_BLOCKED",
        )
    return gate


def _audit_dispatch_failure_with_lock(
    audit_lock: threading.Lock,
    action: str,
    detail: str,
    **extra: Any,
) -> None:
    """D07/MED: Budget-/Usage-Schreibfehler nie auf DEBUG verschlucken."""
    logger.error("[Dispatcher] %s: %s", action, detail)
    try:
        with audit_lock:
            from backend.audit_log import chained_audit_log
            chained_audit_log.record_event(
                category="recovery",
                action=action,
                agent_id="system",
                payload={"detail": str(detail)[:500], **extra},
            )
    except Exception as audit_exc:
        logger.error("[Dispatcher] Audit-Eskalation %s fehlgeschlagen: %s", action, audit_exc)


def _reserve_trajectory_budget_sync(
    task_id: str,
    agent_id: str,
    estimated_tokens: int,
    reason: str = "",
) -> Dict[str, Any]:
    """D13/H-13-1: ticketweite Hop-/Token-Invariante im LLM-Chokepoint."""
    from backend.trajectory_budget import (
        normalize_trajectory_id,
        reserve_hop,
        reserve_tokens,
    )

    tid = normalize_trajectory_id(None, root_ticket_id=str(task_id or ""))
    hop_reason = str(reason or "").strip() or f"llm_call:{agent_id}"
    hop = reserve_hop(
        tid, str(agent_id or ""), hop_reason, root_ticket_id=str(task_id or "")
    )
    if not hop.get("allowed", False):
        return {
            "allowed": False,
            "trajectory_id": tid,
            "stage": "hop",
            "reason": str(hop.get("reason") or "TRAJECTORY_CAP_BLOCKED"),
        }
    tokens = reserve_tokens(tid, int(estimated_tokens or 0), reason="llm_dispatch_estimate")
    if not tokens.get("allowed", False):
        return {
            "allowed": False,
            "trajectory_id": tid,
            "stage": "tokens",
            "reason": str(tokens.get("reason") or "TOKEN_CAP_REACHED"),
        }
    return {
        "allowed": True,
        "trajectory_id": tid,
        "hop": hop,
        "tokens": tokens,
    }


class _DispClosingConn(sqlite3.Connection):
    def __enter__(self) -> "_DispClosingConn":
        super().__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


def _log_dispatcher_usage_sync_impl(
    agent_id: str,
    model: str,
    in_tok: int,
    out_tok: int,
    task_id: str = "",
    *,
    audit_failure_fn: Optional[Callable[..., None]] = None,
) -> None:
    try:
        try:
            from backend.db_paths import resolve_db as _resolve_db
            db_path = _resolve_db("state.db")
        except Exception:
            db_path = (
                "/opt/data/state.db"
                if os.path.exists("/opt/data/state.db")
                else os.path.expanduser("~/.hermes/state.db")
            )
        if not os.path.exists(os.path.dirname(db_path)):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

        from backend.db_paths import DB_BUSY_TIMEOUT_MS
        with sqlite3.connect(
            db_path, timeout=DB_BUSY_TIMEOUT_MS / 1000.0, factory=_DispClosingConn
        ) as conn:
            conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
            now = time.time()
            eff_task = task_id or f"agent_{agent_id}"
            s_id = f"task_{eff_task}" if not str(eff_task).startswith("task_") else str(eff_task)
            t_key = str(eff_task)
            try:
                from backend.llm_kernel import estimate_model_cost_usd
                cost_usd = float(estimate_model_cost_usd(model, in_tok, out_tok))
            except Exception:
                cost_usd = round((in_tok * 0.00000015) + (out_tok * 0.00000030), 6)

            cur = conn.cursor()
            cur.execute("SELECT id FROM sessions WHERE id = ?", (s_id,))
            inserted_session = False
            if not cur.fetchone():
                unique_title = f"Task {eff_task[:25]} [{time.time_ns() % 1000000000}]"
                try:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO sessions (
                            id, source, display_name, title, model, profile_name, started_at, message_count,
                            input_tokens, output_tokens, estimated_cost_usd, actual_cost_usd
                        ) VALUES (?, 'agent_task', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                        """,
                        (s_id, unique_title, unique_title, model, agent_id, now, in_tok, out_tok, cost_usd, cost_usd),
                    )
                    inserted_session = cur.rowcount > 0
                except sqlite3.Error as db_exc:
                    if audit_failure_fn is not None:
                        audit_failure_fn(
                            "usage_log_failed", str(db_exc), stage="session_insert", task_id=str(eff_task)
                        )

            conn.execute(
                """
                INSERT INTO session_model_usage (
                    session_id, model, billing_provider, billing_base_url, billing_mode, task,
                    api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
                    reasoning_tokens, estimated_cost_usd, actual_cost_usd, first_seen, last_seen
                ) VALUES (?, ?, 'omniroute', 'http://omniroute:20128/v1', 'proxy', ?, 1, ?, ?, 0, 0, 0, ?, ?, ?, ?)
                ON CONFLICT(session_id, model, billing_provider, billing_base_url, billing_mode, task) DO UPDATE SET
                    api_call_count = api_call_count + 1,
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    estimated_cost_usd = estimated_cost_usd + excluded.estimated_cost_usd,
                    last_seen = excluded.last_seen
                """,
                (s_id, model, t_key, in_tok, out_tok, cost_usd, cost_usd, now, now),
            )

            if not inserted_session:
                cur_upd = conn.execute(
                    """
                    UPDATE sessions
                    SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?,
                        estimated_cost_usd = estimated_cost_usd + ?
                    WHERE id = ?
                    """,
                    (in_tok, out_tok, cost_usd, s_id),
                )
                if int(cur_upd.rowcount or 0) == 0 and audit_failure_fn is not None:
                    audit_failure_fn(
                        "usage_log_failed",
                        "session update affected 0 rows",
                        stage="session_update",
                        task_id=str(eff_task),
                    )

        if "main" in sys.modules:
            m = sys.modules["main"]
            if hasattr(m, "_LIVE_TELEMETRY_CACHE"):
                m._LIVE_TELEMETRY_CACHE["data"] = None
            if hasattr(m, "_MC_STATE_CACHE"):
                m._MC_STATE_CACHE["data"] = None
        try:
            from backend.execution_receipt_ledger import execution_receipt_ledger
            execution_receipt_ledger.issue_receipt(
                task_id=str(eff_task),
                agent_role=str(agent_id or "dispatcher"),
                model_used=str(model or "unknown"),
                prompt_tokens=int(in_tok),
                completion_tokens=int(out_tok),
                cost_usd=float(cost_usd),
                tools_invoked=["core_dispatcher"],
            )
        except Exception as log_exc:
            logger.error(f"[Dispatcher] Usage-Audit-Log fehlgeschlagen: {log_exc}")
    except Exception as e:
        print(f"[DISPATCHER] Token telemetry write error: {e}", file=sys.stderr)
