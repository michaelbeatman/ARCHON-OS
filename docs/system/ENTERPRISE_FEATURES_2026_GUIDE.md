# Archon OS Handbuch — Enterprise-, Governance- & Operations-Erweiterungen (M25, M43, M44, M48, M49, M51, M52, M53)

Dieses Handbuch-Kapitel beschreibt die neu ergänzten Module, API-Endpunkte, UI-Einstiege und relevanten Einstellungen.

---

## 1. Nativer MCP-Server (`/mcp` Gateway — M48)
- **Endpunkte:** `POST /mcp` (Streamable HTTP JSON-RPC 2.0), `GET /mcp` / `/mcp/sse` (SSE), `DELETE /mcp`, `GET /mcp/info` (Client-Snippets für Claude Desktop, Cursor, VS Code).
- **Sicherheit:** Scoped API-Keys (`Authorization: Bearer archon_live_...` oder `X-Archon-API-Key`) mit den Berechtigungen `read_only`, `kanban_rw`, `agent_execute`, `admin_full`.
- **HITL-Gate:** `archon__trigger_boardroom_debate` und `archon__ask_specialist` erzeugen bei aktiver Policy zunächst eine `pending_hitl_approval`-Anfrage (`request_id`) und werden erst nach Freigabe (`hitl_approval_id`) ausgeführt.
- **Details:** Siehe `docs/system/ARCHON_MCP_SERVER_GUIDE.md`.

---

## 2. Portabler „Squad-Blueprint“-Paketmanager (`.archonpack` — M51)
- **Zweck:** 1-Klick-Export & -Import kompletter Fachabteilungen als geprüfte `.archonpack`-ZIP-Archive.
- **Inhalt:** `manifest.json` (inkl. SHA-256-Checksummen), `agents/roles.json`, `agents/agent_profiles.json` (automatisch Secret-bereinigt), 3-Stufen-`SOUL.md`, `skills/`, `boardroom/frameworks.json`, `prompts/templates.json` und `n8n/`-Workflows.
- **Endpunkte:**
  - `GET /api/v1/squad-packs/domains`
  - `POST /api/v1/squad-packs/export`
  - `POST /api/v1/squad-packs/inspect` (Dry-Run inkl. Zip-Slip- & SHA-256-Prüfung)
  - `POST /api/v1/squad-packs/import` (`conflict_mode`: `skip` | `overwrite`)

---

## 3. Multi-Mandanten-Umschalter & End-to-End DB-Isolation (Holding / GmbH / SPV — M43)
- **UI:** Topbar-/Sidebar-Umschalter + Mandanten-Isolations-Dialog (`static/js/tenant_switcher.js`) zeigt aktive Gesellschaft inkl. Rechtsform, physische DB-Größen/Pfade, Nummernkreise und ermöglicht die 1-Klick-Neuanlage weiterer Gesellschaften (`Holding`, `Operative GmbH`, `SPV`).
- **End-to-End DB-Isolation:** Durchgängig verdrahtete SQLite-Datenbankauflösung (`tenant_context.resolve_active_db`) unter `data/tenants/<company_id>/` für alle 5 Geschäftsdatenbanken (`erp.db`, `kanban.db`, `crm.db`, `contracts.db`, `deals.db`) mit automatischer WAL-Schema-Initialisierung und verlustfreier Primärmandanten-Anbindung.
- **Nummernkreise:** Atomare Zähler je Mandant und Belegtyp (`invoice`, `offer`, `order`, `credit_note`, `contract`).
- **Endpunkte:** `GET /api/v1/tenants/context`, `POST /api/v1/tenants/companies`, `POST /api/v1/tenants/switch`, `GET/POST /api/v1/tenants/{company_id}/number-ranges`, `GET /api/v1/tenants/{company_id}/isolation-status`.

---

## 3b. EU AI Act Compliance-Engine & 1-Klick GoBD-Verfahrensdokumentation PDF (M49)
- **UI (Operations):** Kachel `AI Act / GoBD` (`openComplianceStudio()` in `static/js/eu_ai_act_studio.js`) mit 3 Reitern (Risikoregister & SOUL-Hashes, Art.-4-Kompetenznachweis, Verfahrensdokumentation & GoBD-Prüfung).
- **Risikoklassifizierung & Guardrails:** Wortgrenzen- und rollenbasierte Klassifizierung aller 70 Spezialisten nach Verordnung (EU) 2024/1689 (`HIGH_RISK` Anhang III Nr. 4/5, `SPECIFIC_TRANSPARENCY` Art. 50, `MINIMAL_RISK` Art. 95) inkl. `SOUL.md`-SHA-256-Hash und Vorab-Aktivierungsprüfung (`check_activation_allowed`).
- **Art. 4 KI-Kompetenzregister:** Revisionssicheres Verzeichnis eingewiesener Bediener (`data/ai_act_literacy_register.json`), jede Änderung wird automatisch in die GoBD-SHA-256-Hashkette (`audit_log.py`) geschrieben.
- **1-Klick PDF-Export:** Mehrseitiges DIN-A4-PDF-1.4-Dokument (`backend/compliance_pdf.py`) aus realem Systemzustand (Mandantenstamm, M43-DB-Isolation, Nummernkreise, M22-Zero-Egress, M21-Merkle-Root-Verifikation, 70er-KI-Inventar, Art.-4-Register).
- **Endpunkte:** `GET/POST/DELETE /api/v1/governance/ai-act/literacy-register`, `GET /api/v1/governance/ai-act/guardrails`, `GET /api/v1/governance/compliance/snapshot`, `GET /api/v1/governance/compliance/verfahrensdokumentation.pdf`.

