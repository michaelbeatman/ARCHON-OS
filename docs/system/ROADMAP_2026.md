# Archon OS – Offene Entwicklungs-Roadmap

> **Hinweis:** Abgeschlossene Meilensteine (Stand `v0.6.0.1`, u. a. Execution Hardening, PolicyEngine/BudgetBank, Effect-Ledger, SQLite-WAL-Konsolidierung, Multi-Agent-Orchestrierung, Content-Maschine v2, Passkey-HITL und Audit-Sanierung W0–W7) sind in [`CHANGELOG.md`](../../CHANGELOG.md) dokumentiert. Diese Datei listet ausschließlich **aktuell offene bzw. geplante** Vorhaben. **Produktmodell-Korrektur (23.11.2026):** Keine eigene Content-Domäne — Content läuft durchgängig als `Task → Workflow → Agent → Gate → Artefakt`.

| ID | Offenes Vorhaben | Priorität | Status | Kernfokus |
|---|---|---|---|---|
| **M2 / M34** | **Mobile Steuerapp für Android** | Mittel | Geplant | PWA vs. Native Client, sichere Remote-Anbindung (WireGuard/Tailscale/Tunnel), Push-Freigaben (HITL) & Kamera-Beleg-Scan |
| **M66** | **Hardware-gebundene Agent-Authentifizierung** | Mittel | Geplant | Agentenprozesse ohne eigene Secrets, TPM-2.0-/Secure-Enclave-Authenticator, Step-Up-Passkey-Freigabe & Action-Records |
| **M67** | **Host-seitige Zustandsführung & Prompt-Kompression** | Mittel | Geplant | Schlanker Step-Prompt aus Host-Zustand + deterministischer Antwort-Prüfung (Ergänzung zu OmniRoute/Dispatch-Budgets) |
| **M68** | **Compliance-Inventar, DPIA-Register & Replay-Nachweis** | Mittel | Geplant | Tenant-Compliance-Inventar, Art.-35-DPIA-Register, Aufbewahrungsfristen je Log-Typ, getesteter Audit-Replay & 1-Seiten-Policy-Export |
| **M69** | **Policy-as-Code für Freigaben (YAML & Vendor-Limits)** | Mittel | Geplant | Versionierbare YAML-Regeln in `approval_policy_engine.py`, rollende 24h-Vendor-Limits, Telegram Approve/Deny-Buttons & signierte Freigabe-Tokens |
| **M70 / M74** | **Auto-Review-Runden, Validierungs-Agenten & „Braucht mich“-Panel** | Hoch | Geplant | Einheitliche Freigabe-Oberfläche (Missions-/Policy-/HITL-Gates), Auto-Review vor Menschen-Gate & Beleg-Sammlung durch Validierungs-Agenten |
| **M71** | **Eval-Attestierung (Konfig-Fingerprint je Eval-Lauf)** | Niedrig | Geplant | SHA-256-Fingerprint über Profile/SOUL, Prompts, Policy & Routing-Config je Eval-Arena-Lauf |
| **M72** | **Modellabhängiges Task-Sizing & Skills auf Leihbasis** | Niedrig | Geplant | Dynamische Paketgröße je Modell-Kontextfenster & temporäre Skill-Zuweisung pro Task |
| **M95** | **Multi-User Urlaubs-/Vertretungs-Modus & User-Telegram-Kanäle** | Hoch | Geplant | Menschliche Stellvertreter-Eskalation bei Timeout/Abwesenheit (nie Agent-Fallback) & benutzerspezifische Telegram-Kanäle |
| **M96** | **Visueller Ergebnis-Template- & Report-Designer** | Sehr hoch | Geplant | Zweigeteilter Canvas-Editor mit Drag-&-Drop-Variablen-Pool und individuellen Typografie-/Farb-Properties |
| **M97** | **Einheitliche Modal-, Header- & Blur-Overlay-UI-Überarbeitung** | Hoch | Geplant | Systemweite Vereinheitlichung aller Detail-Modals (Größe, Z-Index, Backdrop-Blur) |
| **M98** | **Vereinheitlichte API-Key- & OmniRoute-Scope-Verwaltung** | Hoch | Geplant | Konsolidierte Sicht auf eingehende Archon-API-Tokens und ausgehende Provider-Keys inkl. OmniRoute-Scope-Steuerung |
| **M99** | **Context-Compaction Audit & modell-dynamische Fenster** | Hoch | Geplant | Dynamisches `max_context_tokens` je Modell (128k/200k/1M) statt pauschal 32k + Settings-UI-Steuerung |
| **M100** | **KPI-Dashboard für Output-Wirtschaftlichkeit** | Hoch | Geplant | Kosten-/Aufwands-Rollup pro Projekt, Agenten-Profil und Deliverable-Typ (inkl. Zeitreihen-Vergleich) |
| **M109** | **Code Mode (Deferred Discovery → Isolierte Sandbox)** | Hoch | Geplant | `search`/`describe`/`call`-Discovery (~800–1.000 Token Footprint) für ~200+ Endpunkte + isolierte Wasm-/Prozess-Sandbox mit Capability-Broker |
| **M111** | **Isolation & Resilience: Bulkheads, Tool-Output-Caps & Circuit-Breaker** | Hoch | Geplant | Getrennte Scheduling-Klassen, harte Tool-Output-Größenlimits vor Kontext-Injektion & Provider-Circuit-Breaker mit Backpressure |

