# W2-B (Security) — Implementierungsbericht

**Datum:** 26.11.2026 · **Welle:** W2 Security · **Befunde:** D04-H1 (HIGH), D04-M4 (MED), D04-M6 (MED)
**Soll-Basis:** `audit_reports/00_SOLL_SPEC.md` §2.1 / §2.2 / §2.6 · `GEWICHTETE_BEFUNDLISTE.md` · `audit_reports/domain_04.md`

---

## 1. Umfang & Dateibesitz

Geändert wurden ausschließlich die vier W2-B-eigenen Dateien plus Tests und dieser Report:

| Datei | Befund | Änderung |
|---|---|---|
| `backend/demo_mode.py` | D04-H1 | `/rest/push` in Hard-Blockliste; WS-Default-Deny mit expliziter Safe-Liste; Doku-Labels |
| `archon/routers/proxies.py` | D04-H1 | Direkter `is_demo_mode()`-Gate in `_ws_forward_n8n_push` (1008-Close) |
| `archon/routers/_rbac.py` | D04-M4 | `get_session_actor()` fail-closed; kein `"admin"`-Fallback; sicherer Audit-Label-Helfer |
| `backend/agent_aliases.py` | D04-M6 | `UNKNOWN_AGENT_ID`-Sentinel für leere/unbekannte IDs |
| `tests/test_w2_b_demo_actor.py` | alle | 24 Regressionstests |
| `audit_reports/w2_b_report.md` | alle | Dieser Report |

**Nicht angefasst:** `operations_execution.py`, `operations_review.py`, `workflow_dag_runner.py`, `boardroom.py`, `chat.py`, `plugins.py`, `operations_sysops.py`, `compliance_engine.py` und alle weiteren fremden Dateien. Keine Commits, kein Replay, keine PostgreSQL-Arbeit.

---

## 2. D04-H1 — Demo-WS-Egress-Bypass über `/rest/push` (HIGH)

**Ist (vorher):** `DEMO_HARD_BLOCKED_PREFIXES` enthielt `/n8n-proxy`, aber nicht den Root-Alias `/rest/push`. Der WS-Zweig in `DemoModeMiddleware.__call__` ließ jeden Pfad passieren, der nicht auf der harten Liste stand. `archon/routers/proxies.py:347-349` registriert `@router.websocket("/rest/push")` → `_ws_forward_n8n_push()`, das Frames an `ws://n8n:5678/rest/push` weiterleitet. Da im Demo auth aus ist, griff der Fallback-Admin in `require_admin_or_503` — der Tunnel war für jedermann erreichbar (Egress-Bypass trotz Read-Only-Demo).

**Fix (3 Schichten, Defense-in-Depth):**

1. `backend/demo_mode.py:49` — `"/rest/push"` in `DEMO_HARD_BLOCKED_PREFIXES` aufgenommen. Die alte Hard-Block-Logik greift damit jetzt auch für HTTP-Aufrufe des n8n-REST-Proxys.
2. `backend/demo_mode.py:55` und `:1322-1329` — neuer `DEMO_SAFE_WEBSOCKET_PATHS` (leer = Default-Deny). Der WS-Zweig schließt mit **1008**, wenn der Pfad nicht explizit auf der Safe-Liste steht **oder** hart blockiert ist. Die harte Liste gewinnt also auch bei versehentlicher Safe-List-Aufnahme. Bestehende HTTP-/SSE-Pfade sind unberührt (SSE ist `http`-Scope, kein `websocket`).
3. `archon/routers/proxies.py:18,249-253` — `is_demo_mode()`-Gate direkt am Anfang von `_ws_forward_n8n_push`, vor Origin-Prüfung, `websocket.accept()` und jedem Upstream-Connect. Bei Demo → Warnlog + `close(code=1008)`. Der Schutz hängt damit nicht mehr allein von der Middleware-Registrierung ab.

**Verifikation:** `tests/test_w2_b_demo_actor.py` prüft Hard-Listen-Eintrag, HTTP-403 für `/rest/push`, 1008-Close für `/rest/push`, `/n8n-proxy/rest/push`, einen beliebigen WS und einen nicht registrierten Pfad, Safe-List-Opt-in, Vorrang der Hard-Blockliste sowie den direkten Proxy-Gate mit einem Fake-WebSocket (kein Accept/Upstream).

---

## 3. D04-M4 — Erfundener `"admin"`-Audit-Actor (MED)

**Ist (vorher):** `get_session_actor(request, fallback="admin")` gab bei `request is None` oder bei **jeder** Exception still `"admin"` zurück — ohne 401/503. U. a. `boardroom.py:189` (DSGVO-Tombstone `redacted_by`) und `:695/:837` (`_actor_id`) nutzten das. Die korrekte Variante `require_session_actor` existierte, wurde aber nicht herangezogen.

**Fix (`archon/routers/_rbac.py`):**

