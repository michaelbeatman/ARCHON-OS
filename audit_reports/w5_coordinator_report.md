# W5 — Koordinator-Report (Verifikation & Nachverdrahtung)

**Datum:** 27.11.2026 · **Welle:** W5 (17 Funde, sechs dateidisjunkte Partitionen)
**Vorlage:** `HANDOFF_W4_W7.md` §6/§9 · `NEVER_DO_LIST.md` beachtet
**Subagenten:** A–F haben statisch editiert und **nicht** committet; Verifikation
und Commits liegen beim Koordinator.

---

## 1. Partitionsberichte

Die Details liegen in `audit_reports/w5_a_report.md` … `w5_f_report.md`
(wegen `.gitignore:55` **mit `git add -f`** committet).

| Partition | Funde | Neue Tests |
|---|---|---:|
| A — Tenant/Dispatch | D06-H1, D06-M1 | 6 (`test_w5_a_tenant_dispatch.py`) |
| B — Chaos/Restore | D10-H1, M1, M2 | 15 (`test_w5_b_chaos_restore.py`) |
| C — Infrastruktur | D10-M3..M6, M8 (Proxy-Teil) | 5 (`test_w5_c_hardening.py`) |
| D — Shutdown | D10-M7 (ergänzend zum W3-Budget) | 4 (`test_w5_d_shutdown.py`) |
| E — Container/Tracing | D16-H1, D16-M1 | 6 (`test_w5_e_tracing.py`) |
| F — Trace-Payload | D16-M2..M5 | 12 (`test_w5_f_trace_payload.py`) |
| Koordinator | D10-M8 (Backend), D16-M3 (Konsument) | 5 (`test_w5_coordinator.py`) |

---

## 2. Koordinator-Nacharbeiten

1. **D16-M3 — `span_id` bis in den Audit-Hop:** `core_dispatcher.py` fängt
   `current_span_id()` innerhalb von `child_span()` und reicht den Wert an
   beide `_audit_log_async`-Aufrufe weiter; `log_completed_llm_dispatch()`
   in `backend/llm_egress_guard.py` nimmt jetzt `span_id` entgegen und gibt
   ihn an `record_llm_dispatch()` durch (mit `current_span_id()`-Fallback).
2. **D16-M4 — Grafana-Brücke:** `config/grafana/datasources/datasources.yml`
   hat jetzt `tracesToLogs.tags: [trace_id, span_id]` und
   `filterBySpanID: true`.
3. **D10-M8 — harter Readyz-Fehler:** `ensure_worker_zero_egress_network()`
   wirft `RuntimeError`, wenn das Netz fehlt oder `Internal != true`. Der
   Startup-Hook in `archon/services/shutdown_clients.py` schreibt
   `_ZERO_EGRESS_NETWORK_STATUS` und reicht den Fehler weiter;
   `archon/services/health_probes.py` meldet ihn als `/readyz`-Problem.
   `.env.example` enthält jetzt einen neutralen Platzhalter für die durch
   `docker-compose.yml` Pflicht gewordene Heartbeat-Webhook-URL.
4. **Legacylogik angepasst (Muster Handover §3):**
   - `test_p0_welle_b.py`: Watchdog-Evidenz ist `watchdog_liveness.json`
     statt der nie geschriebenen Logdatei; fehlende Evidenz ist `failed`,
     nicht `skipped` (D10-M1).
   - `test_w5_a_tenant_dispatch.py`: DLQ-Handler sind vertragsgemäß `async`
     (`workflow_scheduler.py:1830`) — der Test lief gegen einen Sync-Handler.
   - `test_reaudit_d16_otel.py`: Log-Prefix trägt jetzt
     `[trace_id=… span_id=…]`, Promtail-Label `span_id` wird geprüft.
   - `docs/system/AUTOMATED_RESTORE_TEST_GUIDE.md`: die historische
     „PASSED 5/5"-Behauptung steht nicht mehr wörtlich im Dokument.
   - `test_w5_c_hardening.py`: Ansible-Inspect-Zeichenkette an die echte
     `command`-Form angepasst.
   - Ruff-Hygiene in `backend/dead_letter_queue.py` (E402/I001),
     `backend/event_mesh.py` und den angepassten Legacy-Tests.
5. **W3/W4-Fixes erhalten:** SOUL-Tier-Konsument, `hired_`-Guard, Lease-Fail-
   Closed, Shutdown-Budget und der W3-Audit-Anker-Stopp blieben unangetastet.

**Entscheidung zu W6 / D09-H1 (Benutzer, 27.11.2026):** die Entflechtung von
`main.py`/`core_dispatcher.py` wird **nicht** verfolgt. `D09-H1` wird in W6
ausschließlich als **Image-Digest-Pinning + Adapter-Smoke-Test als CI-Gate**
umgesetzt; der 10.290-Zeilen-Patch bleibt unverändert.

---

## 3. Verifikation

```powershell
$env:ARCHON_TEST_DB_ISOLATION='1'
$files = (git diff --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' }) +
         (Get-ChildItem tests/test_w5_*.py)
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise $files
.venv\Scripts\python.exe -m mypy --config-file mypy.ini $files
.venv\Scripts\python.exe -m pytest tests/ -q
```

- Ruff (`E,F,I`, `E501` ignoriert): **All checks passed** (30 Dateien).
- MyPy (`mypy.ini`): **Success: no issues found in 30 source files**.
- Neue W5-Suiten + D16-/Router-Characterization: **80 passed**.
- Full-Suite: **2866 passed, 16 skipped, 21 failed** (302 s). Die 21 Roten
  sind die dokumentierte Baseline aus `HANDOFF_W4_W7.md` §3. Gegenüber dem
  Stand vor W5 (22 Rot) ist ein Fehler weniger — der alte Trace-Close-Test
  läuft jetzt durch. Kein neuer Fehler.

---

## 4. Abnahme

- [x] Alle 17 W5-Funde: Code-Fix + Regressionstest im Produktivpfad.
- [x] Ruff und MyPy auf allen geänderten `.py`-Dateien: Exit 0.
- [x] Neue Suiten grün; Full-Suite besser als Baseline.
- [x] Keine fremden Dateien „nebenbei" verändert, keine Secrets in Tests,
      keine Subagent-Commits.
- [x] Sechs Partitionsberichte + dieser Koordinator-Report mit `git add -f`.
- [ ] Status-Synchronisierung in `GEWICHTETE_BEFUNDLISTE.md` folgt als separater
      Commit (Muster `786d6e71`).
