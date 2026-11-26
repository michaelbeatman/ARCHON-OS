# W3-A — Orchestrierung/Routing: Fix-Report (26.11.2026)

**Scope:** D02-H1, D02-M2, D05-M1, D12-M6 · **Dateibesitz:** `backend/agent_router.py`, `core_dispatcher.py`, `backend/execution_routing_guard.py`, `backend/fleet_self_healing.py`
**Tests:** `tests/test_w3_a_router_dispatch.py` (23 Testfälle inkl. Parametrisierung)
**NEVER_DO_LIST:** kein Coroutine-Replay, kein Event-Sourcing/Snapshotting, keine PostgreSQL-Migration. Alle Änderungen sind additiv/kompatibel im bestehenden SQLite-/Chokepoint-Pfad.

---

## D02-H1 (HIGH) — n8n-Schein-Erfolg im Master-Chat

**Vorher** (`backend/agent_router.py`, alten Zeilen 1098–1112): `_check_deterministic_execution_layer()` rief `trigger_n8n_execution()` und gab unabhängig vom Webhook-Status `{"blocked": False, "text": "… ausgeführt …"}` zurück. `unconfirmed`/`blocked`/fehlende Antwort wurden als Erfolg quittiert; der kanonische Dispatch-Pfad (`core_dispatcher.py:1640–1654`) prüfte korrekt `status == "success"`.

**Nachher** (`backend/agent_router.py:1134–1152`):
- `n8n_ok = _res.get("status") == "success"` — identisch zum Dispatcher.
- Bei `False`: `blocked=True`, `error_code = _res["error_code"] or "N8N_DELIVERY_UNCONFIRMED"`, Text ohne „ausgeführt" (HITL/Outbox-Hinweis). Im Non-Stream-Pfad wird daraus `SilentFailureBlockedError`; im Stream-Pfad (`backend/agent_router.py:1463–1477`) jetzt explizit ein `ERROR: <code>`-Chunk statt eines normalen Antworttexts — der bestehende Chat-Konsument (`archon/routers/chat.py:1171`) behandelt das als Provider-Fehler.
- Erfolgstext nur noch bei bestätigtem Status.

**Tests:** `test_n8n_unconfirmed_is_blocked` (4 Fälle: `unconfirmed`, `blocked` mit eigem `error_code`, `warning`, `{}`), `test_n8n_confirmed_success_still_reports_execution`, `test_stream_does_not_emit_success_text_for_unconfirmed_n8n`.

## D02-M2 (MED) — identische Klassifikation in Router und Dispatcher

**Vorher:** Router nutzte `messages[-4:]` + 160-Zeichen-Titel, Dispatcher den vollen Prompt — für denselben Auftrag unterschiedliche `layer`/`rule_id`. Zusätzlich führte reine Substring-Suche dazu, dass „Analysiere die USt-Split-Logik" als 0-Token-Skript galt.

**Nachher** (`backend/execution_routing_guard.py`):
- `canonical_routing_text(messages=…, prompt=…)` (`:100`): vollständiger, rollenbereinigter Auftragstext (System-/Developer-Direktiven + alle User-Turns, multimodal nur Textblöcke), **kein** `[-4:]`-Fenster und keine 160-Zeichen-Kappung.
- `classify_execution_request(messages=…, prompt=…)` (`:135`): der **eine** kanonische Chokepoint; delegiert an `classify_execution_layer()`.
- Negativ-Kontext `_ANALYSIS_DIRECTIVE_RE` (`:89`) + Prüfung in `classify_execution_layer()` (`:177–189`): `analysiere/beschreibe/erkläre/interpretiere/beurteile` unterbindet die Klassifikation als `deterministic_n8n`/`deterministic_script` (weiter zu Hybrid/Probabilistik). Explizite Direktiven (`layer:n8n`, `action:webhook_*`, `action:publish_*`) haben unverändert Vorrang.
- Router ruft ausschließlich den Helper (`backend/agent_router.py:1105–1114`), Dispatcher ebenfalls (`core_dispatcher.py:1642–1646`).

