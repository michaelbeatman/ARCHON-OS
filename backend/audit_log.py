"""
backend/audit_log.py
Archon OS 2026 - Systemweites GoBD / ISO 27001 Revisionssicheres Audit-Log (Pillar 6 Zero-Trust).
Lückenlose SHA-256 Hashverkettung für alle System-, Rollen-, API-Key-, Finanz-, E-Mail-,
Konfigurations- sowie LLM-Dispatch-Ereignisse (Provider, Modell, Ziel-Endpunkt, Ziel-Host, Egress-Zone)
mit 1-Klick Prüfer-Export (JSON/CSV) und kryptografischer Integritätsprüfung.
"""

import contextlib
import csv
import datetime
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import os
import sqlite3
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import DB_BUSY_TIMEOUT_MS
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
    DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")
    DB_BUSY_TIMEOUT_MS = 5000  # Fallback: SSOT (backend.db_paths) nicht importierbar
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

# D05/M: Platzhalter sind keine echte Versionsangabe. Ein signierter
# Dispatch-Proof mit "unknown" war bisher als vollstaendiger Nachweis
# akzeptiert — in Produktion ist das fail-closed zu behandeln.
_PLACEHOLDER_VERSIONS = frozenset(
    {"unknown", "none", "null", "n/a", "na", "-", "unspecified"}
)


