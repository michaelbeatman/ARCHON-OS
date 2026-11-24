# E2E-/Regressionsbericht 24.11.2026 (Archon OS v0.5.7)

## 1. Ausgangslage

Volllauf (`.ci_venv`, `ARCHON_TEST_DB_ISOLATION=1`): **1840 passed, 1 failed, 16 skipped** (169,23 s).

Der einzige Fehler (`tests/test_audit_b3_souls.py::test_all_profiles_have_negative_guardrails_de_en`)
war **keine Code-Regression aus `3222bd75`/`91f6c13f`**, sondern ein versteckter Arbeitskopie-Drift:

| Ebene | Profile | Guardrails-Marker |
|---|---:|---:|
| `HEAD` | 70 | 280 |
| Arbeitskopie (`git ls-files -v` → `S`, skip-worktree) | 73 | 0 |
| Gebautes Image `agent-os-container:v0.5.7` | 73 | 0 |

→ Die Negativ-Abgrenzungen waren im **laufenden Container nicht wirksam**.

## 2. Weitere Befunde

1. `ARCHON_HEARTBEAT_WEBHOOK_URL` war im Container vorhanden, aber **leer** → Dead-Man-Switch inaktiv.
2. `/livez` lieferte bei einer kontrollierten 4-s-Event-Loop-Blockade mit den alten Defaults
   (15 s / 5000 ms) **200** statt 503 (`loop_lag_ms=2406`). Mit 1 s / 300 ms: **503**
   (`loop_lag_exceeded: 2454ms`) und Erholung auf 200.
3. Docker-Healthcheck-Semantik nachgemessen: 200 → Exit 0, **503 → Exit 1** (HTTPError),
   **Timeout → Exit 1**. Healthcheck markiert `unhealthy`, restartet aber nicht
   (`unless-stopped` greift nur bei Container-Exit); kein Autoheal vorhanden.
4. Prompt Studio: 60er-Batch, `Mehr laden`, 180-ms-Debounce und Koaleszierung
   funktional korrekt (jsdom 12/12, `node --check` Exit 0). Kein Playwright-Test im Repo.

## 3. Umgesetzte Maßnahmen

| Maßnahme | Datei(en) | Wirkung |
|---|---|---|
| skip-worktree aufgelöst, Guardrails in 73 Profile nachgetragen, `--check` grün | `agent_profiles.json`, `scripts/add_role_guardrails.py` | Kein Profil verloren, SSOT wieder konsistent |
| Liveness-Defaults an Healthcheck-Timeout angepasst (8 s / 2000 ms) | `backend/loop_liveness.py` | 503 schon bei kurzen Hängern |
| Schwellen + Alertmanager-URL + Egress-Allowlist in Compose | `docker-compose.yml` | Heartbeat erreicht die bestehende Telegram-Route |
| Alertmanager-v2-Heartbeat mit `endsAt`-TTL (Dead-Man-Switch) | `backend/fleet_self_healing.py` | Ausbleibende Pings feuern Alert; `dead_man_switch_configured` publik |
| Externer Autoheal über Socket-Proxy (`ALLOW_START/STOP`), Health-Gate + Cooldown | `scripts/archon_autoheal.py`, `docker-compose.yml` | `unhealthy` führt zum Neustart, kein `ALLOW_RESTARTS` |
| Regressionstests: echte Blockade, Defaults, Compose-Wiring, Alert-Payload, Chromium-UI | `tests/test_loop_liveness.py`, `tests/test_alertmanager_heartbeat.py`, `tests/ui/prompt_studio_batches.js`, `tests/test_prompt_studio_ui_browser.py` | Lücken dauerhaft abgesichert |

## 4. Verifikation nach dem Rebuild

| Prüfung | Ergebnis |
|---|---|
| Image `agent-os-container:v0.5.7` neu gebaut, `ARCHON-OS` recreated | ✅ Exit 0 |
| Container `ARCHON-OS` | `Up (healthy)`, `RestartCount=0` |
| `/livez`, `/health` | **200 / 200** |
| Guardrails im neuen Image | **292 Marker, 73 Profile** (vorher 0/73) |
| Env im Container | `ARCHON_LIVEZ_MAX_HEARTBEAT_AGE_S=8`, `ARCHON_LIVEZ_MAX_LOOP_LAG_MS=2000`, `ARCHON_HEARTBEAT_ALERTMANAGER_URL=http://alertmanager:9093/api/v2/alerts`, `ARCHON_PROXY_ALLOWED_TARGETS=alertmanager:9093` |
| `archon-autoheal` | Startfehler erkannt, danach „wieder gesund — Fehlerzaehler zurueckgesetzt" |
| Alertmanager-Heartbeat (echter Ping) | `sent=True`; Alert `ArchonHeartbeat` aktiv, `severity=info`, Receiver `archon-telegram`, `endsAt` in der Zukunft → Dead-Man-Switch funktionsfähig |
| Compose-Konfiguration | main + dev + demo + hermes + override: **5× Exit 0** |
| Vollständige Testsuite | **1846 passed, 16 skipped**, 0 failed (siehe `FINAL_VERIFICATION.md`) |

Bewertung nach der Härtung: **9,5 / 10** (vorher 7,7 / 10). Verbleibende Abzüge:
kein Dauerbetrieb über mehrere Tage beobachtet, Telegram-Zustellung nicht explizit
im Chat verifiziert, Alertmanager-TTL von 180 s ist ein bewusster Kompromiss.
