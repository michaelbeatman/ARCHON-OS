"""
backend/semantic_cache.py
Paket 1 (Feature 1): Semantisches Prompt- & Response-Caching mit Vektor-/Cosine-Distanz.
Speichert normalisierte Prompts, Wort-/Bigramm-Frequenzvektoren und LLM-Antworten in SQLite (`semantic_response_cache`).
Treffer mit Cosine-Ähnlichkeit >= similarity_threshold (Standard: 0.95) liefern Antworten in < 10 ms ohne API-Kosten.
"""

import os
import re
import json
import math
import time
import hashlib
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("semantic_cache")
    except Exception:
        return {
            "enabled": True,
            "similarity_threshold": 0.95,
            "ttl_hours": 24,
            "max_entries": 500
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS semantic_response_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exact_hash TEXT UNIQUE,
                model TEXT,
                prompt_text TEXT,
                vector_json TEXT,
                response_text TEXT,
                tokens_saved_estimate INTEGER DEFAULT 0,
                hit_count INTEGER DEFAULT 0,
                created_at TEXT,
                expires_at TEXT,
                last_hit_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sem_cache_hash ON semantic_response_cache(exact_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sem_cache_expires ON semantic_response_cache(expires_at)")
        conn.commit()


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    return cleaned


def _build_sparse_vector(text: str) -> Dict[str, float]:
    """Erzeugt einen L2-normalisierten Wort- und Charakter-3-Gramm-Vektor für schnelle Cosine-Distanz."""
    norm = _normalize_text(text)
    words = re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_]{2,}", norm)
    ngrams = [norm[i:i+3] for i in range(max(0, len(norm) - 2)) if " " not in norm[i:i+3]]
    counts = Counter(words)
    for ng in ngrams[:150]:
        counts[f"#{ng}"] += 0.5

    norm_factor = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: round(v / norm_factor, 5) for k, v in counts.items()}


def _cosine_similarity(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) > len(vec_b):
        vec_a, vec_b = vec_b, vec_a
    dot = sum(val * vec_b.get(k, 0.0) for k, val in vec_a.items())
    return round(min(1.0, max(0.0, dot)), 4)


