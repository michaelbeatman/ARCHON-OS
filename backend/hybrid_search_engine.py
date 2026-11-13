"""
backend/hybrid_search_engine.py
Paket 2 (Feature 6): Hybrid-Search (BM25 Volltextsuche via SQLite FTS5 + Vektor-Cosine-RAG + Reciprocal Rank Fusion).
Kombiniert exakte Keyword-/Fehlercode-Treffer (BM25) mit semantischen Vektor-Treffern über RRF:
score(d) = bm25_weight * (1 / (rrf_k + rank_bm25)) + vector_weight * (1 / (rrf_k + rank_vec)).
"""

import os
import re
import json
import math
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
from collections import Counter
from datetime import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("hybrid_search")
    except Exception:
        return {
            "enabled": True,
            "rrf_k": 60,
            "bm25_weight": 0.5,
            "vector_weight": 0.5,
            "top_k": 5
        }


def _build_sparse_vec(text: str) -> Dict[str, float]:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    words = re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_\-]{2,}", norm)
    counts = Counter(words)
    norm_factor = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: round(v / norm_factor, 5) for k, v in counts.items()}


def _cosine_sim(v1: Dict[str, float], v2: Dict[str, float]) -> float:
    if not v1 or not v2:
        return 0.0
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    return round(min(1.0, max(0.0, sum(val * v2.get(k, 0.0) for k, val in v1.items()))), 4)


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hybrid_knowledge_docs (
                doc_id TEXT PRIMARY KEY,
                title TEXT,
                source TEXT,
                content TEXT,
                vector_json TEXT,
                created_at TEXT
            )
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS hybrid_knowledge_fts
            USING fts5(doc_id UNINDEXED, title, content, source)
        """)
        conn.commit()


class HybridSearchEngine:
    def __init__(self):
        _init_db()

    def index_document(self, doc_id: str, title: str, content: str, source: str = "system_docs") -> Dict[str, Any]:
        vec = _build_sparse_vec(f"{title} {content}")
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.execute("""
                INSERT INTO hybrid_knowledge_docs (doc_id, title, content, source, vector_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    source = excluded.source,
                    vector_json = excluded.vector_json,
                    created_at = excluded.created_at
            """, (doc_id, title, content, source, json.dumps(vec), now_iso))
            conn.execute("DELETE FROM hybrid_knowledge_fts WHERE doc_id = ?", (doc_id,))
            conn.execute(
                "INSERT INTO hybrid_knowledge_fts (doc_id, title, content, source) VALUES (?, ?, ?, ?)",
                (doc_id, title, content, source)
            )
            conn.commit()
        return {"indexed": True, "doc_id": doc_id, "title": title, "source": source}

    def search(
        self,
        query: str,
        top_k_override: Optional[int] = None,
        rrf_k_override: Optional[int] = None
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        rrf_k = int(rrf_k_override or cfg.get("rrf_k", 60))
        bm25_w = float(cfg.get("bm25_weight", 0.5))
        vec_w = float(cfg.get("vector_weight", 0.5))
        top_k = int(top_k_override or cfg.get("top_k", 5))

        q_vec = _build_sparse_vec(query)
        q_tokens = re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_\-]{2,}", query)
        fts_query = " OR ".join(f'"{t}"' for t in q_tokens[:12]) if q_tokens else '""'

        with sqlite3.connect(DB_PATH, timeout=15.0, factory=_ArchonClosingConn) as conn:
            conn.row_factory = sqlite3.Row
            all_docs = {
                r["doc_id"]: dict(r)
                for r in conn.execute("SELECT * FROM hybrid_knowledge_docs").fetchall()
            }

            # 1. BM25 Ranking via SQLite FTS5
            bm25_ranks: Dict[str, int] = {}
            bm25_scores: Dict[str, float] = {}
            if enabled and fts_query != '""':
                try:
                    fts_rows = conn.execute(
                        "SELECT doc_id, bm25(hybrid_knowledge_fts) AS raw_bm25 "
                        "FROM hybrid_knowledge_fts WHERE hybrid_knowledge_fts MATCH ? ORDER BY raw_bm25 LIMIT 50",
                        (fts_query,)
                    ).fetchall()
                    for rank_idx, fr in enumerate(fts_rows, start=1):
                        bm25_ranks[fr["doc_id"]] = rank_idx
                        bm25_scores[fr["doc_id"]] = round(abs(float(fr["raw_bm25"] or 0.0)), 4)
                except Exception:
                    pass

            # 2. Vektor-Cosine Ranking
            vec_scored = []
            for doc_id, doc in all_docs.items():
                try:
                    d_vec = json.loads(doc.get("vector_json") or "{}")
                except Exception:
                    d_vec = {}
                sim = _cosine_sim(q_vec, d_vec)
                vec_scored.append((doc_id, sim))
            vec_scored.sort(key=lambda x: x[1], reverse=True)
            vec_ranks = {doc_id: idx for idx, (doc_id, sim) in enumerate(vec_scored, start=1) if sim > 0.0}
            vec_sims = {doc_id: sim for doc_id, sim in vec_scored}

        # 3. Reciprocal Rank Fusion (RRF)
        combined = []
        candidate_ids = set(bm25_ranks.keys()) | set(vec_ranks.keys())
        for doc_id in candidate_ids:
            doc = all_docs.get(doc_id)
            if not doc:
                continue
            r_bm25 = bm25_ranks.get(doc_id)
            r_vec = vec_ranks.get(doc_id)

            if enabled:
                rrf_bm25 = (bm25_w / (rrf_k + r_bm25)) if r_bm25 else 0.0
                rrf_vec = (vec_w / (rrf_k + r_vec)) if r_vec else 0.0
                rrf_score = round((rrf_bm25 + rrf_vec) * 100, 4)
            else:
                rrf_score = vec_sims.get(doc_id, 0.0)

            combined.append({
                "doc_id": doc_id,
                "title": doc["title"],
                "source": doc["source"],
                "content": doc["content"],
                "rrf_score": rrf_score,
                "bm25_rank": r_bm25,
                "bm25_score": bm25_scores.get(doc_id, 0.0),
                "vector_rank": r_vec,
                "vector_similarity": vec_sims.get(doc_id, 0.0)
            })

        combined.sort(key=lambda x: (x["rrf_score"], x["vector_similarity"]), reverse=True)
        return {
            "query": query,
            "hybrid_enabled": enabled,
            "rrf_k": rrf_k,
            "total_candidates": len(combined),
            "results": combined[:top_k]
        }


hybrid_search_engine = HybridSearchEngine()
