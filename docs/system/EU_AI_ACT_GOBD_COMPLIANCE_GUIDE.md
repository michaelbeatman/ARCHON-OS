# EU AI Act Compliance-Engine, Multi-Mandanten-DB-Isolation & 1-Klick GoBD-Verfahrensdokumentation (M43 & M49)

Dieses Handbuch beschreibt die Architektur, Bedienung und REST-Endpunkte der **Multi-Mandanten-Datenbankisolation (M43)** sowie der **EU AI Act Compliance-Engine & 1-Klick-GoBD-Verfahrensdokumentation (M49)** in Archon OS.

---

## 1. Multi-Mandanten-Umschalter & Physische SQLite-DB-Isolation (M43)

### 1.1 Zielsetzung (DSGVO-Trennungsgebot & GoBD Z3-Prüfungssicherheit)
Unternehmensgruppen (Holding, operative GmbHs, Immobilien-/Projekt-SPVs) benötigen in einer gemeinsamen Archon-OS-Instanz eine strikte rechtliche, steuerliche und datenschutzrechtliche Trennung aller Bewegungsdaten bei gleichzeitigem Zugriff auf die gemeinsame 70-köpfige Spezialisten-Flotte.

### 1.2 Isolierte Datenbanken je Gesellschaft (`data/tenants/<company_id>/`)
Der zentrale `TenantContextManager` (`backend/tenant_context.py`) isoliert für jede Gesellschaft fünf eigenständige SQLite-WAL-Datenbanken:

| Datenbank | Fachmodul | Isolations-Verhalten |
|---|---|---|
| `erp.db` | `backend/erp_manager.py` | Eigene Debitoren/Kreditoren, Artikel, Angebote, Aufträge, Rechnungen & Gutschriften je Mandant |
| `kanban.db` | `backend/operations_api.py`, `archon/routers/kanban.py` | Eigenes Aufgaben-Board je Sekundärmandant; Primärmandant bleibt verlustfrei an die aktive Hermes-Engine angebunden |
| `crm.db` | `backend/crm_service.py` | Eigene Kontakte, Debitoren-/Steuerfelder & Termine je Sekundärmandant; Primärmandant nutzt live `pocketbase/pb_data/data.db` |
| `contracts.db` | `backend/contract_manager.py` | Eigene Verträge, Laufzeiten & Kündigungsfristen-Alarme je Mandant (inkl. automatischer Erst-Migration) |
| `deals.db` | `backend/deal_pipeline.py` | Eigene Vertriebspipeline & gewichteter Umsatz-Forecast je Mandant (inkl. automatischer Erst-Migration) |

Zusätzlich verwaltet jeder Mandant unter `data/tenants/<company_id>/number_ranges.json` atomar getrennte Beleg-Nummernkreise (`invoice` = `RE`, `offer` = `ANG`, `order` = `AB`, `credit_note` = `GS`, `contract` = `VTR`). Jeder Mandantenwechsel wird revisionssicher im GoBD-Audit-Log (`tenant_switched`) protokolliert.

### 1.3 Bedienung im Web-UI & REST-API
- **Topbar-Umschalter (`static/js/tenant_switcher.js`):** Auswahl-Dropdown oben rechts zum sofortigen Wechsel der aktiven Gesellschaft inkl. automatischem Reload geöffneter Fachansichten.
- **Isolations- & Anlage-Dialog:** Klick auf das Zahnrad-Symbol neben dem Mandanten-Dropdown zeigt live alle 5 SQLite-Pfade, Dateigrößen und Nummernkreise und erlaubt die **1-Klick-Anlage neuer Gesellschaften** (`Holding`, `Operative GmbH`, `SPV`).
- **REST-Endpunkte:**
  - `GET /api/v1/tenants/context` — Aktiver Mandant, Firmenliste, DB-Isolationsstatus & Nummernkreise
  - `POST /api/v1/tenants/companies` — Neue Gesellschaft anlegen & 5 SQLite-DBs sofort initialisieren (Admin)
  - `POST /api/v1/tenants/switch` — Aktiven Mandanten atomar umschalten + SSE-Broadcast `tenant_switched` (Admin)
  - `GET /api/v1/tenants/{company_id}/isolation-status` — Physischer DB-Status eines Mandanten
  - `GET / POST /api/v1/tenants/{company_id}/number-ranges[/next]` — Beleg-Nummernkreise abrufen / nächste Nummer vergeben

---

## 2. EU AI Act Compliance-Engine & Art.-4-KI-Kompetenzregister (M49)

### 2.1 Präzise Risikoklassifizierung nach Verordnung (EU) 2024/1689
`backend/eu_ai_act_inventory.py` stuft alle **70 Spezialisten** anhand wortgrenzen- und rollenbasierter Regeln in die drei relevanten Regulierungsstufen der EU-KI-Verordnung ein und berechnet für jeden Spezialisten den kryptografischen **SHA-256-Hash seines aktiven `SOUL.md`-Systemprompts** (`soul_sha256`):

| Risikoklasse | Rechtsgrundlage | Beispiele im Kader | Pflicht-Guardrails |
|---|---|---|---|
| `HIGH_RISK` | Art. 6 Abs. 2 i.V.m. Anhang III Nr. 4/5 EU AI Act | `hr_recruiter`, `labor_law_hr_governance` | `MANDATORY_4_EYES_HITL`, `PII_MASKING`, `GOBD_MERKLE_AUDIT`, `SOUL_HASH_PINNING` |
| `SPECIFIC_TRANSPARENCY` | Art. 50 EU AI Act | `b2b_outreach_specialist`, `pr_press_communicator`, `copywriter`, `telegram_bot` | `OUTBOUND_APPROVAL_QUEUE`, `AI_DISCLOSURE_TAG`, `GOBD_MERKLE_AUDIT` |
| `MINIMAL_RISK` | Art. 95 EU AI Act | Interne Strategie-, Finanz-, Rechtsanalyse-, Research- & DevOps-Spezialisten | `GOBD_MERKLE_AUDIT`, `DUAL_LLM_PROMPT_GUARD` |

