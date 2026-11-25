"""Cluster 9 — automatisches Deliverable-Export-Handling (Showroom/Obsidian).

Reine Extraktion aus ``default_agent_node_executor`` (frueher ~:1463-1481).
KEINE Logikaenderung: Slug-Bildung, ``WF_<slug>/03_Endprodukte``-Zielpfad,
Zeitstempel, Markdown-Header (Agent/Modell/Quality-Score) und der
``except OSError``-Fallback sind 1:1 uebernommen.

Wichtig: ``archon.core.paths.PROJEKTE_DIR`` bleibt ein Lazy-Import, damit die
Test-Isolation per ``patch("archon.core.paths.PROJEKTE_DIR", tmp_path)`` greift
und im Testbetrieb NICHT in den echten Obsidian-Vault geschrieben wird.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, Optional

# Gleicher Logger-Name wie vor der Extraktion (kein stiller Kanal-Wechsel).
logger = logging.getLogger("archon.workflow_dag")

__all__ = ["write_deliverable"]


def write_deliverable(
    *,
    node: Dict[str, Any],
    res: Dict[str, Any],
    content: str,
    is_error: bool,
    is_content_node: bool,
    agent_id: str,
    model: str,
    node_title: str,
    quality_report: Optional[Dict[str, Any]],
    revisions_used: int,
) -> str:
    """Schreibt das Deliverable und liefert den Pfad (``""`` bei Fehler/Skip)."""
    deliverable_path = ""
    if not is_error and content and (bool(node.get("save_to_showroom")) or is_content_node):
        try:
            from archon.core.paths import PROJEKTE_DIR

            wf_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(node.get("workflow_id") or "workflow_deliverables")).strip("_")[:48] or "workflow_deliverables"
            node_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(node.get("id") or "step")).strip("_")[:40] or "step"
            target_dir = os.path.join(PROJEKTE_DIR, f"WF_{wf_slug}", "03_Endprodukte")
            os.makedirs(target_dir, exist_ok=True)
            ts_tag = time.strftime("%Y%m%d_%H%M%S")
            deliverable_path = os.path.join(target_dir, f"{ts_tag}_{node_slug}.md")
            header_md = f"# {node_title}\n\n- **Agent:** `{agent_id}`\n- **Modell:** `{res.get('model') or model}`\n"
            if quality_report is not None:
                header_md += f"- **Anti-Slop Quality-Score:** `{quality_report.get('score')}/100` (Revisionen: {revisions_used})\n"
            header_md += "\n---\n\n"
            with open(deliverable_path, "w", encoding="utf-8") as deliverable_file:
                deliverable_file.write(header_md + content + "\n")
        except OSError as dexc:
            # 1:1 wie im Original: KEIN Reset von deliverable_path. Der Pfad
            # bleibt gesetzt, auch wenn open() fehlschlug. Nicht "bereinigen".
            logger.debug("[WorkflowDAG] Showroom-Deliverable nicht geschrieben: %s", dexc)
    return deliverable_path
