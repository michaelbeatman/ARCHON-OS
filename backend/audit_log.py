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
import hmac
import sqlite3
import datetime
import ipaddress
import threading
import time
import contextlib
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import logging

logger = logging.getLogger(__name__)

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
GENESIS_HASH = "0" * 64


@contextlib.contextmanager
def _read_snapshot(lock: threading.RLock, conn: sqlite3.Connection):
    """F (Audit): In-Process-Lock nur fuer den Transaktionsstart halten.

    ``verify_integrity()`` wird von main.py alle 30 s aufgerufen. Der fruehere
    Volltabellen-Scan unter ``self._lock`` blockierte jeden Schreibvorgang.
    Eine explizite READ-Transaktion in WAL liefert ueber die gesamte Prüfung
    einen konsistenten Snapshot, ohne dass die Lock waehrend des Scans gehalten
    wird. Parallel appends bleiben moeglich; der (asynchrone) Anker wird
    dadurch praefix-tolerant geprueft (siehe G).
    """
    with lock:
        conn.execute("BEGIN")
    try:
        yield
    finally:
        try:
            conn.rollback()
        except Exception:
            pass


# HMAC statt nacktem SHA-256: ohne Separat-Secret kann jemand mit DB-Schreibzugriff
# die Kette ab Block 1 neu signieren. Der Key kommt ausschließlich aus der ENV
# (nicht aus einer Datei neben der DB), damit Backup/Image ihn nicht enthalten.
HMAC_PREFIX = "hmac-sha256:"
ANCHOR_INTERVAL_SEC = 300


