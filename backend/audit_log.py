"""
backend/audit_log.py
Archon OS 2026 - Systemweites GoBD / ISO 27001 Revisionssicheres Audit-Log (Pillar 6 Zero-Trust).
Lückenlose SHA-256 Hashverkettung für alle System-, Rollen-, API-Key-, Finanz-, E-Mail-,
Konfigurations- sowie LLM-Dispatch-Ereignisse (Provider, Modell, Ziel-Endpunkt, Ziel-Host, Egress-Zone)
mit 1-Klick Prüfer-Export (JSON/CSV) und kryptografischer Integritätsprüfung.
"""

import os
import sys
import csv
import io
import json
import hashlib
import sqlite3
import datetime
import ipaddress
import threading
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
GENESIS_HASH = "0" * 64

_SENSITIVE_QUERY_KEYS = frozenset({
    "key", "api_key", "apikey", "token", "access_token", "secret", "password", "auth"
})

_LOCAL_ON_PREM_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "host.docker.internal",
    "ollama",
    "ollama-embed",
    "vllm",
    "lmstudio",
    "local-llm",
})

_INTERNAL_GATEWAY_HOSTS = frozenset({
    "omniroute",
    "hermes",
    "hermes-agent",
    "hermes-dashboard",
    "odysseus",
    "openclaw",
    "openclaw-docker",
})


def sanitize_llm_endpoint(endpoint: str) -> Tuple[str, str, str]:
    """
    Bereinigt einen realen LLM-Ziel-Endpunkt (entfernt Credentials/Query-Keys)
    und extrahiert deterministisch `(clean_endpoint, target_host, egress_zone)`.

    Egress-Zonen:
      - `LOCAL_ON_PREM`: Loopback, host.docker.internal, lokale On-Premise Container/IPs (Ollama, vLLM, LM Studio)
      - `INTERNAL_GATEWAY`: Interne Router/Gateways (`omniroute`, `hermes`, etc.)
      - `EXTERNAL_CLOUD`: Externe Cloud-Hosts (`openrouter.ai`, `api.openai.com`, `api.mistral.ai`, etc.)
    """
    raw = (endpoint or "").strip()
    if not raw:
        return "unknown://unspecified", "unspecified", "UNKNOWN"

    to_parse = raw if "://" in raw else f"http://{raw}"
    parsed = urlparse(to_parse)
    scheme = (parsed.scheme or "http").lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")

    if not hostname:
        return raw, "unspecified", "UNKNOWN"

    try:
        port = parsed.port
    except ValueError:
        port = None

    if ":" in hostname and not hostname.startswith("["):
        netloc_host = f"[{hostname}]"
    else:
        netloc_host = hostname

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if port and not default_port:
        target_host = f"{hostname}:{port}"
        clean_netloc = f"{netloc_host}:{port}"
    else:
        target_host = hostname
        clean_netloc = netloc_host

    clean_query = ""
    if parsed.query:
        filtered_pairs = []
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            if k.lower() in _SENSITIVE_QUERY_KEYS:
                filtered_pairs.append((k, "REDACTED"))
            else:
                filtered_pairs.append((k, v))
        clean_query = urlencode(filtered_pairs)

    clean_path = parsed.path or "/"
    clean_endpoint = urlunparse((scheme, clean_netloc, clean_path, "", clean_query, ""))

    # Egress-Zonen-Klassifikation
    if hostname in _INTERNAL_GATEWAY_HOSTS:
        zone = "INTERNAL_GATEWAY"
    elif hostname in _LOCAL_ON_PREM_HOSTS:
        zone = "LOCAL_ON_PREM"
    else:
        zone = "EXTERNAL_CLOUD"
        try:
            ip_obj = ipaddress.ip_address(hostname)
            if ip_obj.is_loopback or ip_obj.is_private:
                zone = "LOCAL_ON_PREM"
        except ValueError:
            if hostname.endswith((".local", ".lan", ".internal", ".home.arpa")):
                zone = "LOCAL_ON_PREM"

    return clean_endpoint, target_host, zone


