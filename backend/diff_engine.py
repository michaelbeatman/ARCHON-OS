"""
backend/diff_engine.py
Berechnet strukturierte, Git-kompatible Unified-Diffs vor Dateiänderungen.
Ermöglicht dem Benutzer eine Side-by-Side Vorher-/Nachher-Prüfung im Cockpit.
"""

import os
import sys
import difflib
from typing import Dict, Any, List

def compute_file_diff(file_path: str, new_content: str, context_lines: int = 3) -> Dict[str, Any]:
    """
    Vergleicht den existierenden Dateiinhalt mit dem neuen Entwurf.
    Gibt strukturierte Zeilen-Diffs (Rot = Löschung, Grün = Hinzufügung) zurück.
    """
    abs_path = os.path.abspath(file_path)
    old_content = ""
    is_new_file = not os.path.exists(abs_path)

    if not is_new_file:
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                old_content = f.read()
        except Exception as e:
            old_content = f"[Fehler beim Lesen: {e}]"

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = list(difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{os.path.basename(file_path)}",
        tofile=f"b/{os.path.basename(file_path)}",
        n=context_lines
    ))

    additions = 0
    deletions = 0
    structured_lines = []

    for line in diff:
        line_clean = line.rstrip("\r\n")
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            structured_lines.append({"type": "header", "text": line_clean})
        elif line.startswith("+"):
            additions += 1
            structured_lines.append({"type": "addition", "text": line_clean[1:]})
        elif line.startswith("-"):
            deletions += 1
            structured_lines.append({"type": "deletion", "text": line_clean[1:]})
        else:
            structured_lines.append({"type": "context", "text": line_clean[1:] if line.startswith(" ") else line_clean})

    return {
        "file_path": file_path,
        "is_new_file": is_new_file,
        "has_changes": additions > 0 or deletions > 0 or is_new_file,
        "additions": additions,
        "deletions": deletions,
        "structured_diff": structured_lines,
        "unified_diff_raw": "".join(diff)
    }