---

## 4. Operations-Vorlagen & Playbooks (M44)
- **UI (Operations):** `openPlaybooksStudio()` (`static/js/playbooks_studio.js`) mit 3 Reitern:
  1. **Aktive Vorlagen (10+):** Sofort ausführbares Starter-Set (Kunden-Onboarding, Wettbewerbs-Teardown, Lastenheft → Angebot, Monatsabschluss, Vertrags-Risiko-Check, Boardroom-Investment, Weekly Briefing, DSGVO Art. 15, Incident Postmortem, Content-Kampagne).
  2. **Katalog (Nachladen):** 15 weitere Branchen- & Fach-Playbooks (z. B. M&A Due Diligence, ESG-Check, Skonto-Optimierung, ISO-27001-Prep) im n8n-Stil per 1-Klick aktivierbar/ausblendbar.
  3. **Vorlagen-Editor:** Anlegen, Bearbeiten und Löschen eigener Mehr-Schritt-Playbooks mit `{{variablen}}`.
- **Endpunkte:** `GET /api/v1/playbooks`, `POST /api/v1/playbooks`, `PUT /api/v1/playbooks/{id}`, `POST /api/v1/playbooks/{id}/toggle`, `DELETE /api/v1/playbooks/{id}`, `POST /api/v1/playbooks/{id}/run`.

---

## 5. Pre-Flight Cost-Estimator & Shadow-Mode (M52)
- **Pre-Flight:** `POST /api/v1/preflight/estimate` schätzt Input-/Output-Tokens und USD-Kosten für ganze Playbook-/Boardroom-Ketten vor dem Start gegen ein Budget.
- **Shadow-Mode:** `POST /api/v1/shadow-mode/record`, `POST /api/v1/shadow-mode/{id}/evaluate`, `GET /api/v1/shadow-mode/agents/{agent_id}` — verfolgt die Übereinstimmungsquote neuer Agenten; ab **≥ 5 bewerteten Läufen** und **≥ 90 % Trefferquote** wird `ready_for_autopilot: true` gemeldet.

---

## 6. Obsidian „Epistemic Hygiene“-Wächter (M53)
- **Funktion:** Scannt Markdown-Notizen im Obsidian-Vault auf:
  1. Widersprüchliche Kennzahlen/Konditionen (`Preis`, `Tagessatz`, `Budget`, `Honorar`, `Kündigungsfrist`, `Laufzeit`, `Rabatt`, `Stundensatz`) zwischen verschiedenen Notizen.
  2. Abgelaufene Datumsangaben (`Gültig bis`, `Ablauf`, `Stand`).
  3. Verwaiste Notizen ohne `[[Wikilinks]]`.
- **Endpunkte:** `GET /api/v1/vault/epistemic-hygiene`, `POST /api/v1/vault/epistemic-hygiene/scan`.

---

## 7. Operativer Operations-Kalender (M25)
- **Funktion:** Aggregiert Kanban-Deadlines, ERP-Zahlungsziele (`erp_documents.due_date`), n8n-Routine-Crons und eigene Termine/Geburtstage in einer gemeinsamen Timeline.
- **Endpunkte:** `GET /api/v1/calendar/events` (`?start_date=&end_date=&source=all|kanban|erp|n8n|custom`), `POST /api/v1/calendar/events`, `DELETE /api/v1/calendar/events/{id}`.

---

## 8. Relevante Settings (`settings.json` & `agent_workspace/settings.json`)
- **`auth`**: Steuert Multi-User-Auth & Scoped API-Keys (`backend/api_key_manager.py`).
- **`autonomy_governance`**: Steuert HITL-Freigabe-Schwellenwerte (wird auch von `/mcp` für `archon__trigger_boardroom_debate` & `archon__ask_specialist` genutzt).
- **`dry_run_shadow`**: Aktiviert/steuert den Shadow-Mode-Kontext (`M52`).
- **`fleet_and_hygiene`**: Steuert periodische Vault-/Fleet-Hygiene-Prüfungen (`M53`).
- **`ARCHON_DEMO_MODE=true`** (Env): Sperrt schreibende MCP-Tools, Playbook-Mutationen und Tenant-Switches im Read-Only Demo-Modus.
