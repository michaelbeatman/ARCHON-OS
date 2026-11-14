"""
backend/epistemic_hygiene.py
============================
M53 — „Epistemic Hygiene“-Wächter für den Obsidian-Vault.

Erkennt:
1. Widersprüchliche Zahlen/Konditionen (z. B. Preis, Tagessatz, Budget, Rabatt, Frist)
   zwischen verschiedenen Markdown-Notizen.
2. Veraltete Rechts-/Vertragsstände (abgelaufene „gültig bis“-Daten oder alte Jahresstände).
3. Verwaiste Notizen ohne Querverlinkung ([[Wikilinks]]).
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Any, Dict, List, Optional

from archon.core.runtime import OBSIDIAN_VAULT_DIR

METRIC_PATTERN = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(preis|tagessatz|budget|honorar|pauschale|kündigungsfrist|laufzeit|rabatt|stundensatz)\s*[:=]\s*([^\n\r]+)$"
)
EXPIRY_PATTERN = re.compile(
    r"(?i)(?:gültig\s+bis|ablauf|befristet\s+bis|stand)\s*[:=]?\s*(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})"
)


def _parse_date_flexible(raw: str) -> Optional[datetime.date]:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _normalize_metric_val(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip().lower())


def scan_vault_epistemic_hygiene(
    vault_path: Optional[str] = None,
    reference_date: Optional[datetime.date] = None,
) -> Dict[str, Any]:
    root_dir = os.path.realpath(vault_path or OBSIDIAN_VAULT_DIR)
    today = reference_date or datetime.date.today()

    if not os.path.isdir(root_dir):
        return {
            "status": "error",
            "message": f"Obsidian-Vault nicht gefunden: {root_dir}",
            "scanned_files": 0,
            "conflicts": [],
            "stale_legal_entries": [],
            "orphans": [],
        }

    metric_claims: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    stale_entries: List[Dict[str, Any]] = []
    orphans: List[str] = []
    scanned = 0

    for dirpath, _, filenames in os.walk(root_dir):
        for fname in sorted(filenames):
            if not fname.endswith(".md") or fname.startswith("_"):
                continue
            fpath = os.path.realpath(os.path.join(dirpath, fname))
            if not (fpath == root_dir or fpath.startswith(root_dir + os.sep)):
                continue
            rel = os.path.relpath(fpath, root_dir)
            scanned += 1
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read(50_000)
            except Exception:
                continue

            if "[[" not in text:
                orphans.append(rel)

            for m in METRIC_PATTERN.finditer(text):
                key = m.group(1).strip().lower()
                val_raw = m.group(2).strip()
                val_norm = _normalize_metric_val(val_raw)
                metric_claims.setdefault(key, {}).setdefault(val_norm, []).append({
                    "file": rel,
                    "raw_value": val_raw,
                })

            for dm in EXPIRY_PATTERN.finditer(text):
                dt = _parse_date_flexible(dm.group(1))
                if dt and dt < today:
                    stale_entries.append({
                        "file": rel,
                        "date_found": dm.group(1),
                        "days_overdue": (today - dt).days,
                        "context": dm.group(0),
                    })

    conflicts: List[Dict[str, Any]] = []
    for key, val_buckets in sorted(metric_claims.items()):
        if len(val_buckets) > 1:
            variants = []
            for norm_val, occs in val_buckets.items():
                variants.append({
                    "value": occs[0]["raw_value"],
                    "normalized": norm_val,
                    "files": [o["file"] for o in occs],
                })
            conflicts.append({
                "field": key,
                "variant_count": len(variants),
                "variants": variants,
            })

    return {
        "status": "success",
        "vault_path": root_dir,
        "scanned_files": scanned,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "stale_count": len(stale_entries),
        "stale_legal_entries": stale_entries,
        "orphan_count": len(orphans),
        "orphans": orphans[:100],
        "hygiene_score": max(0, 100 - len(conflicts) * 15 - len(stale_entries) * 10 - min(20, len(orphans) * 2)),
    }
