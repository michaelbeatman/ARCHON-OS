"""
scripts/restructure_handbuch.py
Strukturiert das System-Handbuch logisch in 7 thematische Kapitel um.
"""

import re

with open("docs/SYSTEM_HANDBUCH.md", "r", encoding="utf-8") as f:
    text = f.read()

# Prüfe Teil 1
teil1_match = re.search(r'(# Teil 1: Technische Systemarchitektur.*?)(?=# Teil 2: Operative Funktionsanleitung)', text, re.DOTALL)
teil1_content = teil1_match.group(1).strip() if teil1_match else ""

# Header
header = """# Archon OS – Systemarchitektur & Betriebshandbuch

> **Gültig ab Version:** v0.3.6 (Sentinel) / v0.3.7  
> **Klassifizierung:** Intern / Vertraulich (GoBD & ISO 27001 konform)  
> **Stand:** 31. Oktober 2026  
> **Geltungsbereich:** Gesamtes Archon OS Ökosystem (Backend, Hermes-Agenten, UI-Studios, Governance)
"""

doc_parsing_doc = """### 3.3 Dokumenten-Parsing & Tabellenextraktion (Docling-Architektur, t-539b65)

Die Parsing-Engine (`backend/document_parser.py`) verarbeitet komplexe heterogene Dokumente ohne zwingende externe Abhängigkeiten in strukturiertes GitHub-Flavored Markdown:
- **DOCX-Format:** Parst Absätze, Überschriftenhierarchien und Word-Tabellen direkt aus `word/document.xml` mittels `zipfile` und `xml.etree`.
- **XLSX-Arbeitsmappen:** Extrahiert alle Tabellenblätter, formatiert Zellen und löst referenzierte Shared Strings auf.
- **CSV / TSV:** Automatische Erkennung von Delimitern (Komma, Semikolon, Tabulator, Pipe) via Sniffer.
- **PDF-Verarbeitung:** Mehrstufige Pipeline (nutzt `pypdf`/`pymupdf` falls in der Umgebung verfügbar, ansonsten den nativen FlateDecode Stream-Parser).
- **Tabellen-Konverter:** Transformiert 2D-Zellmatrizen in exakt ausgerichtete Markdown-Tabellen (`| Spalte 1 | Spalte 2 |`).
- **REST-API-Endpunkte:**
  - `POST /api/documents/parse`: Gibt Volltext, Markdown, Absatz- und Tabellenanzahl zurück.
  - `POST /api/documents/extract-tables`: Liefert spezifisch alle extrahierten Tabellen als JSON-Matrizen."""

deal_pipeline_doc = r"""### 2.2 Deal-Pipeline mit Stufen & Forecast-Engine (t-5b159d)

Die Vertriebs-Pipeline (`backend/deal_pipeline.py`, `data/deals.db`) strukturiert Geschäftschancen und berechnet automatisierte Umsatzprognosen:
- **Die 6 Vertriebsphasen:**
  1. `lead` (Qualifizierung, Standardwahrscheinlichkeit 10 %)
  2. `discovery` (Erstgespräch / Bedarfsanalyse, 25 %)
  3. `proposal` (Angebot abgegeben, 50 %)
  4. `negotiation` (Vertragsverhandlung, 75 %)
  5. `closed_won` (Gewonnen / Abgeschlossen, 100 %)
  6. `closed_lost` (Verloren, 0 %)
- **Forecast-Berechnung:**
  - **Nominaler Pipeline-Wert:** Gesamtsumme aller aktiven Opportunities.
  - **Gewichteter Forecast:** $\sum (\text{deal\_value} \times \text{probability})$ aller aktiven Deals zur präzisen Liquiditäts- und Umsatzplanung.
  - **Win-Rate:** Verhältnis gewonnener zu verlorenen Abschlüssen in Prozent.
  - **Monatliche Fälligkeitsstaffelung:** Gruppierung nach `expected_close_date`.
- **REST-API-Endpunkte:**
  - `GET /api/deals`: Übersicht aller Deals mit Filter nach Phase, Partner oder zuständigem Agenten.
  - `GET /api/deals/forecast`: Zentrale Vertriebs-KPIs und monatlicher Forecast.
  - `POST /api/deals`: Deal erstellen oder aktualisieren.
  - `POST /api/deals/{id}/move-stage`: Phasenwechsel mit automatischer Anpassung der Eintrittswahrscheinlichkeit."""

print("Script template ready")
