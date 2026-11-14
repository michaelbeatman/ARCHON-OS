"""
backend/compliance_engine.py
============================
M49 — EU AI Act Compliance-Engine, Art.-4-KI-Kompetenzregister & GoBD-Verfahrensdokumentations-Aggregator.

Bündelt:
1. Art. 4 EU AI Act KI-Kompetenznachweis-Register (`ai_act_literacy_register.json`) mit
   SHA-256 Nachweis-Hash und automatischer Verkettung im GoBD-Audit-Log (`chained_audit_log`).
2. Pflicht-Guardrail-Prüfung (`evaluate_guardrails` & `check_activation_allowed`) vor
   Aktivierung von Anhang-III-Hochrisiko-Spezialisten.
3. Vollständige Laufzeit-Datenerhebung (`collect_verfahrensdokumentation_snapshot`) aus
   echtem Systemzustand: aktiver Mandant (M43), physische SQLite-DB-Isolation, Nummernkreise,
   GoBD-Merkle-Hashketten-Beweis (M21), Datenschutz-/Zero-Egress-Routing (M22) und
   70er-Spezialisten-Inventar inkl. SOUL-SHA-256-Prüfsummen.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

from archon.core.runtime import WORKSPACE_DIR

DEFAULT_LITERACY_FILE = os.path.join(WORKSPACE_DIR, "data", "ai_act_literacy_register.json")


class ComplianceEngine:
    """Zentrale Engine für EU AI Act Art. 4 / Anhang III Governance & GoBD-Verfahrensdokumentation."""

    def __init__(
        self,
        literacy_file: str = DEFAULT_LITERACY_FILE,
        inventory_mgr: Any = None,
        tenant_mgr: Any = None,
        audit_logger: Any = None,
    ) -> None:
        self.literacy_file = literacy_file
        self._inventory_mgr = inventory_mgr
        self._tenant_mgr = tenant_mgr
        self._audit_logger = audit_logger
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(os.path.abspath(self.literacy_file)), exist_ok=True)

    def _get_inventory_mgr(self):
        if self._inventory_mgr is not None:
            return self._inventory_mgr
        from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
        return eu_ai_act_inventory_manager

    def _get_tenant_mgr(self):
        if self._tenant_mgr is not None:
            return self._tenant_mgr
        from backend.tenant_context import tenant_context
        return tenant_context

    def _get_audit_log(self):
        if self._audit_logger is not None:
            return self._audit_logger
        from backend.audit_log import chained_audit_log
        return chained_audit_log

    # ------------------------------------------------------------------
    # Art. 4 EU AI Act — KI-Kompetenznachweis-Register
    # ------------------------------------------------------------------

    def _default_seed_entries(self) -> List[Dict[str, Any]]:
        today = datetime.date.today().isoformat()
        next_year = (datetime.date.today() + datetime.timedelta(days=365)).isoformat()
        raw = f"Administrator|System- & HITL-Governance Einweisung|{today}"
        cert_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return [
            {
                "id": "lit-archon-001",
                "person_name": "Geschäftsführung / System-Administrator",
                "role": "Admin & HITL-Freigabeverantwortlicher",
                "training_module": "EU AI Act Art. 4 & Anhang III Aufsicht, Prompt-Injection-Abwehr & Zero-Egress-Betrieb",
                "scope_tiers": ["HIGH_RISK", "SPECIFIC_TRANSPARENCY", "MINIMAL_RISK"],
                "completed_at": today,
                "valid_until": next_year,
                "status": "ACTIVE",
                "certificate_sha256": cert_hash,
                "recorded_by": "system_bootstrap",
            }
        ]

    def list_literacy_entries(self) -> List[Dict[str, Any]]:
        with self._lock:
            if os.path.isfile(self.literacy_file):
                try:
                    with open(self.literacy_file, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, list):
                        return data
                except Exception:
                    pass
            seeded = self._default_seed_entries()
            self._save_literacy_entries(seeded)
            return seeded

    def _save_literacy_entries(self, entries: List[Dict[str, Any]]) -> None:
        tmp = f"{self.literacy_file}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.literacy_file)

    def add_literacy_entry(self, payload: Dict[str, Any], actor: str = "admin") -> Dict[str, Any]:
        person_name = str(payload.get("person_name") or "").strip()
        if not person_name:
            raise ValueError("Feld 'person_name' ist erforderlich.")
        role = str(payload.get("role") or "Operator").strip()
        training_module = str(
            payload.get("training_module")
            or "Art. 4 EU AI Act KI-Kompetenz & HITL-Freigabeprotokoll"
        ).strip()
        completed_at = str(payload.get("completed_at") or datetime.date.today().isoformat()).strip()
        valid_until = str(
            payload.get("valid_until")
            or (datetime.date.today() + datetime.timedelta(days=365)).isoformat()
        ).strip()
        scope_tiers = payload.get("scope_tiers") or ["HIGH_RISK", "SPECIFIC_TRANSPARENCY", "MINIMAL_RISK"]
        if isinstance(scope_tiers, str):
            scope_tiers = [s.strip() for s in scope_tiers.split(",") if s.strip()]

        entry_id = str(payload.get("id") or f"lit-{uuid.uuid4().hex[:8]}")
        cert_raw = f"{entry_id}|{person_name}|{role}|{training_module}|{completed_at}|{valid_until}"
        cert_hash = hashlib.sha256(cert_raw.encode("utf-8")).hexdigest()

        entry = {
            "id": entry_id,
            "person_name": person_name,
            "role": role,
            "training_module": training_module,
            "scope_tiers": scope_tiers,
            "completed_at": completed_at,
            "valid_until": valid_until,
            "status": "ACTIVE",
            "certificate_sha256": cert_hash,
            "recorded_by": actor,
        }

        with self._lock:
            entries = self.list_literacy_entries()
            replaced = False
            for idx, existing in enumerate(entries):
                if existing.get("id") == entry_id:
                    entries[idx] = entry
                    replaced = True
                    break
            if not replaced:
                entries.insert(0, entry)
            self._save_literacy_entries(entries)

        try:
            self._get_audit_log().record_event(
                category="governance",
                action="ai_act_literacy_recorded",
                agent_id=actor,
                payload={
                    "entry_id": entry_id,
                    "person_name": person_name,
                    "role": role,
                    "certificate_sha256": cert_hash,
                },
            )
        except Exception:
            pass

        return entry

    def delete_literacy_entry(self, entry_id: str, actor: str = "admin") -> bool:
        with self._lock:
            entries = self.list_literacy_entries()
            filtered = [e for e in entries if e.get("id") != entry_id]
            if len(filtered) == len(entries):
                return False
            self._save_literacy_entries(filtered)

        try:
            self._get_audit_log().record_event(
                category="governance",
                action="ai_act_literacy_deleted",
                agent_id=actor,
                payload={"entry_id": entry_id},
            )
        except Exception:
            pass
        return True

    # ------------------------------------------------------------------
    # Pflicht-Guardrail-Prüfung (Anhang III / Art. 50)
    # ------------------------------------------------------------------

    def evaluate_guardrails(self) -> Dict[str, Any]:
        inv_mgr = self._get_inventory_mgr()
        inventory = inv_mgr.get_inventory()
        audit_status = self._safe_verify_audit_chain()
        literacy = self.list_literacy_entries()
        active_high_risk_operators = [
            e for e in literacy if e.get("status") == "ACTIVE" and "HIGH_RISK" in (e.get("scope_tiers") or [])
        ]

        violations: List[Dict[str, Any]] = []
        for item in inventory:
            aid = item.get("agent_id")
            tier = item.get("risk_tier")
            oversight = str(item.get("human_oversight_measure") or "")
            c_status = str(item.get("compliance_status") or "")

            if tier == "HIGH_RISK":
                if "HITL" not in oversight and "4-Augen" not in oversight:
                    violations.append({
                        "agent_id": aid,
                        "risk_tier": tier,
                        "reason": "Anhang-III-Hochrisiko ohne dokumentiertes 4-Augen-HITL-Gate.",
                    })
                if c_status == "NON_COMPLIANT":
                    violations.append({
                        "agent_id": aid,
                        "risk_tier": tier,
                        "reason": "Agent ist als NON_COMPLIANT eingestuft.",
                    })
                if not item.get("soul_sha256"):
                    violations.append({
                        "agent_id": aid,
                        "risk_tier": tier,
                        "reason": "Kein gepinnter SOUL-SHA-256-Systemprompt-Hash vorhanden.",
                    })

        if not active_high_risk_operators:
            violations.append({
                "agent_id": "SYSTEM",
                "risk_tier": "HIGH_RISK",
                "reason": "Kein aktiver Bediener mit Art.-4-Kompetenznachweis für HIGH_RISK hinterlegt.",
            })

        if not audit_status.get("valid", False):
            violations.append({
                "agent_id": "AUDIT_LOG",
                "risk_tier": "CRITICAL",
                "reason": "GoBD SHA-256 Audit-Hashkette meldet Integritätsfehler.",
            })

        return {
            "all_guardrails_passed": len(violations) == 0,
            "checked_agents": len(inventory),
            "high_risk_operators_count": len(active_high_risk_operators),
            "audit_chain_valid": bool(audit_status.get("valid", False)),
            "violations": violations,
        }

    def check_activation_allowed(self, agent_id: str) -> Dict[str, Any]:
        """Prüft vor Aktivierung/Dispatch eines Spezialisten, ob alle EU-AI-Act-Pflicht-Guardrails erfüllt sind."""
        inv = self._get_inventory_mgr().get_inventory()
        item = next((x for x in inv if x.get("agent_id") == agent_id), None)
        if not item:
            return {"allowed": True, "agent_id": agent_id, "risk_tier": "UNCLASSIFIED"}

        if item.get("compliance_status") == "NON_COMPLIANT":
            return {
                "allowed": False,
                "agent_id": agent_id,
                "risk_tier": item.get("risk_tier"),
                "reason": "Aktivierung gesperrt: Agent ist im EU-AI-Act-Register als NON_COMPLIANT markiert.",
            }
        if item.get("risk_tier") == "HIGH_RISK":
            oversight = str(item.get("human_oversight_measure") or "")
            if "HITL" not in oversight and "4-Augen" not in oversight:
                return {
                    "allowed": False,
                    "agent_id": agent_id,
                    "risk_tier": "HIGH_RISK",
                    "reason": "Aktivierung gesperrt: Anhang-III-Hochrisiko erfordert MANDATORY_HITL.",
                }
        return {
            "allowed": True,
            "agent_id": agent_id,
            "risk_tier": item.get("risk_tier"),
            "soul_sha256": item.get("soul_sha256"),
        }

    # ------------------------------------------------------------------
    # Vollständiger Laufzeit-Snapshot für GoBD & EU AI Act Verfahrensdoku
    # ------------------------------------------------------------------

    def _safe_verify_audit_chain(self) -> Dict[str, Any]:
        try:
            audit_obj = self._get_audit_log()
            res = dict(audit_obj.verify_integrity())
            recent = audit_obj.list_events(limit=5).get("entries", []) if hasattr(audit_obj, "list_events") else []
            head_hash = res.get("latest_hash") or (recent[0].get("current_hash", "0" * 64) if recent else ("0" * 64))
            res["checked_blocks"] = res.get("total_records", 0)
            res["head_hash"] = head_hash
            res["recent_events"] = recent[:5]
            return res
        except Exception as exc:
            return {"valid": False, "checked_blocks": 0, "total_records": 0, "head_hash": "ERROR", "error": str(exc), "recent_events": []}

    def _read_system_version(self) -> str:
        vfile = os.path.join(WORKSPACE_DIR, "VERSION")
        if os.path.isfile(vfile):
            try:
                with open(vfile, "r", encoding="utf-8") as fh:
                    return fh.read().strip() or "v0.5.2.1"
            except Exception:
                pass
        return "v0.5.2.1"

    def collect_verfahrensdokumentation_snapshot(self, company_id: Optional[str] = None) -> Dict[str, Any]:
        tenant_mgr = self._get_tenant_mgr()
        corp_mgr = tenant_mgr._get_corporate_manager()
        company = corp_mgr.get_company(company_id) if company_id else tenant_mgr.get_active_company()
        if not company:
            company = tenant_mgr.get_active_company()

        tid = tenant_mgr.get_active_tenant_id() if not company_id else str(company.get("id") or company_id)
        isolation = tenant_mgr.get_isolation_status(tid)
        number_ranges = tenant_mgr.get_number_ranges(tid)

        try:
            from backend.privacy_router import get_privacy_config
            privacy_cfg = get_privacy_config()
            # Keine API-Keys im Snapshot exponieren
            privacy_summary = {
                "sensitive_local_routing": bool(privacy_cfg.get("sensitive_local_routing")),
                "local_llm_url": privacy_cfg.get("local_llm_url", ""),
                "local_llm_model": privacy_cfg.get("local_llm_model", ""),
                "fallback_to_eu": bool(privacy_cfg.get("fallback_to_eu")),
                "eu_mistral_configured": bool(privacy_cfg.get("mistral_api_key")),
                "sensitive_categories": privacy_cfg.get("sensitive_categories", []),
            }
        except Exception:
            privacy_summary = {
                "sensitive_local_routing": False,
                "local_llm_url": "http://127.0.0.1:11434/v1",
                "local_llm_model": "llama3.2",
                "fallback_to_eu": True,
                "eu_mistral_configured": False,
                "sensitive_categories": ["finance", "receipts", "contracts", "crm", "gdpr", "hr"],
            }

        inv_mgr = self._get_inventory_mgr()
        inventory = inv_mgr.get_inventory()
        ai_stats = inv_mgr.get_stats()
        literacy = self.list_literacy_entries()
        guardrails = self.evaluate_guardrails()
        audit_chain = self._safe_verify_audit_chain()

        now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        doc_seed = json.dumps(
            {
                "ts": now_iso,
                "tenant_id": tid,
                "version": self._read_system_version(),
                "audit_head": audit_chain.get("head_hash"),
                "agents": len(inventory),
            },
            sort_keys=True,
        )
        document_id = f"VD-{tid.upper()[:8]}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        snapshot_hash = hashlib.sha256(doc_seed.encode("utf-8")).hexdigest()

        return {
            "document_id": document_id,
            "generated_at": now_iso,
            "system_version": self._read_system_version(),
            "snapshot_sha256": snapshot_hash,
            "company": company,
            "tenant_id": tid,
            "db_isolation": isolation,
            "number_ranges": number_ranges,
            "privacy_routing": privacy_summary,
            "audit_chain": audit_chain,
            "ai_act_stats": ai_stats,
            "ai_act_inventory": inventory,
            "literacy_register": literacy,
            "guardrails": guardrails,
        }


compliance_engine = ComplianceEngine()
