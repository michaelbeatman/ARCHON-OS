"""
backend/knowledge_graph_store.py
Paket 2 (Feature 7): Lokaler Knowledge-Graph (Entitäten- & Beziehungs-Tripel-Speicher in SQLite).
Speichert gerichtete Wissens-Tripel (Subjekt -> Prädikat -> Objekt) mit Konfidenz und Quelle,
extrahiert automatisch Entitäten-Beziehungen aus Freitext und unterstützt Multi-Hop-Nachbarschafts-Abfragen.
"""

import os
import re
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional, Set

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("knowledge_graph")
    except Exception:
        return {
            "enabled": True,
            "auto_extract_triples": True,
            "max_traversal_hops": 2,
            "min_confidence": 0.70
        }


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_graph_triples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                predicate TEXT,
                object TEXT,
                confidence REAL DEFAULT 0.9,
                source TEXT DEFAULT 'manual',
                created_at TEXT,
                UNIQUE(subject, predicate, object)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_subj ON knowledge_graph_triples(subject)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_obj ON knowledge_graph_triples(object)")
        conn.commit()


class KnowledgeGraphStore:
    def __init__(self):
        _init_db()

    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float = 0.90,
        source: str = "agent_memory"
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)):
            return {"stored": False, "bypassed": True}
        min_conf = float(cfg.get("min_confidence", 0.70))
        if confidence < min_conf:
            return {"stored": False, "reason": f"Confidence {confidence} < min_confidence {min_conf}"}

        s_clean = subject.strip()
        p_clean = predicate.strip().upper().replace(" ", "_")
        o_clean = obj.strip()
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.execute("""
                INSERT INTO knowledge_graph_triples (subject, predicate, object, confidence, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(subject, predicate, object) DO UPDATE SET
                    confidence = MAX(knowledge_graph_triples.confidence, excluded.confidence),
                    source = excluded.source,
                    created_at = excluded.created_at
            """, (s_clean, p_clean, o_clean, confidence, source, now_iso))
            conn.commit()

        return {
            "stored": True,
            "triple": {"subject": s_clean, "predicate": p_clean, "object": o_clean, "confidence": confidence}
        }

    def ingest_text(self, text: str, source: str = "auto_extractor") -> Dict[str, Any]:
        """Extrahiert automatisch Subjekt-Prädikat-Objekt-Tripel aus deutschem/englischem Fachtext."""
        cfg = _get_cfg()
        if not bool(cfg.get("enabled", True)) or not bool(cfg.get("auto_extract_triples", True)):
            return {"extracted_count": 0, "triples": [], "bypassed": True}

        patterns = [
            (r"([A-ZÄÖÜ][\w\-.\s]{1,35}?)\s+(?:arbeitet bei|ist Teil von|gehört zu)\s+([A-ZÄÖÜ][\w\-.\s]{1,35})", "BELONGS_TO"),
            (r"([A-ZÄÖÜ][\w\-.\s]{1,35}?)\s+(?:nutzt|verwendet|basiert auf)\s+([A-ZÄÖÜa-z0-9][\w\-.\s]{1,35})", "USES"),
            (r"([A-ZÄÖÜ][\w\-.\s]{1,35}?)\s+(?:steuert|verwaltet|überwacht)\s+([A-ZÄÖÜa-z0-9][\w\-.\s]{1,35})", "MANAGES"),
            (r"([A-ZÄÖÜ][\w\-.\s]{1,35}?)\s+(?:ist verantwortlich für|leitet)\s+([A-ZÄÖÜa-z0-9][\w\-.\s]{1,35})", "LEADS"),
        ]

        stored_triples = []
        sentences = re.split(r"[.!?\n]+", text)
        for sent in sentences:
            sent = sent.strip()
            if not sent:
                continue
            for pat, pred in patterns:
                for m in re.finditer(pat, sent):
                    subj, obj = m.group(1).strip(), m.group(2).strip()
                    res = self.add_triple(subj, pred, obj, confidence=0.85, source=source)
                    if res.get("stored"):
                        stored_triples.append(res["triple"])

        return {"extracted_count": len(stored_triples), "triples": stored_triples}

    def query_subgraph(self, entity: str, hops_override: Optional[int] = None) -> Dict[str, Any]:
        cfg = _get_cfg()
        max_hops = int(hops_override or cfg.get("max_traversal_hops", 2))
        min_conf = float(cfg.get("min_confidence", 0.70))

        visited_entities: Set[str] = {entity.strip()}
        frontier: Set[str] = {entity.strip()}
        edges: List[Dict[str, Any]] = []
        seen_edge_ids: Set[int] = set()

        with sqlite3.connect(DB_PATH, timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            for hop in range(1, max_hops + 1):
                if not frontier:
                    break
                next_frontier: Set[str] = set()
                for ent in frontier:
                    rows = conn.execute("""
                        SELECT id, subject, predicate, object, confidence, source
                        FROM knowledge_graph_triples
                        WHERE (LOWER(subject) LIKE LOWER(?) OR LOWER(object) LIKE LOWER(?))
                          AND confidence >= ?
                    """, (f"%{ent}%", f"%{ent}%", min_conf)).fetchall()
                    for r in rows:
                        if r["id"] not in seen_edge_ids:
                            seen_edge_ids.add(r["id"])
                            edges.append({
                                "hop": hop,
                                "subject": r["subject"],
                                "predicate": r["predicate"],
                                "object": r["object"],
                                "confidence": r["confidence"],
                                "source": r["source"]
                            })
                        for neighbor in (r["subject"], r["object"]):
                            if neighbor not in visited_entities:
                                visited_entities.add(neighbor)
                                next_frontier.add(neighbor)
                frontier = next_frontier

        return {
            "seed_entity": entity,
            "max_hops": max_hops,
            "discovered_entities": sorted(visited_entities),
            "edge_count": len(edges),
            "edges": edges
        }


knowledge_graph_store = KnowledgeGraphStore()
