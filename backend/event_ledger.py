"""M112: Unveraenderliches Event-Ledger mit verifizierbarer Hash-Kette.

Das Ledger ist eine *eigene* SQLite-DB (``ledger_events``), getrennt von der
bestehenden ``audit_log``-Tabelle. Es ergaenzt die HMAC-Kette, ersetzt sie
nicht: Block-Signatur und Verifikation laufen ueber die additiven Bruecken in
``backend.audit_log`` (``ledger_block_hash`` / ``ledger_verify_block_hash``).

Garantien:
  * atomare Vor-/Nach-Eintraege je fachlicher Transaktion (BEGIN/COMMIT/ABORT),
    alle Schreibvorgänge unter ``BEGIN IMMEDIATE`` in WAL mit synchronous=FULL;
  * Append-only ueber SQLite-Trigger (kein UPDATE, kein DELETE) — ein Crash
    hinterlaesst einen ``pending``-Eintrag, der beim Oeffnen durch einen
    nachgetragenen ``aborted``-Eintrag aufgeloest wird;
  * periodischer Merkle-Root ueber alle noch nicht verankerten Bloecke mit
    Anker-Adapter (Datei / WORM-Datei / optional externer Timestamp-Dienst);
  * ``verify_ledger()`` prueft Kette, Luecken, Transaktionsstruktur, Trigger
    und Anker; ``replay()`` liefert einen fail-closed Compliance-Replay (M68).

Es gibt bewusst keinen Schalter, der Verification oder Anker-Pflicht
abschaltet. Fehlende Anker und fehlgeschlagene Anker-Schreibvorgänge sind
sichtbar (``ledger_anchor_failures``) und machen die Verification ungueltig,
sobald ein Anker konfiguriert ist.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from backend.db_paths import DB_BUSY_TIMEOUT_MS, DB_BUSY_TIMEOUT_S

logger = logging.getLogger("archon.event_ledger")

GENESIS_HASH = "0" * 64

PHASE_BEGIN = "begin"
PHASE_COMMIT = "commit"
PHASE_ABORT = "abort"
STATUS_PENDING = "pending"
STATUS_COMMITTED = "committed"
STATUS_ABORTED = "aborted"

_EVENTS_TABLE = "ledger_events"
_ANCHORS_TABLE = "ledger_anchors"
_FAILURES_TABLE = "ledger_anchor_failures"
_TABLES = (_EVENTS_TABLE, _ANCHORS_TABLE, _FAILURES_TABLE)

_SENSITIVE_KEY_PARTS = (
    "password", "passphrase", "secret", "token", "api_key", "apikey",
    "private_key", "authorization", "credential", "cookie", "signature",
)


class LedgerError(RuntimeError):
    """Basisfehler des Event-Ledgers."""


class LedgerConfigurationError(LedgerError):
    """Konfiguration fehlt (z. B. HMAC-Key) — Schreiben ist gesperrt."""


class LedgerStateError(LedgerError):
    """Ungueltiger Transaktionszustand (z. B. doppelter Commit)."""


class AnchorError(LedgerError):
    """Anker konnte nicht geschrieben oder nicht verifiziert werden."""


class AnchorStoreError(AnchorError):
    """Fehler im konkreten Anker-Adapter."""


def _now() -> str:
    """UTC-Zeitstempel mit Offset (GoBD-konform, deterministisch sortierbar)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _is_production() -> bool:
    return str(os.environ.get("ENVIRONMENT") or "").strip().lower() in ("production", "prod", "live")


def _redact(value: Any, depth: int = 0) -> Any:
    """Entfernt Klartext-Secrets aus signierten Payloads und Responses."""
    if depth > 8:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).lower()
            if any(part in name for part in _SENSITIVE_KEY_PARTS):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = _redact(item, depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in list(value)[:100]]
    if isinstance(value, str):
        return value if len(value) <= 4096 else value[:4096] + "...[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:256]


def _normalize_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return dict(payload) if isinstance(payload, dict) else {}


def _hash_input(
    prev_hash: str,
    timestamp: str,
    seq: int,
    transaction_id: str,
    phase: str,
    status: str,
    event_type: str,
    actor: str,
    payload_json: str,
) -> str:
    """Eindeutige, deterministische HMAC-Eingabe (keine Trennzeichen-Ambigueitaet)."""
    return json.dumps(
        [
            prev_hash, timestamp, seq, transaction_id, phase, status,
            event_type, actor, payload_json,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _sign(raw: str, block_id: int) -> str:
    """Signatur ueber die SSOT-HMAC-Kette — fail-closed ohne Key."""
    from backend.audit_log import ledger_block_hash

    try:
        return ledger_block_hash(raw, block_id)
    except Exception as exc:
        raise LedgerConfigurationError(
            "HMAC-Key fehlt: Event-Ledger schreibt keine Bloecke ohne Signatur."
        ) from exc


def _verify(raw: str, stored: str, block_id: int) -> bool:
    """Verifikation ueber die SSOT-HMAC-Kette — fail-closed ohne passenden Key."""
    from backend.audit_log import ledger_verify_block_hash

    try:
        return bool(ledger_verify_block_hash(raw, stored, block_id))
    except Exception as exc:
        logger.error("[EventLedger] HMAC-Verifikation fehlgeschlagen: %s", exc)
        return False


def compute_merkle_root(hashes: Sequence[str]) -> str:
    """Merkle-Root ueber Batch-Hashes (unpaarige Ebene: letztes Blatt duplizieren).

    Ein leerer Batch ergibt bewusst den Genesis-Hash und niemals einen
    stillen "Erfolg" mit einem nicht nachvollziehbaren Root.
    """
    if not hashes:
        return GENESIS_HASH
    level = [hashlib.sha256(str(item).encode("utf-8")).digest() for item in hashes]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [
            hashlib.sha256(level[index] + level[index + 1]).digest()
            for index in range(0, len(level), 2)
        ]
    return level[0].hex()


@dataclass(frozen=True)
class LedgerEvent:
    """Unveraenderlicher Ledger-Eintrag."""

    id: int
    timestamp: str
    transaction_id: str
    seq: int
    phase: str
    status: str
    event_type: str
    actor: str
    payload: Dict[str, Any]
    prev_hash: str
    current_hash: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "transaction_id": self.transaction_id,
            "seq": self.seq,
            "phase": self.phase,
            "status": self.status,
            "event_type": self.event_type,
            "actor": self.actor,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "current_hash": self.current_hash,
        }


@dataclass(frozen=True)
class AnchorRecord:
    """Persistierter Merkle-Anker."""

    id: int
    timestamp: str
    merkle_root: str
    first_event_id: int
    last_event_id: int
    event_count: int
    store: str
    external_ref: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "merkle_root": self.merkle_root,
            "first_event_id": self.first_event_id,
            "last_event_id": self.last_event_id,
            "event_count": self.event_count,
            "store": self.store,
            "external_ref": self.external_ref,
        }


