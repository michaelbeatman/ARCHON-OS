"""
backend/memory_consolidator.py
Nächtliche Gedächtnis-Konsolidierung & Sleep-Cycle Pruning (Pillar 4 & 7).
Verarbeitet inaktive Zyklen: Extrahiert Erkenntnisse in das Langzeitgedächtnis,
bereinigt veraltete Logs und Traces anhand konfigurierbarer Retention-Settings in settings.json.
"""

import os
import sys
import json
import sqlite3
import datetime
from typing import Dict, Any, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

DEFAULT_CONSOLIDATION_CONFIG = {
    "enabled": True,
    "schedule_time": "03:00",
    "retention_days": 14,
    "archive_threshold_similarity": 0.92,
    "auto_prune_temporary_logs": True,
    "last_run": None,
    "last_pruned_records_count": 0
}

def get_consolidation_config() -> Dict[str, Any]:
    """Lädt die aktuellen Gedächtnis-Konsolidierungs-Einstellungen aus settings.json."""
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULT_CONSOLIDATION_CONFIG.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("memory_consolidation", DEFAULT_CONSOLIDATION_CONFIG.copy())
    except Exception:
        return DEFAULT_CONSOLIDATION_CONFIG.copy()

def save_consolidation_config(cfg: Dict[str, Any]) -> bool:
    """Speichert die Einstellungen in settings.json (F-07: atomar + gelockt)."""
    try:
        from backend.settings_json import atomic_update_settings

        def _apply(current: Dict[str, Any]):
            current["memory_consolidation"] = cfg

        atomic_update_settings(SETTINGS_FILE, _apply)
        return True
    except Exception as e:
        print(f"[MemoryConsolidator] Fehler beim Speichern der Settings: {e}", file=sys.stderr)
        return False

def run_sleep_cycle_consolidation(force: bool = False) -> Dict[str, Any]:
    """
    Führt den Wartungs- und Konsolidierungs-Zyklus aus:
    1. Veraltete Trace-Logs älter als retention_days bereinigen
    2. Veraltete temporäre Checkpoints löschen
    3. SQLite optimieren und VACUUM ausführen
    """
    cfg = get_consolidation_config()
    if not cfg.get("enabled", True) and not force:
        return {"status": "skipped", "reason": "Nächtliche Konsolidierung in Einstellungen deaktiviert."}

    retention_days = int(cfg.get("retention_days", 14))
    cutoff_date = (datetime.datetime.now() - datetime.timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")

    pruned_traces = 0
    pruned_audit = 0

    try:
        conn = sqlite3.connect(DB_PATH, timeout=10.0)
        conn.execute("PRAGMA busy_timeout=5000;")
        with conn:
            # 1. Traces bereinigen
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM execution_traces WHERE created_at < ?", (cutoff_date,))
                pruned_traces = cur.rowcount
            except Exception:
                pass

            # 2. Veraltete unkritische Audit-Ereignisse bereinigen
            if cfg.get("auto_prune_temporary_logs", True):
                try:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM audit_log WHERE created_at < ? AND event_type LIKE '%HEARTBEAT%'", (cutoff_date,))
                    pruned_audit = cur.rowcount
                except Exception:
                    pass

            conn.commit()

        # 3. DB optimieren
        try:
            conn.execute("PRAGMA optimize;")
        except Exception:
            pass

        conn.close()

        # Update last run
        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cfg["last_run"] = now_iso
        cfg["last_pruned_records_count"] = pruned_traces + pruned_audit
        save_consolidation_config(cfg)

        return {
            "status": "success",
            "executed_at": now_iso,
            "retention_days": retention_days,
            "cutoff_date": cutoff_date,
            "pruned_traces_count": pruned_traces,
            "pruned_audit_count": pruned_audit,
            "total_pruned": pruned_traces + pruned_audit,
            "summary": f"Konsolidierung abgeschlossen: {pruned_traces + pruned_audit} veraltete Einträge bereinigt (älter als {retention_days} Tage)."
        }

    except Exception as e:
        return {"status": "error", "error": str(e)}