class SemanticCacheManager:
    def __init__(self):
        _init_db()

    def lookup(
        self,
        prompt: str,
        model: str = "any",
        threshold_override: Optional[float] = None
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {
                "hit": False,
                "bypassed": True,
                "reason": "Semantic Cache in settings.json deaktiviert.",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
            }

        threshold = float(threshold_override if threshold_override is not None else cfg.get("similarity_threshold", 0.95))
        norm_prompt = _normalize_text(prompt)
        exact_hash = hashlib.sha256(f"{model}::{norm_prompt}".encode("utf-8")).hexdigest()
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            # Abgelaufene Einträge bereinigen
            conn.execute("DELETE FROM semantic_response_cache WHERE expires_at < ?", (now_iso,))

            # 1. Exakter Hash-Match (O(1))
            row = conn.execute(
                "SELECT * FROM semantic_response_cache WHERE exact_hash = ?",
                (exact_hash,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE semantic_response_cache SET hit_count = hit_count + 1, last_hit_at = ? WHERE id = ?",
                    (now_iso, row["id"])
                )
                conn.commit()
                return {
                    "hit": True,
                    "match_type": "exact_hash",
                    "similarity": 1.0,
                    "threshold": threshold,
                    "response": row["response_text"],
                    "cached_model": row["model"],
                    "hit_count": row["hit_count"] + 1,
                    "tokens_saved": row["tokens_saved_estimate"],
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
                }

            # 2. Semantischer Cosine-Scan über aktive Cache-Einträge
            query_vec = _build_sparse_vector(norm_prompt)
            rows = conn.execute(
                "SELECT id, model, prompt_text, vector_json, response_text, hit_count, tokens_saved_estimate "
                "FROM semantic_response_cache ORDER BY id DESC LIMIT ?",
                (int(cfg.get("max_entries", 500)),)
            ).fetchall()

            best_score = 0.0
            best_row = None
            for r in rows:
                if model not in ("any", "*", "") and r["model"] not in ("any", "*", model):
                    continue
                try:
                    cand_vec = json.loads(r["vector_json"] or "{}")
                except Exception:
                    continue
                sim = _cosine_similarity(query_vec, cand_vec)
                if sim > best_score:
                    best_score = sim
                    best_row = r

            if best_row and best_score >= threshold:
                conn.execute(
                    "UPDATE semantic_response_cache SET hit_count = hit_count + 1, last_hit_at = ? WHERE id = ?",
                    (now_iso, best_row["id"])
                )
                conn.commit()
                return {
                    "hit": True,
                    "match_type": "semantic_cosine",
                    "similarity": best_score,
                    "threshold": threshold,
                    "matched_prompt": best_row["prompt_text"],
                    "response": best_row["response_text"],
                    "cached_model": best_row["model"],
                    "hit_count": best_row["hit_count"] + 1,
                    "tokens_saved": best_row["tokens_saved_estimate"],
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
                }

        return {
            "hit": False,
            "best_similarity": best_score,
            "threshold": threshold,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2)
        }

    def store(self, prompt: str, response: str, model: str = "any") -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"stored": False, "bypassed": True}

        norm_prompt = _normalize_text(prompt)
        exact_hash = hashlib.sha256(f"{model}::{norm_prompt}".encode("utf-8")).hexdigest()
        vec = _build_sparse_vector(norm_prompt)
        ttl_hours = int(cfg.get("ttl_hours", 24))
        max_entries = int(cfg.get("max_entries", 500))
        now = datetime.now()
        now_iso = now.strftime("%Y-%m-%d %H:%M:%S")
        exp_iso = (now + timedelta(hours=ttl_hours)).strftime("%Y-%m-%d %H:%M:%S")
        tokens_est = max(1, (len(prompt) + len(response)) // 4)

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.execute("""
                INSERT INTO semantic_response_cache
                (exact_hash, model, prompt_text, vector_json, response_text, tokens_saved_estimate, hit_count, created_at, expires_at, last_hit_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, NULL)
                ON CONFLICT(exact_hash) DO UPDATE SET
                    response_text = excluded.response_text,
                    vector_json = excluded.vector_json,
                    expires_at = excluded.expires_at
            """, (exact_hash, model, prompt.strip(), json.dumps(vec), response, tokens_est, now_iso, exp_iso))

            # Max-Entries Quota einhalten (älteste löschen)
            conn.execute("""
                DELETE FROM semantic_response_cache
                WHERE id NOT IN (
                    SELECT id FROM semantic_response_cache ORDER BY id DESC LIMIT ?
                )
            """, (max_entries,))
            conn.commit()

        return {
            "stored": True,
            "exact_hash": exact_hash[:16],
            "model": model,
            "tokens_saved_estimate": tokens_est,
            "expires_at": exp_iso
        }

    def get_stats(self) -> Dict[str, Any]:
        cfg = _get_cfg()
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS total_entries,
                    COALESCE(SUM(hit_count), 0) AS total_hits,
                    COALESCE(SUM(hit_count * tokens_saved_estimate), 0) AS total_tokens_saved
                FROM semantic_response_cache
            """).fetchone()
        return {
            "enabled": bool(cfg.get("enabled", True)),
            "similarity_threshold": float(cfg.get("similarity_threshold", 0.95)),
            "ttl_hours": int(cfg.get("ttl_hours", 24)),
            "max_entries": int(cfg.get("max_entries", 500)),
            "total_entries": row[0] if row else 0,
            "total_hits": row[1] if row else 0,
            "total_tokens_saved": row[2] if row else 0
        }

    def clear(self) -> Dict[str, Any]:
        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            cur = conn.execute("DELETE FROM semantic_response_cache")
            deleted = cur.rowcount
            conn.commit()
        return {"cleared": True, "deleted_entries": deleted}


semantic_cache_manager = SemanticCacheManager()
