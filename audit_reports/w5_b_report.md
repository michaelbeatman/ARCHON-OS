# Welle W5 — Partition B: Chaos / Autoheal / Restore (D10-H1, D10-M1, D10-M2)

> **Erstellt:** 27.11.2026 · **Branch:** `main` (HEAD bei Start `65e0f4d9`, Arbeitsbaum sauber)
> **Subagent:** statische Edits, **kein Commit, kein `git add`**.
> **Verifikation:** Shell in Subagent-Sessions gesperrt (`pwsh.exe: Zugriff verweigert`,
> bestätigt beim Versuch `py_compile`). Der **Koordinator verifiziert zentral**
> (ruff / mypy / pytest). Alle Änderungen wurden statisch mehrfach gelesen und
> auf Syntax, Importe, Typ-Annotationen und Vertragskonsistenz geprüft.

---

## 1. Fund D10-H1 (HIGH 9) — Restart-SLA war Scheinerfolg

### Produktivcode

| Datei | Änderung |
|---|---|
| `scripts/chaos_tester.py` | `test_simulated_container_restart()` misst jetzt die **End-to-End-Zeit** `t_fail` (unmittelbar vor dem ausgelösten Ausfall) bis `t_recovered` (erster HTTP-200 von `/livez`). `passed` nur bei `(t_recovered - t_fail) < 15 s` **und** `State=Status=running`. Neue Helfer `livez_ok()` (nur 200 zählt), `trigger_restart()` (echter Proxy-Pfad `stop?t=2` + `start`, Fallback `restart_container()`), `wait_for_livez()` (Poll bis `LIVEZ_WAIT_TIMEOUT_S`). Konfiguration: `CHAOS_LIVEZ_URL`, `CHAOS_LIVEZ_POLL_INTERVAL_S`, `CHAOS_LIVEZ_WAIT_TIMEOUT_S`, `CHAOS_RESTART_STOP_GRACE_S`. |
| `scripts/chaos_tester.py` | Dry-Run liefert **`status="skipped"`** mit `reason="dry_run_sla_not_measurable"` statt `passed`. `main()` beendet mit **Exit 1**, wenn `tests_failed > 0` **oder** `tests_skipped > 0`. Damit ist „nicht prüfbar" kein Erfolg mehr (D08-M6-Vertrag übernommen). |
| `scripts/archon_autoheal.py` | Erkennungsbudget von `30 s × 5 = 150 s` auf **`5 s × 2 = 10 s`** gesenkt (+ max. 2 s Probe-Timeout ⇒ ≤ 12 s). `PROBE_TIMEOUT` 5→2 s, `WATCHDOG_MAX_AGE` 120→60 s. `HEALTH_GATE` Default `1`→`0`: der 90-s-Docker-Healthcheck darf die SLA nicht mehr blockieren; Opt-in bleibt möglich. `_do_restart()` nutzt `POST /containers/<name>/stop?t=2` statt `stop` ohne Query (sonst ~10 s SIGTERM-Warte). |
| `config/prometheus/alerts.yml` | Falsche Behauptung „läuft die Suite als harter CI-Gate" korrigiert. Neuer ehrlicher **Gate-Vertrag** als Kommentar: Exit-Bedingungen beider Skripte, Realität `.github/workflows/ci.yml` ruft nur `automated_restore_test.py`, `chaos_tester.py` ist **nicht** verdrahtet. Keine erfundenen `chaos_*`-Metriken. |

`docker-compose.yml:188-195` (Healthcheck) gehört **Partition C** und wurde **nicht** angefasst.

