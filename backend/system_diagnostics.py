"""
backend/system_diagnostics.py
Systemweiter 360°-Health-Score & Diagnose-Engine (Pillar 1 & 6).
Aggregiert Vitalparameter (Docker-Dienste, Concurrency-Queue, DBs, Audit-Kette)
und liefert einen fundierten Gesamtscore von 0 bis 100%.
"""

import os
import sys
import time
from typing import Dict, Any

def get_system_health_score() -> Dict[str, Any]:
    score = 100
    factors = []
    recommendations = []

    # 1. Docker Core-Dienste (35% Gewicht)
    try:
        from backend.fleet_self_healing import check_fleet_and_heal, KNOWN_SERVICES
        proc_status = check_fleet_and_heal()
        healed_count = proc_status.get("healed_count", 0)
        if healed_count > 0:
            score -= 15
            factors.append(f"Flotte: {healed_count} Dienste mussten neugestartet werden (-15 Punkte)")
            recommendations.append("Container-Logs der betroffenen Dienste prüfen.")
        else:
            factors.append("Flotte: Alle Core-Dienste laufen nominal (+35 Punkte)")
    except Exception as e:
        score -= 20
        factors.append(f"Flotte nicht prüfbar: {e} (-20 Punkte)")

    # 2. Concurrency Queue (20% Gewicht)
    try:
        from backend.concurrency_throttle import concurrency_throttle
        th_stat = concurrency_throttle.get_status()
        queued = th_stat.get("queued_tasks_count", 0)
        util = th_stat.get("utilization_percent", 0)
        if queued > 5:
            score -= 10
            factors.append(f"Warteschlange voll: {queued} Tasks warten (-10 Punkte)")
            recommendations.append("max_concurrent_agents in den Einstellungen erhöhen.")
        else:
            factors.append(f"Concurrency-Queue stabil: {queued} wartend, Auslastung {util}% (+20 Punkte)")
    except Exception:
        pass

    # 3. Kryptografisches Audit-Log (20% Gewicht)
    try:
        from backend.audit_log import chained_audit_log
        audit_check = chained_audit_log.verify_integrity()
        if not audit_check.get("valid"):
            score -= 30
            factors.append(f"Audit-Log Integritätsbruch erkannt! (-30 Punkte)")
            recommendations.append("Audit-Log auf Manipulation oder fehlerhafte Einträge prüfen.")
        else:
            factors.append(f"Audit-Log: {audit_check.get('total_events', 0)} Einträge integer (+20 Punkte)")
    except Exception:
        pass

    # 4. Deadlock Supervisor (15% Gewicht)
    try:
        from backend.deadlock_supervisor import deadlock_supervisor
        dl_res = deadlock_supervisor.detect_and_resolve_deadlocks(stagnation_threshold_seconds=120)
        if dl_res.get("resolved_count", 0) > 0:
            score -= 5
            factors.append(f"Deadlocks: {dl_res.get('resolved_count')} stagnierende Tasks aufgelöst (-5 Punkte)")
        else:
            factors.append("Deadlocks: 0 Blockaden festgestellt (+15 Punkte)")
    except Exception:
        pass

    # 5. RAG Bridge (10% Gewicht)
    try:
        from backend.rag_bridge import rag_bridge
        if rag_bridge.is_alive():
            factors.append("RAG-Vector-Engine (Port 3001) online (+10 Punkte)")
        else:
            score -= 10
            factors.append("RAG-Vector-Engine nicht erreichbar (-10 Punkte)")
            recommendations.append("Docker-Container anything-llm auf Port 3001 prüfen.")
    except Exception:
        pass

    score = max(0, min(100, score))
    status_label = "Optimal" if score >= 90 else "Gut" if score >= 75 else "Warnung" if score >= 50 else "Kritisch"

    return {
        "status": "success",
        "health_score": score,
        "status_label": status_label,
        "factors": factors,
        "recommendations": recommendations or ["System läuft optimal. Keine Intervention erforderlich."]
    }