---

## Offene Arbeitspakete im Detail

### M2 / M34: Mobile Steuerapp für Android (Geplant – Mittel)
- **Architektur-Evaluation:** Installierbare Progressive Web App (PWA) vs. schlanker nativer Kotlin/Flutter-Client.
- **Remote-Konnektivität & Security:** Sicherer Zugriff ohne statische IP (WireGuard / Tailscale / Tunnel mit TLS), Push-Benachrichtigungen für HITL-Freigaben, Sprachnotizen und Kamera-Beleg-Scan direkt ins ERP.

### M66: Hardware-gebundene Agent-Authentifizierung („Agent Authenticator“) (Geplant – Mittel)
- **Zielbild:** Agentenprozesse halten keine eigenen Geheimnisse; Schlüssel liegen in Secure Hardware (z. B. TPM 2.0 / Secure Enclave / attestierter KMS) mit Origin-Binding, Step-Up-Passkey-Freigabe und signierten Action-Records in `audit_log.py`.

### M67: Host-seitige Zustandsführung & Prompt-Kompression (Geplant – Mittel)
- **Zielbild:** Auslagerung des Job-Zustands aus dem wachsenden Chat auf den Host, deterministische Prüfung jeder Modellantwort vor Übernahme und frische, kompakte Step-Prompts als Ergänzung zu OmniRoute/`cost_estimator.py`.

### M68: Compliance-Inventar, DPIA-Register & Replay-Nachweis (Geplant – Mittel)
- **Offene Bausteine:**
  - Automatisch generiertes Tenant-Compliance-Inventar („Agent → Datenklasse → Ziel lokal/Cloud → Freigabestufe“) inkl. PDF-Export.
  - DPIA-/Use-Case-Register (Art. 35 DSGVO) mit Change-Trigger bei neuen Modellen/Datenklassen.
  - Unterscheidbare Aufbewahrungsfristen je Log-Typ (GoBD 10 Jahre vs. Betriebs-Logs) + Feldpseudonymisierung.
  - Getesteter Audit-Replay aus Log-Einträgen, Ein-Seiten-Policy-Export sowie Art.-50-KI-Kennzeichnung für agentenerstellte E-Mails/Belege.

### M69: Policy-as-Code für Freigaben (YAML, Vendor-Limits, Telegram-Buttons, Freigabe-Tokens) (Geplant – Mittel)
- **Offene Bausteine:** Versionierbare YAML-Policy-Datei für `approval_policy_engine.py`, rollende 24h-Limits je Provider in `cost_estimator.py`, interaktive Approve/Deny-Buttons direkt in Telegram sowie kurzlebige signierte Freigabe-Tokens mit Prüfung vor Ausführung.

### M70 / M74: Auto-Review-Runden, Validierungs-Agenten & Freigabe-Gate 2.0 (Geplant – Hoch)
- **Offene Bausteine:**
  - Einheitliches **„Braucht mich“-Panel**, das Missions-, Policy- und MCP-HITL-Freigaben sowie Agentenrückfragen und unsichere Abbrüche in einer Liste bündelt.
  - Vorgeschaltete Auto-Review-Runden + Validierungs-Agenten, die vor Hochrisiko-Freigaben Belege/Prüfsummen einsammeln und an den Request hängen.
  - Einheitliche Pflichtfelder, Eskalations-Timeouts und Vertretungslogik über alle Freigabe-Ebenen.

### M71: Eval-Attestierung (Geplant – Niedrig)
- **Zielbild:** Vor jedem Lauf der Agent-Eval-Arena wird ein SHA-256-Fingerprint über Agenten-Profile/`SOUL.md`, Prompts, Policy-Datei und Routing-Config gebildet und am Ergebnis gespeichert.

