# -*- coding: utf-8 -*-
"""
backend/contract_diff_redliner.py
=================================
Meilenstein 40: Vertrags-Diff & Redlining-Ansicht (Alt gegen Neu).

Vergleicht Vertragsversionen auf Klausel-/Absatzebene, erzeugt eine
XSS-sichere HTML-Redline-Ansicht und bewertet juristische Risiko-Schluesselwoerter.
"""

from __future__ import annotations

import difflib
import html
import re
from typing import Any, Dict, List

_RISK_TERMS = {
    "haftung": "high",
    "vertragsstrafe": "high",
    "exklusiv": "high",
    "schadensersatz": "high",
    "kuendigungsfrist": "medium",
    "preiserhoehung": "medium",
    "gerichtsstand": "medium",
    "datenschutz": "medium",
}


def assess_clause_risks(added_clauses: List[str], removed_clauses: List[str]) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    for change_type, items in (("added", added_clauses), ("removed", removed_clauses)):
        for clause in items:
            low = clause.lower()
            matched = [term for term in _RISK_TERMS if re.search(rf"\b{re.escape(term)}", low)]
            if matched:
                sev = "high" if any(_RISK_TERMS[t] == "high" for t in matched) else "medium"
                findings.append({
                    "change": change_type,
                    "severity": sev,
                    "terms": ", ".join(sorted(matched)),
                    "clause": clause,
                })
    return findings


def diff_contract_clauses(old_text: str, new_text: str) -> Dict[str, Any]:
    old_lines = [l.strip() for l in (old_text or "").splitlines() if l.strip()]
    new_lines = [l.strip() for l in (new_text or "").splitlines() if l.strip()]

    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    added: List[str] = []
    removed: List[str] = []
    html_parts: List[str] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for l in old_lines[i1:i2]:
                html_parts.append(f"<p>{html.escape(l)}</p>")
        elif tag in ("replace", "delete"):
            for l in old_lines[i1:i2]:
                removed.append(l)
                html_parts.append(f"<p><del style='background:#7f1d1d;color:#fecaca'>{html.escape(l)}</del></p>")
            if tag == "replace":
                for l in new_lines[j1:j2]:
                    added.append(l)
                    html_parts.append(f"<p><ins style='background:#14532d;color:#bbf7d0'>{html.escape(l)}</ins></p>")
        elif tag == "insert":
            for l in new_lines[j1:j2]:
                added.append(l)
                html_parts.append(f"<p><ins style='background:#14532d;color:#bbf7d0'>{html.escape(l)}</ins></p>")

    risks = assess_clause_risks(added, removed)
    return {
        "added_count": len(added),
        "removed_count": len(removed),
        "added": added,
        "removed": removed,
        "risk_findings": risks,
        "html_redline": "\n".join(html_parts),
    }
