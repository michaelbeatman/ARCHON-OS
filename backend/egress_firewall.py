"""
backend/egress_firewall.py
Paket 4 (Feature 17): Egress-Firewall & Domain-Allowlisting für Agenten.
Prüft ausgehende HTTP-/Webhook-Aufrufe von Agenten gegen die Domain-Allowlist (`allowed_domains`)
und blockiert unautorisierte Ziele oder direkte IP-Exfiltrationen (Prompt-Injection Data-Leak-Abwehr).
"""
import logging

_archon_exc_logger = logging.getLogger("egress_firewall")

import os
import re
import sqlite3


class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

IPV4_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")

# B2: verschluckte GoBD-Audit-Fehler sind messbar zu machen (kein stummes pass).
_AUDIT_ERROR_COUNTS: Dict[str, int] = {}


def _record_audit_error(action: str, exc: BaseException) -> None:
    _AUDIT_ERROR_COUNTS[action] = _AUDIT_ERROR_COUNTS.get(action, 0) + 1
    _archon_exc_logger.error(
        "[GoBD-Audit] '%s' fehlgeschlagen (count=%d): %s",
        action, _AUDIT_ERROR_COUNTS[action], exc,
    )


def _egress_disable_opt_in() -> bool:
    """D04/MED: explizites Opt-in fuer eine Deaktivierung der Egress-Firewall."""
    return os.environ.get("ARCHON_ALLOW_EGRESS_FIREWALL_DISABLE", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _audit_egress_disabled(agent_id: str, host: str, target_url: str, opt_in: bool) -> str:
    """D04/MED: signiertes (HMAC-Hashketten-)Event bei Deaktivierung.

    Die Audit-Schreibung darf den Fail-Closed-Pfad nicht aufweichen: ein
    Fehler wird sichtbar gemacht (_record_audit_error), aber nicht geworfen.
    """
    action = "egress_firewall_disabled"
    try:
        from backend.audit_log import chained_audit_log

        chained_audit_log.record_event(
            category="security",
            action=action,
            agent_id=agent_id or "unknown",
            payload={
                "hostname": host,
                "target_url": target_url,
                "bypassed": True,
                "explicit_opt_in": opt_in,
                "reason": (
                    "Egress-Firewall per settings.json deaktiviert; "
                    "Zugriff fail-closed blockiert."
                ),
            },
        )
    except Exception as exc:
        _record_audit_error(action, exc)
    return action


def _active_tenant_id() -> str:
    """C2: Mandant des aktuellen Requests (Fail-Closed auf 'default')."""
    try:
        from backend.tenant_context import tenant_context
        return str(tenant_context.get_active_tenant_id() or "default")
    except Exception:
        return "default"


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("egress_firewall")
    except Exception:
        return {
            "enabled": True,
            "default_policy": "allowlist_only",
            "allowed_domains": [
                "openrouter.ai", "api.openai.com", "generativelanguage.googleapis.com",
                "api.anthropic.com", "api.groq.com", "github.com", "localhost", "127.0.0.1"
            ],
            "block_raw_ip_egress": True
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS egress_firewall_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT,
                target_url TEXT,
                hostname TEXT,
                allowed INTEGER,
                reason TEXT,
                created_at TEXT,
                tenant_id TEXT DEFAULT ''
            )
        """)
        # C2: Migration bestehender DBs (alte Zeilen bleiben tenant='' = Legacy).
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(egress_firewall_logs)").fetchall()}
            if "tenant_id" not in cols:
                conn.execute("ALTER TABLE egress_firewall_logs ADD COLUMN tenant_id TEXT DEFAULT ''")
        except Exception as exc:
            _archon_exc_logger.error("[EgressFirewall] tenant_id-Migration fehlgeschlagen: %s", exc)
        conn.commit()


class EgressFirewall:
    def __init__(self):
        _init_db()

    def check_url(self, target_url: str, agent_id: str = "agent-worker") -> Dict[str, Any]:
        tenant_id = _active_tenant_id()
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        parsed = urlparse(target_url if "://" in target_url else f"https://{target_url}")
        host = (parsed.hostname or "").lower().strip()

        zero_strict = False
        try:
            from backend.privacy_router import get_privacy_config
            zero_strict = bool(get_privacy_config().get("zero_egress_strict", False))
        except Exception:
            zero_strict = (os.environ.get("PRIVACY_ZERO_EGRESS") or "").strip().lower() in ("1", "true", "yes", "on")

        if zero_strict:
            from backend.audit_log import chained_audit_log, sanitize_llm_endpoint
            clean_ep, _, zone = sanitize_llm_endpoint(target_url)
            if zone != "LOCAL_ON_PREM":
                reason = f"Zero-Egress Strict aktiv: Externes Ziel '{host}' ({zone}) hart blockiert."
                now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
                    conn.execute(
                        "INSERT INTO egress_firewall_logs (agent_id, target_url, hostname, allowed, reason, created_at, tenant_id) VALUES (?, ?, ?, 0, ?, ?, ?)",
                        (agent_id, clean_ep, host, reason, now_iso, tenant_id),
                    )
                    conn.commit()
                try:
                    chained_audit_log.record_event(
                        category="security",
                        action="zero_egress_firewall_blocked",
                        agent_id=agent_id,
                        payload={"target_endpoint": clean_ep, "target_host": host, "egress_zone": zone, "reason": reason},
                    )
                except Exception as _exc:
                    # B2: GoBD-Auditfehler duerfen nicht verschluckt werden.
                    _record_audit_error("zero_egress_firewall_blocked", _exc)
                return {
                    "allowed": False,
                    "blocked": True,
                    "agent_id": agent_id,
                    "target_url": clean_ep,
                    "hostname": host,
                    "reason": reason,
                }

        if not enabled:
            # D04/MED: ein settings.json-Schalter allein war ein ungesicherter
            # Fail-Open-Pfad. Deaktivierung ist nur mit explizitem Env-Opt-in
            # zulaessig und wird signiert auditiert. Ein `bypassed`-Flag darf
            # NIE als Positivpruefung (`allowed=True`) an Aufrufer zurueckgehen.
            opt_in = _egress_disable_opt_in()
            _audit_egress_disabled(agent_id, host, target_url, opt_in)
            reason = (
                "Egress-Firewall ist deaktiviert (bypassed=True) — Zugriff fail-closed "
                "blockiert; allowed=True setzt eine echte Positivpruefung voraus."
            )
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
                    conn.execute(
                        "INSERT INTO egress_firewall_logs "
                        "(agent_id, target_url, hostname, allowed, reason, created_at, tenant_id) "
                        "VALUES (?, ?, ?, 0, ?, ?, ?)",
                        (agent_id, target_url, host, reason, now_iso, tenant_id),
                    )
                    conn.commit()
            except Exception as exc:
                _record_audit_error("egress_firewall_disabled_log", exc)
            return {
                "allowed": False,
                "blocked": True,
                "bypassed": True,
                "agent_id": agent_id,
                "target_url": target_url,
                "hostname": host,
                "explicit_opt_in": opt_in,
                "reason": reason,
            }

        allowlist: List[str] = [str(d).lower().strip() for d in cfg.get("allowed_domains", [])]
        block_raw_ip = bool(cfg.get("block_raw_ip_egress", True))

        allowed = False
        reason = "Domain nicht in Egress-Allowlist enthalten."

        if not host:
            allowed = False
            reason = "Ungültiger Hostname."
        elif block_raw_ip and IPV4_PATTERN.match(host) and host != "127.0.0.1":
            allowed = False
            reason = f"Direkter IP-Egress ({host}) durch Sicherheitsrichtlinie blockiert."
        else:
            for dom in allowlist:
                if host == dom or host.endswith(f".{dom}"):
                    allowed = True
                    reason = f"Autorisiert über Allowlist-Eintrag '{dom}'."
                    break

        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT INTO egress_firewall_logs (agent_id, target_url, hostname, allowed, reason, created_at, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (agent_id, target_url, host, int(allowed), reason, now_iso, tenant_id))
            conn.commit()

        return {
            "allowed": allowed,
            "blocked": not allowed,
            "agent_id": agent_id,
            "target_url": target_url,
            "hostname": host,
            "reason": reason
        }

    def get_logs(self, limit: int = 25, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        # C2: Logs defaultmaessig auf den aktiven Mandanten einschraenken.
        tid = str(tenant_id) if tenant_id is not None else _active_tenant_id()
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM egress_firewall_logs WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
                (tid, limit)
            ).fetchall()
            return [dict(r) for r in rows]


egress_firewall = EgressFirewall()
