# Archon OS — Session Handover

**Datum:** 01.11.2026  
**Ziel-Modell:** Gemini Argon (Fresh Session)  
**Projekt:** Archon OS 2026 (`C:\.Antigravity-projekte\AgenticOS-2026`)

---

## 1. Goal of Next Session
Konzeption und saubere Spezifikation des **Archon CRM- & Stammdaten-Moduls (Kunden- und Lieferanten-Datenbank / Mini-ERP)**.
- **Fokus:** Schlanker Start ("lieber 3-mal vorher durchdacht, um Folgekosten und Umbauten zu vermeiden"), datenkompatibel zum bisherigen CRM, aber vollständig in Archon integriert.
- **Ziel:** Festlegung des relationalen SQLite-Schemas (Kunden, Lieferanten, Ansprechpartner, Konditionen, Zahlungsziele, Bankverbindungen, Steuerdaten) und die saubere Verzahnung mit den bestehenden Modulen `Corporate` (Stammdaten, Vorlagen) und `Rechnungswesen` (Belege, Verträge, automatisiertes Mahnwesen).

---

## 2. State of Play (Was ist abgeschlossen?)
1. **System-Handbuch (Word DOCX) vollständig bereinigt & aktualisiert:**
   - **Gliederung:** Kapitel 1 (`Operations`) bis 16 (`Spezial-Feature: Visual CSS Live Studio & In-Place Inspector`) exakt nach der tatsächlichen UI-Menüstruktur geordnet.
   - **Screenshots:** Alle 44 fehlenden UI-Ansichten und Sub-Views via Headless Chrome automatisiert aufgenommen; insgesamt 72 Abbildungen in [docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx](file:///c:/.Antigravity-projekte/AgenticOS-2026/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx) und [docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx](file:///c:/.Antigravity-projekte/AgenticOS-2026/docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx) eingebettet.
   - **Anhänge I–V repariert:** Durch den neuen zeilenweisen Markdown-Parser in [scripts/rebuild_word_handbuch_clean.py](file:///c:/.Antigravity-projekte/AgenticOS-2026/scripts/rebuild_word_handbuch_clean.py) gibt es keine Fließtextblöcke oder Code-Kommentare mehr in den Überschriften. Tabellen sind echte Word-Tabellen, interne Ticket-IDs wurden entfernt, alle 16 Glossar-Domänen und 55 Decision-Frameworks sind einheitlich hierarchisch formatiert.
2. **Status Kanban-Board (`~/.hermes/kanban.db`):**
   - 36 Tasks `done`, 14 `archived`, 48 offene Tasks (`ready` / `review`).
   - Die wichtigsten CRM-relevanten Kanban-Tasks: `t-5c0f6e` (Kontakt-Zeitleiste), `t-5b159d` (Deal-Pipeline & Forecast), `t-6989ee` (Kontakt-Anreicherung), `t-6b030f` (Lead-Formulare -> CRM).

---

## 3. Open Decisions (Aufgaben für den nächsten Agenten)
1. **Datenmodell & Schema-Design (CRM / ERP-Kern):**
   - Trennung vs. Zusammenführung von Subjekten: Einheiten als `Party` / `Entity` mit Rollen (`Kunde`, `Lieferant`, `Partner`) oder separate Tabellen `customers` und `suppliers`?
   - BWL-Pflichtfelder: USt-IdNr., Steuernummer, Handelsregisternummer, Zahlungsziel (Tage), Skonto-Regeln, Währung, Standard-Konto/IBAN/BIC, Mahnstopp-Flag.
   - 1:n-Beziehungen: Mehrere Ansprechpartner pro Unternehmen (Name, Rolle, Mail, Durchwahl, DSGVO-Opt-In-Status).
2. **Archon-Modulverknüpfung:**
   - Wie greift das `Rechnungswesen` (`invoices`, `receipts`, `contracts`) direkt auf den Kunden-/Lieferantenstamm zu?
   - Wie werden Dokumente über das `Corporate`-Modul (`templates`) mit CRM-Feldern befüllt?
3. **Daten-Import & Sync:**
   - Import-Mechanismus für bestehende Kontakte aus dem bisherigen MCP-CRM ([scripts/archon_crm_mcp.py](file:///c:/.Antigravity-projekte/AgenticOS-2026/scripts/archon_crm_mcp.py)).

---

## 4. Skills to Use
- `database-designer` / `database-schema-designer` (für ERD-Entwurf und SQLite WAL-Tabellen)
- `spec-driven-workflow` (Spezifikation der Datenfelder vor der Code-Implementierung)

---

## 5. Key Artifacts & References
- **Handbuch (Stand 01.11.2026):**
  - `docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx`
  - `docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026.docx`
- **Rebuild-Skripte:**
  - `scripts/rebuild_word_handbuch_clean.py` (Line-by-line Markdown-DOCX Generator)
  - `scripts/capture_missing_views.js` (Playwright/Chrome Screenshot Runner)
- **Bestehendes CRM-Interface (Referenz zum Klonen):**
  - `scripts/archon_crm_mcp.py`
- **System-Datenbanken:**
  - `~/.hermes/kanban.db` (Zentrales Task-Tracking)
