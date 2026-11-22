# -*- coding: utf-8 -*-
"""
backend/offline_memory_vault.py
===============================
Meilenstein 79: Lokaler verschluesselter Offline-Memory-Vault
(compartment-Pattern als Zero-Egress-Ergaenzung zu Obsidian).

Eigenschaften:
- 100 % offline, kein API-Key, kein Netzwerkzugriff
- AEAD-Authentifizierte Verschluesselung (SHA-256-CTR + HMAC-SHA256 EtM)
  fuer Inhalt und lokale Hybrid-Suchvektoren in SQLite WAL

Batch C: Agent-Memory-Scope (private/shared/project/global) mit ACL und TTL.
Die Scope-Konstanten spiegeln bewusst die kanonischen Werte aus
backend.core_memory_manager (kein Import, um dessen DB-Init beim Import zu vermeiden).
"""

from __future__ import annotations
import logging
_archon_exc_logger = logging.getLogger("offline_memory_vault")

from contextlib import contextmanager
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sqlite3
import time
from typing import Any, Dict, Iterator, List, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "compartment_vault.db")
DEFAULT_KEY_PATH = os.path.join(WORKSPACE_DIR, "data", "compartment.key")
VEC_DIM = 64
_AESGCM_MAGIC = b"AGCM1"

# Kanonische Scopes (Spiegelung aus core_memory_manager.py).
SCOPE_PRIVATE = "private"
SCOPE_SHARED = "shared"
SCOPE_PROJECT = "project"
SCOPE_GLOBAL = "global"
VALID_MEMORY_SCOPES = (SCOPE_PRIVATE, SCOPE_SHARED, SCOPE_PROJECT, SCOPE_GLOBAL)


def normalize_scope(scope: Optional[str]) -> str:
    """Validiert einen Scope und liefert den kanonischen Wert (leer => global)."""
    if scope is None or str(scope).strip() == "":
        return SCOPE_GLOBAL
    value = str(scope).strip().lower()
    if value not in VALID_MEMORY_SCOPES:
        raise ValueError(
            f"Ungueltiger Memory-Scope: {scope!r} "
            f"(erlaubt: {', '.join(VALID_MEMORY_SCOPES)})"
        )
    return value


def _normalize_acl(acl: Optional[Any]) -> List[str]:
    """Akzeptiert JSON-String, Liste/Tuple/Set oder ein einzelnes Principal."""
    if not acl:
        return []
    if isinstance(acl, str):
        try:
            acl = json.loads(acl)
        except (ValueError, TypeError):
            return []
    if isinstance(acl, (list, tuple, set)):
        return [str(x) for x in acl if x is not None and str(x)]
    return [str(acl)]


def _expires_from_ttl(ttl_seconds: Optional[float]) -> float:
    """REAL-Zeitstempel aus TTL; 0 bedeutet 'kein Ablauf'."""
    if ttl_seconds is None:
        return 0.0
    try:
        ttl = float(ttl_seconds)
    except (TypeError, ValueError):
        return 0.0
    return time.time() + ttl if ttl > 0 else 0.0


def _is_expired(expires_at: Optional[float]) -> bool:
    """True, wenn der REAL-Zeitstempel in der Vergangenheit liegt."""
    try:
        value = float(expires_at or 0.0)
    except (TypeError, ValueError):
        return False
    return value > 0 and value <= time.time()


def _row_is_visible(
    row: Any,
    agent_id: str,
    project_id: str = "",
    scope_filter: Optional[str] = None,
) -> bool:
    """Sichtbarkeitsregel analog zu core_memory_manager (Scope/ACL/TTL/Legacy)."""
    try:
        data = dict(row)
    except (TypeError, ValueError):
        return False

    if _is_expired(data.get("expires_at")):
        return False

    raw_scope = str(data.get("scope") or "").strip().lower()
    row_scope = raw_scope if raw_scope in VALID_MEMORY_SCOPES else SCOPE_GLOBAL
    if scope_filter is not None and row_scope != normalize_scope(scope_filter):
        return False

    owner = str(data.get("agent_id") or "global")
    requester = str(agent_id or "global")
    acl = _normalize_acl(data.get("acl_json"))

    if row_scope == SCOPE_PRIVATE:
        return requester == owner
    if row_scope == SCOPE_SHARED:
        return requester == owner or requester in acl
    if row_scope == SCOPE_PROJECT:
        row_project = str(data.get("project_id") or "")
        return (bool(project_id) and project_id == row_project) or requester == owner

    # explizit global => fuer alle sichtbar; migrierte Legacy-Zeilen behalten
    # die bisherige agent_id-Regel als Fallback.
    if int(data.get("scope_explicit") or 0) == 1:
        return True
    return owner == "global" or requester == owner


