"""
backend/corrective_rag.py
Paket 2 (Feature 8): Agentic Corrective RAG (CRAG / Selbstkorrigierende Wissensabfrage).
Prüft abgerufene Dokumente vor der Antwortgenerierung auf tatsächliche Relevanz zur Nutzerfrage.
Liegt der beste Score unter `relevance_threshold` (Standard: 0.45), verwirft CRAG das Rauschen,
formuliert die Suchanfrage automatisch um (Query Expansion / Synonym-Anreicherung) und sucht erneut.
"""

import re
from typing import Dict, Any, List, Optional
from backend.hybrid_search_engine import hybrid_search_engine
from backend.knowledge_graph_store import knowledge_graph_store


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("corrective_rag")
    except Exception:
        return {
            "enabled": True,
            "relevance_threshold": 0.45,
            "auto_query_rewrite": True,
            "max_rewrite_attempts": 2
        }


SYNONYM_EXPANSIONS = {
    "fehler": "error bug exception rollback self-healer",
    "container": "docker sandbox fleet restart health",
    "gedächtnis": "memory rag sqlite fts5 hybrid consolidation",
    "sicherheit": "security zero-trust rbac consensus secret",
    "kosten": "budget token guard clipper cache",
    "geschwindigkeit": "performance latency hedge batcher map-reduce"
}


STOPWORDS = {
    "wie", "was", "wer", "wo", "wann", "warum", "der", "die", "das", "ein", "eine",
    "einen", "einem", "einer", "bei", "für", "und", "oder", "mit", "von", "aus",
    "ist", "sind", "wird", "werden", "the", "and", "for", "with", "how", "what"
}


class CorrectiveRAGEngine:
    def _rewrite_query(self, original_query: str, attempt: int) -> str:
        q_low = original_query.lower()
        expansions = []
        for key, syns in SYNONYM_EXPANSIONS.items():
            if key in q_low:
                expansions.append(syns)
        if not expansions:
            words = re.findall(r"[a-zA-Z0-9äöüßÄÖÜ]{4,}", original_query)
            expansions.append(" ".join(words))
        return f"{original_query} {' '.join(expansions[:attempt])}".strip()

    def _grade_document_relevance(self, original_query: str, expanded_query: str, doc: Dict[str, Any]) -> float:
        orig_words = {
            w for w in re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_\-]{3,}", original_query.lower())
            if w not in STOPWORDS
        }
        exp_words = {
            w for w in re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_\-]{3,}", expanded_query.lower())
            if w not in STOPWORDS
        }
        d_words = set(re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_\-]{3,}", f"{doc.get('title', '')} {doc.get('content', '')}".lower()))
        matched_hits = len(exp_words & d_words)
        denom = max(1, min(len(orig_words) or 1, 4))
        lexical_overlap = min(1.0, matched_hits / denom)
        vec_sim = float(doc.get("vector_similarity", 0.0))
        rrf_bonus = min(0.35, float(doc.get("rrf_score", 0.0)) * 0.18)
        return round(min(1.0, (lexical_overlap * 0.55) + (vec_sim * 0.30) + rrf_bonus), 3)

    def retrieve_and_verify(
        self,
        query: str,
        threshold_override: Optional[float] = None
    ) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        threshold = float(threshold_override if threshold_override is not None else cfg.get("relevance_threshold", 0.45))
        auto_rewrite = bool(cfg.get("auto_query_rewrite", True))
        max_attempts = int(cfg.get("max_rewrite_attempts", 2)) if (enabled and auto_rewrite) else 0

        attempts_log: List[Dict[str, Any]] = []
        verified_docs: List[Dict[str, Any]] = []
        current_query = query

        for attempt in range(0, max_attempts + 1):
            if attempt > 0:
                current_query = self._rewrite_query(query, attempt)

            search_res = hybrid_search_engine.search(current_query, top_k_override=6)
            candidates = search_res.get("results", [])

            graded = []
            for c in candidates:
                rel_score = self._grade_document_relevance(query, current_query, c)
                c_copy = dict(c)
                c_copy["crag_relevance_score"] = rel_score
                c_copy["crag_passed"] = (rel_score >= threshold) if enabled else True
                graded.append(c_copy)

            passed = [g for g in graded if g["crag_passed"]]
            attempts_log.append({
                "attempt": attempt + 1,
                "query_used": current_query,
                "candidates_found": len(candidates),
                "passed_count": len(passed),
                "best_score": max((g["crag_relevance_score"] for g in graded), default=0.0)
            })

            if passed:
                verified_docs = passed
                break

        # Ergänze Knowledge-Graph Fakten, falls passende Entitäten im Query vorkommen
        kg_edges = []
        for token in re.findall(r"[A-ZÄÖÜ][\w\-]{2,}", query):
            sub = knowledge_graph_store.query_subgraph(token, hops_override=1)
            if sub.get("edges"):
                kg_edges.extend(sub["edges"][:3])

        status = "verified_hit" if verified_docs else "insufficient_evidence_fallback"
        return {
            "original_query": query,
            "final_query": current_query,
            "crag_enabled": enabled,
            "relevance_threshold": threshold,
            "status": status,
            "rewrite_attempts_used": max(0, len(attempts_log) - 1),
            "attempts_log": attempts_log,
            "verified_documents": verified_docs,
            "knowledge_graph_context": kg_edges[:5]
        }


corrective_rag_engine = CorrectiveRAGEngine()