### M72: Modellabhängiges Task-Sizing & Skills auf Leihbasis (Geplant – Niedrig)
- **Zielbild:** Dynamische Zerlegung von Aufgaben passend zum Kontextfenster des Zielmodells sowie temporäre Skill-Zuweisung je Task aus dem Skill-Index mit automatischer Rückgabe nach Abschluss.

### M95: Multi-User Urlaubs-/Vertretungs-Modus & Benutzer-spezifische Telegram-Kanäle (Geplant – Hoch)
- **Zielbild:** Bei Timeout oder Abwesenheit eskalieren HITL- und 4-Augen-Freigaben ausschließlich an menschliche Stellvertreter (Multi-User-RBAC, niemals Agent-Fallback), zugestellt über benutzerspezifische Telegram-Kanäle.

### M96: Visueller Ergebnis-Template- & Report-Designer (Geplant – Sehr hoch)
- **Zielbild:** Zweigeteilter Editor (Canvas links, Drag-&-Drop-Variablen-Pool rechts) mit individuellen Style-Properties (Schriftgröße, Font, Farbe, Gewicht, Ausrichtung, Abstände) für Aufgaben- und Showroom-Reports.

### M97: Einheitliche Modal-, Header- & Blur-Overlay-UI-Überarbeitung (Geplant – Hoch)
- **Zielbild:** Vereinheitlichung aller Detail-Modals und Overlay-Dialoge nach dem Maßstab des System Control Centers (feste Größen, konsistenter `backdrop-blur` inkl. Header, einheitliche Abstände/Typografie).

### M98: Vereinheitlichte API-Key- & OmniRoute-Scope-Verwaltung (Geplant – Hoch)
- **Zielbild:** Gemeinsame Verwaltungsansicht für eingehende Archon-API-Tokens (`read_only`, `kanban_rw`, `agent_execute`, `admin_full`) und ausgehende LLM-Provider-Keys inklusive OmniRoute-Scope-Steuerung.

### M99: Context-Compaction Audit & modell-dynamische Fenster (Geplant – Hoch)
- **Zielbild:** Automatische Anpassung von `max_context_tokens` an das jeweilige Modell (128k / 200k / 1M statt pauschal 32k), direkte Parametrierung im Settings-UI sowie sichtbare Compaction-Marker im Chatverlauf.

### M100: KPI-Dashboard für Output-Wirtschaftlichkeit (Geplant – Hoch)
- **Zielbild:** Kosten-/Aufwands-Aggregation pro Prozess (Task mit `done` + Deliverable), Rollups nach Projekt/Agenten-Profil/Zeitraum sowie Zeitreihen-Vergleich je Output-Typ bei bewusst manueller Nutzenbewertung.

### M109: Code Mode — Token-Effizienz ohne Sicherheitsverlust (Geplant – Hoch)
- **M109a (Deferred Discovery):** 3 Meta-Tools (`search_capabilities`, `describe_capability`, `call_capability`) über `backend/tool_runtime.py` (~800–1.000 Token Footprint).
- **M109b (Isolierte Code-Sandbox + Capability-Broker):** Prozess-/Wasm-Isolation ohne FS/Env/Netzwerk mit Method+Path-Allowlist, Secret-Masking und `PreDecision`-Review für `write`/`destructive`.

### M111: Isolation & Resilience — Bulkheads, Tool-Output-Caps & Circuit-Breaker (Geplant – Hoch)
- **Zielbild:** Getrennte Scheduling-Klassen (Chat vs. Background-DAG vs. Eval), harte Tool-Output-Größenlimits vor Kontext-Injektion und Provider-Circuit-Breaker mit Fallback-Hierarchie und Backpressure.

---

## Ideen-Pool (beobachten, noch nicht geplant)

- **Externe Website-MCP-Endpunkte (Policy-gesteuert):** Optionale Anbindung externer Web-zu-MCP-Adapter nur für unkritische Recherche-Domänen (strikt ausgeschlossen für Finanzen/Compliance/Zero-Egress).
- **Vektorisierter Code-Index (lokales RAG für Agenten-Navigation):** Indexierung des Code-Stands nach grünen Commits in AnythingLLM/Chroma (mit `Dateipfad:Zeile:Commit` als Kompass, niemals als alleiniger Audit-Nachweis) oder deterministischer AST-/Call-Graph-Index.
- **Konfigurierbarer Docker-Build-Cache-Deckel & Wartungs-Optionen:** Konfigurierbares `ARCHON_DOCKER_BUILD_CACHE_LIMIT` in Update-/Rebuild-Skripten inkl. optionaler Dangling-Image-Bereinigung (ohne Volumes).
