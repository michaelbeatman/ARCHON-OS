# Ereignis-Trigger-Bus & Trigger-Matrix (M105)

Der **Event-Bus** (`backend/workflow_scheduler.py`) ist die zentrale Nervenbahn von Archon OS. Statt isolierter Einzel-Skripte melden alle Module ihre Ereignisse an einen gemeinsamen Bus, der über eine **Trigger-Matrix** geregelt, protokolliert und bei Bedarf erneut abgespielt werden kann.

## 1. Angeschlossene Module (Quellen → Ziele)

| Ereignis-Quelle (`source`) | Auslösende Ereignisse | Typische Ziel-Domänen |
| :--- | :--- | :--- |
| `watchdog` | Neue Web-/Radar-Funde | `workflow`, `comms` |
| `inbox` | Neue Dateien, E-Mails, Rechnungen | `workflow`, `treasury` (nur HITL), `comms` |
| `calendar` | Termin erstellt/verschoben/gesynct, fälliger Termin (`due`) | `workflow`, `comms` |
| `research` | Neues Research-Dossier / Ergebnis | `workflow` |
| `boardroom` | Abgeschlossene Multi-Agent-Debatte | `workflow`, `system` |
| `approval` | HITL-, E-Mail- oder Zahlungsfreigabe erteilt/abgelehnt | `workflow`, `treasury`, `comms` |
| `manual` | Test-Events & API-Triggers | alle |

## 2. Industriestandard-Schutzregeln

1. **Berechtigungs-Matrix (Quellen × Ziel-Domänen):**
   Unter **Telemetrie & Logs → Event-Bus → Trigger-Matrix** legst du pro Kombination fest:
   - **`Erlaubt (allow)`**: Quelle darf Workflows dieser Ziel-Domäne automatisch anstoßen.
   - **`Nur HITL (require_hitl)`**: Ausführung erfolgt nur mit menschlicher Freigabe (Standard für `inbox`/`calendar` → `treasury`).
   - **`Gesperrt (deny)`**: Quelle wird hart blockiert (Standard: `watchdog` → `treasury` / `system` ist gesperrt).
2. **Rate-Limit / Circuit-Breaker (`/min`):** Begrenzt Ereignisse pro Quelle und Minute (`max_per_min`, ohne `skipped_loop`-Zeilen mitzuzählen), damit ein fehlerhafter Webhook oder Mail-Sturm keine Lawine auslöst (`rate_limited`).
3. **Loop- & Dubletten-Schutz (`correlation_id`) + 14-Tage-Retention:** Identische Events werden pro Quelle nicht doppelt ausgeführt (`skipped_loop`); Kalender-Tagesereignisse (`calendar.event_today`) werden vorab dedupliziert, und `workflow_events` bereinigt Einträge älter als 14 Tage automatisch.
4. **HITL-Erzwingung (`require_hitl`):** Steht eine Policy auf `require_hitl`, wird vor der Ausführung automatisch eine HITL-Decision angelegt und das Event als `awaiting_hitl` protokolliert.
5. **Dead-Letter & Replay:** Blockierte (`blocked_policy`), gedrosselte (`rate_limited`) oder ungematchte Events gehen nicht verloren, sondern lassen sich im **Live Event-Log** nach Anpassung der Matrix mit einem Klick auf **Replay** erneut abspielen.

## 3. API-Endpunkte

- `GET /api/v2/workflows/events` — Gefiltertes Event-Log
- `POST /api/v2/workflows/events/emit` — Manuelles/externes Event einspeisen
- `POST /api/v2/workflows/events/{event_id}/replay` — Event erneut durch den Bus senden
- `GET /api/v2/workflows/event-policies` & `POST /api/v2/workflows/event-policies` — Trigger-Matrix & Rate-Limits lesen/speichern
