"""
backend/war_room_simulator.py
Virtueller Pre-Mortem Stresstest & War-Room-Simulation (Pillar 6 & 7).
Simuliert vor kritischen Veröffentlichungen gegnerische Parteien
(skeptischer Kunde, Pentester/Angreifer, Compliance-Auditor) und erstellt eine Risiko-Matrix.
"""
import logging
_archon_exc_logger = logging.getLogger("war_room_simulator")

import os
import sys
import time
import json
import sqlite3
import asyncio
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
try:
    from backend.db_paths import resolve_db as _resolve_db
    DB_PATH = _resolve_db("agentic_memory.db")
except Exception:
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

async def _enforce_hitl_block(
    *,
    topic: str,
    overall_risk: str,
    mitigation_text: str,
    task_id: Optional[str],
) -> Dict[str, Any]:
    """blocked=True ist eine echte HITL-Blockade, keine blosse Empfehlung.

    Es wird eine Freigabe-Entscheidung im Kanban angelegt und — falls ein
    task_id uebergeben wurde — der betroffene Task auf 'blocked' gesetzt.
    """
    enforcement: Dict[str, Any] = {"decision_created": False, "task_blocked": False}
    ref_id = f"war-room:{int(time.time())}:{topic[:60]}"
    try:
        from archon.routers.decisions import create_decision

        decision = await asyncio.to_thread(
            create_decision,
            typ="mission_freigabe",
            titel=f"HITL-Sperre War-Room: {topic[:100]}"[:180],
            kurzfassung=(f"War-Room-Risiko {overall_risk}. Freigabe erforderlich.\n{mitigation_text}")[:600],
            ref_id=ref_id,
            extra={"war_room": {"topic": topic[:250], "risk": overall_risk, "mitigations": mitigation_text[:1000]}},
        )
        enforcement["decision_created"] = bool(decision)
        enforcement["decision"] = decision or None
    except Exception as exc:
        enforcement["decision_error"] = str(exc)[:300]

    if task_id:
        try:
            from backend.workflow_dag_runner import _update_kanban_task_status

            await asyncio.to_thread(
                _update_kanban_task_status,
                task_id,
                "blocked",
                result=f"War-Room blockiert bei Risiko {overall_risk}: {mitigation_text[:500]}",
                block_kind="war_room_risk",
            )
            enforcement["task_blocked"] = True
            enforcement["task_id"] = task_id
        except Exception as exc:
            enforcement["task_block_error"] = str(exc)[:300]
    return enforcement


async def run_war_room_simulation(
    topic: str,
    proposal_text: str,
    model: Optional[str] = None,
    task_id: Optional[str] = None,
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
            # Audit D01: früher wurde hier ein MEDIUM-Risiko erfunden, das
            # anschließend echte HITL-Blockaden ausgelöst hat. Bewusst UNKNOWN
            # und evaluation_failed — nie ein erfundener Risikowert.
            return {
                "adversary": r["name"],
                "risk_rating": "UNKNOWN",
                "evaluation_failed": True,
                "top_vulnerabilities": [f"Simulation fehlgeschlagen: {e}"],
                "worst_case_scenario": "Nicht bewertet (Provider/Parser-Fehler)",
                "mandatory_fix": "Manueller Pre-Mortem Check vor Freigabe erforderlich"
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
    evaluation_failed = any(bool(res.get("evaluation_failed")) for res in results)
    if evaluation_failed:
        overall_risk = "UNKNOWN"
    # Fail-closed: eine fehlgeschlagene Bewertung blockiert immer, statt als
    # MEDIUM durchzuwinken und eine Scheinfreigabe zu erzeugen.
    should_block = evaluation_failed or (risk_order.get(overall_risk, 4) >= risk_order.get(block_threshold, 3))

    mitigations = [res.get("mandatory_fix", "") for res in results if res.get("mandatory_fix")]
    mitigation_text = "\n".join(f"• {m}" for m in mitigations)

    def _persist_war_room():
        conn = sqlite3.connect(DB_PATH, timeout=5.0)
        try:
            with conn:
                conn.execute("""
                    INSERT INTO war_room_simulations 
                    (topic, plan_summary, overall_risk_level, simulation_json, mitigation_advice, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (topic[:250], proposal_text[:500], overall_risk, json.dumps(results, ensure_ascii=False), mitigation_text))
                conn.commit()
        finally:
            conn.close()

    try:
        await asyncio.to_thread(_persist_war_room)
    except Exception as e:
        print(f"[WarRoomSimulator] Fehler beim Speichern: {e}", file=sys.stderr)

    hitl = None
    if should_block:
        hitl = await _enforce_hitl_block(
            topic=topic,
            overall_risk=overall_risk,
            mitigation_text=mitigation_text,
            task_id=task_id,
        )

    return {
        "status": "incomplete" if evaluation_failed else "success",
        "evaluation_failed": evaluation_failed,
        "topic": topic,
        "overall_risk_level": overall_risk,
        "block_threshold": block_threshold,
        "blocked": should_block,
        "hitl_enforcement": hitl,
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
            except Exception as _exc:
                _archon_exc_logger.debug("[war_room_simulator] Ignorierte Ausnahme (Z.183): %s", _exc)
        conn.close()
        return rows
    except Exception:
        return []
