"""
backend/vault_hygiene.py
Obsidian-Vault Indexierer & Graph-Hygiene (Pillar 4 / 2nd Brain).
Scannt 01_PROJEKTE, generiert eine saubere Map of Content (_MOC_Projekt_Index.md)
und identifiziert verwaiste Notizen ohne Querverlinkung.
"""

import os
import sys
import re
import datetime
from pathlib import Path
from typing import Dict, Any, List

def get_vault_path() -> str:
    from local_memory_bridge import LocalMemoryBridge
    bridge = LocalMemoryBridge()
    return bridge.vault_path

def generate_vault_index_and_hygiene() -> Dict[str, Any]:
    vpath = get_vault_path()
    if not os.path.exists(vpath):
        return {"status": "error", "message": f"Obsidian Vault unter {vpath} nicht erreichbar."}

    projects_dir = os.path.join(vpath, "01_PROJEKTE")
    indexed_reports = []
    orphan_files = []

    if os.path.exists(projects_dir):
        for root, dirs, files in os.walk(projects_dir):
            for f in files:
                if f.endswith(".md"):
                    full_p = os.path.join(root, f)
                    rel_p = os.path.relpath(full_p, vpath)
                    stem = Path(f).stem
                    
                    if "endprodukt" in root.lower() or "bericht" in f.lower() or "briefing" in f.lower():
                        indexed_reports.append({"title": stem, "rel_path": rel_p})
                    else:
                        # Prüfe auf Wikilinks im Text
                        try:
                            with open(full_p, "r", encoding="utf-8", errors="ignore") as n_f:
                                txt = n_f.read()
                                if "[[" not in txt:
                                    orphan_files.append(rel_p)
                        except Exception:
                            pass

    # Generiere _MOC_Projekt_Index.md
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    moc_lines = [
        f"# 🧭 Map of Content — Projekt- & Berichts-Index",
        f"*Automatisch generiert von Archon OS Vault-Hygiene am {now_str}*",
        "",
        "## 📑 Zentral archivierte Endberichte & Ausarbeitungen",
        ""
    ]
    if indexed_reports:
        for r in indexed_reports:
            moc_lines.append(f"- [[{r['title']}]] — *`{r['rel_path']}`*")
    else:
        moc_lines.append("*Noch keine archivierten Endberichte erfasst.*")

    moc_lines.append("")
    moc_lines.append("## 🔍 Verwaiste Dokumente (ohne Querverlinkung)")
    if orphan_files:
        for o in orphan_files[:20]:
            moc_lines.append(f"- ⚠️ `{o}`")
    else:
        moc_lines.append("*Alle Dokumente im Projektordner sind vernetzt.*")

    moc_content = "\n".join(moc_lines)
    moc_file = os.path.join(projects_dir, "_MOC_Projekt_Index.md")
    try:
        os.makedirs(projects_dir, exist_ok=True)
        with open(moc_file, "w", encoding="utf-8") as f:
            f.write(moc_content)
    except Exception as e:
        return {"status": "error", "message": f"Konnte Index nicht schreiben: {e}"}

    return {
        "status": "success",
        "index_file": moc_file,
        "indexed_reports_count": len(indexed_reports),
        "orphan_count": len(orphan_files),
        "message": f"Map of Content mit {len(indexed_reports)} Berichten generiert. {len(orphan_files)} verwaiste Notizen erkannt."
    }