### Regressionstests (`tests/test_w5_b_chaos_restore.py`)
`test_d10_h1_dry_run_is_skipped_and_breaks_exit_gate`,
`test_d10_h1_sla_is_measured_from_failure_to_livez_200`,
`test_d10_h1_late_livez_200_is_sla_violation`,
`test_d10_h1_never_healthy_is_failed_not_passed`,
`test_d10_h1_autoheal_detection_budget_and_fast_stop`.
Sie fahren den echten Pfad: `DockerAdminClient` wird nur am Transport gemockt,
`trigger_restart`, `wait_for_livez`, `_record_result`, `main()`-Exit und
`_do_restart()` laufen unverändert. Uhr und `/livez`-Probe sind injizierbar
(Produktivdefaults `time.time` / `livez_ok`).

---

## 2. Fund D10-M1 (MED 7) — Watchdog-Test las nie entstehende Logdatei

### Produktivcode
`scripts/chaos_tester.py::test_watchdog_supervisor_responsiveness()` liest jetzt
ausschließlich die atomare **`watchdog_liveness.json`** (dieselbe Datei, die
`watchdog_daemon.py:76-110,459-511` schreibt) an den bekannten Orten
`DATA_DIR`, `<workspace>/data`, `/app/data`, `<workspace>`. Zwei Proben im
Abstand `CHAOS_WATCHDOG_SAMPLE_INTERVAL_S` (Default 31 s > 30-s-Loop) vergleichen
`loop_count` (muss steigen), `last_seen` (darf nicht zurückgehen) und Alter
(≤ `CHAOS_WATCHDOG_MAX_LIVENESS_AGE_S`, Default 60 s). Fehlende/korrumpiert
Evidenz ⇒ **`failed`**, nie `skipped`. Helper `find_watchdog_liveness()` /
`read_watchdog_liveness()` (fail-closed).

`watchdog_daemon.py` ist **nicht** in meinem Besitz und wurde **nur gelesen**;
kein Fix dort nötig — die Liveness-Datei wird bereits korrekt atomar geschrieben
und bei Loop-Exit auf `alive=false` gesetzt. Der Fix gehört vollständig in den
Test-/Chaos-Pfad.

### Regressionstests
`test_d10_m1_watchdog_uses_liveness_file_not_legacy_log` (statischer Gate),
`test_d10_m1_advancing_loop_count_and_fresh_timestamp_passes`,
`test_d10_m1_missing_liveness_evidence_is_failed`,
`test_d10_m1_stalled_or_stale_watchdog_is_failed`.
Der 31-s-Abstand ist über `sample_interval_s` injizierbar; der Test schreibt
zwischen den beiden echten Datei-Lesevorgängen den nächsten Loop-Tick.

---

## 3. Fund D10-M2 (MED 7) — Restore-Test prüfte nur Config-Präsenz

### Produktivcode
`scripts/automated_restore_test.py`:
- neue Pflichtquelle `ARCHON_LITESTREAM_REPLICA_DIR` (Default `<workspace>/dr_replicas`)
  mit `_find_litestream_replicas()` für `ops.db`, `business.db`, `memory.db`,
  `kanban.db`, `state.db` und `tenants/<tid>/*.db`.
- `_restore_litestream_replica()` führt den echten Befehl aus:
  `litestream restore -o <sandbox>/… -config <config> <db-path>`; der DB-Pfad
  kommt aus `config/litestream.yml` (SSOT, Fallback-Tabelle für die 5
  Bestandseinträge). Timeout `ARCHON_LITESTREAM_RESTORE_TIMEOUT_S`.
- `_verify_sqlite_snapshot()` wendet **dieselbe** Prüfung wie der Backup-Pfad an:
  `integrity_check`, `foreign_key_check`, Tabellen-/Datensatz-Smoke.
- **Frische-Gate**: jüngster Artefakt-Timestamp ≤ `ARCHON_LITESTREAM_MAX_AGE_S`
  (Default 120 s, passend zu `sync-interval` 5–10 s).
- Fehlendes Replikat ⇒ eigenes Detail `LITESTREAM_REPLICA_SOURCE` mit
  `status=FAILED` — **nie `SKIPPED`**, nie stilles Grün.