- `get_session_actor()` (`:73-87`) hat jetzt `fallback: Optional[str] = None`. Mit Request delegiert sie **ausnahmslos** an `require_session_actor()` → 401 bei fehlender Identität, 403 für Service-Tokens, 503 bei Prüffehler. Damit sind alle Aufrufer mit Request (auch die fremd besitzenden) faktisch auf den strikten Pfad umgestellt, ohne dass diese Dateien editiert werden mussten.
- Ohne Request (dokumentierte Hintergrund-Trigger wie `chat.py:938`) bleibt `fallback` ein **explizites Audit-Label**. Privilegierte Werte (`admin`, `administrator`, `root`, `superuser`, auch uppercase) werden auf den eindeutigen Sentinel `"unknown"` reduziert (`:45-46`, `:84-85`). Es wird nie `"admin"` erfunden.
- Neuer `_safe_audit_actor()` (`:49-70`) für Audit-Labels ohne Sicherheitswirkung (RBAC-Denials): wirft niemals, liefert die verifizierte Identität oder `"unknown"`. `_audit_rbac_denial()` nutzt ihn jetzt (`:137`), sodass auch bei Session-Ausfall der Denial-Event mit einem wahrheitsgemäßen Actor signiert wird.
- `require_session_actor()` (`:90-107`) importiert die Session-Hilfe jetzt innerhalb des `try` → auch Importfehler werden 503 statt unkontrolliert durchgereicht.

**Hinweis an fremde Besitzer:** `boardroom.py:189` übergibt weiterhin `fallback="admin"`; der Wert wird wegen des Request-Pfads ignoriert bzw. reduziert. Die Aufrufer können in einer späteren Welle auf explizites `require_session_actor(request)` umgestellt werden — sicherheitswirksam ist das Verhalten bereits jetzt.

**Verifikation:** Tests für `None`/`"admin"`/`"ADMIN"`/`"root"` → `"unknown"`, explizites `boardroom-service` → Label, verifizierter User → `"alice"`, Exception → 503 (auch mit `fallback="admin"`), anonyme Identität → 401, Service-Token → 403, Audit-Label → `"unknown"`.

---

## 4. D04-M6 — Stiller `research_scout`-Fallback bei leerer Agent-ID (MED)

**Ist (vorher):** `resolve_agent_id("")` gab `"research_scout"` zurück. Die Produktivaufrufer rufen den Helper ohne `known_ids`; eine fehlende Ziel-ID wurde damit als echter, klassifizierter Agent ausgeführt (EU-AI-Act-Guardrails für einen nicht ausgewählten Agenten).

**Fix (`backend/agent_aliases.py:68-90`):**

- Neuer eindeutiger Sentinel `UNKNOWN_AGENT_ID = "!UNKNOWN_AGENT!"` (kein gültiges Kader-Profil).
- Leere/whitespace-ID → Sentinel (nie mehr `research_scout`).
- Mit übergebenem `known_ids`: auch eine unbekannte (z. B. veraltete oder getippte) ID → Sentinel statt Raw-Wert. Die bisherige `if known_ids ...: return mapped`-Rückgabe war wirkungslos und ist jetzt echte Default-Deny-Prüfung.
- Bekannte Aliase (`research`, `hermes-coder`, `finance_lead`, …) behalten ihre Zuordnung; bestehende Tests bleiben grün.

**Verantwortung der Aufrufer (nicht in diesem Paket geändert):** `backend/operations_execution.py:553`, `backend/operations_review.py:267` und `backend/workflow_dag_runner.py:1578` (die im Audit genannte Zeile 1349 ist zwischenzeitlich verschoben) rufen `resolve_agent_id()` weiterhin **ohne** `known_ids`. Sie erhalten bei leerer ID jetzt den Sentinel und müssen ihn als `status=blocked` / `error_code=UNKNOWN_AGENT_ID` behandeln. Ohne `known_ids` kann der Helper eine unbekannte, aber nicht leere ID nicht erkennen (er gibt sie wie bisher unverändert zurück) — die Besitzer dieser drei Dateien müssen `known_ids` übergeben und den Sentinel hart blockieren. `backend/compliance_engine.py:357` übergibt bereits `known_ids` und blockiert den Sentinel über die Inventar-Prüfung korrekt.

**Verifikation:** Tests für `None`/`""`/Whitespace → Sentinel und `!= research_scout`, unbekannte ID mit `known_ids` → Sentinel, bekannte Aliase → unveränderte Zuordnung, sowie Dokumentation des `known_ids`-Kontrakts.

---

## 5. Testergebnisse

| Kommando | Ergebnis |
|---|---|
| `python -m pytest tests/test_w2_b_demo_actor.py -q` | **24 passed** |
| `... + test_m47_demo_mode.py + test_phase1_security_and_p0_fixes.py + test_d1_executor_characterization.py + test_med2_d_routers.py` | **135 passed** |
| RBAC/Auth-Suiten (`test_rbac_*`, `test_auth_rbac`, `test_fix_r34_proxy_auth`, `test_p0_auth_hardening`, …) | **439 passed, 1 pre-existing failure** |

Der einzige Fehler ist `tests/test_auth_rbac.py::TestAuthRBAC::test_03_authenticate_failure`: `sqlite3.DatabaseError: database disk image is malformed` beim Schreiben in `backend/audit_log.py:748`. Er tritt auch **isoliert** auf und liegt vollständig in nicht von W2-B geänderten Modulen (`auth_service.py` / `audit_log.py`, lokale Test-DB). Kein Zusammenhang mit den vier geänderten Dateien; keine Reparatur durchgeführt (fremder Dateibesitz).

---

## 6. Konformität

- Kein NEVER-DO-Verstoß: kein Coroutine-Replay, keine PostgreSQL-Migration, keine eigene Content-Domäne.
- Keine fremden Dateien, keine Commits, kein Replay/Postgres.
- Vier-Glieder-Kriterium (§0): Produzent (Gate/Helper) → Konsument (Middleware/Router/Compliance) → Effekt (1008-Close, 401/503, Sentinel) → Verifikation (24 neue Tests).
