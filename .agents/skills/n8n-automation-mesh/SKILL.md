---
name: n8n-automation-mesh
description: Native Archon OS and Claude Desktop n8n automation skill for triggering and managing local workflows via webhook MCP tools.
---

# n8n Automation Mesh Skill

Dieses Skill bindet die lokale n8n-Automatisierungs-Engine über das Model Context Protocol (MCP) in das Archon OS Mesh ein. Es stellt Agenten spezialisierte Werkzeuge für Recherche, Kommunikation, Dokumentenerstellung und CRM-Sync bereit, ohne dass Agenten direkte Administrationsrechte auf n8n benötigen.

## Verfügbare MCP-Werkzeuge

### 1. `mcp__n8n__extract_article`
Extrahiert sauberen, werbefreien Fließtext oder Markdown von Webseiten, Stellenausschreibungen oder Dokumentationsseiten.
- **Webhook:** `POST /webhook/archon-extract-article`
- **Parameter:**
  - `url` (string, Pflicht): Zieladresse der Webseite.
  - `format` (string, optional): `"markdown"` (Standard), `"text"` oder `"html"`.
  - `include_metadata` (bool, optional): Titel, Autor, Datum miterfassen.

### 2. `mcp__n8n__dispatch_message`
Verschickt Nachrichten oder Benachrichtigungen über verschiedene Kanäle (E-Mail, Telegram, Slack, Teams).
- **Webhook:** `POST /webhook/archon-dispatch-message`
- **Parameter:**
  - `channel` (string, Pflicht): `"email"`, `"telegram"`, `"slack"`, `"teams"`
  - `recipient` (string, Pflicht): E-Mail-Adresse, Chat-ID oder Channel
  - `subject` (string, optional): Betreffzeile
  - `body` (string, Pflicht): Nachrichtentext (Text oder Markdown)
  - `attachments` (array, optional): Dateipfade oder URLs von Anhängen

### 3. `mcp__n8n__render_document`
Kompiliert HTML oder Markdown in fertige PDFs oder Office-Dokumente (z. B. Bewerbungsunterlagen, Lebensläufe, Berichte).
- **Webhook:** `POST /webhook/archon-render-document`
- **Parameter:**
  - `content` (string, Pflicht): Quelltext in HTML oder Markdown
  - `document_type` (string, optional): `"pdf"` (Standard) oder `"docx"`
  - `title` (string, optional): Dokumenttitel
  - `filename` (string, optional): Gewünschter Dateiname

### 4. `mcp__n8n__search_or_feed`
Fragt Live-Feeds, RSS-Quellen oder Such-Endpunkte nach neuen Vakanzen und Marktinformationen ab.
- **Webhook:** `POST /webhook/archon-search-feed`
- **Parameter:**
  - `category` (string): `"jobs"`, `"news"`, `"rss"`
  - `query` (string, optional): Suchbegriff
  - `feed_url` (string, optional): Direkte Feed-URL
  - `limit` (int, optional): Max. Trefferanzahl (Standard: 10)

### 5. `mcp__n8n__sync_crm_record`
Erstellt oder aktualisiert Leads, Kontakte oder Vakanzen im CRM, PocketBase oder Notion.
- **Webhook:** `POST /webhook/archon-sync-crm`
- **Parameter:**
  - `entity_type` (string, Pflicht): `"lead"`, `"contact"`, `"vacancy"`, `"interaction"`
  - `identifier` (string, optional): Eindeutiger Identifikator zur Deduplizierung
  - `data` (object, Pflicht): Zu speichernde Felder

### 6. `mcp__n8n__trigger_workflow`
Generischer Fallback für beliebige benutzerdefinierte n8n-Workflows.
- **Webhook:** `POST /webhook/{webhook_path}`
- **Parameter:**
  - `webhook_path` (string, Pflicht): Relativer Webhook-Pfad
  - `payload` (object, Pflicht): JSON-Payload für den Workflow

### 7. `mcp__n8n__list_capabilities`
Gibt den aktuellen Katalog aller verfügbaren Automatisierungswerkzeuge und deren Status zurück.

### 8. `mcp__n8n__health_check`
Prüft Erreichbarkeit, Statuscode und Netzwerklatenz des n8n-Daemons.

## Governance & Ausführungsregeln
- **Timeout & Retries:** 20 Sekunden Latenz-Budget mit exponentiellem Backoff (3 Versuche) bei Server- oder Netzwerkfehlern.
- **Zero-Dependency:** Der Treiber arbeitet standardmäßig mit Pythons Standardbibliothek (`urllib`) und läuft ohne externe Zusatzpakete sowohl nativ unter Windows als auch in Containern.
- **Stdio-Server:** Unterstützt JSON-RPC 2.0 zur nahtlosen Einbindung in Claude Desktop, Hermes oder andere MCP-Host-Umgebungen via `python scripts/mcp_n8n_driver.py --stdio`.
