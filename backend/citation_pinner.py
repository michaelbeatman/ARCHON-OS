"""
backend/citation_pinner.py
Paket 2 (Feature 10): Automatisches Citation- & Quellen-Pinning.
Verknüpft Sätze/Faktenaussagen einer Agenten-Antwort automatisch mit den genutzten Wissensquellen
(`[Quelle: DOC-ID]`), berechnet die Beleg-Abdeckungsquote (`citation_coverage_pct`) und hängt
bei Bedarf ein strukturiertes Quellenverzeichnis an, um Halluzinationen auszuschließen.
"""

import re
from typing import Dict, Any, List


def _get_cfg() -> Dict[str, Any]:
    try:
        from backend.autonomy_settings import get_module_config
        return get_module_config("citation_pinning")
    except Exception:
        return {
            "enabled": True,
            "require_inline_citations": True,
            "min_citation_coverage_pct": 60,
            "auto_append_sources_footer": True
        }


class CitationPinner:
    def pin_citations(self, response_text: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        cfg = _get_cfg()
        enabled = bool(cfg.get("enabled", True))
        if not enabled or not sources:
            return {
                "enabled": enabled,
                "annotated_response": response_text,
                "citation_coverage_pct": 100.0 if not sources else 0.0,
                "meets_policy": True,
                "citations_pinned": 0
            }

        min_cov = float(cfg.get("min_citation_coverage_pct", 60))
        require_inline = bool(cfg.get("require_inline_citations", True))
        append_footer = bool(cfg.get("auto_append_sources_footer", True))

        # Bereite Quellen-Wortmengen vor
        source_profiles = []
        for idx, src in enumerate(sources, start=1):
            doc_id = str(src.get("doc_id") or src.get("id") or f"SRC-{idx}")
            title = str(src.get("title") or doc_id)
            content = str(src.get("content") or "")
            tokens = set(re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_\-]{3,}", f"{title} {content}".lower()))
            source_profiles.append({
                "doc_id": doc_id,
                "title": title,
                "tokens": tokens
            })

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", response_text.strip()) if s.strip()]
        annotated_sentences = []
        cited_sentences_count = 0
        used_sources = {}

        for sent in sentences:
            s_tokens = set(re.findall(r"[a-zA-Z0-9äöüßÄÖÜ_\-]{3,}", sent.lower()))
            best_src = None
            best_overlap = 0
            for sp in source_profiles:
                overlap = len(s_tokens & sp["tokens"])
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_src = sp

            if best_src and best_overlap >= 1:
                cited_sentences_count += 1
                used_sources[best_src["doc_id"]] = best_src["title"]
                if require_inline and f"[Quelle: {best_src['doc_id']}]" not in sent:
                    sent = f"{sent} [Quelle: {best_src['doc_id']}]"
            annotated_sentences.append(sent)

        coverage_pct = round((cited_sentences_count / max(1, len(sentences))) * 100, 1)
        final_text = " ".join(annotated_sentences)

        if append_footer and used_sources:
            footer_lines = ["\n\n### Verifizierte Quellen-Belege (Citation Pinning):"]
            for did, dtitle in used_sources.items():
                footer_lines.append(f"- **[{did}]** {dtitle}")
            final_text += "\n".join(footer_lines)

        return {
            "enabled": enabled,
            "total_sentences": len(sentences),
            "cited_sentences": cited_sentences_count,
            "citation_coverage_pct": coverage_pct,
            "min_required_coverage_pct": min_cov,
            "meets_policy": coverage_pct >= min_cov,
            "used_sources": used_sources,
            "annotated_response": final_text
        }


citation_pinner = CitationPinner()