class ChainedAuditLog:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        category TEXT NOT NULL,
                        action TEXT NOT NULL,
                        event_type TEXT,
                        agent_id TEXT NOT NULL,
                        provider TEXT DEFAULT '',
                        model TEXT DEFAULT '',
                        target_host TEXT DEFAULT '',
                        target_endpoint TEXT DEFAULT '',
                        egress_zone TEXT DEFAULT '',
                        payload_json TEXT NOT NULL,
                        prev_hash TEXT NOT NULL,
                        current_hash TEXT NOT NULL
                    )
                """)

                cur = conn.cursor()
                cur.execute("PRAGMA table_info(audit_log)")
                existing_cols = {c["name"] for c in cur.fetchall()}

                if "timestamp" not in existing_cols and "created_at" in existing_cols:
                    conn.execute("ALTER TABLE audit_log ADD COLUMN timestamp TEXT DEFAULT ''")
                    conn.execute("UPDATE audit_log SET timestamp = created_at WHERE timestamp = ''")
                if "category" not in existing_cols:
                    conn.execute("ALTER TABLE audit_log ADD COLUMN category TEXT DEFAULT 'system'")
                if "action" not in existing_cols and "event_type" in existing_cols:
                    conn.execute("ALTER TABLE audit_log ADD COLUMN action TEXT DEFAULT 'event'")
                    conn.execute("UPDATE audit_log SET action = event_type WHERE action = 'event'")
                if "event_type" not in existing_cols and "action" in existing_cols:
                    conn.execute("ALTER TABLE audit_log ADD COLUMN event_type TEXT DEFAULT ''")
                    conn.execute("UPDATE audit_log SET event_type = action WHERE event_type = ''")
                if "current_hash" not in existing_cols and "hash" in existing_cols:
                    conn.execute("ALTER TABLE audit_log ADD COLUMN current_hash TEXT DEFAULT ''")
                    conn.execute("UPDATE audit_log SET current_hash = hash WHERE current_hash = ''")
                if "payload_json" not in existing_cols and "payload" in existing_cols:
                    conn.execute("ALTER TABLE audit_log ADD COLUMN payload_json TEXT DEFAULT '{}'")
                    conn.execute("UPDATE audit_log SET payload_json = payload WHERE payload_json = '{}'")

                for dispatch_col in ("provider", "model", "target_host", "target_endpoint", "egress_zone"):
                    if dispatch_col not in existing_cols:
                        conn.execute(f"ALTER TABLE audit_log ADD COLUMN {dispatch_col} TEXT DEFAULT ''")

                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_category ON audit_log(category)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_target_host ON audit_log(target_host)")

            conn.commit()
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(audit_log)")
            self.cols = {c["name"] for c in cur.fetchall()}
        finally:
            conn.close()

    def record_event(self, category: str, action: str, agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fügt ein neues manipulationssicheres Ereignis an die SHA-256 Hashkette an.
        Hash = SHA256(prev_hash + '|' + timestamp + '|' + category + '|' + action + '|' + agent_id + '|' + payload_json)
        Bei `category == 'llm_dispatch'` werden `provider`, `model`, `target_host`,
        `target_endpoint` und `egress_zone` sowohl kryptografisch in `payload_json` signiert
        als auch in dedizierten Index-Spalten abgelegt.
        """
        safe_payload = dict(payload or {})
        payload_str = json.dumps(safe_payload, sort_keys=True, ensure_ascii=False)
        now_iso = datetime.datetime.now().isoformat()

        provider_val = str(safe_payload.get("provider", "") or "") if category == "llm_dispatch" else str(safe_payload.get("provider", "") or "")
        model_val = str(safe_payload.get("model", "") or "") if category == "llm_dispatch" else str(safe_payload.get("model", "") or "")
        target_host_val = str(safe_payload.get("target_host", "") or "")
        target_ep_val = str(safe_payload.get("target_endpoint", "") or "")
        egress_zone_val = str(safe_payload.get("egress_zone", "") or "")

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                cur.execute("SELECT current_hash FROM audit_log ORDER BY id DESC LIMIT 1")
                last_row = cur.fetchone()
                prev_hash = last_row["current_hash"] if last_row and last_row["current_hash"] else GENESIS_HASH

                raw_str = f"{prev_hash}|{now_iso}|{category}|{action}|{agent_id}|{payload_str}"
                current_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

                col_map = {
                    "timestamp": now_iso,
                    "category": category,
                    "action": action,
                    "event_type": action,
                    "agent_id": agent_id,
                    "provider": provider_val,
                    "model": model_val,
                    "target_host": target_host_val,
                    "target_endpoint": target_ep_val,
                    "egress_zone": egress_zone_val,
                    "payload_json": payload_str,
                    "prev_hash": prev_hash,
                    "current_hash": current_hash,
                    "hash": current_hash,
                    "payload": payload_str,
                    "created_at": now_iso,
                }

                active_cols = [c for c in col_map if c in getattr(self, "cols", col_map.keys())]
                placeholders = ", ".join(["?"] * len(active_cols))
                col_names = ", ".join(active_cols)
                values = [col_map[c] for c in active_cols]

                cur.execute(f"INSERT INTO audit_log ({col_names}) VALUES ({placeholders})", values)
                conn.commit()
                event_id = cur.lastrowid
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                conn.close()

            result = {
                "event_id": event_id,
                "timestamp": now_iso,
                "category": category,
                "action": action,
                "agent_id": agent_id,
                "prev_hash": prev_hash,
                "current_hash": current_hash,
            }
            if category == "llm_dispatch":
                result.update({
                    "provider": provider_val,
                    "model": model_val,
                    "target_host": target_host_val,
                    "target_endpoint": target_ep_val,
                    "egress_zone": egress_zone_val,
                })
            return result

    def record_llm_dispatch(
        self,
        *,
        agent_id: str,
        provider: str,
        model: str,
        target_endpoint: str,
        action: str = "llm_call_dispatched",
        data_category: str = "general",
        http_status: int = 200,
        zero_egress_active: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Protokolliert einen einzelnen LLM-Dispatch (oder geblockten Versuch) revisionssicher
        in der SHA-256-Hashkette mit realem Ziel-Endpunkt, Provider, Modell und Ziel-Host.
        """
        clean_ep, target_host, egress_zone = sanitize_llm_endpoint(target_endpoint)
        norm_provider = (str(provider or "").strip() or "unknown").lower()
        norm_model = str(model or "").strip() or "unknown"

        payload: Dict[str, Any] = {
            "provider": norm_provider,
            "model": norm_model,
            "target_endpoint": clean_ep,
            "target_host": target_host,
            "egress_zone": egress_zone,
            "data_category": str(data_category or "general"),
            "http_status": int(http_status),
            "zero_egress_active": bool(zero_egress_active),
        }
        if extra and isinstance(extra, dict):
            for k, v in extra.items():
                if k not in payload:
                    payload[k] = v

        return self.record_event(
            category="llm_dispatch",
            action=action,
            agent_id=str(agent_id or "system"),
            payload=payload,
        )

    def verify_integrity(self) -> Dict[str, Any]:
        """
        Vollständige GoBD / ISO 27001 Revisionsprüfung:
        Prüft jedes Kettenglied von Block 1 bis N auf mathematische Unversehrtheit
        inklusive lückenloser Validierung aller `llm_dispatch`-Nachweisfelder
        (`provider`, `model`, `target_host`, `target_endpoint`, `egress_zone`).
        """
        with self._lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                select_cols = [
                    "id", "timestamp", "category", "action", "agent_id",
                    "payload_json", "prev_hash", "current_hash",
                ]
                has_dispatch_cols = all(
                    c in getattr(self, "cols", set())
                    for c in ("provider", "model", "target_host", "target_endpoint", "egress_zone")
                )
                if has_dispatch_cols:
                    select_cols.extend(["provider", "model", "target_host", "target_endpoint", "egress_zone"])

                cur.execute(f"SELECT {', '.join(select_cols)} FROM audit_log ORDER BY id ASC")
                rows = cur.fetchall()

                if not rows:
                    return {
                        "valid": True,
                        "total_records": 0,
                        "llm_dispatch_records": 0,
                        "genesis_hash": GENESIS_HASH,
                        "latest_hash": GENESIS_HASH,
                        "message": "Audit-Log ist leer. Keine Transaktionen vorhanden.",
                    }

                expected_prev = GENESIS_HASH
                llm_dispatch_count = 0

                for r in rows:
                    # 1. Kettenglied-Prüfung
                    if r["prev_hash"] != expected_prev:
                        return {
                            "valid": False,
                            "corrupted_id": r["id"],
                            "reason": f"Kettenbruch bei Block #{r['id']}: Vorheriger Hash stimmt nicht mit vorherigem Block überein.",
                            "expected_prev": expected_prev,
                            "actual_prev": r["prev_hash"],
                        }

                    # 2. Inhalts-Signatur Prüfung (SHA-256)
                    raw_str = f"{r['prev_hash']}|{r['timestamp']}|{r['category']}|{r['action']}|{r['agent_id']}|{r['payload_json']}"
                    recomputed = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()

                    if recomputed != r["current_hash"]:
                        return {
                            "valid": False,
                            "corrupted_id": r["id"],
                            "reason": f"Manipulationsalarm bei Block #{r['id']}: Inhalt oder Zeitstempel weicht vom signierten Hash ab.",
                            "expected_hash": recomputed,
                            "actual_hash": r["current_hash"],
                        }

                    # 3. LLM-Dispatch Nachweis- & Spaltenkonsistenz-Prüfung
                    if r["category"] == "llm_dispatch":
                        llm_dispatch_count += 1
                        try:
                            parsed_payload = json.loads(r["payload_json"])
                        except Exception:
                            return {
                                "valid": False,
                                "corrupted_id": r["id"],
                                "reason": f"Ungültiges Payload-JSON in LLM-Dispatch Block #{r['id']}.",
                            }
                        for req_key in ("provider", "model", "target_host", "target_endpoint"):
                            if not str(parsed_payload.get(req_key, "")).strip():
                                return {
                                    "valid": False,
                                    "corrupted_id": r["id"],
                                    "reason": f"Unvollständiger LLM-Dispatch-Nachweis bei Block #{r['id']}: Feld '{req_key}' fehlt.",
                                }
                        if has_dispatch_cols:
                            for col_key in ("provider", "model", "target_host", "target_endpoint", "egress_zone"):
                                col_val = str(r[col_key] or "")
                                pay_val = str(parsed_payload.get(col_key, "") or "")
                                if col_val and col_val != pay_val:
                                    return {
                                        "valid": False,
                                        "corrupted_id": r["id"],
                                        "reason": f"Spaltenmanipulation bei Block #{r['id']}: Indexspalte '{col_key}' ('{col_val}') weicht vom signierten Hash-Payload ('{pay_val}') ab.",
                                    }

                    expected_prev = r["current_hash"]

                return {
                    "valid": True,
                    "total_records": len(rows),
                    "llm_dispatch_records": llm_dispatch_count,
                    "genesis_hash": GENESIS_HASH,
                    "latest_hash": expected_prev,
                    "message": f"Kryptografische GoBD/ISO Audit-Kette vollständig intakt ({len(rows)} Blöcke verifiziert, davon {llm_dispatch_count} LLM-Dispatches).",
                }
            finally:
                conn.close()

    def list_events(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        provider: Optional[str] = None,
        target_host: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Liefert gefilterte Audit-Events mit Paginierung für UI und Dashboards."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            query = "SELECT * FROM audit_log WHERE 1=1"
            params: List[Any] = []

            if category and category.lower() not in ("all", "alle"):
                query += " AND category = ?"
                params.append(category)

            if provider and provider.strip():
                query += " AND provider = ?"
                params.append(provider.strip().lower())

            if target_host and target_host.strip():
                query += " AND target_host LIKE ?"
                params.append(f"%{target_host.strip().lower()}%")

            if search:
                query += " AND (action LIKE ? OR agent_id LIKE ? OR payload_json LIKE ? OR target_host LIKE ? OR model LIKE ?)"
                term = f"%{search}%"
                params.extend([term, term, term, term, term])

            count_query = query.replace("SELECT *", "SELECT COUNT(*)")
            cur.execute(count_query, params)
            total = cur.fetchone()[0]

            query += " ORDER BY id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cur.execute(query, params)
            res = []
            for r in cur.fetchall():
                d = dict(r)
                d["hash"] = d.get("current_hash")
                d["event_type"] = d.get("action")
                d["payload"] = d.get("payload_json", "{}")
                try:
                    parsed = json.loads(d.get("payload_json", "{}"))
                except Exception:
                    parsed = {}
                d["payload_parsed"] = parsed
                # Rückwärtskompatible Anreicherung aus Payload falls Spalte leer
                for f_key in ("provider", "model", "target_host", "target_endpoint", "egress_zone"):
                    if not d.get(f_key) and isinstance(parsed, dict) and parsed.get(f_key):
                        d[f_key] = parsed.get(f_key)
                res.append(d)

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "entries": res,
            }
        finally:
            conn.close()

    def list_llm_dispatches(
        self,
        limit: int = 50,
        offset: int = 0,
        provider: Optional[str] = None,
        target_host: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Liefert die chronologisch neuesten kryptografisch verketteten LLM-Dispatch-Nachweise."""
        res = self.list_events(
            category="llm_dispatch",
            limit=limit,
            offset=offset,
            provider=provider,
            target_host=target_host,
        )
        out: List[Dict[str, Any]] = []
        for entry in res.get("entries", []):
            p = entry.get("payload_parsed") or {}
            out.append({
                "id": entry.get("id"),
                "timestamp": entry.get("timestamp"),
                "action": entry.get("action"),
                "agent_id": entry.get("agent_id"),
                "provider": entry.get("provider") or p.get("provider", ""),
                "model": entry.get("model") or p.get("model", ""),
                "target_host": entry.get("target_host") or p.get("target_host", ""),
                "target_endpoint": entry.get("target_endpoint") or p.get("target_endpoint", ""),
                "egress_zone": entry.get("egress_zone") or p.get("egress_zone", ""),
                "data_category": p.get("data_category", "general"),
                "http_status": p.get("http_status", 0),
                "zero_egress_active": bool(p.get("zero_egress_active", False)),
                "prev_hash": entry.get("prev_hash"),
                "current_hash": entry.get("current_hash"),
            })
        return out

    def generate_compliance_export(self, format_type: str = "json") -> Dict[str, Any]:
        """
        Generiert einen revisionssicheren Prüfbericht für GoBD / ISO 27001 Auditoren.
        Enthält alle Blöcke, die Merkle-/SHA-256-Prüfsumme, LLM-Dispatch-Nachweise und Validierungs-Signatur.
        """
        verification = self.verify_integrity()
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM audit_log ORDER BY id ASC")
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        meta = {
            "standard": "GoBD & ISO/IEC 27001 Revisionssicherheits-Nachweis",
            "system": "Archon OS - Zero-Trust Cryptographic Ledger",
            "exported_at": datetime.datetime.now().isoformat(),
            "verification_status": "VALID_INTACT" if verification["valid"] else "COMPROMISED",
            "total_blocks": len(rows),
            "llm_dispatch_blocks": verification.get("llm_dispatch_records", 0),
            "genesis_hash": GENESIS_HASH,
            "latest_hash": verification.get("latest_hash", GENESIS_HASH),
        }

        if format_type.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
            writer.writerow([
                "#ID", "Zeitstempel", "Kategorie", "Aktion", "Agent/Initiator",
                "Provider", "Modell", "Ziel_Host", "Ziel_Endpunkt", "Egress_Zone",
                "Vorheriger_Hash", "Block_Hash", "Payload_JSON",
            ])
            for r in rows:
                try:
                    p = json.loads(r.get("payload_json") or "{}")
                except Exception:
                    p = {}
                writer.writerow([
                    r["id"],
                    r["timestamp"],
                    r["category"],
                    r["action"],
                    r["agent_id"],
                    r.get("provider") or p.get("provider", ""),
                    r.get("model") or p.get("model", ""),
                    r.get("target_host") or p.get("target_host", ""),
                    r.get("target_endpoint") or p.get("target_endpoint", ""),
                    r.get("egress_zone") or p.get("egress_zone", ""),
                    r["prev_hash"],
                    r["current_hash"],
                    r["payload_json"],
                ])
            return {
                "filename": f"archon_gobd_audit_export_{int(datetime.datetime.now().timestamp())}.csv",
                "content_type": "text/csv; charset=utf-8",
                "content": output.getvalue(),
                "metadata": meta,
            }
        else:
            export_doc = {
                "audit_meta": meta,
                "verification_proof": verification,
                "blocks": rows,
            }
            return {
                "filename": f"archon_gobd_audit_export_{int(datetime.datetime.now().timestamp())}.json",
                "content_type": "application/json; charset=utf-8",
                "content": json.dumps(export_doc, indent=2, ensure_ascii=False),
                "metadata": meta,
            }


# Singleton Instanz
chained_audit_log = ChainedAuditLog()
