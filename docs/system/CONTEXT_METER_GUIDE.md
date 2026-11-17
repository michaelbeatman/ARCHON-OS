# Kontext-Meter & Session-Compaction (M73)

> Status: Implementiert (M73, Teil 1–4). Konfiguration: `settings.json` → `context_compactor`.

Das Kontextfenster ist das Arbeitsgedächtnis des Modells: System-Prompt, Chatverlauf
und Anhänge müssen gemeinsam hineinpassen. Ab Werk berücksichtigt Archon OS das
Fenster bei jedem Versand — und macht den Füllstand im Chat sichtbar.

## Bedienelemente im Master-Chat

1. **Kontext-Meter (unter der Eingabezeile).**
   Kleiner Balken im Footer: genutzte Tokens / Fenstergröße (z. B. `2,1k/32,0k`).
   Farben: **grün** < 60 %, **gelb** < 85 %, **rot** ≥ 85 %.
   Der Balken aktualisiert sich automatisch bei Session-Wechsel und nach jeder Nachricht.

2. **Klick auf den Balken → Panel „Kontextfenster".**
   Zeigt den Füllstand als große Anzeige sowie die Anzahl aktiver Nachrichten und
   bereits verdichteter Verlaufsteile. Darin: der Knopf
   **„Kontext jetzt komprimieren"**.

3. **Manuelle Kompaktierung.**
   Der Knopf ruft `POST /api/chat/compact-session` auf. Alte Nachrichten werden zu
   einem strukturierten `[HIERARCHICAL_MEMORY_STATE]`-Block verdichtet
   (Kernziele, Entscheidungen, Dateipfade, Fehler/Fixes), die letzten
   `keep_recent_turns` Nachrichten bleiben im Original erhalten. Das Panel zeigt die
   Einsparung, der Chat lädt den verdichteten Verlauf neu.

## Automatische Kompaktierung (Teil 3)

Vor jedem Chat-Versand prüft der Stream-Handler den Füllstand der Session
(`archon/routers/context_meter.py::maybe_auto_compact_session`):

- Schwelle: `auto_compact_pct` (Standard **85 %** des Fensters)
- Mindesthistorie: `auto_compact_min_messages` (Standard **24**), frische Sessions
  werden nie verdichtet
- Ausgeführt wird dieselbe Verdichtung wie beim manuellen Knopf; der Vorgang wird
  im Server-Log unter `[Chat Stream] Auto-Kompaktierung` protokolliert.

## Orchestrator-Trigger (Teil 4, immer mit Freigabe)

CEO und andere Level-1-Agenten können die Kompaktierung über das MCP-Werkzeug
**`archon__compress_agent_context`** anstoßen
(`backend/mcp_gateway.py`, Scope `agent_execute`, **HITL-pflichtig**):

1. Agent ruft das Werkzeug mit `session_id` auf → erhält eine
   Freigabe-Request-ID (Domain `context_hygiene`).
2. Mensch gibt im Freigabe-Flow (Inbox / Telegram) frei oder lehnt ab.
3. Agent ruft das Werkzeug erneut mit `hitl_approval_id` auf; das Gateway
   verifiziert Request-ID, Werkzeug und Argumente gegen Replay und führt erst
   dann aus.

Es gibt keinen Weg, eine Session ohne menschliche Freigabe aus einem Agenten
zu komprimieren — Absicht (Vier-Augen-Prinzip), nicht Nachlässigkeit.

## Konfiguration (`settings.json`)

```json
"context_compactor": {
  "enabled": true,
  "trigger_token_threshold": 6000,
  "keep_recent_turns": 20,
  "target_compression_ratio": 0.3,
  "auto_compact_pct": 85,
  "auto_compact_min_messages": 24
}
```

- `keep_recent_turns`: so viele letzte Nachrichten bleiben bei jeder
  Verdichtung im Original.
- `auto_compact_pct` / `auto_compact_min_messages`: Schwellenwerte der
  Automatik (siehe oben).
- Die Fenstergröße für die Anzeige kommt aus `guardian.agent.max_context_tokens`
  (Standard 32.000).

## Endpunkte

| Endpunkt | Zweck |
|---|---|
| `GET /api/chat/context-status?session_id=…` | Füllstand für die Chat-Anzeige |
| `POST /api/chat/compact-session` | Manuelle Kompaktierung (Admin) |
| MCP: `archon__compress_agent_context` | Orchestrator-Trigger, HITL-geschützt |

## Technische Grundlagen

- Jede Nachricht wird bereits beim Empfang mit `token_count` in der
  State-DB abgelegt; fehlende Werte werden über die übliche Schätzung
  Zeichen ÷ 4 ergänzt.
- Das `compacted`-Flag markiert verdichtete Nachrichten (`active = 0`),
  der Zusammenfassungsblock selbst ist eine `system`-Nachricht mit
  `compacted = 1` und bleibt aktiv.
- Die Verdichtung ist heuristisch (Regex-basierte Faktenextraktion), nicht
  LLM-basiert — sie kostet keine Tokens und verlässt das System nicht
  (Zero-Egress).
