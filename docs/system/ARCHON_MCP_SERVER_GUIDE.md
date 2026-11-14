# Archon OS als MCP-Server (Model Context Protocol)

## Überblick
Archon OS stellt einen vollwertigen, dem MCP-Standard (`2024-11-05` & `2025-03-26` Streamable HTTP + SSE) entsprechenden **MCP-Server** bereit:
- **HTTP/SSE Gateway (M48):** `POST /mcp`, `GET /mcp` (`/mcp/sse`), `DELETE /mcp` und `GET /mcp/info` (`archon/routers/mcp_gateway.py` + `backend/mcp_gateway.py`).
- **Lokaler stdio-Server:** `scripts/archon_mcp_server.py`.

Damit können externe Clients wie **Claude Desktop**, **Cursor**, **VS Code**, **Antigravity** oder **Hermes** direkt auf die Kernfähigkeiten des Betriebssystems zugreifen (inkl. Scoped API-Keys `read_only` / `kanban_rw` / `agent_execute` / `admin_full` und HITL-Freigabe-Gate):
- Erstellen und Verwalten von Kanban-Aufgaben
- Auflisten und Delegieren an die 70 Fachspezialisten (`archon__list_specialists`, `archon__ask_specialist`)
- Durchsuchen des lokalen Obsidian-Vaults (`archon__search_vault`)
- CRM- und Kontaktrecherche in PocketBase
- Auslesen der Triage-Inbox (E-Mails, Telegram, Systemmeldungen)
- Anstoßen strukturierter Debatten im AI Boardroom (HITL-geschützt)
- Abfrage von System- und Observability-Metriken (`resources/list`, `prompts/list`)

> **Tipp:** Rufen Sie `GET /mcp/info` auf Ihrer laufenden Instanz auf, um fertige Copy-Paste-Konfigurationen für **Claude Desktop**, **Cursor** und **VS Code** (Streamable HTTP + `Authorization: Bearer archon_live_...`) zu erhalten.

---

## 1. Verfügbare MCP-Werkzeuge (Tools)

| Tool-Name | Beschreibung | Wichtige Parameter |
|---|---|---|
| `archon__create_task` | Legt eine neue Aufgabe im Operations Kanban Board an. | `title` (erforderlich), `body`, `assignee`, `priority` (1-4) |
| `archon__list_tasks` | Liest Aufgaben gefiltert nach Spalte/Status aus `kanban.db`. | `status` (`ready`, `in_progress`, `review`, `done`, `all`), `limit` |
| `archon__update_task_status` | Verschiebt eine Aufgabe im Kanban Board. | `task_id` (z. B. `t-123456`), `status` |
| `archon__search_crm_contacts` | Durchsucht die PocketBase-Kontakte nach Name, E-Mail oder Firma. | `query` (Suchbegriff), `limit` |
| `archon__get_inbox_messages` | Liest eingehende Nachrichten aus dem Posteingang. | `category` (`all`, `emails`, `telegram`, `internal`), `limit` |
| `archon__trigger_boardroom_debate` | Startet eine strukturierte Debatte im AI Boardroom. | `topic` (erforderlich), `framework`, `budget` |
| `archon__get_system_metrics` | Liefert Live-Metriken (Queue-Tiefe, Kosten, Fehlerrate, Betriebszeit). | *keine* |

---

## 2. Einbindung in Claude Desktop & Cursor

Tragen Sie die folgende Konfiguration in Ihre `claude_desktop_config.json` ein:

```json
{
  "mcpServers": {
    "archon-os": {
      "command": "python",
      "args": [
        "/path/to/archon-os",
        "--stdio"
      ],
      "env": {
        "WORKSPACE_DIR": "/path/to/archon-os"
      }
    }
  }
}
```

Für Unix/Docker-Umgebungen:
```json
{
  "mcpServers": {
    "archon-os": {
      "command": "docker",
      "args": [
        "exec", "-i", "ARCHON-OS", "python3", "scripts/archon_mcp_server.py", "--stdio"
      ]
    }
  }
}
```

---

## 3. CLI- und Direkttest-Befehle

Der Server kann direkt im Terminal inspiziert oder getestet werden:

```bash
# 1. Server-Informationen und Werkzeugliste anzeigen
python scripts/archon_mcp_server.py

# 2. JSON-Schema aller Werkzeuge ausgeben
python scripts/archon_mcp_server.py --tools

# 3. Einzelnes Werkzeug direkt ausführen
python scripts/archon_mcp_server.py --call archon__get_system_metrics "{}"
python scripts/archon_mcp_server.py --call archon__list_tasks '{"status": "ready", "limit": 5}'

# 4. Standardmäßigen JSON-RPC 2.0 stdio-Modus starten
python scripts/archon_mcp_server.py --stdio
```

---

## 4. REST-Brücke

Für Web-Clients und externe Services sind identische Endpunkte über die FastAPI Operations API verfügbar:

- `GET /api/operations/mcp/tools`: Liefert Metadaten und Schemas aller registrierten Werkzeuge.
- `POST /api/operations/mcp/call`: Führt ein Werkzeug synchron aus.
  ```json
  {
    "name": "archon__create_task",
    "arguments": {
      "title": "Dokumentenprüfung Kaufvertrag",
      "assignee": "commercial_jurist_contracts",
      "priority": 3
    }
  }
  ```