- `TENANT_REPLICATION` ist nur noch `PASSED`, wenn Configabdeckung **und** ein
  echtes Tenant-Replikat restore-verifiziert wurde (`litestream_config_present`
  + `litestream_restore_verified` im Report).

`docs/system/AUTOMATED_RESTORE_TEST_GUIDE.md` komplett aktualisiert: kein
„5 Ziele, PASSED 5/5" mehr, neuer Abschnitt zum echten Replikat-Restore inkl.
Env-Variablen-Tabelle, Frische-Gate, ehrlicher CI-Gate-Status (§6).

### Regressionstests
`test_d10_m2_replica_is_really_restored_and_verified`,
`test_d10_m2_missing_replica_is_failed_not_skipped`,
`test_d10_m2_stale_replica_is_failed`,
`test_d10_m2_restore_command_failure_is_failed`,
`test_d10_m2_tenant_replication_needs_real_restore`,
`test_d10_m2_guide_and_alerts_are_honest`.
Der `litestream`-Subprocess wird am subprocess-Rand gemockt und schreibt eine
**echte SQLite-Datei** in die Sandbox; danach laufen die echten PRAGMAs.

---

## 4. Abnahme/Verifikation — offene Punkte für den Koordinator

1. **Zentrale Verifikation:** `ruff check --select E,F,I --ignore E501`,
   `mypy --config-file mypy.ini` und `pytest tests/test_w5_b_chaos_restore.py`
   (mit `ARCHON_TEST_DB_ISOLATION=1`) laufen lassen. Shell war hier gesperrt.
   Statisch geprüft: Imports sortiert, ungenutzter `subprocess`-Import entfernt,
   `Optional` ergänzt, `# type: ignore[misc]` am Generator, **kein `# noqa` in
   einer String-öffnenden Zeile**, keine `sk-<…>`-Secrets.
2. **Legacy-Test-Anpassung nötig (Datei nicht in meinem Besitz):**
   `tests/test_p0_welle_b.py:35-51` glaubt noch an den alten Logdatei-Vertrag.
   `test_chaos_watchdog_without_evidence_is_not_passed` erwartet `skipped`
   (jetzt `failed`) und `test_chaos_watchdog_with_fresh_log_can_pass` erwartet
   `passed` bei `watchdog_daemon.log` (jetzt `failed`). Bitte Fixture auf
   `watchdog_liveness.json` umstellen (`last_seen=time.time()`,
   `loop_count=n`, `alive=true`) und die Erwartung auf `passed`/`failed`
   angleichen. `test_chaos_watchdog_with_stale_log_fails` bleibt grün.
3. `tests/test_fix_w4_c_hardening.py::test_chaos_restart_sla_is_enforced`
   bleibt inhaltlich grün (`status=failed`, `sla_violation=True`,
   `fake.restarted==1`), braucht aber bis zu ~15 s, weil der `/livez`-Poll
   jetzt real bis zum Fensterende läuft. Bei Bedarf `CHAOS_LIVEZ_WAIT_TIMEOUT_S`
   in diesem Test senken — nicht in Partition B ändern.
4. **`.github/workflows/ci.yml`** gehört keiner W5-B-Datei an: `chaos_tester.py`
   ist dort weiterhin nicht verdrahtet. Doku und `alerts.yml` behaupten das
   jetzt ausdrücklich nicht mehr. Falls ein echter CI-Gate gewünscht ist, muss
   der Koordinator ihn zentral ergänzen.
5. Nicht verändert: `docker-compose.yml` (C), `watchdog_daemon.py` (lesend),
   `ci.yml`, `tests/test_p0_welle_b.py`, `tests/test_fix_w4_c_hardening.py`,
   `GEWICHTETE_BEFUNDLISTE.md`.

**Keine Commits, keine Staging-Operationen durch diesen Subagenten.**
Hinweis für den Koordinator: `.gitignore:55` (`**/*report*`) erfasst auch
`audit_reports/w5_b_report.md` → beim zentralen Commit `git add -f` verwenden.