def _hmac_epochs() -> list:
    """Sortierte (from_block, key)-Epochen aus der Umgebung.

    P1: Ermoeglicht sichere Key-Rotation. Der aktuelle Key steht in
    ``ARCHON_AUDIT_HMAC_KEY`` (optional mit ``ARCHON_AUDIT_HMAC_EPOCH_FROM``).
    Fruehere Keys koennen als JSON-Liste in ``ARCHON_AUDIT_HMAC_EPOCHS``
    stehen: ``[{"key": "...", "from_block": 1}, ...]``. Bloecke werden mit
    genau dem Key verifiziert, der zum Zeitpunkt ihres Schreibens galt —
    alte Bloecke bleiben nach einer Rotation verifizierbar.
    """
    epochs: list = []
    raw = os.environ.get("ARCHON_AUDIT_HMAC_EPOCHS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data:
                    key = str(item.get("key", "")).strip().encode("utf-8")
                    if key:
                        epochs.append((int(item.get("from_block", 0)), key))
        except Exception as exc:
            logger.error("[Audit] ARCHON_AUDIT_HMAC_EPOCHS ungueltig: %s", exc)
    current = os.environ.get("ARCHON_AUDIT_HMAC_KEY", "").strip().encode("utf-8")
    if current:
        epochs.append((int(os.environ.get("ARCHON_AUDIT_HMAC_EPOCH_FROM", "0") or 0), current))
    # F-18: deterministische Sortierung nur nach from_block (nie lexikografisch nach Key-Bytes).
    # Bei doppeltem from_block gewinnt der zuletzt konfigurierte Key (mit Fehler-Log).
    by_block: Dict[int, bytes] = {}
    for start, key in epochs:
        if start in by_block and by_block[start] != key:
            logger.error(
                "[Audit] Doppelte HMAC-Epoche fuer from_block=%s erkannt — letzter Key ueberschreibt.",
                start,
            )
        by_block[start] = key
    return sorted(by_block.items(), key=lambda item: item[0])


def _hmac_key() -> bytes:
    """Aktueller (juengster) Key — rueckwaerts kompatibel mit alten Aufrufern."""
    epochs = _hmac_epochs()
    return epochs[-1][1] if epochs else b""


def _anchor_key() -> bytes:
    """Dedizierter Anker-Key (ARCHON_AUDIT_ANCHOR_KEY), Fallback auf Audit-HMAC-Key."""
    dedicated = os.environ.get("ARCHON_AUDIT_ANCHOR_KEY", "").strip().encode("utf-8")
    return dedicated or _hmac_key()


def _key_for_block(block_id) -> bytes:
    epochs = _hmac_epochs()
    if not epochs:
        return b""
    if block_id is None:
        return epochs[-1][1]
    try:
        block_num = int(block_id)
    except (TypeError, ValueError):
        # E (Audit): z. B. treasury_transactions nutzt TEXT-IDs ('tx-...').
        # Nicht mit ValueError abbrechen, sondern konsistent zum Schreibpfad
        # (der None uebergibt) den juengsten Key verwenden.
        return epochs[-1][1]
    usable = [key for start, key in epochs if start <= block_num]
    return usable[-1] if usable else b""


def sign_block(raw_str: str, block_id=None, *, allow_legacy: bool = False) -> str:
    """Zentrale Signier-API fuer Haupt- und alle Nebenketten (d05 F-01).

    Fail-closed: Ohne konfigurierten HMAC-Key wird KEIN ungesalzener SHA-256-Block
    geschrieben, solange ``sha256_dispatch_audit_enforced`` aktiv ist (Default True),
    es sei denn der Aufrufer fordert explizit ``allow_legacy=True`` (nur fuer
    Leseverifikation / Diagnose).
    """
    key = _key_for_block(block_id)
    if key:
        digest = hmac.new(key, raw_str.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{HMAC_PREFIX}{digest}"
    if not allow_legacy and _dispatch_audit_enforced():
        raise RuntimeError(
            "[Audit] ARCHON_AUDIT_HMAC_KEY fehlt: neue Audit-Bloecke duerfen "
            "nicht mit nacktem SHA-256 geschrieben werden "
            "(sha256_dispatch_audit_enforced=True)."
        )
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def _chain_hash(raw_str: str, block_id=None, *, allow_legacy: bool = False) -> str:
    return sign_block(raw_str, block_id=block_id, allow_legacy=allow_legacy)


def _verify_hash(raw_str: str, stored: str, block_id=None) -> bool:
    stored = str(stored or "")
    if stored.startswith(HMAC_PREFIX):
        key = _key_for_block(block_id)
        if not key:
            return False  # fail-closed: HMAC-Blöcke ohne passenden Key nicht verifizierbar
        expected = HMAC_PREFIX + hmac.new(key, raw_str.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, stored)
    return hmac.compare_digest(hashlib.sha256(raw_str.encode("utf-8")).hexdigest(), stored)


# F-027: Die GoBD-Invariante sha256_dispatch_audit_enforced wird im Kryptopfad
# tatsächlich ausgewertet (nicht nur als Statusanzeige in settings.json).
# Default True = fail-closed: ohne HMAC-Key werden keine neuen Blöcke mehr mit
# nacktem SHA-256 geschrieben. Legacy-SHA256 bleibt ausschließlich LESEND ueber
# legacy_max / _verify_hash zulaessig. Cache mit kurzem TTL vermeidet einen
# settings.json-Read pro Audit-Event.
_FAUDIT_ENFORCE_CACHE_TTL_SEC = 30.0
_faudit_enforce_cache = None


def _dispatch_audit_enforced() -> bool:
    global _faudit_enforce_cache
    now = time.monotonic()
    if _faudit_enforce_cache and (now - _faudit_enforce_cache[0]) < _FAUDIT_ENFORCE_CACHE_TTL_SEC:
        return _faudit_enforce_cache[1]
    enforced = True
    try:
        from backend.autonomy_settings import is_sha256_dispatch_audit_enforced
        enforced = bool(is_sha256_dispatch_audit_enforced())
    except Exception as exc:
        logger.error("[Audit] sha256_dispatch_audit_enforced nicht lesbar: %s — fail-closed (True)", exc)
        enforced = True
    _faudit_enforce_cache = (now, enforced)
    return enforced


# F-029: substring-basierte Erkennung statt exakter Matchliste. Die alte
# exakte Liste liess refresh_token, id_token, auth_token, sig, signature,
# code, session und X-Amz-Signature unredigiert im signierten Endpoint stehen.
_SENSITIVE_QUERY_KEYS = frozenset({
    "key", "api_key", "apikey", "token", "access_token", "secret", "password", "auth"
})
_SENSITIVE_QUERY_SUBSTRINGS = (
    "token", "secret", "key", "sig", "auth", "password", "code", "session",
)
# Explizite Allowlist harmloser Parameter, die einen Sensitivitäts-Substring
# enthalten (z. B. "design" enthaelt "sig", "author" enthaelt "auth").
_SENSITIVE_QUERY_ALLOWLIST = frozenset({
    "design", "designer", "signal", "signals", "keyword", "keywords",
    "keyboard", "author", "authors", "codec", "encode", "decode",
})


def _is_sensitive_query_key(key: str) -> bool:
    kl = (key or "").strip().lower()
    if not kl:
        return False
    if kl in _SENSITIVE_QUERY_ALLOWLIST:
        return False
    if kl in _SENSITIVE_QUERY_KEYS:
        return True
    return any(token in kl for token in _SENSITIVE_QUERY_SUBSTRINGS)

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
            if _is_sensitive_query_key(k):
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
            if not ip_obj.is_link_local and (ip_obj.is_loopback or ip_obj.is_private):
                zone = "LOCAL_ON_PREM"
        except ValueError:
            # Nur explizit erlaubte interne Hosts und localhost.localdomain als LOCAL_ON_PREM;
            # beliebige .local/.lan Hosts muessen explizit per Allowlist freigegeben werden.
            # '.internal' ist bewusst KEIN lokales Suffix mehr (metadata.google.internal!)
            extra_local = {
                h.strip().lower()
                for h in (os.environ.get("ARCHON_LOCAL_LLM_HOSTS", "")).split(",")
                if h.strip()
            }
            if hostname in extra_local or hostname == "localhost.localdomain":
                zone = "LOCAL_ON_PREM"

    return clean_endpoint, target_host, zone


class ChainedAuditLog:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        # W3: stoppbarer Anker-Thread. Vorher konnte der Daemon beim
        # Graceful Shutdown mitten in _write_anchor() abgebrochen werden
        # -> halb geschriebene Integritätsdatei.
        self._anchor_stop = threading.Event()
        self._init_db()
        self._start_anchor_worker()

    def _start_anchor_worker(self) -> None:
        """Optionaler externer Anker. Läuft als Daemon-Thread und schreibt
        ausschließlich im Hintergrund — niemals im Request-Pfad und ohne
        Netzwerkzugriff (funktioniert offline und im Container)."""
        path = os.environ.get("ARCHON_AUDIT_ANCHOR_PATH", "").strip()
        if not path:
            return
        worker = threading.Thread(
            target=self._anchor_loop,
            args=(path,),
            name="archon-audit-anchor",
            daemon=True,
        )
        worker.start()

    def _anchor_loop(self, path: str) -> None:
        while not self._anchor_stop.is_set():
            try:
                self._write_anchor(path)
            except Exception as exc:
                logger.warning("Audit-Log: Anker-Schreibfehler: %s", exc)
            # Event.wait statt time.sleep: sofortiger, kontrollierter Stopp.
            if self._anchor_stop.wait(ANCHOR_INTERVAL_SEC):
                break

    def stop_anchor_worker(self) -> None:
        """Wird vom Graceful-Shutdown-Coordinator aufgerufen."""
        self._anchor_stop.set()
        try:
            self._write_anchor()
        except Exception as exc:
            logger.error("Audit-Log: Finaler Shutdown-Anker fehlgeschlagen: %s", exc)

    def _write_anchor(self, path: Optional[str] = None) -> Optional[str]:
        anchor = (path or os.environ.get("ARCHON_AUDIT_ANCHOR_PATH", "")).strip()
        if not anchor:
            return None
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT id, current_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        if not row:
            return None
        block_id = int(row["id"])
        latest = str(row["current_hash"] or "")
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        akey = _anchor_key()
        sig = (
            hmac.new(akey, f"{ts}|{block_id}|{latest}".encode("utf-8"), hashlib.sha256).hexdigest()
            if akey
            else ""
        )
        os.makedirs(os.path.dirname(os.path.abspath(anchor)), exist_ok=True)
        with open(anchor, "a", encoding="utf-8") as fh:
            fh.write(f"{ts}\t{block_id}\t{latest}\t{sig}\n")
        return latest

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            if os.environ.get("ARCHON_DISABLE_WAL", "").strip().lower() not in ("1", "true", "yes"):
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                    conn.execute("PRAGMA synchronous=NORMAL;")
                except Exception as exc:
                    logger.warning("Audit-Log: WAL-PRAGMA fehlgeschlagen: %s", exc)
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        category TEXT NOT NULL,
                        action TEXT NOT NULL,
                        event_type TEXT,
                        agent_id TEXT NOT NULL,
                        company_id TEXT DEFAULT 'default',
                        provider TEXT DEFAULT '',
                        model TEXT DEFAULT '',
                        target_host TEXT DEFAULT '',
                        target_endpoint TEXT DEFAULT '',
                        egress_zone TEXT DEFAULT '',
                        trace_id TEXT DEFAULT '',
                        session_id TEXT DEFAULT '',
                        correlation_id TEXT DEFAULT '',
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
                if "company_id" not in existing_cols:
                    conn.execute("ALTER TABLE audit_log ADD COLUMN company_id TEXT DEFAULT 'default'")

                for dispatch_col in (
                    "provider", "model", "target_host", "target_endpoint", "egress_zone",
                    "trace_id", "session_id", "correlation_id",
                ):
                    if dispatch_col not in existing_cols:
                        conn.execute(f"ALTER TABLE audit_log ADD COLUMN {dispatch_col} TEXT DEFAULT ''")

                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_category ON audit_log(category)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_target_host ON audit_log(target_host)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_company_id ON audit_log(company_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_trace_id ON audit_log(trace_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_session_id ON audit_log(session_id)")

                # P1: Append-only. Ohne Trigger konnte jemand mit DB-Schreibzugriff
                # die letzten N Bloecke loeschen — verify_integrity() prueft nur
                # vorhandene Bloecke und meldete weiter "valid".
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS audit_log_no_update
                    BEFORE UPDATE ON audit_log
                    BEGIN
                        SELECT RAISE(ABORT, 'audit_log is append-only');
                    END
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
                    BEFORE DELETE ON audit_log
                    BEGIN
                        SELECT RAISE(ABORT, 'audit_log is append-only');
                    END
                """)

            conn.commit()
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(audit_log)")
            self.cols = {c["name"] for c in cur.fetchall()}
        finally:
            conn.close()

    def record_event(
        self,
        category: str,
        action: str,
        agent_id: str,
        payload: Dict[str, Any],
        *,
        trace_id: str = "",
        session_id: str = "",
        correlation_id: str = "",
    ) -> Dict[str, Any]:
        """
        Fügt ein neues manipulationssicheres Ereignis an die SHA-256 Hashkette an.
        Hash = HMAC-SHA256(prev_hash + '|' + timestamp + '|' + category + '|' + action + '|' + agent_id + '|' + company_id + '|' + payload_json)
        Bei `category == 'llm_dispatch'` werden `provider`, `model`, `target_host`,
        `target_endpoint` und `egress_zone` sowohl kryptografisch in `payload_json` signiert
        als auch in dedizierten Index-Spalten abgelegt.
        """
        safe_payload = dict(payload or {})
        # Audit D16: ohne expliziten Parameter den aktiven W3C-Trace aus
        # contextvars übernehmen — damit Audit-Eintrag und OTel-/HTTP-Trace
        # dieselbe Korrelations-ID tragen.
        from backend.trace_context import current_trace_id as _current_trace_id

        trace_id_val = str(trace_id or safe_payload.get("trace_id") or _current_trace_id() or "").strip()
        session_id_val = str(session_id or safe_payload.get("session_id") or "").strip()
        correlation_id_val = str(correlation_id or safe_payload.get("correlation_id") or "").strip()
        if trace_id_val and "trace_id" not in safe_payload:
            safe_payload["trace_id"] = trace_id_val
        if session_id_val and "session_id" not in safe_payload:
            safe_payload["session_id"] = session_id_val
        if correlation_id_val and "correlation_id" not in safe_payload:
            safe_payload["correlation_id"] = correlation_id_val

        payload_str = json.dumps(safe_payload, sort_keys=True, ensure_ascii=False)
        # GoBD: eindeutige Zeitreferenz mit UTC-Offset (frueher naive Lokalzeit).
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        # F-19: tote Bedingung entfernt — Dispatch-Spalten klar aus Payload extrahieren.
        provider_val = str(safe_payload.get("provider", "") or "")
        model_val = str(safe_payload.get("model", "") or "")
        target_host_val = str(safe_payload.get("target_host", "") or "")
        target_ep_val = str(safe_payload.get("target_endpoint", "") or "")
        egress_zone_val = str(safe_payload.get("egress_zone", "") or "")
        company_id_val = str(safe_payload.get("company_id") or "").strip()
        if not company_id_val:
            try:
                from backend.tenant_context import tenant_context
                company_id_val = tenant_context.get_active_tenant_id() or "default"
            except Exception:
                company_id_val = "default"
        else:
            try:
                from backend.tenant_context import sanitize_tenant_id
                company_id_val = sanitize_tenant_id(company_id_val)
            except Exception as exc:
                logger.debug("Audit-Log: sanitize_tenant_id nicht verfuegbar: %s", exc)

        # F-027: Neue Bloecke NEVER mit nacktem SHA-256 schreiben. Die
        # GoBD-Invariante sha256_dispatch_audit_enforced erzwingt den HMAC-Key
        # im Schreibpfad; nacktes SHA-256 bleibt lesend auf den explizit
        # markierten legacy_max-Bereich beschraenkt (siehe verify_integrity).
        if not _hmac_epochs():
            if _dispatch_audit_enforced():
                raise RuntimeError(
                    "[Audit] ARCHON_AUDIT_HMAC_KEY fehlt: neue Audit-Bloecke duerfen "
                    "nicht mit nacktem SHA-256 geschrieben werden "
                    "(sha256_dispatch_audit_enforced=True)."
                )
            logger.error(
                "[Audit] OPT-OUT sha256_dispatch_audit_enforced=False: neuer Block "
                "%s/%s wird UNGESCHUETZT mit nacktem SHA-256 geschrieben.",
                category, action,
            )

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                cur.execute("SELECT id, current_hash FROM audit_log ORDER BY id DESC LIMIT 1")
                last_row = cur.fetchone()
                prev_hash = last_row["current_hash"] if last_row and last_row["current_hash"] else GENESIS_HASH
                # E (Audit): Schreib- und Lesepfad muessen dieselbe Block-ID
                # verwenden. verify_integrity() uebergibt r["id"] an
                # _verify_hash(); ohne ID naehme _chain_hash() immer den
                # juengsten Key und eine Rotation mit EPOCH_FROM waere wirkungslos.
                next_id = int(cur.execute(
                    "SELECT COALESCE(MAX(id), 0) + 1 FROM audit_log"
                ).fetchone()[0])

                # company_id in den signierten String aufnehmen: sonst kann die
                # Mandantenzuordnung nachträglich geändert werden, ohne dass
                # verify_integrity() alarmiert.
                raw_str = f"{prev_hash}|{now_iso}|{category}|{action}|{agent_id}|{company_id_val}|{payload_str}"
                current_hash = _chain_hash(raw_str, next_id)

                col_map = {
                    "id": next_id,
                    "timestamp": now_iso,
                    "category": category,
                    "action": action,
                    "event_type": action,
                    "agent_id": agent_id,
                    "company_id": company_id_val,
                    "provider": provider_val,
                    "model": model_val,
                    "target_host": target_host_val,
                    "target_endpoint": target_ep_val,
                    "egress_zone": egress_zone_val,
                    "trace_id": trace_id_val,
                    "session_id": session_id_val,
                    "correlation_id": correlation_id_val,
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
                except Exception as exc:
                    logger.debug("Audit-Log: Rollback fehlgeschlagen: %s", exc)
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
        cost_usd: Optional[float] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        trace_id: str = "",
        session_id: str = "",
        correlation_id: str = "",
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
        # H (Audit): Kosten und Token-Verbrauch sind revisionsrelevant und
        # gehoeren in den signierten Payload, sofern der Aufrufer sie liefert.
        # Optionale Parameter -> bestehende Aufrufer bleiben kompatibel.
        if cost_usd is not None:
            payload["cost_usd"] = float(cost_usd)
        if prompt_tokens is not None:
            payload["prompt_tokens"] = int(prompt_tokens)
        if completion_tokens is not None:
            payload["completion_tokens"] = int(completion_tokens)
        if extra and isinstance(extra, dict):
            for k, v in extra.items():
                if k not in payload:
                    payload[k] = v

        return self.record_event(
            category="llm_dispatch",
            action=action,
            agent_id=str(agent_id or "system"),
            payload=payload,
            trace_id=trace_id,
            session_id=session_id,
            correlation_id=correlation_id,
        )

    def verify_integrity(self) -> Dict[str, Any]:
        """
        Vollständige GoBD / ISO 27001 Revisionsprüfung:
        Prüft jedes Kettenglied von Block 1 bis N auf mathematische Unversehrtheit
        inklusive lückenloser Validierung aller `llm_dispatch`-Nachweisfelder
        (`provider`, `model`, `target_host`, `target_endpoint`, `egress_zone`).
        """
        conn = self._get_conn()
        with _read_snapshot(self._lock, conn):
            try:
                cur = conn.cursor()
                select_cols = [
                    "id", "timestamp", "category", "action", "agent_id",
                    "company_id", "payload_json", "prev_hash", "current_hash",
                ]
                if "company_id" not in getattr(self, "cols", set()):
                    select_cols.remove("company_id")
                has_event_type_col = "event_type" in getattr(self, "cols", set())
                if has_event_type_col:
                    select_cols.append("event_type")
                has_dispatch_cols = all(
                    c in getattr(self, "cols", set())
                    for c in ("provider", "model", "target_host", "target_endpoint", "egress_zone")
                )
                if has_dispatch_cols:
                    select_cols.extend(["provider", "model", "target_host", "target_endpoint", "egress_zone"])

                # F-08: Append-only Trigger-Existenz pruefen.
                existing_triggers = {
                    str(tr[0])
                    for tr in cur.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='audit_log'"
                    ).fetchall()
                }
                triggers_intact = {"audit_log_no_update", "audit_log_no_delete"}.issubset(existing_triggers)

                cur.execute(f"SELECT {', '.join(select_cols)} FROM audit_log ORDER BY id ASC")
                rows = cur.fetchall()

                key_active = bool(_hmac_epochs())
                hmac_blocks = sum(
                    1 for r in rows if str(r["current_hash"] or "").startswith(HMAC_PREFIX)
                )
                try:
                    legacy_max = int(
                        os.environ.get("ARCHON_AUDIT_LEGACY_MAX_BLOCK", "0") or 0
                    )
                except ValueError:
                    legacy_max = 0

                # Audit 23.11.2026 (K-1): mit aktivem HMAC-Key duerfen keine
                # ungesalzten SHA-256-Bloecke ausserhalb des explizit markierten
                # Legacy-Bereichs liegen. Sonst kann ein Angreifer mit
                # DB-Schreibzugriff die PRAEFIXE entfernen, die Kette mit nacktem
                # SHA-256 neu signieren und erhaelt trotzdem valid=True — der
                # HMAC-Schutz waere wirkungslos (Schein-Kryptografie).
                if key_active:
                    plain_ids = [
                        int(r["id"]) for r in rows
                        if not str(r["current_hash"] or "").startswith(HMAC_PREFIX)
                        and int(r["id"]) > legacy_max
                    ]
                    if plain_ids:
                        return {
                            "valid": False,
                            "hmac_active": True,
                            "hmac_blocks": hmac_blocks,
                            "plain_sha_blocks": len(rows) - hmac_blocks,
                            "corrupted_id": plain_ids[0],
                            "reason": (
                                "HMAC-Key ist aktiv, aber Block(e) ohne HMAC-Signatur "
                                "vorhanden — moeglicher Downgrade auf nacktes SHA-256."
                            ),
                        }

                # P1: Ein HMAC-Log ohne Key ist NICHT verifizierbar. Frueher
                # fiel _chain_hash() still auf nacktes SHA-256 zurueck und
                # verify_integrity() meldete trotzdem valid=True.
                if hmac_blocks and not key_active:
                    return {
                        "valid": False,
                        "hmac_active": False,
                        "hmac_blocks": hmac_blocks,
                        "reason": (
                            "HMAC-signierte Audit-Bloecke vorhanden, aber ARCHON_AUDIT_HMAC_KEY "
                            "fehlt — Kette nicht verifizierbar (fail-closed)."
                        ),
                    }

                if not rows:
                    return {
                        "valid": True,
                        "hmac_active": key_active,
                        "total_records": 0,
                        "llm_dispatch_records": 0,
                        "genesis_hash": GENESIS_HASH,
                        "latest_hash": GENESIS_HASH,
                        "message": "Audit-Log ist leer. Keine Transaktionen vorhanden.",
                    }

                expected_prev = GENESIS_HASH
                llm_dispatch_count = 0
                chain_hashes: List[str] = []  # G: alle Head-Hashes fuer Anker-Pruefung

                for r in rows:
                    # 1. Kettenglied-Prüfung
                    if r["prev_hash"] != expected_prev:
                        return {
                            "valid": False,
                            "hmac_active": key_active,
                            "hmac_blocks": hmac_blocks,
                            "corrupted_id": r["id"],
                            "reason": f"Kettenbruch bei Block #{r['id']}: Vorheriger Hash stimmt nicht mit vorherigem Block überein.",
                            "expected_prev": expected_prev,
                            "actual_prev": r["prev_hash"],
                        }

                    # 2. Inhalts-Signatur Prüfung (HMAC-SHA256 bzw. Legacy-SHA256)
                    raw_new = (
                        f"{r['prev_hash']}|{r['timestamp']}|{r['category']}|{r['action']}|"
                        f"{r['agent_id']}|{r['company_id'] if 'company_id' in r.keys() else ''}|{r['payload_json']}"
                    )
                    raw_legacy = (
                        f"{r['prev_hash']}|{r['timestamp']}|{r['category']}|{r['action']}|"
                        f"{r['agent_id']}|{r['payload_json']}"
                    )
                    stored_hash = str(r["current_hash"] or "")
                    ok = _verify_hash(raw_new, stored_hash, r["id"])
                    if not ok and not stored_hash.startswith(HMAC_PREFIX):
                        # P1: Der Legacy-Pfad (ohne company_id im signierten
                        # String) erlaubte das Aendern der Mandantenzuordnung
                        # ohne Alarm. Er ist jetzt auf explizit markierte
                        # Alt-Bloecke begrenzt; Default 0 = nie. legacy_max
                        # wird einmalig am Anfang dieser Pruefung bestimmt.
                        if int(r["id"]) <= legacy_max:
                            ok = _verify_hash(raw_legacy, stored_hash, r["id"])

                    if not ok:
                        return {
                            "valid": False,
                            "hmac_active": key_active,
                            "hmac_blocks": hmac_blocks,
                            "corrupted_id": r["id"],
                            "reason": f"Manipulationsalarm bei Block #{r['id']}: Inhalt oder Zeitstempel weicht vom signierten Hash ab.",
                            "expected_hash": _chain_hash(raw_new, r["id"], allow_legacy=True),
                            "actual_hash": stored_hash,
                        }

                    # F-23: event_type-Spalte gegen signierte action pruefen
                    if has_event_type_col:
                        ev_type_val = str(r["event_type"] or "").strip()
                        if ev_type_val and ev_type_val != str(r["action"] or "").strip():
                            return {
                                "valid": False,
                                "hmac_active": key_active,
                                "hmac_blocks": hmac_blocks,
                                "corrupted_id": r["id"],
                                "reason": f"Spaltenmanipulation bei Block #{r['id']}: event_type ('{ev_type_val}') weicht von action ('{r['action']}') ab.",
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
                        # F-028: egress_zone ist Pflichtfeld des Beweises
                        # (S-5.2) und darf nicht leer bleiben.
                        for req_key in ("provider", "model", "target_host", "target_endpoint", "egress_zone"):
                            if not str(parsed_payload.get(req_key, "")).strip():
                                return {
                                    "valid": False,
                                    "corrupted_id": r["id"],
                                    "reason": f"Unvollständiger LLM-Dispatch-Nachweis bei Block #{r['id']}: Feld '{req_key}' fehlt.",
                                }
                        # F-028: zusaetzlich auf eine der drei definierten
                        # Zonen validieren — beliebiger/manipulierter Wert
                        # (z. B. "" oder "GARBAGE") ist kein gueltiger Nachweis.
                        zone_val = str(parsed_payload.get("egress_zone", "") or "").strip()
                        if zone_val not in {"LOCAL_ON_PREM", "INTERNAL_GATEWAY", "EXTERNAL_CLOUD"}:
                            return {
                                "valid": False,
                                "corrupted_id": r["id"],
                                "reason": (
                                    f"Ungueltige egress_zone bei LLM-Dispatch Block #{r['id']}: "
                                    f"'{zone_val}'."
                                ),
                            }
                        if has_dispatch_cols:
                            for col_key in ("provider", "model", "target_host", "target_endpoint", "egress_zone"):
                                col_val = str(r[col_key] or "")
                                pay_val = str(parsed_payload.get(col_key, "") or "")
                                if col_val != pay_val:
                                    return {
                                        "valid": False,
                                        "corrupted_id": r["id"],
                                        "reason": f"Spaltenmanipulation bei Block #{r['id']}: Indexspalte '{col_key}' ('{col_val}') weicht vom signierten Hash-Payload ('{pay_val}') ab.",
                                    }

                    chain_hashes.append(str(r["current_hash"] or ""))
                    expected_prev = r["current_hash"]

                # F-02: Signierter externer Anker + Tail-Loeschungs- & Rollback-Pruefung.
                # Format v2 (4 Spalten): ts \t block_id \t current_hash \t hmac_sig
                # Format v1 (Legacy, 2 Spalten): ts \t current_hash
                anchor_path = os.environ.get("ARCHON_AUDIT_ANCHOR_PATH", "").strip()
                anchor_ok: Optional[bool] = None
                id_to_hash = {int(r["id"]): str(r["current_hash"] or "") for r in rows}
                max_id = int(rows[-1]["id"]) if rows else 0
                prod_env = str(os.environ.get("ENVIRONMENT") or "").strip().lower()
                is_prod = prod_env in ("production", "prod", "live")
                akey = _anchor_key()
                if anchor_path and os.path.isfile(anchor_path):
                    try:
                        with open(anchor_path, "r", encoding="utf-8") as fh:
                            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
                        if lines:
                            anchor_ok = True
                            prev_anchor_id = -1
                            prev_legacy_idx = -1
                            for ln in lines:
                                parts = ln.split("\t")
                                if len(parts) >= 4:
                                    ts_val, bid_str, a_hash, a_sig = parts[0], parts[1], parts[2].strip(), parts[3].strip()
                                    try:
                                        bid = int(bid_str)
                                    except ValueError:
                                        anchor_ok = False
                                        break
                                    # Signaturpruefung (fail-closed wenn Key aktiv)
                                    if akey:
                                        exp_sig = hmac.new(
                                            akey,
                                            f"{ts_val}|{bid}|{a_hash}".encode("utf-8"),
                                            hashlib.sha256,
                                        ).hexdigest()
                                        if not a_sig or not hmac.compare_digest(exp_sig, a_sig):
                                            anchor_ok = False
                                            break
                                    elif is_prod:
                                        anchor_ok = False
                                        break
                                    # Monotonie (kein Rollback-Anhang) & Tail-Loeschung (bid > max_id)
                                    if bid < prev_anchor_id or bid > max_id:
                                        anchor_ok = False
                                        break
                                    if id_to_hash.get(bid) != a_hash:
                                        anchor_ok = False
                                        break
                                    prev_anchor_id = bid
                                else:
                                    # Legacy 2-Spalten-Anker: in Produktion unsigniert ablehnen
                                    if is_prod and key_active:
                                        anchor_ok = False
                                        break
                                    a_hash = parts[-1].strip()
                                    if a_hash not in chain_hashes:
                                        anchor_ok = False
                                        break
                                    idx = chain_hashes.index(a_hash)
                                    if idx < prev_legacy_idx:
                                        anchor_ok = False
                                        break
                                    prev_legacy_idx = idx
                    except Exception as exc:
                        logger.error("Audit-Log: Anker nicht lesbar: %s", exc)
                        anchor_ok = False
                if anchor_ok is False:
                    return {
                        "valid": False,
                        "triggers_intact": triggers_intact,
                        "corrupted_id": "audit_anchor",
                        "reason": "Externer Audit-Anker ungueltig oder weicht von der Kette ab (Tail-Loeschung, Rollback oder Signaturbruch).",
                    }
                if is_prod and not triggers_intact:
                    return {
                        "valid": False,
                        "triggers_intact": False,
                        "corrupted_id": "audit_triggers",
                        "reason": "Append-only SQLite-Trigger auf audit_log fehlen (moegliche Manipulation).",
                    }
                # Audit 23.11.2026: in Produktion ist ein fehlender/nicht
                # verifizierbarer Anker KEIN Erfolg (sonst bleibt Tail-
                # Löschung unentdeckt). Development bleibt privilegiert.
                if is_prod and anchor_ok is not True:
                    return {
                        "valid": False,
                        "triggers_intact": triggers_intact,
                        "corrupted_id": "audit_anchor",
                        "reason": "Kein verifizierbarer externer Audit-Anker in Produktion — Revisionssicherheit nicht nachweisbar.",
                    }

                return {
                    "valid": True,
                    "triggers_intact": triggers_intact,
                    "anchor_verified": anchor_ok,
                    "hmac_active": key_active,
                    "hmac_blocks": hmac_blocks,
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
        company_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Liefert gefilterte Audit-Events mit Paginierung für UI und Dashboards."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            query = "SELECT * FROM audit_log WHERE 1=1"
            params: List[Any] = []

            if company_id and str(company_id).strip():
                try:
                    from backend.tenant_context import sanitize_tenant_id
                    cid = sanitize_tenant_id(str(company_id).strip())
                except Exception:
                    cid = str(company_id).strip()
                query += " AND company_id = ?"
                params.append(cid)

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
        company_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Liefert die chronologisch neuesten kryptografisch verketteten LLM-Dispatch-Nachweise."""
        res = self.list_events(
            category="llm_dispatch",
            limit=limit,
            offset=offset,
            provider=provider,
            target_host=target_host,
            company_id=company_id,
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

    def generate_compliance_export(
        self,
        format_type: str = "json",
        company_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Generiert einen revisionssicheren Prüfbericht für GoBD / ISO 27001 Auditoren.
        Enthält alle Blöcke, die Merkle-/SHA-256-Prüfsumme, LLM-Dispatch-Nachweise und Validierungs-Signatur.
        """
        verification = self.verify_integrity()
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            # Mandantenfilter (IDOR-Schutz): ein Admin sieht nur die Blöcke
            # seines aktiven Mandanten (Audit 23.11.2026).
            if company_id and str(company_id).strip() and "company_id" in getattr(self, "cols", set()):
                try:
                    from backend.tenant_context import sanitize_tenant_id
                    cid = sanitize_tenant_id(str(company_id).strip())
                except Exception:
                    cid = str(company_id).strip()
                sql = "SELECT * FROM audit_log WHERE company_id = ? ORDER BY id ASC"
                params: tuple = (cid,)
            else:
                sql = "SELECT * FROM audit_log ORDER BY id ASC"
                params = ()
            if limit and limit > 0:
                sql += " LIMIT ?"
                params = params + (int(limit),)
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

        meta = {
            "standard": "GoBD & ISO/IEC 27001 Revisionssicherheits-Nachweis",
            "system": "Archon OS - Zero-Trust Cryptographic Ledger",
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
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
