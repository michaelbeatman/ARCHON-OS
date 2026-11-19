# -*- coding: utf-8 -*-
"""
backend/session_receipts.py
===========================
Meilenstein 82: Subagenten- & Session-Receipts
(delegation-receipts & session-receipts-Pattern).

Erzeugt strukturierte Abschluss-Receipts je Subagent sowie ein autarkes,
XSS-sicheres Offline-HTML-Belegdokument inkl. Fehlversuchen und Retries.
"""

from __future__ import annotations

import datetime
import html
from typing import Any, Dict, List, Optional


def build_delegation_receipt(
    task_id: str,
    agent_id: str,
    status: str,
    changed_files: Optional[List[str]] = None,
    proof_command: str = "",
    proof_exit_code: int = 0,
    summary: str = "",
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "agent_id": agent_id,
        "status": status,
        "changed_files": list(changed_files or []),
        "proof_command": proof_command,
        "proof_exit_code": int(proof_exit_code),
        "summary": summary,
        "issued_at": datetime.datetime.now().isoformat(),
    }


def render_offline_html_receipt(
    task_id: str,
    title: str,
    original_ask: str,
    events: List[Dict[str, Any]],
) -> str:
    """Erzeugt ein eigenstaendiges Offline-HTML-Belegdokument (GoBD-/Audit-tauglich)."""
    esc = html.escape
    rows = []
    for idx, ev in enumerate(events, start=1):
        kind = esc(str(ev.get("kind") or "event"))
        ts = esc(str(ev.get("created_at") or ev.get("timestamp") or ""))
        status = esc(str(ev.get("status") or ""))
        detail = esc(str(ev.get("detail") or ev.get("payload") or ""))
        badge_bg = "#10b981" if status in ("done", "completed", "success", "ok") else ("#ef4444" if status in ("failed", "error", "blocked") else "#3b82f6")
        rows.append(
            f"<tr><td>{idx}</td><td>{ts}</td><td><code>{kind}</code></td>"
            f"<td><span class='badge' style='background:{badge_bg}'>{status or '-'}</span></td>"
            f"<td><pre>{detail}</pre></td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8"/>
<title>Archon OS Receipt — {esc(task_id)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 1.25rem; margin-bottom: 1.25rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ border-bottom: 1px solid #334155; padding: 0.6rem; text-align: left; vertical-align: top; }}
  pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 0.82rem; color: #cbd5e1; }}
  .badge {{ padding: 2px 8px; border-radius: 999px; color: #fff; font-size: 0.75rem; }}
</style>
</head>
<body>
  <div class="card">
    <h1>Archon OS Session Receipt: {esc(title)}</h1>
    <p><strong>Task-ID:</strong> <code>{esc(task_id)}</code> | <strong>Schritte/Events:</strong> {len(events)}</p>
    <p><strong>Urspruenglicher Auftrag:</strong></p>
    <pre>{esc(original_ask)}</pre>
  </div>
  <div class="card">
    <h2>Ausfuehrungs- &amp; Belegkette (inkl. Retries &amp; Fehlversuche)</h2>
    <table>
      <thead><tr><th>#</th><th>Zeitpunkt</th><th>Event</th><th>Status</th><th>Details</th></tr></thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
  </div>
</body>
</html>"""
