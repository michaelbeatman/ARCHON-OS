# Archon OS — Strikte Trennungsregel: Deterministische Workflows (n8n/Skripte) vs. Probabilistische KI-Agenten

Dieses Dokument legt die verbindliche Architektur-Abgrenzung für **Archon OS (Virtuelle Firma)** fest. Ziel ist es, Token-Verschwendung und Halluzinationsrisiken bei Standardprozessen auszuschließen und KI-Agenten ausschließlich dort einzusetzen, wo kognitive Urteilskraft, Synthese oder kreative Erstellung nötig ist.

---

## 1. Das 3-Schichten-Bauprinzip

### Schicht A: Orchestrierungs-, Budget- & UI-Layer (Archon Mission Control & Organigramm)
- **Zuständigkeit:** Hierarchisches Organigramm (Tier 1 Executive/Orchestrator, Tier 2 Department Leads, Tier 3 Spezialisten), visuelles Kanban-/Issue-Board (`ops.db`) und Artefakt-Ablage im Obsidian Vault (`01_PROJEKTE`).
- **Harte Token- & Euro-Budgets ([backend/role_budget_engine.py](file:///c:/.Antigravity-projekte/AgenticOS-2026/backend/role_budget_engine.py)):**
  - Jede Rolle besitzt ein hartes Tages- und Monatslimit in Tokens und Euro (`role_budget_policies` + `role_daily_budget_ledger`).
  - Bei Überschreitung wird die Rolle für den restlichen Tag automatisch auf `paused_budget` gesetzt.
  - Wird beim Anlegen einer Aufgabe ein Aufgaben-Tokenlimit (`token_budget`) vergeben, reserviert der Orchestrator 15 % für Triage und End-Synthese (Lisa) und teilt die verbleibenden 85 % gewichtet nach **Aufgabenkomplexität** (`complexity_weight` 0.7–2.0) auf die beteiligten Sub-Agenten auf.
- **Autonomes CEO-Hiring (`allow_autonomous_hiring`):**
  - Ist beim Anlegen einer Aufgabe die Option *„Autonomes CEO-Hiring erlauben“* aktiv, darf Robert (`executive_decision_architect`) für Spezialanforderungen temporäre Ad-hoc-Spezialisten (`hired_<slug>_<hash>`) mit passenden Skills aus `.agents/skills/` und eigenem Teil-Budget rekrutieren und nach Projektabschluss wieder auflösen.

### Schicht B: Ausführungs- & Sicherheits-Layer (n8n Agent Harness + Python-Skripte + MCP)
- **Grundregel („Deterministisch vor Probabilistisch“):**
  - Kein LLM darf für Aufgaben gerufen werden, deren Eingabe-Ausgabe-Logik nach festen Regeln, Formeln oder API-Schemata abläuft.
  - KI-Agenten greifen niemals direkt mit Roh-Passwörtern auf externe Systeme zu, sondern ausschließlich über gekapselte MCP-Werkzeuge ([archon/routers/mcp_gateway.py](file:///c:/.Antigravity-projekte/AgenticOS-2026/archon/routers/mcp_gateway.py)), den Credential-Vault (`.env` mit `0600`) und zwingende Human-in-the-Loop-Freigaben ([archon/routers/operations_approvals.py](file:///c:/.Antigravity-projekte/AgenticOS-2026/archon/routers/operations_approvals.py)).

### Schicht C: Kontext- & Qualitäts-Layer (Hermes Memory + `voice.md` + Human-Score Gate)
- **Unternehmensgedächtnis:** Alle Entscheidungen, Kontakte und Projektergebnisse fließen in die SQLite-WAL-Datenbanken und den Obsidian Second Brain Vault (inkl. 3D-Wissensgraph „Galaxy“).
- **Verbindliche Qualitäts-Gates vor Außenwirkung:**
  - Jeder Social-Media- oder LinkedIn-Entwurf durchläuft vor der Freigabe das **[config/voice.md](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/voice.md)**-Profil und den **5-Punkte Human-Score-Prüfer** (`li-human` / `anti-ai-slop` in [backend/content_machine.py](file:///c:/.Antigravity-projekte/AgenticOS-2026/backend/content_machine.py)). Entwürfe unter einem Human-Score von 70 oder mit KI-Floskeln/unsichtbaren Unicode-Wasserzeichen werden markiert bzw. bereinigt, bevor sie ins Approval-Gate wandern.

---

## 2. Verbindliche Routing-Matrix (Was läuft wo?)

Die technische Klassifizierung erfolgt automatisch über [backend/execution_routing_guard.py](file:///c:/.Antigravity-projekte/AgenticOS-2026/backend/execution_routing_guard.py) (`classify_execution_layer`):

| Aufgaben-Kategorie | Ausführungs-Layer | Ziel-Engine / Modul | Token-Kosten | HITL-Pflicht |
| :--- | :--- | :--- | :--- | :--- |
| **1. E-Mail-Polling & CRM-Kontaktabgleich** | `deterministic_n8n` | n8n / `scripts/archon_crm_mcp.py` | **0 Tokens** | Nein |
| **2. RSS-, News- & Wettbewerber-Scans** | `deterministic_script` | `backend/internet_watchdog.py` + `watchdog_radar_v2.py` | **0 Tokens** | Nein |
| **3. Telegram-zu-CRM / Ideen-Ingest** | `deterministic_script` | `backend/competitor_idea_bridge.py` | **0 Tokens** | Nein |
| **4. Finanzmathematik, USt-Split & Backups** | `deterministic_script` | `backup_archon.py`, `auto-calculate-vat-split` | **0 Tokens** | Nein |
| **5. Zeitgesteuertes Publishing (nach Freigabe)** | `deterministic_n8n` | n8n (`/webhook/archon-execution`) | **0 Tokens** | **Ja (vorab)** |
| **6. Content-Repurposing & LinkedIn-Drafting** | `hybrid_harness` | Watchdog/CRM Intake → `@linkedin_social_media_specialist` (`li-post` + `li-human` + `voice.md`) → HITL → n8n | **Task-Budget** | **Ja** |
| **7. Strategie, Recht, Steuer, Code & Boardroom** | `probabilistic_agent` | Archon Organigramm (Robert, Sandy, Spezialisten, Lisa) | **Role- & Task-Budget** | Nach Policy |

---

## 3. API-Endpunkte für Governance & Routing-Prüfung

- `GET /api/operations/routing/matrix` — Liefert die vollständige 4-Schichten-Routing-Matrix.
- `POST /api/operations/routing/classify` — Prüft für einen Aufgabentitel und Beschreibungstext vorab, ob die Aufgabe deterministisch (`token_free: true`) über n8n/Skript oder probabilistisch über einen budgetierten Archon-Agenten ausgeführt wird.
- `GET /api/operations/org/budgets` — Echtzeit-Übersicht aller Rollen-Tagesbudgets (Tokens & EUR), Auslastung in Prozent und pausierter Agenten.
- `POST /api/operations/org/budgets` — Setzt oder ändert harte Tages-/Monatslimits für eine Rolle.
- `POST /api/operations/tasks/{task_id}/allocate-budget` — Berechnet die komplexitätsgewichtete Budgetaufteilung einer Aufgabe auf ihre Sub-Agenten (inkl. optionalem CEO-Hiring).