def _is_placeholder_version(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return not text or text in _PLACEHOLDER_VERSIONS


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


def _anchor_key_epochs() -> list:
    """(from_block, key)-Epochen des dedizierten Anker-Keys (H-05-1).

    ``ARCHON_AUDIT_ANCHOR_KEY`` ist bewusst unabhängig vom rotierenden
    Audit-HMAC-Key: eine Audit-Key-Rotation darf historische Anker nicht
    ungültig machen. Frühere Anker-Keys stehen als JSON-Liste in
    ``ARCHON_AUDIT_ANCHOR_EPOCHS`` (Format wie ARCHON_AUDIT_HMAC_EPOCHS).
    Ohne dedicated Konfiguration greift der Audit-Key als Fallback — dann
    trägt jede Ankerzeile einen Epochen-Marker (siehe ``_anchor_signing_key``).
    """
    epochs: list = []
    raw = os.environ.get("ARCHON_AUDIT_ANCHOR_EPOCHS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data:
                    key = str(item.get("key", "")).strip().encode("utf-8")
                    if key:
                        epochs.append((int(item.get("from_block", 0)), key))
        except Exception as exc:
            logger.error("[Audit] ARCHON_AUDIT_ANCHOR_EPOCHS ungueltig: %s", exc)
    current = os.environ.get("ARCHON_AUDIT_ANCHOR_KEY", "").strip().encode("utf-8")
    if current:
        try:
            start = int(os.environ.get("ARCHON_AUDIT_ANCHOR_EPOCH_FROM", "0") or 0)
        except ValueError:
            start = 0
        epochs.append((start, current))
    by_block: Dict[int, bytes] = {}
    for start, key in epochs:
        if start in by_block and by_block[start] != key:
            logger.error("[Audit] Doppelte Anker-HMAC-Epoche fuer from_block=%s.", start)
        by_block[start] = key
    return sorted(by_block.items(), key=lambda item: item[0])


def _anchor_key() -> bytes:
    """Aktueller Anker-Key: dedizierter Key, sonst Fallback auf Audit-HMAC-Key."""
    epochs = _anchor_key_epochs()
    return epochs[-1][1] if epochs else _hmac_key()


def _anchor_key_for_epoch(epoch_from: int) -> bytes:
    """Key zum Epochen-Marker einer Ankerzeile (dediziert oder Audit-Fallback)."""
    for source in (_anchor_key_epochs(), _hmac_epochs()):
        for start, key in source:
            if start == epoch_from:
                return key
    return b""


def _anchor_known_keys() -> List[bytes]:
    """Alle bekannten Anker-Keys — für Legacy-Ankerzeilen ohne Epochen-Marker."""
    keys: List[bytes] = []
    for _start, key in (_anchor_key_epochs() or _hmac_epochs()):
        if key not in keys:
            keys.append(key)
    return keys


def _anchor_signing_key(block_id) -> Tuple[bytes, int]:
    """(Key, epoch_from) für eine neue Ankerzeile — epochenbewusst (H-05-1)."""
    epochs = _anchor_key_epochs() or _hmac_epochs()
    if not epochs:
        return b"", 0
    try:
        bid = int(block_id)
    except (TypeError, ValueError):
        bid = None
    usable = [(start, key) for start, key in epochs if bid is None or start <= bid]
    start, key = usable[-1] if usable else epochs[-1]
    return key, start


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
    geschrieben. Es gibt keinen Abschalter mehr — die fruehere Invariante
    ``sha256_dispatch_audit_enforced`` war ueber settings.json umgehbar.
    Nacktes SHA-256 ist ausschliesslich ueber explizites ``allow_legacy=True``
    im Lese-/Verify-Pfad zulaessig.
    """
    key = _key_for_block(block_id)
    if key:
        digest = hmac.new(key, raw_str.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{HMAC_PREFIX}{digest}"
    if not allow_legacy:
        raise RuntimeError(
            "[Audit] ARCHON_AUDIT_HMAC_KEY fehlt: neue Audit-Bloecke duerfen "
            "nicht mit nacktem SHA-256 geschrieben werden (HMAC-Pflicht, kein Abschalter)."
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


# d05 F-01: Der Abschalter ``sha256_dispatch_audit_enforced`` wurde aus dem
# Schreibpfad entfernt; es gibt bewusst KEINEN neuen Schalter. D01-M8: die
# Invariante ist nicht mehr eine blinde Konstante, sondern wird aus einer
# echten, isolierten Kette via ``verify_integrity()`` nachgewiesen. Damit
# schlaegt das Flag fehl, wenn der Kryptopfad manipuliert ist oder der Key
# fehlt — der Schreibpfad selbst bleibt unabhaengig davon fail-closed.
def _dispatch_audit_integrity() -> Dict[str, Any]:
    """Schreibt einen echten llm_dispatch-Block und verifiziert seine Kette."""
    try:
        with tempfile.TemporaryDirectory(prefix="archon_dispatch_audit_") as tmp_dir:
            probe = ChainedAuditLog(
                db_path=os.path.join(tmp_dir, "probe.db"),
                start_anchor=False,
            )
            event = probe.record_event(
                category="llm_dispatch",
                action="enforcement_probe",
                agent_id="system",
                payload={
                    "provider": "local-probe",
                    "model": "probe-model",
                    "target_host": "127.0.0.1",
                    "target_endpoint": "/probe",
                    "egress_zone": "LOCAL_ON_PREM",
                    "prompt_version": "v1",
                    "canary_version": "v1",
                },
            )
            status = dict(probe.verify_integrity())
            status["probe_hash"] = str(event.get("current_hash") or "")
            return status
    except Exception as exc:
        logger.error("[Audit] Dispatch-Audit-Probe fehlgeschlagen: %s", exc)
        return {
            "valid": False,
            "hmac_active": bool(_hmac_epochs()),
            "reason": f"probe_failed: {exc}",
        }


def _dispatch_audit_enforced() -> bool:
    """HMAC-Dispatch-Audit ist aktiv — aus verify_integrity() abgeleitet."""
    status = _dispatch_audit_integrity()
    return (
        bool(status.get("valid"))
        and bool(status.get("hmac_active"))
        and str(status.get("probe_hash") or "").startswith(HMAC_PREFIX)
    )


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


# D16/H4: Schluessel, unter denen ein Receipt-/Event-Kontext in Audit-Payloads
# verschachtelt geliefert wird (Background-Audits ohne Request-Kontext).
_TRACE_CONTEXT_KEYS = (
    "receipt", "event", "context", "trace_context", "trace",
    "extra", "meta", "metadata",
)


def _trace_id_from_event_context(payload: Any, _depth: int = 0) -> str:
    """Trace-ID aus einem uebergebenen Receipt/Event ziehen — nie neu erfinden.

    Background-Audits laufen ohne Request-Kontext; die W3C-ID steht dann bereits
    im Payload (direkt oder in einem verschachtelten Kontext-Dict), ggf. nur als
    ``traceparent``. Ohne Treffer bleibt der Rueckgabewert leer, damit kein
    kuenstlicher zweiter Root entsteht.
    """
    if not isinstance(payload, dict) or _depth > 2:
        return ""
    direct = str(payload.get("trace_id") or "").strip()
    if direct:
        return direct
    tp = str(payload.get("traceparent") or "").strip()
    if tp:
        try:
            from backend.trace_context import parse_traceparent
            parsed = parse_traceparent(tp)
            if parsed:
                return parsed[0]
        except Exception:
            pass
    for key in _TRACE_CONTEXT_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _trace_id_from_event_context(nested, _depth + 1)
            if found:
                return found
    return ""


def _span_id_from_event_context(
    payload: Any, expected_trace_id: str = "", _depth: int = 0
) -> str:
    """D16/M3: Span-ID aus Receipt-/Event-Kontext — nie neu erfinden.

    Analog zu :func:`_trace_id_from_event_context`. Ein ``traceparent`` wird
    nur übernommen, wenn seine Trace-ID zum schon aufgelösten Trace passt;
    sonst entstünde eine Schein-Kante in einen fremden Trace.
    """
    if not isinstance(payload, dict) or _depth > 2:
        return ""
    direct = str(payload.get("span_id") or "").strip()
    if direct:
        return direct
    tp = str(payload.get("traceparent") or "").strip()
    if tp:
        try:
            from backend.trace_context import parse_traceparent

            parsed = parse_traceparent(tp)
            if parsed and (not expected_trace_id or parsed[0] == expected_trace_id):
                return parsed[1]
        except Exception:
            pass
    for key in _TRACE_CONTEXT_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _span_id_from_event_context(nested, expected_trace_id, _depth + 1)
            if found:
                return found
    return ""


class ChainedAuditLog:
    def __init__(self, db_path: str = DB_PATH, start_anchor: bool = True):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        # W3: stoppbarer Anker-Thread. Vorher konnte der Daemon beim
        # Graceful Shutdown mitten in _write_anchor() abgebrochen werden
        # -> halb geschriebene Integritätsdatei.
        self._anchor_stop = threading.Event()
        self._init_db()
        if start_anchor:
            self._start_anchor_worker()

    def _start_anchor_worker(self) -> None:
        """Optionaler externer Anker. Läuft als Daemon-Thread und schreibt
        ausschließlich im Hintergrund — niemals im Request-Pfad und ohne
        Netzwerkzugriff (funktioniert offline und im Container)."""
        path = os.environ.get("ARCHON_AUDIT_ANCHOR_PATH", "").strip()
        if not path:
            # H-05-2: in Produktion ist "kein externes Ziel" kein neutraler
            # Zustand, sondern ein Integritätsvorfall (verify_integrity()
            # fail-closed). Hier zusätzlich laut im Log sichtbar machen.
            if _is_production() and not _allow_insecure_audit_dev():
                logger.error(
                    "[Audit] ARCHON_AUDIT_ANCHOR_PATH fehlt — externe Verankerung "
                    "in Produktion inaktiv (fail-closed via verify_integrity)."
                )
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
                # d05 F-05: Audit-Schreibfehler nie auf WARNING verschlucken.
                logger.error("Audit-Log: Anker-Schreibfehler: %s", exc)
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
        # H-05-1: Anker mit dem Key der passenden Epoche signieren und den
        # Epochen-Marker als 5. Spalte mitschreiben. Alte Anker bleiben nach
        # einer Rotation verifizierbar (analog _key_for_block).
        akey, epoch_from = _anchor_signing_key(block_id)
        sig = (
            hmac.new(akey, f"{ts}|{block_id}|{latest}".encode("utf-8"), hashlib.sha256).hexdigest()
            if akey
            else ""
        )
        line = f"{ts}\t{block_id}\t{latest}\t{sig}\t{epoch_from}\n"
        os.makedirs(os.path.dirname(os.path.abspath(anchor)), exist_ok=True)
        try:
            # H-05-2: 0600 statt umask-abhängiger Default-Rechte. DACL-Härtung
            # auf Windows erfolgt im Installer (utils/secret_files.py).
            fd = os.open(anchor, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        except OSError:
            with open(anchor, "a", encoding="utf-8") as fh:
                fh.write(line)
        else:
            with os.fdopen(fd, "a", encoding="utf-8") as fh:
                fh.write(line)
        with contextlib.suppress(OSError):
            os.chmod(anchor, 0o600)
        return latest

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
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
                        span_id TEXT DEFAULT '',
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
                    "trace_id", "span_id", "session_id", "correlation_id",
                ):
                    if dispatch_col not in existing_cols:
                        conn.execute(f"ALTER TABLE audit_log ADD COLUMN {dispatch_col} TEXT DEFAULT ''")

                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_category ON audit_log(category)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_target_host ON audit_log(target_host)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_company_id ON audit_log(company_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_trace_id ON audit_log(trace_id)")
                # D16/M3: Span→Audit direkt (ohne Join über otel_spans).
                conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_span_id ON audit_log(span_id)")
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
        span_id: str = "",
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
        from backend.trace_context import (
            current_span_id as _current_span_id,
        )
        from backend.trace_context import (
            current_trace_id as _current_trace_id,
        )

        # D16: Reihenfolge — expliziter Parameter > Receipt-/Event-Kontext >
        # aktiver Request-Kontext. Kein Fallback auf neu generierte IDs.
        _active_trace_id = str(_current_trace_id() or "").strip()
        trace_id_val = str(
            trace_id
            or _trace_id_from_event_context(safe_payload)
            or _active_trace_id
            or ""
        ).strip()
        # D16/M3: dieselbe Reihenfolge für die Span-ID. Explizit gesetzt
        # (vom geforkten Hop-Span) > Event-Kontext > aktiver Span. Ein
        # fremder aktiver Span wird nie an einen Event-Trace gehängt.
        _active_span_id = str(_current_span_id() or "").strip()
        if _active_trace_id and trace_id_val and _active_trace_id != trace_id_val:
            _active_span_id = ""
        span_id_val = str(
            span_id
            or _span_id_from_event_context(safe_payload, trace_id_val)
            or _active_span_id
            or ""
        ).strip()
        session_id_val = str(session_id or safe_payload.get("session_id") or "").strip()
        correlation_id_val = str(correlation_id or safe_payload.get("correlation_id") or "").strip()
        if trace_id_val and "trace_id" not in safe_payload:
            safe_payload["trace_id"] = trace_id_val
        # Im signierten payload_json — damit ist span_id im HMAC-Input
        # (raw_str enthält payload_str) und nicht bloss in einer Index-Spalte.
        if span_id_val and "span_id" not in safe_payload:
            safe_payload["span_id"] = span_id_val
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

        # d05 F-01: Neue Bloecke NEVER mit nacktem SHA-256 schreiben — ohne
        # HMAC-Key gilt immer fail-closed. Nacktes SHA-256 bleibt lesend auf den
        # explizit markierten legacy_max-Bereich beschraenkt (verify_integrity).
        # Ein OPT-OUT existiert nicht mehr.
        if not _hmac_epochs():
            raise RuntimeError(
                "[Audit] ARCHON_AUDIT_HMAC_KEY fehlt: neue Audit-Bloecke duerfen "
                "nicht mit nacktem SHA-256 geschrieben werden (HMAC-Pflicht, kein Abschalter)."
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
                    "span_id": span_id_val,
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
                    logger.error("Audit-Log: Rollback fehlgeschlagen: %s", exc)
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
        prompt_version: str = "",
        canary_version: str = "",
        cost_usd: Optional[float] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        trace_id: str = "",
        span_id: str = "",
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

        # d05 F-04: Prompt-/Canary-Version sind Pflichtfelder des signierten
        # Beweises. Der Dispatcher liefert sie teils unter `version_num`
        # statt `version` (D11-Key-Mismatch) — hier im Audit-Pfad normalisieren.
        info = {}
        if isinstance(extra, dict) and isinstance(extra.get("effective_prompt_info"), dict):
            info = extra["effective_prompt_info"]
        pv_raw = str(prompt_version or "").strip()
        cv_raw = str(canary_version or "").strip()
        if not pv_raw:
            pv_raw = str(info.get("version") or info.get("version_num") or "").strip()
        if not cv_raw:
            cv_raw = str(info.get("canary") or info.get("canary_version") or "").strip()
        # Zentraler Fallback: viele Aufrufer (v. a. geblockte Dispatches) haben
        # keinen Prompt-Kontext im extra-Dict — dann die aktive Registry-Version
        # nachschlagen, statt still "unknown" zu signieren.
        if not pv_raw or not cv_raw:
            try:
                from backend.prompt_registry import prompt_registry
                for v in prompt_registry.list_versions(str(agent_id or "default")):
                    if v.get("is_active"):
                        if not pv_raw:
                            pv_raw = str(v.get("version") or v.get("version_num") or "").strip()
                        if not cv_raw:
                            # canary_percentage=0 ist der Regelfall (stable),
                            # darf aber nicht als leerer Wert enden (B4).
                            c_raw = v.get("canary")
                            if c_raw is None:
                                c_raw = v.get("canary_version")
                            if c_raw is None:
                                c_raw = v.get("canary_percentage")
                            cv_raw = "stable" if c_raw is None or str(c_raw).strip() in ("", "0") else str(c_raw).strip()
                        break
            except Exception:
                pass
        # D05/H: Auch ohne Registry-Eintrag (statische Agent-Prompts, geblockte
        # Versuche) darf kein Platzhalter signiert werden — sonst bricht der
        # Dispatch unter ARCHON_AUDIT_STRICT=1 ab (B4-Nachlauf).
        if not pv_raw:
            pv_raw = "v1-static"
        if not cv_raw:
            cv_raw = "stable"
        pv = pv_raw
        cv = cv_raw
        if _is_placeholder_version(pv) or _is_placeholder_version(cv):
            logger.error(
                "[Audit] LLM-Dispatch-Proof ohne vollstaendige Prompt-/Canary-Version "
                "(agent=%s, action=%s) — 'unknown' gesetzt; Aufrufer pruefen.",
                agent_id, action,
            )
            # D05/H: fail-closed unabhaengig von ENVIRONMENT. Default
            # ARCHON_AUDIT_STRICT=1; die ausgelieferte Dev-Konfiguration darf
            # ebensowenig einen Platzhalter als GoBD-Nachweis signieren.
            if _is_audit_strict():
                raise RuntimeError(
                    "[Audit] LLM-Dispatch-Proof ohne echte Prompt-/Canary-Version "
                    f"(agent={agent_id}, action={action}) — 'unknown' ist kein Nachweis."
                )

        payload: Dict[str, Any] = {
            "provider": norm_provider,
            "model": norm_model,
            "target_endpoint": clean_ep,
            "target_host": target_host,
            "egress_zone": egress_zone,
            "data_category": str(data_category or "general"),
            "http_status": int(http_status),
            "zero_egress_active": bool(zero_egress_active),
            "prompt_version": pv,
            "canary_version": cv,
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
            span_id=span_id,
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
        with _read_snapshot(self._lock, conn):  # type: ignore[arg-type]
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
                has_correlation_cols = all(
                    c in getattr(self, "cols", set())
                    for c in ("trace_id", "span_id", "session_id", "correlation_id")
                )
                if has_correlation_cols:
                    select_cols.extend(["trace_id", "span_id", "session_id", "correlation_id"])

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
                # D05/H: Platzhalter-Versionen sind unabhängig von ENVIRONMENT
                # kein Nachweis (ARCHON_AUDIT_STRICT defaultet auf 1).
                unverified_version_blocks: List[int] = []

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

                    # 3. Nachweis- & Spaltenkonsistenz-Prüfung
                    parsed_payload: Optional[Dict[str, Any]] = None
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
                        # d05 F-04: Prompt-/Canary-Version sind seit diesem Fix
                        # Pflichtfelder. Alt-Bloecke bis legacy_max bleiben
                        # verifizierbar (default 0 = alle neuen Bloecke streng).
                        for req_key in ("prompt_version", "canary_version"):
                            req_value = str(parsed_payload.get(req_key, "") or "").strip()
                            placeholder = _is_placeholder_version(req_value)
                            if int(r["id"]) > legacy_max and (not req_value or placeholder):
                                if placeholder:
                                    unverified_version_blocks.append(int(r["id"]))
                                # D05/H: Platzhalter sind IMMER ungueltig — nicht nur
                                # in Produktion. `unverified_version_blocks` darf
                                # niemals mit valid=True einhergehen.
                                if not req_value or placeholder:
                                    return {
                                        "valid": False,
                                        "hmac_active": key_active,
                                        "hmac_blocks": hmac_blocks,
                                        "corrupted_id": r["id"],
                                        "reason": (
                                            f"Unvollständiger LLM-Dispatch-Nachweis bei Block #{r['id']}: "
                                            f"Pflichtfeld '{req_key}' "
                                            f"{f'enthält nur einen Platzhalter ({req_value})' if placeholder else 'fehlt'}."
                                        ),
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
                    elif has_dispatch_cols:
                        # D05/M: record_event() befüllt die Dispatch-Spalten
                        # kategorienunabhängig aus dem Payload. Auch z. B.
                        # rbac-/webhook-/api_keys-/chain_anchor-Blöcke müssen
                        # daher gegen ihr signiertes Payload geprüft werden.
                        try:
                            parsed_payload = json.loads(r["payload_json"])
                        except Exception:
                            parsed_payload = None

                    # D05/M: Spalten-/Payload-Konsistenz für JEDEN Block mit
                    # mindestens einer befüllten Dispatch-Spalte (nicht nur
                    # category == "llm_dispatch").
                    if has_dispatch_cols and isinstance(parsed_payload, dict):
                        dispatch_keys = (
                            "provider", "model", "target_host", "target_endpoint", "egress_zone",
                        )
                        col_values = {k: str(r[k] or "") for k in dispatch_keys}
                        if any(col_values.values()):
                            for col_key in dispatch_keys:
                                col_val = col_values[col_key]
                                pay_val = str(parsed_payload.get(col_key, "") or "")
                                if col_val != pay_val:
                                    return {
                                        "valid": False,
                                        "hmac_active": key_active,
                                        "hmac_blocks": hmac_blocks,
                                        "corrupted_id": r["id"],
                                        "reason": f"Spaltenmanipulation bei Block #{r['id']}: Indexspalte '{col_key}' ('{col_val}') weicht vom signierten Hash-Payload ('{pay_val}') ab.",
                                    }

                    # D05/MED: trace_id/session_id/correlation_id sind denormalisierte
                    # OTel-Korrelationsspalten. Sie werden signiert, aber bisher
                    # nie gegen den Payload geprüft — ein Angreifer konnte die
                    # Trace-Zuordnung ändern, ohne dass valid=False wird.
                    if has_correlation_cols:
                        if parsed_payload is None:
                            try:
                                parsed_payload = json.loads(r["payload_json"])
                            except Exception:
                                parsed_payload = None
                        if isinstance(parsed_payload, dict):
                            for col_key in ("trace_id", "session_id", "correlation_id"):
                                col_val = str(r[col_key] or "")
                                pay_val = str(parsed_payload.get(col_key, "") or "")
                                if col_val != pay_val:
                                    return {
                                        "valid": False,
                                        "hmac_active": key_active,
                                        "hmac_blocks": hmac_blocks,
                                        "corrupted_id": r["id"],
                                        "reason": f"Spaltenmanipulation bei Block #{r['id']}: Korrelationsspalte '{col_key}' ('{col_val}') weicht vom signierten Payload ('{pay_val}') ab.",
                                    }

                    chain_hashes.append(str(r["current_hash"] or ""))
                    expected_prev = r["current_hash"]

                # F-02: Signierter externer Anker + Tail-Loeschungs- & Rollback-Pruefung.
                # Format v3 (5 Spalten): ts \t block_id \t current_hash \t hmac_sig \t epoch_from
                # Format v2 (4 Spalten): ts \t block_id \t current_hash \t hmac_sig
                # Format v1 (Legacy, 2 Spalten): ts \t current_hash
                anchor_path = os.environ.get("ARCHON_AUDIT_ANCHOR_PATH", "").strip()
                anchor_ok: Optional[bool] = None
                id_to_hash = {int(r["id"]): str(r["current_hash"] or "") for r in rows}
                max_id = int(rows[-1]["id"]) if rows else 0
                known_anchor_keys = _anchor_known_keys()
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
                                    # H-05-1: v3 trägt den Epochen-Marker als 5.
                                    # Spalte — der historische Key wird
                                    # verwendet, damit Rotation alte Anker
                                    # nicht ungültig macht. v2 akzeptiert jeden
                                    # bekannten Anker-/Audit-Epochen-Key.
                                    if len(parts) >= 5:
                                        try:
                                            epoch_from = int(parts[4].strip())
                                        except ValueError:
                                            anchor_ok = False
                                            break
                                        epoch_key = _anchor_key_for_epoch(epoch_from)
                                        # Marker existiert nach einer
                                        # Konfigurationsänderung evtl. nicht mehr
                                        # exakt (z. B. EPOCH_FROM verschoben) —
                                        # dann alle bekannten Keys als Fallback,
                                        # aber nie ein unbekannter Key.
                                        candidate_keys = (
                                            [epoch_key] if epoch_key else known_anchor_keys
                                        )
                                    else:
                                        candidate_keys = known_anchor_keys
                                    if candidate_keys:
                                        msg = f"{ts_val}|{bid}|{a_hash}".encode("utf-8")
                                        signature_ok = bool(a_sig) and any(
                                            hmac.compare_digest(
                                                hmac.new(k, msg, hashlib.sha256).hexdigest(), a_sig
                                            )
                                            for k in candidate_keys
                                        )
                                        if not signature_ok:
                                            anchor_ok = False
                                            break
                                    elif not _allow_insecure_audit_dev():
                                        # Ohne bekannten Key ist eine signierte
                                        # Ankerzeile nicht pruefbar.
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
                                    # D05/H: Legacy-2-Spalten-Anker (unsigniert)
                                    # sind bei aktivem HMAC-Key nie ein Nachweis.
                                    if key_active and not _allow_insecure_audit_dev():
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
                # H-05-2: externer Anker ist Produktions-Default. Ohne Ziel
                # fail-closed statt inaktiv — kein stilles "valid=True".
                if _is_production() and not anchor_path and not _allow_insecure_audit_dev():
                    return {
                        "valid": False,
                        "triggers_intact": triggers_intact,
                        "corrupted_id": "audit_anchor",
                        "reason": "Kein externer Audit-Anker konfiguriert — Produktion fail-closed.",
                    }
                # D05/H: Strukturprüfungen unbedingt, also ohne is_prod.
                # Einziger (laut geloggter) Ausweg: explizites
                # ARCHON_ALLOW_INSECURE_AUDIT_DEV=1 — in Produktion wirkungslos.
                if not triggers_intact and not _allow_insecure_audit_dev():
                    return {
                        "valid": False,
                        "triggers_intact": False,
                        "corrupted_id": "audit_triggers",
                        "reason": "Append-only SQLite-Trigger auf audit_log fehlen (moegliche Manipulation).",
                    }
                # D05/H: Auf der produktiven Zentral-DB ist ein fehlender externer
                # Anker KEIN Erfolg — auf isolierten tmp_path-Test-DBs ohne
                # Anker-Datei wird nur eine vorhandene/gebrochene Anker-Datei
                # (anchor_ok is False) abgewiesen.
                if (
                    anchor_ok is not True
                    and not _allow_insecure_audit_dev()
                    and (os.path.abspath(self.db_path) == os.path.abspath(DB_PATH))
                ):
                    return {
                        "valid": False,
                        "triggers_intact": triggers_intact,
                        "corrupted_id": "audit_anchor",
                        "reason": "Kein verifizierbarer externer Audit-Anker — Revisionssicherheit nicht nachweisbar.",
                    }

                return {
                    "valid": True,
                    "triggers_intact": triggers_intact,
                    "anchor_verified": anchor_ok,
                    "hmac_active": key_active,
                    "hmac_blocks": hmac_blocks,
                    "total_records": len(rows),
                    "llm_dispatch_records": llm_dispatch_count,
                    # D05/M: auch ausserhalb Produktion sichtbar machen, wie viele
                    # Dispatch-Proofs nur Platzhalter-Versionen tragen.
                    "unverified_version_blocks": sorted(set(unverified_version_blocks)),
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


# ---------------------------------------------------------------------------
# d05 F-03: signierte Head-Anker + Append-only-Trigger-Pruefung fuer die
# sechs Nebenketten. Anker liegen in der ZENTRALEN (HMAC-geschuetzten,
# append-only) audit_log — damit kann jemand mit Schreibzugriff auf eine
# Nebenkette den Tail nicht unbemerkt loeschen.
# ---------------------------------------------------------------------------
CHAIN_ANCHOR_CATEGORY = "chain_anchor"

# chain -> (Tabelle, Hash-Spalte, Sortierspalte)
SECONDARY_CHAIN_HEADS = {
    "api_key_audit_log": ("api_key_audit_log", "block_hash", "id"),
    "approval_policy_audit_chain": ("approval_policy_audit_chain", "current_hash", "id"),
    "treasury_transactions": ("treasury_transactions", "entry_hash", "rowid"),
    "email_draft_audit_log": ("email_draft_audit_log", "block_hash", "id"),
    "gdpr_audit_log": ("gdpr_audit_log", "hash", "id"),
    "execution_receipts_ledger": ("execution_receipts_ledger", "receipt_hash", "id"),
}

# chain -> zwingend vorhandene Append-only-Trigger
SECONDARY_CHAIN_TRIGGERS = {
    "api_key_audit_log": ("api_key_audit_no_update", "api_key_audit_no_delete"),
    "approval_policy_audit_chain": ("approval_chain_no_hash_update", "approval_chain_no_delete"),
    "treasury_transactions": ("treasury_tx_no_tamper", "treasury_tx_no_delete"),
    "email_draft_audit_log": ("email_draft_audit_no_update", "email_draft_audit_no_delete"),
    "gdpr_audit_log": ("gdpr_audit_no_update", "gdpr_audit_no_delete"),
    "execution_receipts_ledger": (
        "execution_receipts_no_update", "execution_receipts_no_delete",
        "execution_receipt_bypass_no_update", "execution_receipt_bypass_no_delete",
    ),
}


def _is_production() -> bool:
    return str(os.environ.get("ENVIRONMENT") or "").strip().lower() in ("production", "prod", "live")


def _is_audit_strict() -> bool:
    """D05/H: Fail-Closed-Platzhalterpruefung — Default AN, unabhaengig von ENVIRONMENT.

    Die ausgelieferte Konfiguration defaultet auf ``development``; dort durfte
    bisher ein ``"unknown"``-Proof signiert werden. ``ARCHON_AUDIT_STRICT=0``
    ist der einzige explizite Opt-out und wird nie aus ENVIRONMENT abgeleitet.
    """
    raw = str(os.environ.get("ARCHON_AUDIT_STRICT", "1") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "none"}


def _allow_insecure_audit_dev() -> bool:
    """D05/H: expliziter, laut geloggter Dev-Opt-out fuer Strukturpruefungen.

    In Produktion greift der Opt-out nie (fail-closed).
    """
    raw = str(os.environ.get("ARCHON_ALLOW_INSECURE_AUDIT_DEV", "") or "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return False
    if _is_production():
        logger.error(
            "[Audit] ARCHON_ALLOW_INSECURE_AUDIT_DEV wird in Produktion ignoriert "
            "(fail-closed)."
        )
        return False
    logger.warning(
        "[Audit] ARCHON_ALLOW_INSECURE_AUDIT_DEV=1: Trigger-/Anker-Strukturpruefungen "
        "sind deaktiviert — keine Revisionssicherheit in diesem Prozess."
    )
    return True


def _secondary_db_path(chain: str, db_path: Optional[str] = None) -> str:
    """Nebenketten liegen meist in agentic_memory.db — Treasury in treasury.db."""
    if db_path:
        return db_path
    if chain == "treasury_transactions":
        try:
            from backend.db_paths import resolve_db
            return resolve_db("treasury.db")
        except Exception:
            return os.path.join(WORKSPACE_DIR, "data", "treasury.db")
    return DB_PATH


def get_chain_anchors(
    chain: str, limit: int = 20, *, db_path: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Liefert die letzten gespeicherten Head-Anker (neueste zuerst) aus der Zentralkette.

    D05-Testisolierung: Anker werden pro Quell-DB gefiltert. Ohne diesen Filter
    vergleicht eine isolierte Test-DB ihren 1-Block-Stand mit den Ankern der
    produktiven Zentral-DB (=> falscher "Tail-Loeschung"-Alarm). Legacy-Anker
    ohne ``db_path`` bleiben für den Default-Pfad der Kette akzeptiert.
    """
    anchors: List[Dict[str, Any]] = []
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    expected_db = os.path.abspath(db_path) if db_path else ""
    try:
        rows = conn.execute(
            "SELECT id, payload_json FROM audit_log WHERE category=? AND action='chain_head_anchor' ORDER BY id DESC LIMIT ?",
            (CHAIN_ANCHOR_CATEGORY, max(1, int(limit) * 40)),
        ).fetchall()
        for r in rows:
            try:
                p = json.loads(r["payload_json"])
            except Exception:
                continue
            if str(p.get("chain", "")) != chain:
                continue
            anchor_db = str(p.get("db_path") or "")
            if expected_db:
                if anchor_db:
                    if os.path.abspath(anchor_db) != expected_db:
                        continue
                elif expected_db != os.path.abspath(_secondary_db_path(chain)):
                    continue
            anchors.append({
                "id": int(r["id"]),
                "head": str(p.get("head", "") or ""),
                "count": int(p.get("count", 0) or 0),
                "db_path": anchor_db,
            })
            if len(anchors) >= int(limit):
                break
    except Exception as exc:
        logger.error("[Audit] Head-Anker fuer %s nicht lesbar (fail-closed): %s", chain, exc)
    finally:
        conn.close()
    return anchors


def get_chain_anchor(chain: str, *, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    # Rückwärtskompatibel zu Aufrufern, die get_chain_anchors() mit der
    # alten 2-Argument-Signatur monkeypatchen (z. B. tests/test_reaudit_stage5).
    anchors = (
        get_chain_anchors(chain, limit=1)
        if db_path is None
        else get_chain_anchors(chain, limit=1, db_path=db_path)
    )
    return anchors[0] if anchors else None


def record_chain_anchor(
    chain: str, head: str, count: int, *, db_path: Optional[str] = None
) -> Dict[str, Any]:
    """Schreibt einen signierten Head-Anker in die Zentralkette (idempotent bei unveraendertem Head)."""
    existing = get_chain_anchor(chain) if db_path is None else get_chain_anchor(chain, db_path=db_path)
    if existing and existing["head"] == str(head or "") and existing["count"] == int(count):
        return {"chain": chain, "written": False, "head": existing["head"], "count": existing["count"]}
    # R-B/D05 (Re-Audit): frueher wurde jeder abweichende Head bedingungslos
    # neu verankert. Eine Tail-Loeschung war damit nach einem 30-s-Loop
    # "gewaschen" und fuer den Verify-Endpoint unsichtbar. Jetzt fail-closed:
    # kein kuerzerer Count, kein Head-Wechsel bei gleichem Count.
    if existing:
        old_count = int(existing.get("count") or 0)
        old_head = str(existing.get("head") or "")
        new_count = int(count)
        new_head = str(head or "")
        if new_count < old_count or (new_count == old_count and new_head != old_head):
            logger.error(
                "[Audit] Chain-Head-Anker-Verletzung fuer %s: count %s -> %s, head %s -> %s",
                chain, old_count, new_count, old_head[:16], new_head[:16],
            )
            try:
                chained_audit_log.record_event(
                    category=CHAIN_ANCHOR_CATEGORY,
                    action="chain_anchor_violation",
                    agent_id="system",
                    payload={
                        "chain": chain,
                        "expected_count": old_count,
                        "expected_head": old_head,
                        "observed_count": new_count,
                        "observed_head": new_head,
                    },
                )
            except Exception as exc:
                logger.error("[Audit] Signiertes Anker-Verletzungs-Event fehlgeschlagen: %s", exc)
            return {
                "chain": chain, "written": False, "violation": True,
                "head": new_head, "count": new_count,
                "expected_head": old_head, "expected_count": old_count,
            }
    ev = chained_audit_log.record_event(
        category=CHAIN_ANCHOR_CATEGORY,
        action="chain_head_anchor",
        agent_id="system",
        payload={
            "chain": chain,
            "head": str(head or ""),
            "count": int(count),
            "db_path": str(db_path or ""),
        },
    )
    return {"chain": chain, "written": True, "head": str(head or ""), "count": int(count), "event_id": ev.get("event_id")}


def _secondary_chain_hashes(chain: str, db_path: Optional[str] = None) -> List[str]:
    spec = SECONDARY_CHAIN_HEADS.get(chain)
    if not spec:
        return []
    table, hash_col, order_col = spec
    conn = sqlite3.connect(_secondary_db_path(chain, db_path), timeout=10.0)
    try:
        has_tbl = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not has_tbl:
            return []
        rows = conn.execute(
            f"SELECT {hash_col} FROM {table} ORDER BY {order_col} ASC"
        ).fetchall()
        return [str(r[0] or "") for r in rows]
    finally:
        conn.close()


def get_secondary_chain_head(chain: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    hashes = _secondary_chain_hashes(chain, db_path=db_path)
    return {"chain": chain, "head": hashes[-1] if hashes else "", "count": len(hashes)}


def anchor_secondary_chains(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Wird aus dem 30-s-Loop aufgerufen: verankert alle sechs Nebenketten-Heads."""
    result: Dict[str, Any] = {}
    for chain in SECONDARY_CHAIN_HEADS:
        try:
            head_info = get_secondary_chain_head(chain, db_path=db_path)
            result[chain] = record_chain_anchor(
                chain, head_info["head"], head_info["count"],
                db_path=_secondary_db_path(chain, db_path),
            )
        except Exception as exc:
            # Audit-Schreibfehler niemals verschlucken (d05 F-05).
            logger.error("[Audit] Head-Anker %s fehlgeschlagen: %s", chain, exc)
            result[chain] = {"chain": chain, "written": False, "error": type(exc).__name__}
    return result


def finalize_secondary_chain_verification(
    chain: str,
    result: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Ergänzt ein verify-Result um Head-Anker- und Trigger-Pruefung (fail-closed in Produktion)."""
    if not isinstance(result, dict):
        return result
    # Receipt-Ledger liefert `chain_valid` statt `valid` — auf einen gemeinsamen
    # Schluessel normalisieren und am Ende beide zurueckschreiben.
    if "valid" not in result and "chain_valid" in result:
        result["valid"] = bool(result["chain_valid"])
    hashes = _secondary_chain_hashes(chain, db_path=db_path)
    count = len(hashes)
    head = hashes[-1] if hashes else ""

    anchors = get_chain_anchors(chain, limit=1, db_path=db_path)
    anchor_verified: Optional[bool] = None
    anchor_reason: Optional[str] = None
    if anchors:
        stored = anchors[0]
        stored_count = int(stored["count"])
        stored_head = str(stored["head"])
        if stored_count > count:
            anchor_verified = False
            anchor_reason = (
                f"Head-Anker von {chain} meldet {stored_count} Bloecke, Kette hat aber nur "
                f"{count} — Tail-Loeschung."
            )
        elif stored_count > 0 and hashes[stored_count - 1] != stored_head:
            anchor_verified = False
            anchor_reason = (
                f"Head-Anker von {chain} stimmt nicht mit Block {stored_count} der Kette "
                "ueberein — Rollback oder nachtraegliche Neu-Signatur."
            )
        else:
            anchor_verified = True

    # Append-only-Trigger muessen physisch existieren (sqlite_master).
    triggers_intact: Optional[bool] = None
    missing: List[str] = []
    try:
        conn = sqlite3.connect(_secondary_db_path(chain, db_path), timeout=10.0)
        try:
            spec = SECONDARY_CHAIN_HEADS.get(chain)
            table_exists = bool(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (spec[0],)
            ).fetchone()) if spec else False
            existing = {
                str(tr[0]) for tr in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                ).fetchall()
            }
        finally:
            conn.close()
        if table_exists:
            missing = [t for t in SECONDARY_CHAIN_TRIGGERS.get(chain, ()) if t not in existing]
            triggers_intact = not missing
        else:
            # Tabelle (noch) nicht vorhanden: kein Trigger-Check moeglich, aber
            # auch kein Manipulationsrisiko. Prod-Anker-Regel greift weiterhin.
            triggers_intact = None
    except Exception as exc:
        logger.error("[Audit] Trigger-Pruefung %s fehlgeschlagen (fail-closed): %s", chain, exc)
        triggers_intact = False
        missing = ["<unlesbar>"]

    result["count"] = count
    result["latest_hash"] = head
    result["anchor_verified"] = anchor_verified
    result["triggers_intact"] = triggers_intact
    result["missing_triggers"] = missing
    if result.get("valid") is True:
        if triggers_intact is False:
            result["valid"] = False
            result["reason"] = f"Append-only-Trigger fehlen bei {chain}: {missing}"
        elif anchor_verified is False:
            result["valid"] = False
            result["reason"] = anchor_reason or f"Head-Anker von {chain} weicht ab."
        elif _is_production() and count > 0 and anchor_verified is not True:
            result["valid"] = False
            result["reason"] = f"Kein verifizierbarer Head-Anker fuer {chain} in Produktion."
    if "chain_valid" in result:
        result["chain_valid"] = result["valid"]
    return result


# ---------------------------------------------------------------------------
# F024: einheitlicher Pflicht-Audit-Helper für sicherheitsrelevante Pfade.
# Schreibfehler werden nie verschluckt; der Aufrufer entscheidet über die
# fail-closed-Reaktion (typisch: ARCHON_AUDIT_STRICT=1 => HTTP 503 / deny).
# ---------------------------------------------------------------------------
def is_audit_strict() -> bool:
    """Öffentliche Lesart des Strict-Flags (Default AN)."""
    return _is_audit_strict()


def audit_actor_context(*, ip_address: str = "", user_agent: str = "") -> Dict[str, str]:
    """Hashes für IP/User-Agent — keine Klartext-PII in signierten Payloads."""
    salt = _hmac_key() or b"archon-audit-context"
    def _digest(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return hmac.new(salt, text.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return {
        "client_ip_hash": _digest(ip_address),
        "user_agent_hash": _digest(user_agent),
    }


def _require_audit_event(
    category: str,
    action: str,
    agent_id: str,
    payload: Dict[str, Any],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Pflicht-Event: bei Schreibfehler immer RuntimeError('audit_write_failed')."""
    try:
        return chained_audit_log.record_event(
            category=category,
            action=action,
            agent_id=agent_id,
            payload=payload,
            **kwargs,
        )
    except Exception as exc:
        logger.error("[Audit] Pflicht-Event %s/%s fehlgeschlagen: %s", category, action, exc)
        raise RuntimeError("audit_write_failed") from exc


# Singleton Instanz
chained_audit_log = ChainedAuditLog()