class AnchorStore(Protocol):
    """Schnittstelle fuer WORM-Datei, Timestamping und Blockchain-Anchor.

    ``mode='offline'`` bedeutet, dass der Anker bei der Verification erneut
    gelesen und gegen den Merkle-Root geprueft wird. Bei ``mode='delegated'``
    bestaetigt ein externer Dienst ausserhalb des Prozesses; der gespeicherte
    Referenzwert wird dann als Nachweis ausgewiesen, aber nicht still als
    offline verifiziert markiert.
    """

    name: str
    mode: str

    def write(
        self, merkle_root: str, first_event_id: int, last_event_id: int, event_count: int
    ) -> str: ...

    def read(self, merkle_root: str) -> Optional[str]: ...


class FileAnchorStore:
    """Anker in einer JSONL-Datei oder als unveraenderliche Einzeldokumente.

    ``worm=True`` erzeugt pro Merkle-Root eine Datei mit O_EXCL und 0400;
    ein erneuter Schreibversuch mit gleichem Root ist idempotent, eine
    Aenderung eines bestehenden Ankers ist nicht moeglich.

    Einschaenkung: unter Windows ersetzt O_EXCL/0400 kein echtes WORM-Storage
    (Dateiattribute sind umgehbar). Fuer compliance-relevante Unveraenderlichkeit
    ist ein dedizierter WORM-/Timestamping-Adapter zu konfigurieren.
    """

    def __init__(self, path: str | Path, *, worm: bool = False) -> None:
        self.path = Path(path)
        self.worm = bool(worm)
        self.name = "worm-file" if worm else "file"
        self.mode = "offline"

    def _worm_path(self, merkle_root: str) -> Path:
        return self.path.parent / f"{self.path.stem}-{merkle_root}.anchor.json"

    def _lines(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        entries: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(parsed, dict):
                        entries.append(parsed)
        except OSError as exc:
            raise AnchorStoreError(f"Ankerdatei nicht lesbar: {exc}") from exc
        return entries

    def write(
        self, merkle_root: str, first_event_id: int, last_event_id: int, event_count: int
    ) -> str:
        record = {
            "merkle_root": merkle_root,
            "first_event_id": first_event_id,
            "last_event_id": last_event_id,
            "event_count": event_count,
            "timestamp": _now(),
        }
        blob = json.dumps(record, sort_keys=True, ensure_ascii=False)
        try:
            if self.worm:
                target = self._worm_path(merkle_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    return target.name  # identischer Root: idempotent, nie ueberschreiben
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(blob + "\n")
                with contextlib.suppress(OSError):
                    os.chmod(str(target), 0o400)
                return target.name
            os.makedirs(os.path.dirname(os.path.abspath(str(self.path))), exist_ok=True)
            if any(str(e.get("merkle_root") or "") == merkle_root for e in self._lines()):
                return str(self.path)
            fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(blob + "\n")
            with contextlib.suppress(OSError):
                os.chmod(str(self.path), 0o600)
            return str(self.path)
        except AnchorStoreError:
            raise
        except OSError as exc:
            raise AnchorStoreError(f"Anker-Schreibfehler ({self.name}): {exc}") from exc

    def read(self, merkle_root: str) -> Optional[str]:
        if self.worm:
            target = self._worm_path(merkle_root)
            if not target.is_file():
                return None
            try:
                with open(target, "r", encoding="utf-8") as handle:
                    parsed = json.loads(handle.readline() or "{}")
            except (OSError, ValueError) as exc:
                raise AnchorStoreError(f"WORM-Anker nicht lesbar: {exc}") from exc
            return target.name if str(parsed.get("merkle_root") or "") == merkle_root else None
        for entry in self._lines():
            if str(entry.get("merkle_root") or "") == merkle_root:
                return str(self.path)
        return None


class CallbackAnchorStore:
    """Optionaler externer Anker (RFC 3161 Timestamping / Blockchain).

    Der Callback bekommt ausschliesslich den 64-Zeichen-Merkle-Root — keine
    Payloads, keine Secrets, keine Netzwerkzugriffe durch das Ledger selbst.
    """

    def __init__(
        self, callback: Callable[[str], str], *, name: str = "external"
    ) -> None:
        if not callable(callback):
            raise AnchorStoreError("Externer Anker bentigt einen aufrufbaren Callback.")
        self._callback = callback
        self.name = name
        self.mode = "delegated"

    def write(
        self, merkle_root: str, first_event_id: int, last_event_id: int, event_count: int
    ) -> str:
        try:
            reference = str(self._callback(merkle_root) or "").strip()
        except Exception as exc:
            raise AnchorStoreError(f"Externer Anker fehlgeschlagen: {exc}") from exc
        if not reference:
            raise AnchorStoreError("Externer Anker lieferte keine Referenz.")
        return reference[:512]

    def read(self, merkle_root: str) -> Optional[str]:
        # Externe Dienste sind nicht offline lesbar: der gespeicherte Ref wird
        # in der Verification als 'delegated' ausgewiesen, nie als offline geprueft.
        return None


def anchor_store_from_env() -> Optional[AnchorStore]:
    """Baut den konfigurierten Datei-/WORM-Adapter (leer = kein Anker)."""
    path = str(os.environ.get("ARCHON_EVENT_LEDGER_ANCHOR_PATH") or "").strip()
    if not path:
        return None
    worm = str(os.environ.get("ARCHON_EVENT_LEDGER_ANCHOR_WORM") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    return FileAnchorStore(path, worm=worm)


def default_ledger_path() -> str:
    """Heimatpfad ueber die SSOT; kein stilles Fallback auf fremde Leer-DBs."""
    try:
        from backend.db_paths import resolve_db

        return resolve_db("event_ledger.db")
    except Exception:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "data", "event_ledger.db")


class EventLedger:
    """Append-only Event-Sourcing-Ledger mit HMAC-Kette und Merkle-Ankern."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        *,
        anchor_store: Optional[AnchorStore] = None,
        auto_recover: bool = True,
    ) -> None:
        self.db_path = os.path.abspath(str(db_path or default_ledger_path()))
        self._anchor_store = anchor_store
        self._lock = threading.RLock()
        self._recovery_error: Optional[str] = None
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        if auto_recover:
            try:
                self.recover_pending()
            except Exception as exc:
                # Kein stilzes Verlieren: der Fehler erscheint in status()/verify().
                self._recovery_error = str(exc)
                logger.error("[EventLedger] Crash-Recovery fehlgeschlagen: %s", exc)

    @property
    def anchor_store(self) -> Optional[AnchorStore]:
        """Explizit gesetzter oder per ENV konfigurierter Anker-Adapter."""
        return self._anchor_store or anchor_store_from_env()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=DB_BUSY_TIMEOUT_S)
        conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS};")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            if str(os.environ.get("ARCHON_DISABLE_WAL") or "").strip().lower() not in (
                "1", "true", "yes",
            ):
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                except sqlite3.Error as exc:
                    logger.warning("[EventLedger] WAL nicht aktivierbar: %s", exc)
            # FULL statt NORMAL: ein abgebrochener Prozess darf keinen halben
            # Transaktions-Eintrag hinterlassen.
            conn.execute("PRAGMA synchronous=FULL;")
            with conn:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {_EVENTS_TABLE} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        transaction_id TEXT NOT NULL,
                        seq INTEGER NOT NULL CHECK(seq >= 0),
                        phase TEXT NOT NULL CHECK(phase IN ('begin','commit','abort')),
                        status TEXT NOT NULL CHECK(status IN ('pending','committed','aborted')),
                        event_type TEXT NOT NULL,
                        actor TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        prev_hash TEXT NOT NULL,
                        current_hash TEXT NOT NULL
                    )
                """)
                conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_ledger_events_tx "
                    f"ON {_EVENTS_TABLE}(transaction_id, seq)"
                )
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {_ANCHORS_TABLE} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        merkle_root TEXT NOT NULL UNIQUE,
                        first_event_id INTEGER NOT NULL,
                        last_event_id INTEGER NOT NULL,
                        event_count INTEGER NOT NULL,
                        store TEXT NOT NULL,
                        external_ref TEXT NOT NULL
                    )
                """)
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {_FAILURES_TABLE} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        merkle_root TEXT NOT NULL,
                        last_event_id INTEGER NOT NULL,
                        reason TEXT NOT NULL
                    )
                """)
                for table in _TABLES:
                    conn.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_update "
                        f"BEFORE UPDATE ON {table} BEGIN "
                        f"SELECT RAISE(ABORT, '{table} is append-only'); END"
                    )
                    conn.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete "
                        f"BEFORE DELETE ON {table} BEGIN "
                        f"SELECT RAISE(ABORT, '{table} is append-only'); END"
                    )
        finally:
            conn.close()

    def _row_to_event(self, row: sqlite3.Row) -> LedgerEvent:
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except ValueError:
            payload = {}
        return LedgerEvent(
            id=int(row["id"]),
            timestamp=str(row["timestamp"] or ""),
            transaction_id=str(row["transaction_id"] or ""),
            seq=int(row["seq"] or 0),
            phase=str(row["phase"] or ""),
            status=str(row["status"] or ""),
            event_type=str(row["event_type"] or ""),
            actor=str(row["actor"] or ""),
            payload=payload if isinstance(payload, dict) else {},
            prev_hash=str(row["prev_hash"] or ""),
            current_hash=str(row["current_hash"] or ""),
        )

    def _insert_event(
        self,
        cur: sqlite3.Cursor,
        *,
        transaction_id: str,
        seq: int,
        phase: str,
        status: str,
        event_type: str,
        actor: str,
        payload: Optional[Dict[str, Any]],
    ) -> LedgerEvent:
        """Fuegt einen Block in einer bereits offenen IMMEDIATE-Transaktion ein."""
        payload_str = json.dumps(
            _redact(_normalize_payload(payload)),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        timestamp = _now()
        last = cur.execute(
            f"SELECT current_hash FROM {_EVENTS_TABLE} ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = str(last["current_hash"] or GENESIS_HASH) if last else GENESIS_HASH
        block_id = int(cur.execute(
            f"SELECT COALESCE(MAX(id), 0) + 1 FROM {_EVENTS_TABLE}"
        ).fetchone()[0])
        raw = _hash_input(
            prev_hash, timestamp, seq, transaction_id, phase, status,
            event_type, actor, payload_str,
        )
        current_hash = _sign(raw, block_id)
        cur.execute(
            f"INSERT INTO {_EVENTS_TABLE} "
            "(id, timestamp, transaction_id, seq, phase, status, event_type, actor, "
            "payload_json, prev_hash, current_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                block_id, timestamp, transaction_id, seq, phase, status, event_type,
                actor, payload_str, prev_hash, current_hash,
            ),
        )
        return LedgerEvent(
            id=block_id,
            timestamp=timestamp,
            transaction_id=transaction_id,
            seq=seq,
            phase=phase,
            status=status,
            event_type=event_type,
            actor=actor,
            payload=_redact(_normalize_payload(payload)),
            prev_hash=prev_hash,
            current_hash=current_hash,
        )

    def _check_transaction_open(self, cur: sqlite3.Cursor, transaction_id: str) -> int:
        """Erwartet genau einen offenen BEGIN und liefert die naechste seq."""
        rows = cur.execute(
            f"SELECT seq, phase FROM {_EVENTS_TABLE} WHERE transaction_id=? ORDER BY id ASC",
            (transaction_id,),
        ).fetchall()
        if not rows or int(rows[0]["seq"]) != 0 or str(rows[0]["phase"]) != PHASE_BEGIN:
            raise LedgerStateError("Kein gueltiger BEGIN-Eintrag fuer diese Transaktion.")
        if any(str(r["phase"]) in (PHASE_COMMIT, PHASE_ABORT) for r in rows):
            raise LedgerStateError("Transaktion ist bereits abgeschlossen (append-only).")
        return len(rows)

    def _append(
        self,
        *,
        transaction_id: str,
        seq: int,
        phase: str,
        status: str,
        event_type: str,
        actor: str,
        payload: Optional[Dict[str, Any]],
        require_open: bool = False,
    ) -> LedgerEvent:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                expected_seq = self._check_transaction_open(cur, transaction_id) if require_open else seq
                if require_open and expected_seq != seq:
                    raise LedgerStateError("Unerwartete Event-Sequenz innerhalb der Transaktion.")
                event = self._insert_event(
                    cur,
                    transaction_id=transaction_id,
                    seq=seq,
                    phase=phase,
                    status=status,
                    event_type=event_type,
                    actor=actor,
                    payload=payload,
                )
                conn.commit()
                return event
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def begin_transaction(
        self,
        *,
        event_type: str,
        actor: str,
        payload: Optional[Dict[str, Any]] = None,
        transaction_id: Optional[str] = None,
    ) -> LedgerEvent:
        """Schreibt den atomaren Vor-Eintrag (status=pending)."""
        tx_id = str(transaction_id or uuid.uuid4().hex)
        return self._append(
            transaction_id=tx_id,
            seq=0,
            phase=PHASE_BEGIN,
            status=STATUS_PENDING,
            event_type=event_type,
            actor=actor,
            payload=payload,
        )

    def commit_transaction(
        self,
        transaction_id: str,
        *,
        actor: str,
        event_type: str = "transaction_commit",
        payload: Optional[Dict[str, Any]] = None,
    ) -> LedgerEvent:
        """Schreibt den Nach-Eintrag (status=committed); kein UPDATE des BEGIN."""
        return self._append(
            transaction_id=transaction_id,
            seq=1,
            phase=PHASE_COMMIT,
            status=STATUS_COMMITTED,
            event_type=event_type,
            actor=actor,
            payload=payload,
            require_open=True,
        )

    def abort_transaction(
        self,
        transaction_id: str,
        *,
        actor: str,
        event_type: str = "transaction_abort",
        payload: Optional[Dict[str, Any]] = None,
    ) -> LedgerEvent:
        """Schreibt den Nach-Eintrag (status=aborted); kein UPDATE des BEGIN."""
        return self._append(
            transaction_id=transaction_id,
            seq=1,
            phase=PHASE_ABORT,
            status=STATUS_ABORTED,
            event_type=event_type,
            actor=actor,
            payload=payload,
            require_open=True,
        )

    @contextlib.contextmanager
    def transaction(
        self,
        *,
        event_type: str,
        actor: str,
        payload: Optional[Dict[str, Any]] = None,
        transaction_id: Optional[str] = None,
    ) -> Iterator[str]:
        """Komfort-Pfad: Commit bei Erfolg, Abort bei Exception."""
        tx_id = self.begin_transaction(
            event_type=event_type, actor=actor, payload=payload, transaction_id=transaction_id
        ).transaction_id
        try:
            yield tx_id
        except BaseException as exc:
            self.abort_transaction(
                tx_id, actor=actor, payload={"reason": type(exc).__name__}
            )
            raise
        self.commit_transaction(tx_id, actor=actor)

    def recover_pending(self, *, reason: str = "crash_recovery") -> int:
        """Traegt fuer jeden BEGIN ohne Nach-Eintrag einen ABORT nach.

        Alle Nachtraege laufen in *einer* ``BEGIN IMMEDIATE``-Transaktion und
        nutzen dieselbe HMAC-Kette. Der BEGIN bleibt unveraendert bestehen —
        die Recovery ist selbst ein signierter Ledger-Eintrag.
        """
        with self._lock:
            conn = self._connect()
            recovered = 0
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                begins = cur.execute(
                    f"SELECT id, transaction_id, actor FROM {_EVENTS_TABLE} "
                    f"WHERE phase=? ORDER BY id ASC",
                    (PHASE_BEGIN,),
                ).fetchall()
                for row in begins:
                    tx_id = str(row["transaction_id"])
                    terminal = cur.execute(
                        f"SELECT 1 FROM {_EVENTS_TABLE} "
                        f"WHERE transaction_id=? AND phase IN (?, ?) LIMIT 1",
                        (tx_id, PHASE_COMMIT, PHASE_ABORT),
                    ).fetchone()
                    if terminal:
                        continue
                    seq = self._check_transaction_open(cur, tx_id)
                    self._insert_event(
                        cur,
                        transaction_id=tx_id,
                        seq=seq,
                        phase=PHASE_ABORT,
                        status=STATUS_ABORTED,
                        event_type="crash_recovery",
                        actor=str(row["actor"] or "system"),
                        payload={"reason": reason, "recovered_begin_id": int(row["id"])},
                    )
                    recovered += 1
                conn.commit()
                if recovered:
                    logger.warning("[EventLedger] %s offene Transaktion(en) abgebrochen.", recovered)
                return recovered
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _unanchored_events(self, cur: sqlite3.Cursor) -> List[sqlite3.Row]:
        last = cur.execute(
            f"SELECT MAX(last_event_id) AS last_id FROM {_ANCHORS_TABLE}"
        ).fetchone()
        last_id = int(last["last_id"] or 0) if last else 0
        rows = cur.execute(
            f"SELECT * FROM {_EVENTS_TABLE} WHERE id > ? ORDER BY id ASC", (last_id,)
        ).fetchall()
        return list(rows)

    def _record_anchor_failure(
        self, merkle_root: str, last_event_id: int, reason: str
    ) -> None:
        """Failed-closed sichtbar machen —nie still einen Anker verlieren."""
        try:
            with self._lock:
                conn = self._connect()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        f"INSERT INTO {_FAILURES_TABLE} "
                        "(timestamp, merkle_root, last_event_id, reason) VALUES (?, ?, ?, ?)",
                        (_now(), merkle_root, last_event_id, reason[:1000]),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()
        except Exception as exc:
            logger.error("[EventLedger] Ankerfehler-Event nicht schreibbar: %s", exc)

    def anchor_batch(self, store: Optional[AnchorStore] = None) -> Optional[AnchorRecord]:
        """Verankert alle noch nicht verankerten Bloecke als Merkle-Root."""
        adapter = store or self.anchor_store
        merkle_root = ""
        last_id = 0
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                rows = self._unanchored_events(cur)
                if not rows:
                    conn.rollback()
                    return None
                merkle_root = compute_merkle_root([str(r["current_hash"]) for r in rows])
                existing = cur.execute(
                    f"SELECT * FROM {_ANCHORS_TABLE} WHERE merkle_root=?", (merkle_root,)
                ).fetchone()
                if existing:
                    conn.rollback()
                    return self._row_to_anchor(existing)
                first_id = int(rows[0]["id"])
                last_id = int(rows[-1]["id"])
                if adapter is None:
                    raise AnchorError(
                        "Kein Anker-Adapter konfiguriert — Merkle-Root nicht verankert."
                    )
                try:
                    reference = adapter.write(merkle_root, first_id, last_id, len(rows))
                except Exception as exc:
                    raise AnchorError(f"Anker-Schreibfehler ({adapter.name}): {exc}") from exc
                timestamp = _now()
                cur.execute(
                    f"INSERT INTO {_ANCHORS_TABLE} "
                    "(timestamp, merkle_root, first_event_id, last_event_id, event_count, "
                    "store, external_ref) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        timestamp, merkle_root, first_id, last_id, len(rows),
                        adapter.name, reference,
                    ),
                )
                anchor = AnchorRecord(
                    id=int(cur.lastrowid or 0),
                    timestamp=timestamp,
                    merkle_root=merkle_root,
                    first_event_id=first_id,
                    last_event_id=last_id,
                    event_count=len(rows),
                    store=adapter.name,
                    external_ref=reference,
                )
                conn.commit()
                return anchor
            except Exception as exc:
                conn.rollback()
                # Fehler darf nicht im DB-Only landen: er wird zusaetzlich als
                # eigener, unveraenderlicher Eintrag sichtbar gemacht.
                if isinstance(exc, AnchorError):
                    self._record_anchor_failure(merkle_root, last_id, str(exc))
                    raise
                wrapped = AnchorError(str(exc))
                self._record_anchor_failure(merkle_root, last_id, str(wrapped))
                raise wrapped from exc
            finally:
                conn.close()

    def _row_to_anchor(self, row: sqlite3.Row) -> AnchorRecord:
        return AnchorRecord(
            id=int(row["id"]),
            timestamp=str(row["timestamp"] or ""),
            merkle_root=str(row["merkle_root"] or ""),
            first_event_id=int(row["first_event_id"]),
            last_event_id=int(row["last_event_id"]),
            event_count=int(row["event_count"]),
            store=str(row["store"] or ""),
            external_ref=str(row["external_ref"] or ""),
        )

    def status(self) -> Dict[str, Any]:
        """Kompakter Zustand fuer /status — ohne Payload-Daten."""
        conn = self._connect()
        try:
            total = int(conn.execute(f"SELECT COUNT(*) FROM {_EVENTS_TABLE}").fetchone()[0])
            # Offene Transaktionen = BEGIN ohne nachfolgenden COMMIT/ABORT.
            # Der BEGIN bleibt unveraenderlich 'pending' — deshalb
            # zaehlen wir nicht die Zeilen, sondern die Transaktionen.
            pending = int(conn.execute(
                f"SELECT COUNT(*) FROM {_EVENTS_TABLE} AS e "
                f"WHERE e.phase=? AND NOT EXISTS ("
                f"SELECT 1 FROM {_EVENTS_TABLE} AS t "
                "WHERE t.transaction_id=e.transaction_id "
                "AND t.phase IN (?, ?))",
                (PHASE_BEGIN, PHASE_COMMIT, PHASE_ABORT),
            ).fetchone()[0])
            anchor_count = int(conn.execute(
                f"SELECT COUNT(*) FROM {_ANCHORS_TABLE}"
            ).fetchone()[0])
            failure_count = int(conn.execute(
                f"SELECT COUNT(*) FROM {_FAILURES_TABLE}"
            ).fetchone()[0])
            last_event = conn.execute(
                f"SELECT id, current_hash FROM {_EVENTS_TABLE} ORDER BY id DESC LIMIT 1"
            ).fetchone()
            last_anchor = conn.execute(
                f"SELECT id, merkle_root, last_event_id FROM {_ANCHORS_TABLE} "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        adapter = self.anchor_store
        return {
            "status": "ok",
            "total_events": total,
            "pending_events": pending,
            "anchor_count": anchor_count,
            "anchor_failure_count": failure_count,
            "latest_event_id": int(last_event["id"]) if last_event else 0,
            "latest_hash": str(last_event["current_hash"]) if last_event else GENESIS_HASH,
            "genesis_hash": GENESIS_HASH,
            "last_anchor": {
                "id": int(last_anchor["id"]),
                "merkle_root": str(last_anchor["merkle_root"]),
                "last_event_id": int(last_anchor["last_event_id"]),
            } if last_anchor else None,
            "anchor_store": adapter.name if adapter else None,
            "anchor_mode": adapter.mode if adapter else None,
            "hmac_active": self._hmac_active(),
            "recovery_error": self._recovery_error,
        }

    def verify_ledger(
        self, *, store: Optional[AnchorStore] = None, require_anchor: Optional[bool] = None
    ) -> Dict[str, Any]:
        """Vollpruefung: Kette, Luecken, Transaktionen, Trigger und Anker.

        Liefert immer ein Dict mit ``valid``; bei Abweichungen ``issues`` und
        ``reason``. Es werden keine Daten geschrieben (reine Lesepruefung).
        """
        issues: List[Dict[str, Any]] = []
        adapter = store or self.anchor_store
        hmac_active = self._hmac_active()
        hmac_prefix = self._hmac_prefix()

        def fail(code: str, reason: str, **extra: Any) -> Dict[str, Any]:
            issue = {"code": code, "reason": reason}
            issue.update(extra)
            issues.append(issue)
            return issue

        conn = self._connect()
        try:
            with self._lock:
                conn.execute("BEGIN")
            try:
                cur = conn.cursor()
                rows = list(cur.execute(f"SELECT * FROM {_EVENTS_TABLE} ORDER BY id ASC"))
                expected_prev = GENESIS_HASH
                expected_id = 1
                for row in rows:
                    block_id = int(row["id"])
                    if block_id != expected_id:
                        fail(
                            "gap",
                            f"Luecke in der Kette: erwartete Block-ID {expected_id}, "
                            f"gefunden {block_id}.",
                            corrupted_id=block_id,
                        )
                    if str(row["prev_hash"] or "") != expected_prev:
                        fail(
                            "chain_break",
                            f"Kettenbruch bei Block #{block_id}: prev_hash weicht ab.",
                            corrupted_id=block_id,
                        )
                    stored_hash = str(row["current_hash"] or "")
                    if hmac_active and not stored_hash.startswith(hmac_prefix):
                        fail(
                            "hmac_downgrade",
                            f"Block #{block_id} ohne HMAC-Signatur bei aktivem Key "
                            "(Downgrade auf nacktes SHA-256).",
                            corrupted_id=block_id,
                        )
                    raw = _hash_input(
                        str(row["prev_hash"] or ""),
                        str(row["timestamp"] or ""),
                        int(row["seq"]),
                        str(row["transaction_id"] or ""),
                        str(row["phase"] or ""),
                        str(row["status"] or ""),
                        str(row["event_type"] or ""),
                        str(row["actor"] or ""),
                        str(row["payload_json"] or ""),
                    )
                    if not _verify(raw, stored_hash, block_id):
                        fail(
                            "manipulation",
                            f"Manipulationsalarm bei Block #{block_id}: "
                            "Inhalt weicht vom signierten HMAC ab.",
                            corrupted_id=block_id,
                        )
                    if str(row["phase"]) not in (PHASE_BEGIN, PHASE_COMMIT, PHASE_ABORT) or str(
                        row["status"]
                    ) not in (STATUS_PENDING, STATUS_COMMITTED, STATUS_ABORTED):
                        fail(
                            "invalid_state",
                            f"Unzulaessiger Zustand in Block #{block_id}.",
                            corrupted_id=block_id,
                        )
                    expected_prev = str(row["current_hash"] or "")
                    expected_id = block_id + 1

                # Transaktionsstruktur: genau ein BEGIN (seq 0), hoechstens ein
                # Terminaleintrag (seq 1), keine Eintraege danach.
                transactions: Dict[str, List[LedgerEvent]] = {}
                for row in rows:
                    event = self._row_to_event(row)
                    transactions.setdefault(event.transaction_id, []).append(event)
                for tx_id, events in transactions.items():
                    if events[0].phase != PHASE_BEGIN or events[0].seq != 0:
                        fail(
                            "transaction_structure",
                            "Transaktion ohne gueltigen BEGIN-Eintrag.",
                            transaction_id=tx_id,
                        )
                    terminal = [e for e in events if e.phase in (PHASE_COMMIT, PHASE_ABORT)]
                    if len(terminal) > 1:
                        fail(
                            "transaction_structure",
                            "Mehrere Abschluss-Eintraege fuer eine Transaktion.",
                            transaction_id=tx_id,
                        )
                    if len(events) > (2 if terminal else 1):
                        fail(
                            "transaction_structure",
                            "Eintraege nach dem Abschluss der Transaktion.",
                            transaction_id=tx_id,
                        )
                    for index, event in enumerate(events):
                        if event.seq != index:
                            fail(
                                "transaction_gap",
                                f"Lueckige Event-Sequenz bei {tx_id[:16]}: "
                                f"erwartet {index}, gefunden {event.seq}.",
                                transaction_id=tx_id,
                            )

                if self._recovery_error:
                    fail("recovery", f"Crash-Recovery fehlgeschlagen: {self._recovery_error}")

                # Anker: Root ueber den exakt verankerten ID-Bereich nachrechnen.
                anchors = [
                    self._row_to_anchor(row)
                    for row in cur.execute(
                        f"SELECT * FROM {_ANCHORS_TABLE} ORDER BY id ASC"
                    )
                ]
                previous_last = 0
                for anchor in anchors:
                    covered = [
                        str(r["current_hash"]) for r in rows
                        if anchor.first_event_id <= int(r["id"]) <= anchor.last_event_id
                    ]
                    if (
                        anchor.first_event_id != previous_last + 1
                        or len(covered) != anchor.event_count
                        or compute_merkle_root(covered) != anchor.merkle_root
                    ):
                        fail(
                            "anchor_mismatch",
                            "Merkle-Anker passt nicht zum verankerten Blockbereich.",
                            anchor_id=anchor.id,
                        )
                    if adapter is not None and adapter.mode == "offline":
                        reference = adapter.read(anchor.merkle_root)
                        if not reference:
                            fail(
                                "anchor_missing",
                                "Externer Merkle-Anker fehlt oder ist unlesbar.",
                                anchor_id=anchor.id,
                            )
                    if not anchor.external_ref:
                        fail(
                            "anchor_ref_missing",
                            "Anker-Eintrag ohne externe Referenz.",
                            anchor_id=anchor.id,
                        )
                    previous_last = anchor.last_event_id

                # Fehlgeschlagene Anker muessen durch einen spaeteren Anker
                # ueberdeckt sein — sonst bleibt der Vorfall sichtbar/ungueltig.
                for failure in cur.execute(
                    f"SELECT * FROM {_FAILURES_TABLE} ORDER BY id ASC"
                ):
                    covered_again = any(
                        anchor.last_event_id >= int(failure["last_event_id"])
                        for anchor in anchors
                    )
                    if not covered_again:
                        fail(
                            "anchor_failure",
                            f"Ankerfehler nicht nachgeholt: {str(failure['reason'])[:200]}",
                            failure_id=int(failure["id"]),
                        )

                missing_triggers = [
                    f"{table}_{suffix}"
                    for table in _TABLES
                    for suffix in ("no_update", "no_delete")
                    if not cur.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=?",
                        (f"{table}_{suffix}",),
                    ).fetchone()
                ]
                if missing_triggers:
                    fail(
                        "append_only",
                        "Append-only-Trigger fehlen: " + ", ".join(missing_triggers),
                    )

                needs_anchor = (
                    require_anchor
                    if require_anchor is not None
                    else (adapter is not None or _is_production())
                )
                if needs_anchor and rows and not anchors:
                    fail(
                        "anchor_required",
                        "Kein verifizierbarer Merkle-Anker fuer vorhandene Ledger-Eintraege.",
                    )

                valid = not issues
                return {
                    "valid": valid,
                    "total_events": len(rows),
                    "total_transactions": len(transactions),
                    "genesis_hash": GENESIS_HASH,
                    "latest_hash": expected_prev,
                    "hmac_active": hmac_active,
                    "anchors_verified": (
                        not any(i["code"].startswith("anchor") for i in issues)
                        if anchors else None
                    ),
                    "anchor_count": len(anchors),
                    "issues": issues,
                    "pending_transactions": sum(
                        1 for events in transactions.values()
                        if not any(e.phase in (PHASE_COMMIT, PHASE_ABORT) for e in events)
                    ),
                    "reason": issues[0]["reason"] if issues else "",
                    "message": (
                        "Event-Ledger intakt ("
                        f"{len(rows)} Eintraege, {len(transactions)} Transaktionen)."
                        if valid
                        else "Event-Ledger nicht verifizierbar: " + issues[0]["reason"]
                    ),
                }
            finally:
                conn.rollback()
        finally:
            conn.close()

    @staticmethod
    def _hmac_active() -> bool:
        from backend.audit_log import ledger_hmac_active

        try:
            return bool(ledger_hmac_active())
        except Exception:
            return False

    @staticmethod
    def _hmac_prefix() -> str:
        from backend.audit_log import HMAC_PREFIX

        return HMAC_PREFIX

    def replay(
        self,
        *,
        from_block: int = 1,
        to_block: Optional[int] = None,
        limit: Optional[int] = None,
        include_pending: bool = False,
        store: Optional[AnchorStore] = None,
    ) -> Dict[str, Any]:
        """Compliance-Replay (M68) in der Reihenfolge der finalen Eintraege.

        Bei ungueltiger Verification wird NICHT replayt (fail-closed).
        """
        verification = self.verify_ledger(store=store)
        if not verification.get("valid"):
            return {
                "status": "invalid",
                "valid": False,
                "transactions": [],
                "issues": verification.get("issues", []),
                "reason": verification.get("reason", ""),
            }
        conn = self._connect()
        try:
            sql = f"SELECT * FROM {_EVENTS_TABLE} WHERE id >= ?"
            params: List[Any] = [max(1, int(from_block))]
            if to_block is not None:
                sql += " AND id <= ?"
                params.append(int(to_block))
            sql += " ORDER BY id ASC"
            rows = list(conn.execute(sql, params))
        finally:
            conn.close()

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            event = self._row_to_event(row).to_dict()
            grouped.setdefault(str(event["transaction_id"]), []).append(event)

        replayed: List[Dict[str, Any]] = []
        for tx_id, events in grouped.items():
            terminal = [e for e in events if e.get("phase") in (PHASE_COMMIT, PHASE_ABORT)]
            if not terminal and not include_pending:
                continue
            final = terminal[0] if terminal else events[0]
            replayed.append({
                "transaction_id": tx_id,
                "status": final["status"],
                "finalized_at_block": final["id"],
                "started_at_block": events[0]["id"],
                "event_count": len(events),
                "events": events,
            })
        replayed.sort(key=lambda item: (int(item["finalized_at_block"]), item["transaction_id"]))
        if limit is not None:
            replayed = replayed[:max(0, int(limit))]
        return {
            "status": "ok",
            "valid": True,
            "from_block": max(1, int(from_block)),
            "to_block": int(to_block) if to_block is not None else None,
            "replayed_transactions": len(replayed),
            "replayed_events": sum(int(item["event_count"]) for item in replayed),
            "transactions": replayed,
        }


