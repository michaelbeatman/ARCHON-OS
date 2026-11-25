"""
backend/execution_receipt_ledger.py
Paket 4 (Feature 20): Manipulationssichere Kosten- & Entscheidungs-Quittungen (Execution Receipts).
Erzeugt für jeden abgeschlossenen Task eine kryptografisch verkettete SHA-256-Quittung (`prev_receipt_hash` -> `receipt_hash`)
mit Modell, Token-Verbrauch, Kosten in USD, genutzten Tools und Policy-Status in SQLite (`execution_receipts_ledger`).
"""

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
import uuid

logger = logging.getLogger(__name__)


class _ArchonClosingConn(sqlite3.Connection):
    def __enter__(self):
        super().__enter__()
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEDGER_LOCK = threading.RLock()

# HMAC statt nacktem SHA-256: mit DB-Schreibzugriff koennte sonst die gesamte
# Kette ab Block 1 neu signiert werden. Der Key kommt ausschliesslich aus der
# ENV (gleicher Zweck wie ARCHON_AUDIT_HMAC_KEY, aber eigener Namespace).
RECEIPT_HMAC_PREFIX = "hmac-sha256:"
# Audit 23.11.2026: eigener Key-Namespace mit Domain-Separation. Fällt nur
# zu Installationen ohne separaten Key zurück (Legacy-Kompatibilität).
_RECEIPT_KEY_ENV = "ARCHON_RECEIPT_HMAC_KEY"
_LEGACY_KEY_ENV = "ARCHON_AUDIT_HMAC_KEY"
_HMAC_DOMAIN = b"archon-receipt-chain:v1:"
_RECEIPT_EPOCHS_ENV = "ARCHON_RECEIPT_HMAC_EPOCHS"
_LEGACY_EPOCHS_ENV = "ARCHON_AUDIT_HMAC_EPOCHS"
_RECEIPT_EPOCH_FROM_ENV = "ARCHON_RECEIPT_HMAC_EPOCH_FROM"
_LEGACY_EPOCH_FROM_ENV = "ARCHON_AUDIT_HMAC_EPOCH_FROM"


