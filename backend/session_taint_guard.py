# -*- coding: utf-8 -*-
"""
backend/session_taint_guard.py
==============================
Meilenstein 89: Information-Flow-Taint-Tracking & Session-Versiegelung
(airlock-Pattern mit HITL-Freigabe-Gate).

Sobald eine Session untrusted Content liest (Webseiten, externe E-Mails,
fremde MCP-Outputs), wird sie als `tainted` markiert. Kritische Ausgaenge
(E-Mail-Versand, Payment/pay, git push, Deploy, Memory-Write) werden dann
geparkt und benoetigen eine explizite HITL-Freigabe.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("archon.session_taint_guard")


def _audit_strict() -> bool:
    """D04-M1 (W2-C): Audit-Fehler sind default-maessig hart (fail-closed)."""
    raw = str(os.environ.get("ARCHON_AUDIT_STRICT", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "none"}


# B2/D04-M1: verschluckte Audit-Fehler sind messbar (kein stummes pass).
_AUDIT_ERROR_COUNTS: Dict[str, int] = {}


def _record_audit_error(action: str, exc: BaseException) -> None:
    _AUDIT_ERROR_COUNTS[action] = _AUDIT_ERROR_COUNTS.get(action, 0) + 1
    logger.error(
        "[TaintGuard] Audit-Event '%s' fehlgeschlagen (count=%d): %s",
        action, _AUDIT_ERROR_COUNTS[action], exc,
    )


def _record_taint_audit(action: str, agent_id: str, payload: Dict[str, Any]) -> None:
    """Pflicht-Audit VOR dem Status-Commit (§0/§2.5: nie verschlucken).

    Bei ARCHON_AUDIT_STRICT=1 (Default) wird ein Schreibfehler als
    ``RuntimeError("audit_write_failed")`` eskaliert. Der Aufrufer muss den
    Aufruf VOR ``conn.commit()`` machen, damit die Statusaenderung dann
    zurueckgerollt wird und die Freigabe nicht einloesbar bleibt.
    """
    try:
        from backend.audit_log import chained_audit_log
        chained_audit_log.record_event(
            category="security",
            action=action,
            agent_id=agent_id,
            payload=payload,
        )
    except Exception as exc:
        _record_audit_error(action, exc)
        if _audit_strict():
            raise RuntimeError("audit_write_failed") from exc


WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "taint_guard.db")

CRITICAL_EGRESS_TOOLS = frozenset({
    "send_email",
    "email_send",
    "pay",
    "pay-cli",
    "pay_cli",
    "git_push",
    "deploy",
    "memory_write",
    "execute_shell",
    "webhook_post",
    "telegram_send",
})

CRITICAL_EGRESS_PREFIXES = ("pay_", "mcp__pay", "mcp__email", "deploy_")

# Alle Tools mit Egress-/Code-Ausfuehrungs-Faehigkeit muessen durch den
# Taint-Gate. Vorher war nur eine 11-Eintrags-Exact-Liste hinterlegt —
# `terminal`, `execute_code`, `computer_use`, `mcp__slack__chat_postMessage`
# und `node_plugin:http_post` galten als harmlos und konnten eine tainted
# Session verlassen, ohne HITL zu triggern (Datenabfluss ohne Freigabe).
CRITICAL_EGRESS_NAMES = frozenset({
    "terminal", "shell", "execute_code", "computer_use", "filesystem",
    "file_write", "http_post", "browser", "browser_navigate", "code_execute",
})
CRITICAL_EGRESS_NAME_FRAGMENTS = ("mcp__", "node_plugin:", "http_post", "webhook", "email")
# Explizit als harmlos bekannte Tools (keine Egress-Wirkung).
NON_EGRESS_TOOLS = frozenset({
    "read_file", "file_read", "search", "web_search", "web_fetch", "calculate",
    "get_time", "list_files", "thinking", "memory_read",
})


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    # C2: ohne expliziten Pfad mandantenisolierte DB verwenden (sonst sahen
    # alle Mandanten dieselben Taint-Marker/HITL-Freigaben).
    path = db_path
    if not path:
        try:
            from backend.tenant_context import tenant_context
            from backend.tenant_db_registry import resolve_tenant_db_path
            path = resolve_tenant_db_path("taint_guard.db", tenant_context.get_active_tenant_id())
        except Exception as exc:
            # D07: fail-closed — kein stillen Fallback auf die globale DB.
            # Sonst landen Taint-Marker/Freigaben mandantenübergreifend und ein
            # kritischer Egress wird allowed=True.
            raise RuntimeError(
                f"TaintStoreUnavailable: mandantenisolierte DB nicht auflösbar: {exc}"
            ) from exc
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tainted_sessions (
                session_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                reason TEXT DEFAULT '',
                tainted_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS taint_hitl_approvals (
                approval_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                args_json TEXT DEFAULT '{}',
                taint_source TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                reviewer TEXT DEFAULT '',
                -- Audit D04/MED: Ersteller/Anforderer der geparkten Aktion.
                -- Freigabe und Ausfuehrung muessen verschiedene Identitaeten tragen.
                requested_by TEXT DEFAULT '',
                created_at REAL NOT NULL,
                resolved_at REAL,
                consumed INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Bestehende DBs: Spalte nachziehen (keine PostgreSQL-Migration, SQLite-ALTER).
        try:
            conn.execute("ALTER TABLE taint_hitl_approvals ADD COLUMN requested_by TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits
        conn.commit()
        yield conn
    finally:
        conn.close()


def is_critical_egress_tool(tool_name: str) -> bool:
    """Default-Deny fuer alle Tools mit Egress-/Ausfuehrungs-Faehigkeit.

    Unbekannte Tool-Namen werden als kritisch behandelt (fail-closed): ein
    neues MCP-/Plugin-Tool darf nicht automatisch am HITL-Gate vorbei.
    """
    norm = (tool_name or "").strip().lower()
    if not norm:
        return True  # leerer Tool-Name -> fail-closed
    if norm in NON_EGRESS_TOOLS:
        return False
    if norm in CRITICAL_EGRESS_TOOLS or norm in CRITICAL_EGRESS_NAMES:
        return True
    if any(norm.startswith(pref) for pref in CRITICAL_EGRESS_PREFIXES):
        return True
    if any(frag in norm for frag in CRITICAL_EGRESS_NAME_FRAGMENTS):
        return True
    # Unbekannt -> kritisch (Default-Deny). Harmlose Tools muessen explizit
    # in NON_EGRESS_TOOLS stehen.
    return True


def mark_session_tainted(
    session_id: str,
    source: str,
    reason: str = "",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    now = time.time()
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tainted_sessions (session_id, source, reason, tainted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                source = excluded.source,
                reason = excluded.reason,
                tainted_at = excluded.tainted_at
            """,
            (session_id, source, reason, now),
        )
        conn.commit()
    return {"session_id": session_id, "tainted": True, "source": source, "reason": reason}


