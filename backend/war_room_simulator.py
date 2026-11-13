"""
backend/war_room_simulator.py
Virtueller Pre-Mortem Stresstest & War-Room-Simulation (Pillar 6 & 7).
Simuliert vor kritischen Veröffentlichungen gegnerische Parteien
(skeptischer Kunde, Pentester/Angreifer, Compliance-Auditor) und erstellt eine Risiko-Matrix.
"""

import os
import sys
import json
import sqlite3
import asyncio
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

def _init_war_room_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS war_room_simulations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                plan_summary TEXT,
                overall_risk_level TEXT NOT NULL,
                simulation_json TEXT NOT NULL,
                mitigation_advice TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

_init_war_room_db()

async def run_war_room_simulation(
    topic: str,
    proposal_text: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    Führt einen 3-Parteien-Stresstest (Kunde, Pentester, Compliance) durch.
    Berücksichtigt die War-Room-Einstellungen (block_threshold, enabled) aus settings.json.
    """
    block_threshold = "HIGH"
    try:
        from backend.autonomy_settings import get_module_config
        cfg = get_module_config("war_room")
        if not cfg.get("enabled", True):
            return {"status": "disabled", "topic": topic, "overall_risk_level": "LOW", "recommendation": "War-Room ist in den Einstellungen deaktiviert."}
        block_threshold = cfg.get("block_threshold", "HIGH")
        if not model:
            model = cfg.get("default_model", "deepseek/deepseek-chat")
    except Exception:
        if not model:
            model = "deepseek/deepseek-chat"

    import core_dispatcher

    roles = [
        {
            "name": "Kritischer Großkunde",
            "perspective": "Fokus auf Usability-Verwirrung, versteckte Kosten, Performance-Einbußen und Churn-Gründe."
        },
        {
            "name": "Offensiver Pentester / Red-Teamer",
            "perspective": "Fokus auf Angriffsvektoren, Datenabfluss, Rechte-Eskalation, Race-Conditions und Denial-of-Service."
        },
        {
            "name": "Strenger DSGVO- & Compliance-Auditor",
            "perspective": "Fokus auf Haftungsrisiken, Dokumentationspflichten, Datenübermittlung und rechtliche Grauzonen."
        }
    ]

    async def _attack(r):
        prompt = f"""Du nimmst im Archon War Room die folgende Rolle ein:
ROLLE: {r['name']}
PERSPEKTIVE: {r['perspective']}

GEPLANTES VORHABEN / ENTWURF:
Thema: {topic}
Details:
{proposal_text[:3500]}

AUFGABE:
Führe einen schonungslosen Pre-Mortem-Stresstest durch. Wo wird dieser Plan in der Praxis scheitern?
Antworte AUSSCHLIESSLICH im folgenden JSON-Format:
{{
  "adversary": "{r['name']}",
  "risk_rating": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "top_vulnerabilities": ["Punkt 1", "Punkt 2"],
  "worst_case_scenario": "Was passiert im schlimmsten Fall?",
  "mandatory_fix": "Was muss zwingend geändert werden?"
}}"""
        try:
            res = await core_dispatcher.dispatch_to_omniroute_or_container(
                agent_id=f"war-room-{r['name'][:10].lower()}",
                agent_name=r['name'],
                prompt=prompt,
                role=r['name'],
                system_prompt="Du bist ein gnadenloser Kritiker im Pre-Mortem-Stresstest. Antworte nur in JSON.",
                model=model
            )
            c = res.get("content", "")
            if "```json" in c:
                c = c.split("```json")[1].split("```")[0].strip()
            elif "```" in c:
                c = c.split("```")[1].split("```")[0].strip()
            return json.loads(c)
        except Exception as e:
            return {
                "adversary": r["name"],
                "risk_rating": "MEDIUM",
                "top_vulnerabilities": [f"Simulation-Fallback: {e}"],
                "worst_case_scenario": "Unbekannte Risiken durch Provider-Timeout",
                "mandatory_fix": "Manueller Pre-Mortem Check erforderlich"
            }

    results = await asyncio.gather(*[_attack(r) for r in roles])

    ratings = [res.get("risk_rating", "MEDIUM") for res in results]
    if "CRITICAL" in ratings:
        overall_risk = "CRITICAL"
    elif "HIGH" in ratings:
        overall_risk = "HIGH"
    elif "MEDIUM" in ratings:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"

    risk_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    should_block = risk_order.get(overall_risk, 2) >= risk_order.get(block_threshold, 3)

    mitigations = [res.get("mandatory_fix", "") for res in results if res.get("mandatory_fix")]
    mitigation_text = "\n".join(f"• {m}" for m in mitigations)

    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        with conn:
            conn.execute("""
                INSERT INTO war_room_simulations 
                (topic, plan_summary, overall_risk_level, simulation_json, mitigation_advice, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (topic[:250], proposal_text[:500], overall_risk, json.dumps(results, ensure_ascii=False), mitigation_text))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WarRoomSimulator] Fehler beim Speichern: {e}", file=sys.stderr)

    return {
        "status": "success",
        "topic": topic,
        "overall_risk_level": overall_risk,
        "block_threshold": block_threshold,
        "blocked": should_block,
        "adversary_evaluations": results,
        "mitigation_plan": mitigations,
        "recommendation": "STOPP & ÜBERARBEITUNG: Risiko überschreitet Schwellenwert!" if should_block else "Freigabe empfohlen mit Auflagen"
    }

def get_war_room_history(limit: int = 20) -> List[Dict[str, Any]]:
    """Liefert vergangene Stresstest-Simulationen."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM war_room_simulations ORDER BY id DESC LIMIT ?", (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try:
                r["simulation_json"] = json.loads(r["simulation_json"])
            except Exception:
                pass
        conn.close()
        return rows
    except Exception:
        return []