def _receipt_epochs() -> list:
    """C (Audit): (from_block, key)-Epochen analog zu audit_log.py.

    Jeder Block wird mit dem Key verifiziert, der bei seinem Schreiben galt.
    Ohne Konfiguration gibt es genau eine Epoche ab Block 0 — damit bleiben
    alle bestehenden Quittungen nach diesem Fix unveraendert verifizierbar.
    Das JSON-Format entspricht ARCHON_AUDIT_HMAC_EPOCHS:
    ``[{"key": "...", "from_block": 1}, ...]``.
    """
    epochs: list = []
    raw = os.environ.get(_RECEIPT_EPOCHS_ENV, "").strip()
    if not raw:
        raw = os.environ.get(_LEGACY_EPOCHS_ENV, "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data:
                    key = str(item.get("key", "")).strip().encode("utf-8")
                    if key:
                        epochs.append((int(item.get("from_block", 0)), key))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("Ungueltige Receipt-HMAC-Epochen: %s", exc)
    key = os.environ.get(_RECEIPT_KEY_ENV, "").strip()  # type: ignore[assignment]
    if key:
        from_env = _RECEIPT_EPOCH_FROM_ENV
    else:
        key = os.environ.get(_LEGACY_KEY_ENV, "").strip()  # type: ignore[assignment]
        from_env = _LEGACY_EPOCH_FROM_ENV
    if key:
        try:
            start = int(os.environ.get(from_env, "0") or 0)
        except ValueError:
            start = 0
        epochs.append((start, key.encode("utf-8")))  # type: ignore[attr-defined]
    try:
        return sorted(set(epochs))
    except Exception:
        return epochs


def _receipt_key_for_block(block_id) -> bytes:
    epochs = _receipt_epochs()
    if not epochs:
        return b""
    if block_id is None:
        return epochs[-1][1]
    try:
        block_num = int(block_id)
    except (TypeError, ValueError):
        return epochs[-1][1]
    usable = [key for start, key in epochs if start <= block_num]
    return usable[-1] if usable else b""


def _receipt_key() -> bytes:
    """Aktueller (juengster) Key — rueckwaerts kompatibel mit alten Aufrufern."""
    return _receipt_key_for_block(None)


def _receipt_uses_legacy_key() -> bool:
    """True, wenn kein eigener Receipt-Key konfiguriert ist (D05/MED).

    Der Fallback auf ARCHON_AUDIT_HMAC_KEY darf nie als domain-getrennter
    Schutz ausgegeben werden: ein kompromittierter Audit-Key würde sonst auch
    alle Quittungen kompromittieren. Der Verify-Result meldet das ehrlich mit
    ``hmac_protected=False`` / ``key_source='legacy_audit_key'``.
    """
    dedicated_key = bool(os.environ.get(_RECEIPT_KEY_ENV, "").strip())
    dedicated_epochs = bool(os.environ.get(_RECEIPT_EPOCHS_ENV, "").strip())
    return not (dedicated_key or dedicated_epochs)


def _receipt_digest(canonical: str, block_id=None, *, allow_legacy: bool = False) -> str:
    """D05/MED: ohne HMAC-Key keine neue (ungeschuetzte) Quittung schreiben.

    Der fruehere stille Fallback auf nacktes SHA-256 war ein impliziter
    HMAC-Abschalter: fehlte ``ARCHON_RECEIPT_HMAC_KEY``/``ARCHON_AUDIT_HMAC_KEY``,
    wurden neue Bloecke ungeschuetzt geschrieben und dennoch als valid
    ausgewiesen. Legacy-Bloecke bleiben nur im Verify-Pfad ueber explizites
    ``allow_legacy=True`` pruefbar.
    """
    key = _receipt_key_for_block(block_id)
    payload = canonical.encode("utf-8")
    if key:
        import hmac as _hmac
        return RECEIPT_HMAC_PREFIX + _hmac.new(key, _HMAC_DOMAIN + payload, hashlib.sha256).hexdigest()
    if not allow_legacy:
        raise RuntimeError(
            "[Receipt] HMAC-Key fehlt — keine ungeschuetzte Quittung schreiben. "
            "ARCHON_RECEIPT_HMAC_KEY (oder ARCHON_AUDIT_HMAC_KEY) setzen."
        )
    return hashlib.sha256(payload).hexdigest()
try:
    from backend.db_paths import resolve_db
    DB_PATH = resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("execution_receipts")
    except Exception:
        return {
            "enabled": True,
            "hash_algorithm": "sha256",
            "chain_receipts": True,
            "include_cost_breakdown": True
        }


def _receipt_trace_fields(
    trace_id: str = "",
    span_id: str = "",
    traceparent: str = "",
) -> tuple:
    """D16/H4: W3C-Kontext einer Quittung zuordnen (nie eine neue Root-ID erfinden).

    Explizite Werte (z. B. aus einem Drainer-Kontext) haben Vorrang. Fehlen sie,
    wird der aktive Kontext aus ``trace_context`` uebernommen. Ohne Kontext
    bleiben alle Felder leer — die Kette wird dadurch nicht neu gerootet.
    """
    tid = str(trace_id or "").strip()
    sid = str(span_id or "").strip()
    tp = str(traceparent or "").strip()
    try:
        from backend import trace_context as _tc

        if tp and not (tid and sid):
            parsed = _tc.parse_traceparent(tp)
            if parsed:
                tid = tid or parsed[0]
                sid = sid or parsed[1]
        if not tid:
            tid = str(_tc.current_trace_id() or "").strip()
        if not sid:
            sid = str(_tc.current_span_id() or "").strip()
        if not tp and tid and sid:
            tp = _tc.format_traceparent(tid, sid, bool(_tc.current_sampled()))
    except Exception as exc:  # pragma: no cover - Trace-Kontext optional
        # A9-DELEGATED (D16/MED): kein stiller DEBUG-Swallower; Fehler im
        # zentralen Tracing-Status zaehlen (note_local_trace_error).
        logger.warning("[Receipt] Trace-Kontext nicht verfuegbar: %s", exc)
        try:
            from backend.trace_context import note_local_trace_error
            note_local_trace_error("receipt-context", exc)
        except Exception as _count_exc:
            logger.debug("[Receipt] Fehlerzaehler nicht erreichbar: %s", _count_exc)
    return tid, sid, tp


def _init_db(db_path: str = None) -> None:  # type: ignore[assignment]
    target = db_path or DB_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with sqlite3.connect(target, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_receipts_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id TEXT UNIQUE,
                task_id TEXT,
                agent_role TEXT,
                model_used TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                cost_usd REAL,
                tools_invoked_json TEXT,
                prev_hash TEXT,
                receipt_hash TEXT,
                created_at TEXT
            )
        """)
        # D16/H4: bestandskompatible Trace-Spalten. ALTER TABLE ADD COLUMN mit
        # DEFAULT '' veraendert keine bestehenden Zeilen und damit auch keine
        # signierungsrelevante Spalte — alte Quittungen bleiben verifizierbar.
        ledger_cols = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(execution_receipts_ledger)"
            ).fetchall()
        }
        for trace_col in ("trace_id", "span_id", "traceparent"):
            if trace_col not in ledger_cols:
                conn.execute(
                    f"ALTER TABLE execution_receipts_ledger ADD COLUMN {trace_col} TEXT DEFAULT ''"
                )

        # F-032: persistente Marker fuer explizite Bypass-Ereignisse. Ohne
        # diese Tabelle war ARCHON_ALLOW_RECEIPT_BYPASS eine unsichtbare
        # Luecke in der ansonsten unveraenderbaren Quittungskette.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_receipt_bypass_markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                agent_role TEXT,
                reason TEXT,
                audit_event_id TEXT,
                created_at TEXT
            )
        """)
        marker_cols = {
            row[1] for row in conn.execute(
                "PRAGMA table_info(execution_receipt_bypass_markers)"
            ).fetchall()
        }
        for trace_col in ("trace_id", "span_id", "traceparent"):
            if trace_col not in marker_cols:
                conn.execute(
                    f"ALTER TABLE execution_receipt_bypass_markers ADD COLUMN {trace_col} TEXT DEFAULT ''"
                )

        # Append-only: UPDATE/DELETE an Quittungen und Bypass-Markern muss fehlschlagen (d05 F-09).
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS execution_receipts_no_update
            BEFORE UPDATE ON execution_receipts_ledger
            BEGIN SELECT RAISE(ABORT, 'execution receipts are append-only'); END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS execution_receipts_no_delete
            BEFORE DELETE ON execution_receipts_ledger
            BEGIN SELECT RAISE(ABORT, 'execution receipts are append-only'); END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS execution_receipt_bypass_no_update
            BEFORE UPDATE ON execution_receipt_bypass_markers
            BEGIN SELECT RAISE(ABORT, 'bypass markers are append-only'); END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS execution_receipt_bypass_no_delete
            BEFORE DELETE ON execution_receipt_bypass_markers
            BEGIN SELECT RAISE(ABORT, 'bypass markers are append-only'); END
        """)
        conn.commit()


class ExecutionReceiptLedger:
    def __init__(self, db_path: str = None):  # type: ignore[assignment]
        self._lock = _LEDGER_LOCK
        self.db_path = db_path or DB_PATH
        _init_db(self.db_path)

    def issue_receipt(
        self,
        task_id: str,
        agent_role: str,
        model_used: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float,
        tools_invoked: List[str],
        trace_id: str = "",
        span_id: str = "",
        traceparent: str = "",
    ) -> Dict[str, Any]:
        trace_id, span_id, traceparent = _receipt_trace_fields(
            trace_id, span_id, traceparent
        )
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            # I (Audit): Die Modul-Config allein darf die Quittungskette nicht
            # deaktivieren — sonst entsteht eine signierte Audit-Luecke.
            # Fail-closed, nur mit explizitem Opt-out.
            if os.environ.get("ARCHON_ALLOW_RECEIPT_BYPASS", "").strip().lower() == "true":
                # F-032: Bypass darf nicht unsichtbar eine Kettenluecke reissen.
                # Signiertes Zentral-Event (Grund + Akteur) und ein persistenter
                # Marker, den verify_chain_integrity() als INVALID meldet.
                reason = "ARCHON_ALLOW_RECEIPT_BYPASS=true"
                audit_ev = None
                try:
                    from backend.audit_log import chained_audit_log as _alog
                    audit_ev = _alog.record_event(
                        category="receipt_bypass",
                        action="receipt_issuance_bypassed",
                        agent_id=agent_role or "system",
                        trace_id=trace_id,
                        payload={
                            "task_id": task_id,
                            "agent_role": agent_role,
                            "reason": reason,
                            "actor": agent_role or "system",
                        },
                    )
                except Exception as exc:
                    logger.error("[Receipt] Bypass-Audit-Event fehlgeschlagen: %s", exc)
                audit_event_id = str(audit_ev.get("event_id")) if audit_ev else "audit_error"
                try:
                    with sqlite3.connect(self.db_path, timeout=15.0, factory=_ArchonClosingConn) as mconn:
                        mconn.execute(
                            "INSERT INTO execution_receipt_bypass_markers "
                            "(task_id, agent_role, reason, audit_event_id, created_at, "
                            "trace_id, span_id, traceparent) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (task_id, agent_role, reason, audit_event_id,
                             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
                             trace_id, span_id, traceparent),
                        )
                        mconn.commit()
                except Exception as exc:
                    logger.error("[Receipt] Bypass-Marker nicht persistiert: %s", exc)
                return {
                    "issued": False,
                    "bypassed": True,
                    # persistent sichtbarer Ungueltig-Marker
                    "chain_valid": False,
                    "audit_status": "ok" if audit_ev else "error",
                    "audit_event_id": audit_event_id,
                    "reason": reason,
                    "trace_id": trace_id,
                    "span_id": span_id,
                    "traceparent": traceparent,
                }

        receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
        # GoBD: eindeutige UTC-Zeitreferenz mit Offset.
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        tools_json = json.dumps(tools_invoked or [], ensure_ascii=False)
        rounded_cost = round(float(cost_usd), 6)

        with getattr(self, "_lock", _LEDGER_LOCK):
            with sqlite3.connect(self.db_path, timeout=15.0, factory=_ArchonClosingConn) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT receipt_hash FROM execution_receipts_ledger ORDER BY id DESC LIMIT 1"
                ).fetchone()
                # Immer kryptografisch verketten, damit verify_chain_integrity nie an Config-Wechseln bricht
                prev_hash = row[0] if row else "GENESIS_BLOCK_00000000"
                # C (Audit): Block-ID an den Schreibpfad geben, damit bei einer
                # Key-Rotation derselbe Epochen-Key wie in
                # verify_chain_integrity() (r["id"]) verwendet wird.
                next_id = int(conn.execute(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM execution_receipts_ledger"
                ).fetchone()[0])

                canonical_str = (
                    f"{receipt_id}|{task_id}|{agent_role}|{model_used}|"
                    f"{prompt_tokens}|{completion_tokens}|{rounded_cost:.6f}|{tools_json}|{prev_hash}|{now_iso}"
                )
                receipt_hash = _receipt_digest(canonical_str, next_id)

                conn.execute("""
                    INSERT INTO execution_receipts_ledger
                    (id, receipt_id, task_id, agent_role, model_used, prompt_tokens, completion_tokens,
                     cost_usd, tools_invoked_json, prev_hash, receipt_hash, created_at,
                     trace_id, span_id, traceparent)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    next_id, receipt_id, task_id, agent_role, model_used,
                    prompt_tokens, completion_tokens, rounded_cost,
                    tools_json, prev_hash, receipt_hash, now_iso,
                    trace_id, span_id, traceparent
                ))
                conn.commit()

        return {
            "issued": True,
            "receipt_id": receipt_id,
            "task_id": task_id,
            "agent_role": agent_role,
            "model_used": model_used,
            "total_tokens": prompt_tokens + completion_tokens,
            "cost_usd": rounded_cost,
            "prev_hash": prev_hash,
            "receipt_hash": receipt_hash,
            "created_at": now_iso,
            "trace_id": trace_id,
            "span_id": span_id,
            "traceparent": traceparent,
        }

    def verify_chain_integrity(self) -> Dict[str, Any]:
        # d05 F-03: Quittungskette + Head-Anker + Trigger.
        from backend.audit_log import finalize_secondary_chain_verification
        return finalize_secondary_chain_verification(
            "execution_receipts_ledger", self._verify_chain_integrity_raw(), db_path=self.db_path
        )

    def _verify_chain_integrity_raw(self) -> Dict[str, Any]:
        # C3: immer die Instanz-DB pruefen, nicht die globale Standard-DB.
        with sqlite3.connect(self.db_path, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM execution_receipts_ledger ORDER BY id ASC").fetchall()
            # F-032 / d05 F-09: persistente Bypass-Marker sind ein Integritaetsvorfall.
            bypass_markers: List[Dict[str, Any]] = []
            bypass_markers_unreadable = False
            has_marker_tbl = bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_receipt_bypass_markers'"
            ).fetchone())
            if has_marker_tbl:
                try:
                    for m in conn.execute(
                        "SELECT id, task_id, agent_role, reason, audit_event_id, created_at, "
                        "trace_id, span_id, traceparent "
                        "FROM execution_receipt_bypass_markers ORDER BY id ASC"
                    ).fetchall():
                        bypass_markers.append({
                            "id": m["id"], "task_id": m["task_id"], "agent_role": m["agent_role"],
                            "reason": m["reason"], "audit_event_id": m["audit_event_id"],
                            "created_at": m["created_at"],
                            "trace_id": m["trace_id"] if "trace_id" in m.keys() else "",
                            "span_id": m["span_id"] if "span_id" in m.keys() else "",
                            "traceparent": m["traceparent"] if "traceparent" in m.keys() else "",
                        })
                except sqlite3.Error as exc:
                    logger.error("[ReceiptLedger] bypass_markers nicht lesbar (fail-closed): %s", exc)
                    bypass_markers_unreadable = True

        expected_prev = "GENESIS_BLOCK_00000000"
        broken_links = []
        tampered_hashes = []
        # F-032: Sequenzluecken ueber die numerische id erkennbar machen —
        # eine uebersprungene Quittung (z. B. durch einen Bypass) brach frueher
        # die prev_hash-Kette nicht und blieb daher unsichtbar.
        sequence_gaps: List[Dict[str, Any]] = []
        prev_id: Optional[int] = None
        for r in rows:
            cur_id = int(r["id"])
            if prev_id is not None and cur_id != prev_id + 1:
                sequence_gaps.append({"after_id": prev_id, "expected": prev_id + 1, "actual": cur_id})
            prev_id = cur_id
        for idx, r in enumerate(rows):
            rid = r["receipt_id"]
            if r["prev_hash"] != expected_prev:
                broken_links.append(rid)
            canonical_str = (
                f"{rid}|{r['task_id']}|{r['agent_role']}|{r['model_used']}|"
                f"{int(r['prompt_tokens'])}|{int(r['completion_tokens'])}|{float(r['cost_usd']):.6f}|"
                f"{r['tools_invoked_json']}|{r['prev_hash']}|{r['created_at']}"
            )
            stored = str(r["receipt_hash"] or "")
            if stored.startswith(RECEIPT_HMAC_PREFIX):
                # C (Audit): mit dem Key der Epoche des Blocks pruefen, nicht
                # mit dem aktuellen — sonst loest Rotation einen Fehlalarm aus.
                # Verify ist lesend: allow_legacy=True verhindert einen Raise,
                # falls der Key nach dem Schreiben entfernt wurde — der Hash
                # mismatch markiert den Block dann als `tampered` (fail-closed).
                recomputed = _receipt_digest(canonical_str, r["id"], allow_legacy=True)
            elif _receipt_key():
                # Audit 23.11.2026: bei aktivem eigenen HMAC-Key darf keine
                # Quittung ohne HMAC-Praefix akzeptiert werden (Downgrade).
                tampered_hashes.append(rid)
                expected_prev = stored
                continue
            else:
                # Legacy-Quittungen (vor HMAC-Einfuehrung) nur explizit im
                # Verify-Pfad pruefbar — der Schreibpfad nutzt allow_legacy=False.
                recomputed = _receipt_digest(canonical_str, r["id"], allow_legacy=True)
            if not hmac.compare_digest(stored, recomputed):
                tampered_hashes.append(rid)
            expected_prev = r["receipt_hash"]

        legacy_key = _receipt_uses_legacy_key()
        strict = str(os.environ.get("ARCHON_AUDIT_STRICT", "1") or "1").strip().lower() not in {
            "0", "false", "no", "off", "none",
        }
        production = str(os.environ.get("ENVIRONMENT") or "").strip().lower() in {
            "production", "prod", "live",
        }
        chain_valid = (
            len(broken_links) == 0 and len(tampered_hashes) == 0
            and len(sequence_gaps) == 0 and len(bypass_markers) == 0
            and not bypass_markers_unreadable
            # D05/MED: eine Kette ohne HMAC-Key ist fuer Pruefer nie "valide",
            # auch wenn alle (Legacy-)Hashes formal zusammenpassen.
            and bool(_receipt_key())
        )
        # D05/MED: in Produktion ist der Legacy-Fallback auf den Audit-Key
        # kein wirksamer Domain-Schutz -> fail-closed (ausser explizitem
        # Strict-Opt-out). In Dev/Test bleibt die Kette formal verifizierbar,
        # wird aber unmissverstaendlich als nicht domain-getrennt markiert.
        if legacy_key and production and strict:
            chain_valid = False
        return {
            "chain_valid": chain_valid,
            "bypass_markers_unreadable": bypass_markers_unreadable,
            "hmac_protected": bool(_receipt_key()) and not legacy_key,
            "domain_separated": not legacy_key,
            "key_source": "legacy_audit_key" if legacy_key else "dedicated_receipt_key",
            "total_receipts": len(rows),
            "broken_links": broken_links,
            "tampered_hashes": tampered_hashes,
            "sequence_gaps": sequence_gaps,
            "bypass_markers": bypass_markers,
            # D16/H4: Verify-/Export-Pfad traegt dieselben W3C-Felder wie der
            # Schreibpfad. r.keys() schuetzt vor Bestands-DBs ohne neue Spalten.
            "trace_context": [
                {
                    "receipt_id": r["receipt_id"],
                    "trace_id": r["trace_id"] if "trace_id" in r.keys() else "",
                    "span_id": r["span_id"] if "span_id" in r.keys() else "",
                    "traceparent": r["traceparent"] if "traceparent" in r.keys() else "",
                }
                for r in rows
            ],
            "latest_hash": expected_prev if rows else None
        }


execution_receipt_ledger = ExecutionReceiptLedger()