**Tests:** Äquivalenz messages↔prompt, Direktive in altem Turn, vier Negativ-Kontext-Fälle, Vorrang expliziter Direktiven, Spy auf dem Router-Helper sowie statische Verifikation, dass beide Chokepoints `classify_execution_request` und nicht mehr `classify_execution_layer(` / `[:160]` direkt verwenden.

## D05-M1 (MED) — Audit-/Receipt-Schreibfehler nur geloggt

**Vorher:** `agent_router.py:1395–1396` (und Stream `:1729–1730`) loggten den Receipt-Fehler nur (`warning`/`error`) und gaben den LLM-Erfolg zurück; `fleet_self_healing.py:258–285` setzte `status: "success"` trotz `audit_write_failed=True`.

**Nachher:**
- `backend/agent_router.py:19–40`: `_audit_strict()` (Default 1) und `_issue_execution_receipt()`. Bei Schreibfehler `RuntimeError("audit_write_failed")` im Strict-Modus, sonst ERROR-Log mit sichtbarem Fehler (expliziter Opt-out `ARCHON_AUDIT_STRICT=0`). Beide Receipt-Call-Sites (Chat/Stream) rufen jetzt ausschließlich diesen Helper — kein Erfolg ohne Ketteneintrag.
- `backend/fleet_self_healing.py:24–28, 272–275`: nach fehlgeschlagenem `record_event()` hart `RuntimeError("audit_write_failed")` bei Strict=1; `check_fleet_and_heal()` meldet damit `status="error"` statt eine Heilung zu quittieren. Im Opt-out bleibt das Result mit `audit_status="error"`/`audit_write_failed=True` markiert. Der GoBD-Fehlerzähler `_AUDIT_ERROR_COUNTS` bleibt erhalten.

**Tests:** Strict-Negativprobe und Opt-out-Sichtbarkeit für Receipt; Strict-Negativprobe und Opt-out-Flag für Fleet (Docker/Audit/Notification gemockt).

## D12-M6 (MED) — Budget-Settlement-/Semantic-Cache-Fehler

**Vorher** (`core_dispatcher.py`, alten Zeilen 1191–1214): Cache-Store-Fehler nur `logger.debug`, Settlement-Fehler nur `logger.error`; der Dispatch blieb `status="success"`.

**Nachher** (`core_dispatcher.py:853–879, 1220–1245`):
- `_mark_cache_store_failed()` → `res["cache_unverified"] = True` (visibility, kein harter Fehler).
- `_mark_budget_settlement_failed()` → signiertes Audit-Event vom Typ `budget_settlement_failed` über `_audit_dispatch_failure()`, `status="error"`, `error_code="BUDGET_SETTLEMENT_FAILED"`, `error`, `budget_status="paused_budget"` (fail-closed: Verbrauch unbekannt). Aufrufsetzt `is_ok = False`, damit OTel-Span, Bandit-Feedback und Output-Cleanup den Fehler ebenfalls ausweisen; das Reservierungs-`finally` gibt die Reservierung frei.

**Tests:** Helper-Negativprobe (Status/Code/Rolle/Audit-Call), statische Prüfung des `is_ok = False` am Call-Site, Cache-Marker.

---

## Verifikationsstatus

- **Shell/PowerShell in dieser Subagent-Umgebung gesperrt** (`failed to spawn … pwsh.exe: Zugriff verweigert (os error 5)`). Die Testsuite konnte daher **nicht lokal ausgeführt** werden; der Koordinator verifiziert `python -m pytest tests/test_w3_a_router_dispatch.py -q`.
- Statische Verifikation durchgeführt: alle geänderten Abschnitte erneut gelesen, Call-Sites und monkeypatchbare Symbole geprüft, Rückwärtskompatibilität zu bestehenden statischen Tests sichergestellt (`test_reaudit_stage15.py:14` verlangt den String `classify_execution_layer` im Router-Helper — dort als dokumentierender Kommentar enthalten; `test_f22_dag_and_delegation_gates.py` und `test_p4_handoff_fixes.py` patchen `classify_execution_layer`, was über den kanonischen Helper weiterhin greift).
- Keine Commits, keine fremden Dateien, kein Replay, kein Postgres, keine echten externen Calls in den Tests.