def get_session_taint(session_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT session_id, source, reason, tainted_at FROM tainted_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None


def check_egress_tool_call(
    session_id: str,
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    approval_id: Optional[str] = None,
    db_path: Optional[str] = None,
    requested_by: str = "",
) -> Dict[str, Any]:
    """
    Prueft, ob ein Tool-Aufruf in `session_id` ausgefuehrt werden darf.
    Bei kontaminierten Sessions werden kritische Ausgaenge ueber HITL geparkt.
    """
    if not is_critical_egress_tool(tool_name):
        return {"allowed": True, "tainted": False, "tool": tool_name}

    taint = get_session_taint(session_id, db_path=db_path)
    if not taint:
        return {"allowed": True, "tainted": False, "tool": tool_name}

    # Freigaben sind an die EXAKTEN Argumente gebunden (TOCTOU-Schutz).
    # Vorher genuegten approval_id + tool_name: nach Freigabe von
    # pay{amount:10,to:alice} konnte pay{amount:10000,to:attacker} durch.
    canonical_args = json.dumps(args or {}, sort_keys=True, ensure_ascii=False)

    with _connect(db_path) as conn:
        if approval_id:
            row = conn.execute(
                """
                SELECT approval_id, status, consumed, tool_name, session_id, args_json, requested_by
                FROM taint_hitl_approvals
                WHERE approval_id = ? AND session_id = ? AND tool_name = ?
                """,
                (approval_id, session_id, tool_name),
            ).fetchone()
            approved_args = {}
            if row:
                try:
                    approved_args = json.loads(row["args_json"] or "{}")
                except (TypeError, ValueError):
                    approved_args = None  # type: ignore[assignment]
            args_match = approved_args == (args or {})
            if row and not str(row["requested_by"] or "").strip():
                # D04/H-04-3: Legacy-Freigaben ohne Anforderer sind nicht
                # vier-augen-fähig und werden als kompromittiert abgelehnt.
                return {
                    "allowed": False,
                    "blocked": True,
                    "requires_hitl": True,
                    "tainted": True,
                    "approval_id": None,
                    "tool": tool_name,
                    "reason": "Freigabe ohne verifizierten requested_by (Legacy) — fail-closed abgelehnt.",
                }
            if row and not args_match:
                return {
                    "allowed": False,
                    "blocked": True,
                    "requires_hitl": True,
                    "tainted": True,
                    "approval_id": None,
                    "tool": tool_name,
                    "reason": "HITL-Freigabe gueltig, aber die Tool-Argumente weichen ab — Freigabe abgelehnt.",
                }
            if row and row["status"] == "approved" and int(row["consumed"]) == 0:
                # KRITISCH (Audit 23.11.2026): CAS — ohne `AND consumed = 0`
                # konnten zwei parallele Calls dieselbe Freigabe verbrauchen
                # und den kritischen Egress doppelt ausführen.
                cur = conn.execute(
                    "UPDATE taint_hitl_approvals SET consumed = 1 "
                    "WHERE approval_id = ? AND session_id = ? AND tool_name = ? "
                    "AND status = 'approved' AND consumed = 0",
                    (approval_id, session_id, tool_name),
                )
                if int(cur.rowcount or 0) != 1:
                    return {
                        "allowed": False,
                        "blocked": True,
                        "requires_hitl": True,
                        "tainted": True,
                        "approval_id": None,
                        "tool": tool_name,
                        "reason": "HITL-Freigabe wurde parallel bereits verbraucht — abgelehnt.",
                    }
                conn.commit()
                return {
                    "allowed": True,
                    "tainted": True,
                    "hitl_approved": True,
                    "approval_id": approval_id,
                    "tool": tool_name,
                }

        # D04/H-04-3: der verifizierte Anforderer ist Pflicht, bevor eine
        # HITL-Freigabe ANGELEGT wird. Ohne ihn ist das Vier-Augen-Prinzip
        # nicht prüfbar -> kein 'pending'-Eintrag, harter Deny. Das
        # Einlösen einer bereits vorhandenen Freigabe bleibt zulässig.
        clean_requester = str(requested_by or "").strip()
        if not clean_requester:
            return {
                "allowed": False,
                "blocked": True,
                "requires_hitl": True,
                "tainted": True,
                "approval_id": None,
                "tool": tool_name,
                "reason": "requested_by fehlt — kritische Egress-Freigabe fail-closed verweigert (Vier-Augen-Prinzip).",
            }

        new_id = f"ta-{secrets.token_hex(6)}"
        conn.execute(
            """
            INSERT INTO taint_hitl_approvals
                (approval_id, session_id, tool_name, args_json, taint_source, status, requested_by, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (
                new_id, session_id, tool_name, canonical_args, taint["source"],
                clean_requester, time.time(),
            ),
        )
        conn.commit()

    return {
        "allowed": False,
        "blocked": True,
        "requires_hitl": True,
        "tainted": True,
        "approval_id": new_id,
        "tool": tool_name,
        "taint_source": taint["source"],
        "reason": f"Session '{session_id}' ist durch '{taint['source']}' versiegelt. HITL-Freigabe '{new_id}' fuer '{tool_name}' erforderlich.",
    }


def resolve_taint_approval(
    approval_id: str,
    approved: bool,
    reviewer: str = "admin",
    db_path: Optional[str] = None,
    passkey_proof: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """HITL-Freigabe mit Vier-Augen und Passkey-Proof (fail-closed)."""
    reviewer = str(reviewer or "").strip()
    if not reviewer:
        raise PermissionError("Kein verifizierter Reviewer fuer die Taint-Freigabe.")
    new_status = "approved" if approved else "rejected"
    now = time.time()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM taint_hitl_approvals WHERE approval_id = ? AND status = 'pending'",
            (approval_id,),
        ).fetchone()
        if not row:
            return None
        requested_by = str(row["requested_by"] or "").strip() if "requested_by" in row.keys() else ""
        # Audit D04/H-04-3: ohne verifizierten Anforderer ist das Vier-Augen-
        # Prinzip nicht pruefbar -> harte Ablehnung (kein stilles Ueberspringen).
        if not requested_by:
            raise PermissionError(
                "Freigabe ohne verifizierten requested_by — Vier-Augen-Prinzip nicht pruefbar (fail-closed)."
            )
        # Audit D04/MED: identischer Ersteller/Genehmiger -> harte Ablehnung.
        if hmac.compare_digest(requested_by, reviewer):
            logger.warning(
                "[TaintGuard] Vier-Augen-Verletzung: %s wurde von '%s' angefordert "
                "und soll von '%s' freigegeben werden.", approval_id, requested_by, reviewer
            )
            raise PermissionError("Ersteller darf die eigene Taint-Freigabe nicht bestaetigen (Vier-Augen-Prinzip).")

        # Audit D04/MED: Passkey-Proof fuer kritische Tools, an Aktion+Ressource gebunden.
        if approved and is_critical_egress_tool(str(row["tool_name"] or "")):
            # D07: der Passkey-Proof ist ZWINGEND. Der frühere Env-Schalter
            # `ARCHON_TAINT_HITL_ALLOW_NO_PROOF` war undokumentiert und
            # deaktivierte den Proof für kritische Egress-Freigaben.
            proof = str(passkey_proof or "").strip()
            if not proof:
                raise PermissionError(
                    "Passkey-Proof erforderlich, um einen kritischen Taint-Egress freizugeben."
                )
            try:
                from backend.passkey_hitl import consume_hitl_proof_token
                ok = consume_hitl_proof_token(
                    proof, reviewer, "system",
                    action=f"Taint-Freigabe {approval_id}", resource=approval_id,
                )
            except Exception as exc:
                raise PermissionError(f"Taint-HITL-Proof nicht pruefbar: {exc}")
            if not ok:
                raise PermissionError("Ungueltiger oder nicht an diese Freigabe gebundener Passkey-Proof.")

        cur = conn.execute(
            """
            UPDATE taint_hitl_approvals
            SET status = ?, reviewer = ?, resolved_at = ?
            WHERE approval_id = ? AND status = 'pending'
            """,
            (new_status, reviewer, now, approval_id),
        )
        if cur.rowcount == 0:
            return None

        # D04-M1 (W2-C): signiertes Audit-Event mit BEIDEN Actors VOR dem Commit.
        # Bei Auditfehler eskaliert _record_taint_audit (ARCHON_AUDIT_STRICT=1
        # default) mit RuntimeError("audit_write_failed"). Die Ausnahme verlaesst
        # den `with`-Block vor conn.commit(); sqlite3 rollt die UPDATE damit beim
        # close() zurueck. Die Freigabe bleibt 'pending' und ist nicht einloesbar.
        _record_taint_audit(
            action="taint_hitl_resolved",
            agent_id=reviewer,
            payload={
                "approval_id": approval_id,
                "requested_by": requested_by,
                "reviewer": reviewer,
                "approved": approved,
            },
        )

        conn.commit()
        result = conn.execute("SELECT * FROM taint_hitl_approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        res = dict(result) if result else None
    return res


def list_pending_taint_approvals(
    db_path: Optional[str] = None,
    session_id: Optional[str] = None,
    include_args: bool = False,
) -> List[Dict[str, Any]]:
    """Nur Verified-Admins duerfen `args_json` sehen (include_args=True)."""
    with _connect(db_path) as conn:
        query = "SELECT * FROM taint_hitl_approvals WHERE status = 'pending'"
        params: List[Any] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if not include_args and item.get("args_json"):
                item["args_json"] = "[MASKED: nur fuer Administratoren sichtbar]"
            out.append(item)
        return out