def load_or_create_vault_key(key_path: Optional[str] = None) -> bytes:
    env_hex = (os.environ.get("COMPARTMENT_VAULT_KEY") or "").strip()
    if env_hex:
        return hashlib.sha256(env_hex.encode("utf-8")).digest()
    path = key_path or DEFAULT_KEY_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        with open(path, "rb") as f:
            raw = f.read().strip()
            if len(raw) >= 32:
                return raw[:32]
    key = secrets.token_bytes(32)
    with open(path, "wb") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError as _exc:
        _archon_exc_logger.debug("[offline_memory_vault] Ignorierte Ausnahme (Z.53): %s", _exc)
    return key


def _legacy_keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        blk = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
        out.extend(blk)
        counter += 1
    return bytes(out[:length])


def aead_encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    """Authentifizierte Verschluesselung mit Standard AES-256-GCM."""
    aes_key = hashlib.sha256(key + b"aes256gcm").digest()
    nonce = secrets.token_bytes(12)
    ct = AESGCM(aes_key).encrypt(nonce, plaintext, aad or None)
    return _AESGCM_MAGIC + nonce + ct


def aead_decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    """Entschluesselt AES-256-GCM Blobs (und abwaertskompatibel Legacy-Blobs)."""
    if blob.startswith(_AESGCM_MAGIC):
        if len(blob) < len(_AESGCM_MAGIC) + 12 + 16:
            raise ValueError("Ungueltiges AES-GCM Ciphertext-Format.")
        aes_key = hashlib.sha256(key + b"aes256gcm").digest()
        nonce = blob[len(_AESGCM_MAGIC):len(_AESGCM_MAGIC) + 12]
        ct = blob[len(_AESGCM_MAGIC) + 12:]
        try:
            return AESGCM(aes_key).decrypt(nonce, ct, aad or None)
        except Exception as exc:
            raise ValueError("AEAD-Integritaetspruefung fehlgeschlagen (Manipulation oder falscher Key).") from exc

    # Abwaertskompatibilitaet fuer bestehende Legacy-Eintraege vor AES-256-GCM-Migration
    if len(blob) < 48:
        raise ValueError("Ungueltiges AEAD-Ciphertext-Format.")
    enc_key = hashlib.sha256(key + b"enc").digest()
    mac_key = hashlib.sha256(key + b"mac").digest()
    nonce, tag, ct = blob[:16], blob[16:48], blob[48:]
    expected = hmac.new(mac_key, aad + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("AEAD-Integritaetspruefung fehlgeschlagen (Manipulation oder falscher Key).")
    ks = _legacy_keystream(enc_key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks))


def _local_embed(text: str) -> List[float]:
    """Deterministisches lokales Offline-Hashing-Embedding (64-dim) ohne Netz/API."""
    vec = [0.0] * VEC_DIM
    tokens = re.findall(r"[a-zA-Z0-9äöüß_-]{2,}", (text or "").lower())
    for tok in tokens:
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=4).digest(), "big")
        vec[h % VEC_DIM] += 1.0
        for i in range(max(0, len(tok) - 2)):
            trigram = tok[i:i + 3]
            hg = int.from_bytes(hashlib.blake2b(trigram.encode("utf-8"), digest_size=4).digest(), "big")
            vec[hg % VEC_DIM] += 0.5
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 5) for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


_VAULT_COLUMNS = (
    ("scope", "TEXT DEFAULT 'global'"),
    ("acl_json", "TEXT DEFAULT '[]'"),
    ("expires_at", "REAL DEFAULT 0"),
    ("project_id", "TEXT DEFAULT ''"),
    ("agent_id", "TEXT DEFAULT 'global'"),
    ("scope_explicit", "INTEGER DEFAULT 0"),
)
_VAULT_SELECT = (
    "id, namespace, cipher_blob, created_at, scope, acl_json, expires_at, "
    "project_id, agent_id, scope_explicit"
)


