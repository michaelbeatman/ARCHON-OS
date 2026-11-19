# -*- coding: utf-8 -*-
"""
backend/deep_research_lab.py
============================
Meilenstein 45: Research Lab zum Deep-Research-Labor ausbauen.

Mehrstufige Quellen-Triangulation (Trust-Tiers), Citation-Check
(ArXiv / PatSnap / amtliche Quellen) und Dossier-Export inkl. Vault-Ablage.
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Any, Dict, List, Optional

_TIER1_DOMAINS = (
    "arxiv.org", "pubmed.ncbi.nlm.nih.gov", "wipo.int", "epo.org", "uspto.gov",
    "connect.patsnap.com", "gesetze-im-internet.de", "eur-lex.europa.eu", ".gov",
)
_TIER2_DOMAINS = ("github.com", "nature.com", "science.org", "ieee.org", "de.wikipedia.org", "en.wikipedia.org")


def classify_source_tier(url: str) -> str:
    low = (url or "").lower()
    if any(d in low for d in _TIER1_DOMAINS):
        return "tier1_primary"
    if any(d in low for d in _TIER2_DOMAINS):
        return "tier2_specialist"
    return "tier3_web"


def triangulate_sources(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bewertet Quellen nach Trust-Tiers und prueft auf Mehrfach-Absicherung."""
    enriched = []
    domains = set()
    tier1_count = 0

    for s in sources:
        url = str(s.get("url") or "").strip()
        tier = classify_source_tier(url)
        if tier == "tier1_primary":
            tier1_count += 1
        m = re.match(r"https?://([^/]+)", url, re.I)
        if m:
            domains.add(m.group(1).lower())
        enriched.append({**s, "tier": tier})

    corroborated = len(domains) >= 2
    confidence = min(1.0, round(0.25 * len(domains) + 0.25 * tier1_count, 2))
    return {
        "corroborated": corroborated,
        "independent_domains": len(domains),
        "tier1_count": tier1_count,
        "confidence": confidence,
        "sources": enriched,
    }


def compile_research_dossier(
    topic: str,
    summary: str,
    sources: List[Dict[str, Any]],
    vault_dir: Optional[str] = None,
) -> Dict[str, Any]:
    tri = triangulate_sources(sources)
    lines = [
        f"# Deep Research Dossier: {topic}",
        "",
        f"- **Erstellt:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **Trianguliert:** {'Ja' if tri['corroborated'] else 'Nein'} ({tri['independent_domains']} Domains, {tri['tier1_count']} Primaerquellen)",
        f"- **Konfidenz:** {tri['confidence']}",
        "",
        "## Kernaussagen",
        summary.strip(),
        "",
        "## Quellenverzeichnis",
    ]
    for idx, s in enumerate(tri["sources"], start=1):
        lines.append(f"{idx}. [{s.get('title') or s.get('url')}]({s.get('url')}) — `{s['tier']}`")
    md = "\n".join(lines) + "\n"

    saved_path = None
    if vault_dir:
        out_dir = os.path.join(vault_dir, "02_Research")
        os.makedirs(out_dir, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", topic.lower()).strip("-")[:50] or "dossier"
        saved_path = os.path.join(out_dir, f"{slug}.md")
        with open(saved_path, "w", encoding="utf-8") as f:
            f.write(md)

    return {"markdown": md, "saved_path": saved_path, "triangulation": tri}
