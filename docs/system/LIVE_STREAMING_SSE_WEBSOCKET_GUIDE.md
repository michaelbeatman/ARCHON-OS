# Live-Streaming per SSE / WebSocket (Echtzeit-Push & Token-Streaming)

## Überblick
Zur Beseitigung von ineffizientem Client-Polling setzt Archon OS auf eine durchgängige **Server-Sent Events (SSE)** und WebSocket-Architektur:
1. **Globaler Board- & Event-Stream** (`/api/v1/events/stream`):
   - Überträgt Änderungen am Kanban-Board (`kanban_updated`), Statuswechsel (`task_status`) und System-Ticker-Meldungen (`ticker_update`) in Millisekunden an alle verbundenen Web-Clients.
   - Das Frontend ([`static/js/operations_kanban.js`](../../static/js/operations_kanban.js)) aktualisiert sich automatisch ohne störendes Seiten-Neuladen oder Flackern.
2. **Aufgaben- & Token-Live-Stream** (`/api/operations/tasks/{task_id}/stream`):
   - Ermöglicht die synchrone Beobachtung langlaufender Multi-Agenten-Synthesen (z. B. Aggregationen durch Lisa oder strategische Bewertungen durch Robert).
   - Generierte Text-Tokens und Zwischenschritte werden kontinuierlich als Chunk-Events gestreamt.
3. **Multi-Agenten Boardroom Stream** (`/api/boardroom/debate/stream`):
   - Live-Streaming von Debattenrunden, Experten-Reaktionen und Konsensfindungen.

---

## 1. Architektur

```
[Agent / Synthese-Prozess]
          │
          ▼  broadcast_event("kanban_updated" | "task_chunk")
 ┌────────────────────────────────────────────────────────┐
 │   FastAPI Event Broadcaster (main._SSE_SUBSCRIBERS)    │
 └────────┬───────────────────────────────────────┬───────┘
          │ (Keepalive alle 20s)                  │
          ▼                                       ▼
  [Globaler SSE-Stream]                  [Task-Live-Stream]
 /api/v1/events/stream                  /api/operations/tasks/{id}/stream
          │                                       │
          ▼                                       ▼
  Browser Kanban Board                    Live-Token Drawer / Modal
(Sofortige Kartenverschiebung)          (Fließender Textaufbau)
```

---

## 2. Endpunkte

### Globaler Event-Stream
```http
GET /api/v1/events/stream
Accept: text/event-stream
```
**Empfangene Events:**
```json
data: {"type": "connected", "timestamp": 1793389000.12}

data: {"type": "kanban_updated", "timestamp": 1793389005.45, "data": {"action": "status_changed", "task_id": "t-123", "from": "in_progress", "to": "review"}}
```

### Task-Spezifischer Token-Stream
```http
GET /api/operations/tasks/{task_id}/stream
Accept: text/event-stream
```

### Chunk / Teilergebnis einspielen (aus Worker-Prozess)
```http
POST /api/operations/tasks/{task_id}/chunk
Content-Type: application/json

{
  "chunk": "Analysiere Risiko-Faktoren bezüglich Liquidität...",
  "agent_id": "executive_decision_architect",
  "status": "in_progress"
}
```

---

## 3. Frontend-Integration

In [`static/js/operations_kanban.js`](../../static/js/operations_kanban.js) verbindet `initOpsRealtimeStream()` automatisch beim ersten Laden:

```javascript
_opsEventSource = new EventSource('/api/v1/events/stream');
_opsEventSource.onmessage = function(event) {
  const msg = JSON.parse(event.data);
  if (msg.type === 'kanban_updated' || msg.type === 'task_status') {
    // Board im Hintergrund synchronisieren
    loadOperationsData(false);
  }
};
```
Bei Verbindungsabbrüchen stellt ein automatischer Timer (`5000 ms`) die Verbindung ohne Benutzereingriff wieder her.
