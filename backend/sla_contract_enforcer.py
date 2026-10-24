"""
backend/sla_contract_enforcer.py
SLA- & Übergabe-Verträge zwischen Agenten (Contract Enforcement, Pillar 2 & 6).
Definiert verbindliche Liefergegenstände, Formate und Akzeptanzkriterien für interne Delegationen.
Weist unvollständige Teillieferungen autonom zurück.
"""

import os
import sys
import json
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(WORKSPACE_DIR, "data", "agentic_memory.db")

def _init_contracts_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA busy_timeout=5000;")
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_contracts (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                delegator_agent TEXT NOT NULL,
                assignee_agent TEXT NOT NULL,
                contract_terms_json TEXT NOT NULL,
                delivery_payload_json TEXT,
                compliance_status TEXT DEFAULT 'PENDING',
                violations_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                validated_at TIMESTAMP
            )
        """)
        conn.commit()
    conn.close()

_init_contracts_db()

class SLAContractEnforcer:
    def create_contract(
        self,
        task_id: str,
        delegator_agent: str,
        assignee_agent: str,
        required_keys: Optional[List[str]] = None,
        min_content_length: Optional[int] = None,
        acceptance_criteria: Optional[List[str]] = None,
        max_turnaround_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """Erstellt einen rechtsverbindlichen digitalen Übergabevertrag zwischen zwei Agenten."""
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("sla_contracts")
            if not cfg.get("enabled", True):
                return {"status": "disabled", "task_id": task_id, "message": "SLA-Vertragsprüfung ist in den Einstellungen deaktiviert."}
            if min_content_length is None:
                min_content_length = int(cfg.get("min_content_length", 100))
            if max_turnaround_minutes is None:
                max_turnaround_minutes = int(cfg.get("max_turnaround_minutes", 60))
        except Exception:
            min_content_length = min_content_length or 100
            max_turnaround_minutes = max_turnaround_minutes or 60

        contract_id = f"sla-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{task_id[:8]}"
        terms = {
            "required_keys": required_keys or ["summary", "result"],
            "min_content_length": min_content_length,
            "acceptance_criteria": acceptance_criteria or ["Quellenangaben vorhanden", "Fakten geprüft"],
            "max_turnaround_minutes": max_turnaround_minutes
        }

        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            with conn:
                conn.execute("""
                    INSERT INTO agent_contracts
                    (id, task_id, delegator_agent, assignee_agent, contract_terms_json, compliance_status, created_at)
                    VALUES (?, ?, ?, ?, ?, 'PENDING', CURRENT_TIMESTAMP)
                """, (contract_id, task_id, delegator_agent, assignee_agent, json.dumps(terms, ensure_ascii=False)))
                conn.commit()
            conn.close()

            return {
                "status": "success",
                "contract_id": contract_id,
                "task_id": task_id,
                "delegator": delegator_agent,
                "assignee": assignee_agent,
                "terms": terms
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def validate_delivery(self, contract_id: str, delivery_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validiert die übergebenen Ergebnisse gegen die Vertragskriterien.
        Gibt bei Nichterfüllung automatisch ein 'REJECTED' mit Mängelliste zurück.
        """
        auto_reject = True
        try:
            from backend.autonomy_settings import get_module_config
            cfg = get_module_config("sla_contracts")
            if not cfg.get("enabled", True):
                return {"status": "success", "contract_id": contract_id, "is_compliant": True, "verdict": "COMPLIANT_BYPASSED"}
            auto_reject = bool(cfg.get("auto_reject_incomplete", True))
        except Exception:
            pass

        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM agent_contracts WHERE id = ?", (contract_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return {"status": "error", "message": f"Vertrag '{contract_id}' nicht gefunden."}

            item = dict(row)
            terms = json.loads(item["contract_terms_json"])

            violations = []

            for k in terms.get("required_keys", []):
                if k not in delivery_payload or not delivery_payload[k]:
                    violations.append(f"Pflichtfeld '{k}' fehlt in der Übergabe.")

            min_len = terms.get("min_content_length", 100)
            text_rep = json.dumps(delivery_payload, ensure_ascii=False)
            if len(text_rep) < min_len:
                violations.append(f"Lieferumfang zu kurz ({len(text_rep)} Zeichen < gefordert: {min_len}).")

            is_compliant = (len(violations) == 0) or (not auto_reject)
            new_status = "COMPLIANT" if len(violations) == 0 else ("REJECTED_REVISION_REQUIRED" if auto_reject else "COMPLIANT_WITH_WARNINGS")

            with conn:
                conn.execute("""
                    UPDATE agent_contracts
                    SET delivery_payload_json = ?, compliance_status = ?, violations_json = ?, validated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (
                    json.dumps(delivery_payload, ensure_ascii=False),
                    new_status,
                    json.dumps(violations, ensure_ascii=False),
                    contract_id
                ))
                conn.commit()
            conn.close()

            return {
                "status": "success",
                "contract_id": contract_id,
                "is_compliant": is_compliant,
                "verdict": new_status,
                "violations_count": len(violations),
                "violations": violations,
                "action": "Abnahme erfolgt" if is_compliant else "Lieferung autonom abgelehnt. Nachbesserung angefordert."
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def list_contracts(self, limit: int = 25) -> List[Dict[str, Any]]:
        """Liefert die Historie der Agenten-Verträge."""
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM agent_contracts ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                try:
                    r["contract_terms_json"] = json.loads(r["contract_terms_json"])
                except Exception:
                    pass
                try:
                    r["violations_json"] = json.loads(r["violations_json"])
                except Exception:
                    pass
            conn.close()
            return rows
        except Exception:
            return []

sla_contract_enforcer = SLAContractEnforcer()