# Modul-Level-Singleton wird bewusst NICHT angelegt: der Router injiziert die
# Instanz per configure(), damit Tests und Integration eigene DB-Pfade nutzen.
_ANCHOR_WORKER: Dict[str, Any] = {"stopper": None, "thread": None}


def start_anchor_worker(interval_sec: float = 60.0) -> Callable[[], None]:
    """Startet den periodischen Merkle-Anker als daemonischen Hintergrund-Thread.

    Ein laufender Worker wird nicht dupliziert; die zurueckgegebene Funktion
    stoppt ihn (Join mit Timeout). Ohne konfigurierten Adapter wird der Lauf
    uebersprungen — die Verification bleibt dann bewusst fail-closed (M112).
    """
    existing_stopper = _ANCHOR_WORKER.get("stopper")
    existing_thread = _ANCHOR_WORKER.get("thread")
    if existing_thread is not None and existing_thread.is_alive() and existing_stopper is not None:
        return existing_stopper

    stop = threading.Event()
    delay = max(1.0, float(interval_sec or 60.0))

    def _loop() -> None:
        while not stop.is_set():
            try:
                ledger = EventLedger()
                if ledger.anchor_store is None:
                    logger.debug(
                        "[EventLedger] Kein Anker-Adapter konfiguriert — "
                        "periodischer Anker uebersprungen (Verification fail-closed)."
                    )
                else:
                    ledger.anchor_batch()
            except Exception as exc:
                # Fehlschlaege sind zusaetzlich in ledger_anchor_failures sichtbar.
                logger.warning("[EventLedger] Periodischer Anker fehlgeschlagen: %s", exc)
            stop.wait(delay)

    def _stop() -> None:
        stop.set()
        thread.join(timeout=5.0)

    thread = threading.Thread(target=_loop, daemon=True, name="m112-anchor-worker")
    _ANCHOR_WORKER["stopper"] = _stop
    _ANCHOR_WORKER["thread"] = thread
    thread.start()
    return _stop


def stop_anchor_worker() -> None:
    """Stoppt den periodischen Anker (Shutdown-Hook)."""
    stopper = _ANCHOR_WORKER.get("stopper")
    if stopper is not None:
        stopper()
    thread = _ANCHOR_WORKER.get("thread")
    if thread is not None:
        thread.join(timeout=5.0)
    _ANCHOR_WORKER["stopper"] = None
    _ANCHOR_WORKER["thread"] = None
