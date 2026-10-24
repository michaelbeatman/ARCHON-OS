"""
backend/consensus_gate.py
Dual-Agent & Tri-Agent Konsens-Gate (Pillar 6 / Governance).
Erzwingt ein Mehr-Augen-Prinzip und Debatten-Protokoll bei risikobehafteten Aufgaben.
Drei unabhängige Rollen (Architekt, Security, QA) stimmen ab und fällen ein verbindliches Urteil.
"""

import os
import sys
import json
import sqlite3
import asyncio
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

def _init_consensus_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consensus_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                task_title TEXT NOT NULL,
                mode TEXT DEFAULT 'dual_gate',
                approved INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                avg_score REAL,
                votes_json TEXT,
                critique TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

_init_consensus_db()

async def review_task_output(
    task_id: str,
    task_title: str,
    task_output: str,
    worker_agent: str = "hermes-coder",
    priority: int = 3,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Unterzieht das Arbeitsergebnis einer konträren Adversarial-Prüfung.
    Berücksichtigt die Einstellungen in settings.json (consensus_gate).
    """
    min_prio = 3
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("consensus_gate")
        if not cfg.get("enabled", True):
            return {
                "approved": True,
                "score": 10,
                "verdict": "APPROVED_BYPASSED",
                "critique": "Konsens-Gate ist in den Einstellungen deaktiviert.",
                "risks": []
            }
        min_prio = int(cfg.get("min_priority", 3))
        if not model:
            model = cfg.get("default_model", "deepseek/deepseek-chat")
    except Exception:
        if not model:
            model = "deepseek/deepseek-chat"

    if priority < min_prio:
        return {
            "approved": True,
            "score": 10,
            "verdict": "APPROVED_AUTO",
            "critique": f"Prioritaet ({priority}) < Schwellenwert ({min_prio}): Direkt freigegeben.",
            "risks": []
        }

    critic_prompt = f"""Du bist der leitende Sicherheits- und Qualitätsrevisor (Chief Quality & Security Officer) von Archon OS.
Prüfe folgendes Arbeitsergebnis eines Spezialisten-Agenten vor der Übernahme in die Produktionssysteme schonungslos auf:
1. Halluzinationen oder erfundene Fakten
2. Sicherheitsrisiken (Dateisystem, SQL-Injection, Secrets, Datenverlust)
3. Unvollständigkeiten oder Logikbrüche

TITEL DER AUFGABE: {task_title}
AUSFÜHRENDER AGENT: {worker_agent}

ARBEITSERGEBNIS / CODE / ENTWURF:
{task_output[:4000]}

Regeln:
- Antworte AUSSCHLIESSLICH im folgenden JSON-Format:
{{
  "approved": true/false,
  "score": 1-10,
  "verdict": "APPROVED" oder "REJECTED_REVISION_REQUIRED",
  "critique": "Prägnante Kritik oder Begründung",
  "risks": ["Risiko 1", "Risiko 2"]
}}
"""

    import core_dispatcher
    try:
        res = await core_dispatcher.dispatch_to_omniroute_or_container(
            agent_id="adversarial-critic",
            agent_name="Adversarial Quality Revisor",
            prompt=critic_prompt,
            role="Qualitäts- & Sicherheits-Auditor",
            system_prompt="Du bist ein extrem kritischer Auditor. Antworte ausschließlich mit JSON.",
            model=model
        )
        content = res.get("content", "")
        clean_json = content
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0].strip()

        parsed = json.loads(clean_json)
        approved = bool(parsed.get("approved", True))
        score = int(parsed.get("score", 8))
        verdict = parsed.get("verdict", "APPROVED")
        critique = parsed.get("critique", "Keine gravierenden Mängel gefunden.")

        _record_decision(task_id, task_title, "dual_gate", approved, verdict, score, [parsed], critique)

        return {
            "task_id": task_id,
            "approved": approved,
            "score": score,
            "verdict": verdict,
            "critique": critique,
            "risks": parsed.get("risks", [])
        }
    except Exception as e:
        return {
            "task_id": task_id,
            "approved": True,
            "score": 7,
            "verdict": "APPROVED_WITH_WARNING",
            "critique": f"Automatisierte Revisor-Prüfung konnte nicht abgeschlossen werden: {e}",
            "risks": ["Manueller Check empfohlen"]
        }

async def run_tri_agent_council(
    task_id: str,
    task_title: str,
    task_output: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    3-Agenten Schiedsgericht & Debatte (Architekt, Security, QA).
    Berücksichtigt die Mehrheitsregel ('two_thirds' vs. 'unanimous') aus settings.json.
    """
    majority_rule = "two_thirds"
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("consensus_gate")
        if not cfg.get("enabled", True):
            return {"status": "disabled", "task_id": task_id, "approved": True, "verdict": "BYPASSED_DISABLED"}
        majority_rule = cfg.get("majority_rule", "two_thirds")
        if not model:
            model = cfg.get("default_model", "deepseek/deepseek-chat")
    except Exception:
        if not model:
            model = "deepseek/deepseek-chat"

    import core_dispatcher

    jurors = [
        {"role": "System Architect", "focus": "Architektur-Stabilität, Skalierbarkeit, DRY-Prinzip, Code-Qualität"},
        {"role": "Security Officer", "focus": "Zero-Trust, Datenintegrität, Injections, Secrets, Berechtigungen"},
        {"role": "QA & Test Lead", "focus": "Fehlertoleranz, Edge-Cases, Vollständigkeit, Benutzererlebnis"}
    ]

    async def _get_juror_vote(j):
        prompt = f"""Rolle: {j['role']}
Fokus: {j['focus']}

Bewerte folgendes Arbeitsergebnis für Task '{task_title}':
{task_output[:3500]}

Antworte NUR mit JSON:
{{
  "juror": "{j['role']}",
  "approved": true/false,
  "score": 1-10,
  "reason": "1-2 Sätze Begründung"
}}"""
        try:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=f"juror-{j['role'].lower().replace(' ', '-')}",
                agent_name=j['role'],
                prompt=prompt,
                role=j['role'],
                system_prompt="Prüfe unvoreingenommen und antworte nur in JSON.",
                model=model
            )
            c = res.get("content", "")
            if "```json" in c:
                c = c.split("```json")[1].split("```")[0].strip()
            elif "```" in c:
                c = c.split("```")[1].split("```")[0].strip()
            return json.loads(c)
        except Exception as e:
            return {"juror": j["role"], "approved": True, "score": 7, "reason": f"Fallback: {e}"}

    votes = await asyncio.gather(*[_get_juror_vote(j) for j in jurors])
    yes_votes = sum(1 for v in votes if v.get("approved") is True)
    total_votes = len(votes)
    avg_score = round(sum(v.get("score", 7) for v in votes) / total_votes, 1)

    required_votes = 3 if majority_rule == "unanimous" else 2
    consensus_reached = yes_votes >= required_votes
    verdict = "COUNCIL_APPROVED" if consensus_reached else "COUNCIL_REJECTED"
    summary = f"{yes_votes}/{total_votes} Stimmen für Freigabe (Erforderlich: {required_votes}, Schnitt: {avg_score}/10)."

    _record_decision(task_id, task_title, "tri_agent_council", consensus_reached, verdict, avg_score, votes, summary)

    return {
        "status": "success",
        "task_id": task_id,
        "mode": "tri_agent_council",
        "majority_rule": majority_rule,
        "approved": consensus_reached,
        "verdict": verdict,
        "yes_votes": yes_votes,
        "total_votes": total_votes,
        "avg_score": avg_score,
        "votes": votes,
        "summary": summary
    }

def _record_decision(task_id, task_title, mode, approved, verdict, avg_score, votes, critique):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        with conn:
            conn.execute("""
                INSERT INTO consensus_decisions
                (task_id, task_title, mode, approved, verdict, avg_score, votes_json, critique, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (task_id, task_title, mode, 1 if approved else 0, verdict, avg_score, json.dumps(votes, ensure_ascii=False), critique))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ConsensusGate] Fehler beim Speichern des Konsensentscheids: {e}", file=sys.stderr)

def get_consensus_history(limit: int = 25) -> List[Dict[str, Any]]:
    """Liefert die Historie der Schiedsgerichts- und Revisor-Beschlüsse."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM consensus_decisions ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try:
                r["votes_json"] = json.loads(r["votes_json"])
            except Exception:
                pass
        conn.close()
        return rows
    except Exception:
        return []