### 2.2 Pflicht-Guardrail-Prüfung & Aktivierungs-Sperre
`backend/compliance_engine.py` prüft über `evaluate_guardrails()` und `check_activation_allowed(agent_id)`:
1. Besitzt jeder `HIGH_RISK`-Spezialist ein aktives 4-Augen-HITL-Gate und einen gepinnten `SOUL`-SHA-256-Hash?
2. Ist mindestens ein aktiver Funktionsträger im Art.-4-Kompetenzregister für `HIGH_RISK` eingewiesen?
3. Meldet die GoBD-SHA-256-Audit-Hashkette (`chained_audit_log.verify_integrity()`) mathematische Unversehrtheit?

Ist ein Hochrisiko-Spezialist als `NON_COMPLIANT` markiert oder ohne HITL-Aufsicht konfiguriert, blockiert `check_activation_allowed()` die Aktivierung deterministisch.

### 2.3 KI-Kompetenznachweis-Register nach Art. 4 EU AI Act
Unter `data/ai_act_literacy_register.json` verwaltet die `ComplianceEngine` alle eingewiesenen Bediener und Aufsichtsverantwortlichen inklusive Rolle, Schulungsmodul, Gültigkeitsdauer und `certificate_sha256`. Jede Eintragung oder Löschung erzeugt automatisch einen signierten Block im GoBD-Audit-Log (`ai_act_literacy_recorded` / `ai_act_literacy_deleted`).

---

## 3. Prüferfertige 1-Klick-Verfahrensdokumentation als PDF (GoBD + EU AI Act)

### 3.1 Aufbau des generierten DIN-A4-Prüfer-PDFs (`backend/compliance_pdf.py`)
Der abhängigkeitsfreie Pure-Python-PDF-1.4-Generator (`WinAnsiEncoding` / volle deutsche Sonderzeichenunterstützung) erzeugt zur Laufzeit ein mehrseitiges, seitennummeriertes Prüfdokument aus dem **echten Live-Zustand** des gewählten Mandanten:

1. **Deckblock & Mandanten-Identität:** Unternehmensstamm, Rechtsform, Gesellschaftstyp, Dokument-ID (`VD-...`), Systemversion (`v0.5.2.1`) und Snapshot-SHA-256.
2. **Kapitel 1 — Allgemeine Beschreibung & Unternehmensstamm (GoBD Rz. 151–153):** Anschrift, Handelsregister, Geschäftsführung, Steuernummer/USt-IdNr. und Bankverbindung.
3. **Kapitel 2 — Technische Systemdokumentation & Mandantentrennung (M43):** Live-Tabelle aller 5 Mandanten-SQLite-Datenbanken (Modus, Status, Dateigröße, Pfad) sowie die aktiven Beleg-Nummernkreise.
4. **Kapitel 3 — Internes Kontrollsystem (IKS), Zero-Egress & GoBD-Hashkette (M21/M22/M23):** Live-Prüfergebnis der kryptografischen SHA-256-Merkle-Kette (Anzahl verifizierter Blöcke, aktueller Head-Hash), lokales LLM-/Zero-Egress-Routing und Prompt-Injection-Schutz.
5. **Kapitel 4 — EU AI Act KI-Systemregister (VO 2024/1689):** Vollständige Tabelle aller 70 Spezialisten mit Risikoklasse, Aufsichts-Gate und `SOUL`-SHA-256-Prüfsumme.
6. **Kapitel 5 — Art. 4 KI-Kompetenznachweis-Register & Unterschriftsblock:** Eingewiesene Funktionsträger inkl. Zertifikats-Hash sowie Zeichnungsfelder für Geschäftsführung und Wirtschaftsprüfer/Datenschutz.

Jeder PDF-Abruf wird mit Dokument-ID und `pdf_sha256` im GoBD-Audit-Log (`verfahrensdokumentation_pdf_exported`) festgehalten.

### 3.2 Bedienung im Web-UI & REST-Endpunkte
- **UI-Einstieg:** In **Operations** auf die Kachel **`AI Act / GoBD`** klicken (`window.openComplianceStudio()`). Oben rechts steht jederzeit der Direkt-Button **„GoBD + EU AI Act PDF herunterladen“** bereit.
- **REST-Endpunkte (`archon/routers/governance.py`):**
  - `GET /api/v1/governance/ai-act/inventory` & `/stats` — Vollständiges 70er-Inventar inkl. `soul_sha256`
  - `POST /api/v1/governance/ai-act/reclassify/{agent_id}` — Manuelles Admin-Override inkl. GoBD-Log
  - `GET / POST / DELETE /api/v1/governance/ai-act/literacy-register[/{entry_id}]` — Art.-4-Kompetenzregister
  - `GET /api/v1/governance/ai-act/guardrails` — Live-Guardrail- & Aktivierungsprüfung
  - `GET /api/v1/governance/compliance/snapshot?company_id=...` — JSON-Gesamtsnapshot der Verfahrensdokumentation
  - `GET /api/v1/governance/compliance/verfahrensdokumentation.pdf?company_id=...` *(Alias: `/api/governance/ai-act/export/pdf`)* — **1-Klick PDF-Download** (`application/pdf`, Header `X-Document-SHA256`)
