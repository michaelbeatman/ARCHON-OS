# W6 — Koordinator-Report (Verifikation & Nachverdrahtung)

**Datum:** 27.11.2026 · **Welle:** W6 (17 Funde, fünf dateidisjunkte Partitionen)
**Vorlage:** `HANDOFF_W4_W7.md` §7/§9 · `NEVER_DO_LIST.md` beachtet
**Subagenten:** A–E haben statisch editiert und **nicht** committet; Verifikation
und Commits liegen beim Koordinator.

---

## 1. Partitionsberichte

Die Details liegen in `audit_reports/w6_a_report.md` … `w6_e_report.md`
(wegen `.gitignore:55` **mit `git add -f`** committet).

| Partition | Funde | Neue Tests |
|---|---|---:|
| A — Async-Idempotency | D08-H1 | 6 (`test_w6_a_perf.py`) |
| B — Sync-Blöcke | D08-M1..M5 | 8 (`test_w6_b_sync.py`) |
| C — Gates/Index/Budget | D08-M6, M7, M9, D09-M3 | 10 (`test_w6_c_gates.py`) |
| D — Digest/Smoke (REDuziert) | D09-H1, D09-M4 | 11 (`test_w6_d_patch.py`) |
| E — CI-Gates/Typen | D09-M1, M2, M5, M6, M8 | 15 (`test_w6_e_ci.py`) |

**Benutzerentscheidung zu D09-H1:** nur Image-Digest-Pinning + Adapter-Smoke-Test
als hartes CI-Gate. Keine Zerlegung des 10.290-Zeilen-Patches, keine
Entflechtung von `main.py`/`core_dispatcher.py`. Der Patch blieb byte-identisch;
`main.py` wurde nur an der einen `D09-M4`-Route geändert.

---

## 2. Koordinator-Nacharbeiten

1. **Zweiter Import-Linter-Contract** (D09-M2): `tests/test_import_layer_contracts.py`
   prüft jetzt zusätzlich `importlinter:contract:core-no-router-imports`
   (Source `archon.core`, forbidden `archon.routers`, `allow_indirect_imports=false`)
   und den transitiven Umweg über `archon.services`.
2. **CI-Root-Dateilisten vervollständigt** (D09-M5): `research_engine.py`,
   `research_engine_v2.py`, `seo_execution_agent.py`, `telegram_notify.py` und
   `update_dist.py` fehlten in `compileall`, `bandit` und `ruff` — alle drei
   Gates erfassen jetzt denselben ausgelieferten Code. Der Test
   `test_w6_e_root_module_list_matches_checkout` gleicht die Liste mit dem
   Checkout ab.
3. **Undo-TTL-Urteil erreichbar gemacht** (D09-M6): in `backend/operations_bulk.py`
   lief `_prune_undo_store()` vor der TTL-Prüfung, wodurch abgelaufene Tokens
   fälschlich `404 „nicht gefunden"` statt `400 „abgelaufen"` ergaben. Die
   TTL-Prüfung steht jetzt vor dem Pruning; CAS und `RLock` blieben erhalten.
4. **Korrektur der Handover-Zeilennummern:** `D08-H1` verwies auf `:1645/1675/1705`;
   nach der W3-Cluster-Extraktion liegt der echte Retry-Pfad bei `:1980`.

**Verteidigte Alt-Fixes:** W4-SOUL-Konsument/`hired_`-Guard, W5-Tenant-Cycle,
W5-Chaos-SLA, W5-Trace-Kontext, W3-Shutdown-Budget und der W3-Audit-Anker-Stopp
blieben unangetastet.

---

## 3. Verifikation

```powershell
$env:ARCHON_TEST_DB_ISOLATION='1'
$files = (git diff --name-only --diff-filter=ACMR | Where-Object { $_ -match '\.py$' }) +
         (Get-ChildItem tests/test_w6_*.py)
.venv\Scripts\python.exe -m ruff check --select E,F,I --ignore E501 --output-format=concise $files
.venv\Scripts\python.exe -m mypy --config-file mypy.ini $files
.venv\Scripts\python.exe -m pytest tests/ -q
```

- Ruff (`E,F,I`, `E501` ignoriert): **All checks passed** (18 Dateien).
- MyPy (`mypy.ini`, jetzt `python_version = 3.13`): **Success: no issues found
  in 18 source files**.
- Smoke-Gate `python scripts/telegram_adapter_smoke_test.py`: **Exit 0**
  (Digest in 2 Services, Mount, 8 Hooks, 9 `register_platform`-Kwargs,
  4 Patch-Marker). Negativproben der Partition D liefern Exit 1.
- Neue W6-Suiten + Import-/Bulk-/Router-Characterization: **66 passed**.
- Full-Suite: **2918 passed, 16 skipped, 21 failed** (303 s). Die 21 Roten
  sind exakt die Baseline aus `HANDOFF_W4_W7.md` §3. Kein neuer Fehler.

`lint-imports` ist im lokalen venv nicht installiert (kommt hash-geprüft aus
`requirements-ci.lock.txt`); der CI-Schritt ist verdrahtet, der lokale Lauf
entfiel daher. Die Config selbst ist durch Partition E und die beiden Tests
abgesichert.

---

## 4. Abnahme

- [x] Alle 17 W6-Funde: Code-Fix + Regressionstest im Produktivpfad.
- [x] Ruff und MyPy auf allen geänderten `.py`-Dateien: Exit 0.
- [x] Neue Suiten grün; Full-Suite auf Baseline-Niveau.
- [x] Keine fremden Dateien „nebenbei" verändert, keine Secrets in Tests,
      keine Subagent-Commits.
- [x] Fünf Partitionsberichte + dieser Koordinator-Report mit `git add -f`.
- [ ] Status-Synchronisierung in `GEWICHTETE_BEFUNDLISTE.md` folgt als separater
      Commit (Muster `786d6e71`).
