# -*- coding: utf-8 -*-
"""
backend/external_connectors.py
==============================
Meilenstein 87: Externe Fach-Connectoren
(inkly, local-business-leads, hermes-issue-sync, ghl-command).
"""

from __future__ import annotations

from typing import Any, Dict, List


CONNECTOR_REGISTRY: List[Dict[str, str]] = [
    {"id": "inkly", "domain": "eSignature", "description": "Vertrags-Signatur-Workflows aus Vorlagen/PDFs"},
    {"id": "local-business-leads", "domain": "Sales/Outreach", "description": "Normalisierte B2B-Lead-Listen fuer CRM"},
    {"id": "hermes-issue-sync", "domain": "DevOps/Kanban", "description": "2-Wege-Sync zwischen Kanban und Linear/Jira/GitHub"},
    {"id": "ghl-command", "domain": "CRM", "description": "GoHighLevel Kontakte, Deals & Pipeline-Sync"},
]

_KANBAN_TO_ISSUE_STATUS = {
    "todo": "open",
    "ready": "open",
    "in_progress": "in_progress",
    "blocked": "blocked",
    "done": "closed",
}


def list_connector_capabilities() -> List[Dict[str, str]]:
    return list(CONNECTOR_REGISTRY)


def prepare_esignature_envelope(doc_title: str, signer_name: str, signer_email: str, template_id: str = "") -> Dict[str, Any]:
    return {
        "connector": "inkly",
        "doc_title": doc_title,
        "signer": {"name": signer_name, "email": signer_email},
        "template_id": template_id,
        "status": "draft_ready_for_hitl",
    }


def normalize_local_lead(raw_lead: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "connector": "local-business-leads",
        "company": str(raw_lead.get("name") or raw_lead.get("company") or "").strip(),
        "phone": str(raw_lead.get("phone") or "").strip(),
        "email": str(raw_lead.get("email") or "").strip().lower(),
        "website": str(raw_lead.get("website") or "").strip(),
        "city": str(raw_lead.get("city") or "").strip(),
        "source": str(raw_lead.get("source") or "google_maps"),
    }


def map_kanban_to_issue(task: Dict[str, Any], target: str = "github") -> Dict[str, Any]:
    st = str(task.get("status") or "todo").lower()
    return {
        "connector": "hermes-issue-sync",
        "target": target,
        "external_status": _KANBAN_TO_ISSUE_STATUS.get(st, "open"),
        "title": task.get("title") or task.get("id"),
        "body": task.get("body") or "",
        "labels": ["archon-sync", f"assignee:{task.get('assignee', 'default')}"],
    }


def build_ghl_crm_payload(contact: Dict[str, Any], pipeline_stage: str = "qualified") -> Dict[str, Any]:
    return {
        "connector": "ghl-command",
        "firstName": contact.get("first_name") or "",
        "lastName": contact.get("last_name") or "",
        "email": contact.get("email") or "",
        "phone": contact.get("phone") or "",
        "pipelineStage": pipeline_stage,
    }
