"""
backend/egress_firewall.py
Paket 4 (Feature 17): Egress-Firewall & Domain-Allowlisting für Agenten.
Prüft ausgehende HTTP-/Webhook-Aufrufe von Agenten gegen die Domain-Allowlist (`allowed_domains`)
und blockiert unautorisierte Ziele oder direkte IP-Exfiltrationen (Prompt-Injection Data-Leak-Abwehr).
"""

import os
import re
import sqlite3
from urllib.parse import urlparse
from datetime import datetime
from typing import Dict, Any, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

IPV4_PATTERN = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")


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
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
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
                created_at TEXT
            )
        """)
        conn.commit()


class EgressFirewall:
    def __init__(self):
        _init_db()

    def check_url(self, target_url: str, agent_id: str = "agent-worker") -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        parsed = urlparse(target_url if "://" in target_url else f"https://{target_url}")
        host = (parsed.hostname or "").lower().strip()

        if not enabled:
            return {"allowed": True, "bypassed": True, "hostname": host, "url": target_url}

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
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.execute("""
                INSERT INTO egress_firewall_logs (agent_id, target_url, hostname, allowed, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (agent_id, target_url, host, int(allowed), reason, now_iso))
            conn.commit()

        return {
            "allowed": allowed,
            "blocked": not allowed,
            "agent_id": agent_id,
            "target_url": target_url,
            "hostname": host,
            "reason": reason
        }

    def get_logs(self, limit: int = 25) -> List[Dict[str, Any]]:
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM egress_firewall_logs ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]


egress_firewall = EgressFirewall()
