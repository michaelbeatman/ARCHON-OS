# ToDo-Liste für Samstag (Session nach Token-Reset)

## 1. Workflow-Optimierung & Autonomie
- [ ] **E2E-Delegationsablauf ohne Zwischenschritte:** Robert (`executive_decision_architect`) soll nach Abschluss aller delegierten Unteraufgaben selbstständig aufwachen, Zwischenergebnisse aus `01_Zwischenberichte/` konsolidieren und den finalen Bericht direkt in `03_Endprodukte/` ablegen.
- [ ] **Token-Schonung & Routing:** Prompts auf das Wesentliche kürzen, Kontextfenster schlank halten und Loop-Sanitisierung beibehalten, damit keine Token unnötig verbraucht werden.
- [ ] **Klarheit im Dialog:** Robert fasst das Ergebnis kurz und präzise im Master Chat zusammen und verlinkt direkt auf das fertige HTML-Endprodukt.

## 2. Showroom-Überarbeitung
- [ ] **Projekt-Erkennung & Metadaten:** Keine kryptischen IDs oder rein generische Datumsbezeichnungen mehr in den Karten.
- [ ] **Sprechende Vorschauen:** Jedes Projekt zeigt Titel, Leitagent, Erstellungsdatum, Fertigstellungsgrad und Status-Badge.
- [ ] **Direktzugriff:** 1-Klick-Aktionen für HTML-Endprodukt, Ordner-Explorer und Kontext-Chat.

## 3. UI-Haptik & Element-Redesign
- [x] **Navigation & Rollen:**
  - *Dashboard:* Reine Mission Control (Telemetrie, Flotte, Token-Sparkline, HITL-Freigaben, Katalog) ohne störende Subtabs.
  - *Operations:* Vollständiger operativer Arbeitsbereich mit den 6 Icon-Tabs:
    1. **Operations** (Projekt-Zentrale)
    2. **Master Chat** (direkt als 2. Tab zur nahtlosen Agenteninteraktion)
    3. **KANBAN** (Board & Aufgaben)
    4. **Organisation** (Organigramm & Kader)
    5. **n8n-Automation** (Workflow-Engine)
    6. **Kommunikation** (Funkverkehr)
  - *Master Chat:* Aus der linken Menüleiste entfernt und in Operations integriert.
- [ ] **Haptik & Layout-Flow:**
  - Scroll-Verhalten in Containern harmonisieren (keine doppelten Scrollbars).
  - Schaltflächen-Feedbacks (Hover, Focus, Ladezustände) vereinheitlichen.
  - Kontraste und Lesbarkeit bei Karten und Modals schärfen.
