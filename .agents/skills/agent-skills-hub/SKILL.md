---
name: agent-skills-hub
description: Integration of autonomous workflow execution scripts and trigger-action mappings from agentskillshub.dev for Archon OS.
---

# Agent Skills Hub (Automation & Workflow)

Ermöglicht die autonome Steuerung komplexer mehrstufiger Automatisierungsprozesse basierend auf den Standards von `agentskillshub.dev`.

## Funktionsweise & Mappings
- **Trigger-Action Routing:** Eingehende Ereignisse (z. B. CRM-Updates, Webhook-Pings, neue Vorlagen) werden anhand einer konfigurierbaren Matrix an spezialisierte Sub-Agenten oder Automations-Skripte weitergeleitet.
- **Zustands-Tracking:** Verfolgung des Task-Status gemäß Säule 2 des Archon OS Manifests (`pending` -> `in_progress` -> `completed` / `failed`).
- **Idempotenz:** Ausführungsschlüssel verhindern doppelte Ausführungen bei wiederholten Webhook-Triggern.

## Schnittstellen
- **Registry:** Skripte werden dynamisch geladen und über die standardisierte Archon `core_skills_engine.py` registriert.
- **Governance:** Direkte Fehlermeldung bei Schema-Verletzungen ohne unkontrollierte Nebeneffekte.
