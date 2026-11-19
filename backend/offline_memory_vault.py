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
"""

from __future__ import annotations

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

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(WORKSPACE_DIR, "data", "compartment_vault.db")
DEFAULT_KEY_PATH = os.path.join(WORKSPACE_DIR, "data", "compartment.key")
VEC_DIM = 64


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
    return key


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        blk = hashlib.sha256(enc_key + nonce + counter.to_bytes(4, "big")).digest()
        out.extend(blk)
        counter += 1
    return bytes(out[:length])


def aead_encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    enc_key = hashlib.sha256(key + b"enc").digest()
    mac_key = hashlib.sha256(key + b"mac").digest()
    nonce = secrets.token_bytes(16)
    ks = _keystream(enc_key, nonce, len(plaintext))
    ct = bytes(a ^ b for a, b in zip(plaintext, ks))
    tag = hmac.new(mac_key, aad + nonce + ct, hashlib.sha256).digest()
    return nonce + tag + ct


def aead_decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    if len(blob) < 48:
        raise ValueError("Ungueltiges AEAD-Ciphertext-Format.")
    enc_key = hashlib.sha256(key + b"enc").digest()
    mac_key = hashlib.sha256(key + b"mac").digest()
    nonce, tag, ct = blob[:16], blob[16:48], blob[48:]
    expected = hmac.new(mac_key, aad + nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("AEAD-Integritaetspruefung fehlgeschlagen (Manipulation oder falscher Key).")
    ks = _keystream(enc_key, nonce, len(ct))
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
                created_at REAL NOT NULL
            )
        """)
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
) -> str:
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
    blob = aead_encrypt(k, payload, aad=namespace.encode("utf-8"))
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO vault_entries (id, namespace, cipher_blob, created_at) VALUES (?, ?, ?, ?)",
            (eid, namespace, blob, time.time()),
        )
        conn.commit()
    return eid


def recall_memory(
    namespace: str,
    query: str,
    top_k: int = 5,
    db_path: Optional[str] = None,
    key: Optional[bytes] = None,
) -> List[Dict[str, Any]]:
    k = key or load_or_create_vault_key()
    q_vec = _local_embed(query)
    q_terms = set(re.findall(r"[a-zA-Z0-9äöüß_-]{2,}", (query or "").lower()))

    results: List[Dict[str, Any]] = []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, cipher_blob, created_at FROM vault_entries WHERE namespace = ? ORDER BY created_at DESC",
            (namespace,),
        ).fetchall()

    for r in rows:
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
        })

    results.sort(key=lambda x: -x["score"])
    return results[:top_k]