@contextmanager
def _connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or DEFAULT_DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10.0)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vault_entries (
                id TEXT PRIMARY KEY,
                namespace TEXT NOT NULL,
                cipher_blob BLOB NOT NULL,
                created_at REAL NOT NULL,
                scope TEXT DEFAULT 'global',
                acl_json TEXT DEFAULT '[]',
                expires_at REAL DEFAULT 0,
                project_id TEXT DEFAULT '',
                agent_id TEXT DEFAULT 'global',
                scope_explicit INTEGER DEFAULT 0
            )
        """)
        # Migration bestehender DBs (alte Zeilen behalten scope='global' => Legacy-Verhalten).
        for col, cdef in _VAULT_COLUMNS:
            try:
                conn.execute(f"ALTER TABLE vault_entries ADD COLUMN {col} {cdef}")
            except sqlite3.OperationalError as _exc:
                _archon_exc_logger.debug("[offline_memory_vault] Ignorierte Ausnahme (Z.150): %s", _exc)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_vault_ns ON vault_entries(namespace)")
        conn.commit()
        yield conn
    finally:
        conn.close()


def store_memory(
    namespace: str,
    content: str,
    tags: Optional[List[str]] = None,
    db_path: Optional[str] = None,
    key: Optional[bytes] = None,
    *,
    scope: str = SCOPE_GLOBAL,
    acl: Optional[Any] = None,
    ttl_seconds: Optional[float] = None,
    agent_id: str = "global",
    project_id: str = "",
) -> str:
    """Speichert einen Eintrag; Scope/ACL/TTL sind rueckwaertskompatibel optional."""
    scope = normalize_scope(scope)
    k = key or load_or_create_vault_key()
    eid = f"mem-{secrets.token_hex(6)}"
    payload = json.dumps(
        {
            "content": content,
            "tags": tags or [],
            "vec": _local_embed(f"{content} {' '.join(tags or [])}"),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    # AAD bleibt der Namespace - unveraendert zur bestehenden AES-GCM-Verdrahtung.
    blob = aead_encrypt(k, payload, aad=namespace.encode("utf-8"))
    expires_at = _expires_from_ttl(ttl_seconds)
    acl_json = json.dumps(_normalize_acl(acl), ensure_ascii=False)
    with _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO vault_entries
               (id, namespace, cipher_blob, created_at, scope, acl_json, expires_at,
                project_id, agent_id, scope_explicit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (eid, namespace, blob, time.time(), scope, acl_json, expires_at, project_id, agent_id),
        )
        conn.commit()
    return eid


def recall_memory(
    namespace: str,
    query: str,
    top_k: int = 5,
    db_path: Optional[str] = None,
    key: Optional[bytes] = None,
    *,
    scope: Optional[str] = None,
    agent_id: str = "global",
    project_id: str = "",
) -> List[Dict[str, Any]]:
    """Recall mit Scope-/ACL-/TTL-Sichtbarkeit; Defaults erhalten das alte Verhalten."""
    scope_filter = normalize_scope(scope) if scope is not None else None
    k = key or load_or_create_vault_key()
    q_vec = _local_embed(query)
    q_terms = set(re.findall(r"[a-zA-Z0-9äöüß_-]{2,}", (query or "").lower()))

    results: List[Dict[str, Any]] = []
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {_VAULT_SELECT} FROM vault_entries WHERE namespace = ? ORDER BY created_at DESC",
            (namespace,),
        ).fetchall()

    for r in rows:
        if not _row_is_visible(r, agent_id, project_id=project_id, scope_filter=scope_filter):
            continue
        data = json.loads(aead_decrypt(k, r["cipher_blob"], aad=namespace.encode("utf-8")).decode("utf-8"))
        c_terms = set(re.findall(r"[a-zA-Z0-9äöüß_-]{2,}", data["content"].lower()))
        lex = (len(q_terms & c_terms) / max(1, len(q_terms))) if q_terms else 0.0
        sim = _cosine(q_vec, data["vec"])
        score = round(0.7 * sim + 0.3 * lex, 4)
        results.append({
            "id": r["id"],
            "content": data["content"],
            "tags": data.get("tags") or [],
            "score": score,
            "created_at": r["created_at"],
            "scope": r["scope"] or SCOPE_GLOBAL,
            "agent_id": r["agent_id"] or "global",
            "project_id": r["project_id"] or "",
            "expires_at": r["expires_at"] or 0.0,
        })

    results.sort(key=lambda x: -x["score"])
    return results[:top_k]
