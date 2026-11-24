# Fix-Wellen-Status (24.11.2026) — Archon OS v0.5.7.6

Baseline: `audit-baseline-v0.5.7.6` = `8ed2c025`.
Zwei Stränge: **A (Core, Gemini NEON)** = `audit-fixes-core`, **B (Masse, Hy4 High)** = `audit-fixes-mass`.
B wurde auf A und anschließend auf `origin/main` (9947e098) rebase't; beide Stränge sind linear.

## Strang A — Core (4 Commits)

| Commit | Domänen | Inhalt |
|---|---|---|
| `8817a9f4` | D05, D04 | Zentrale fail-closed `sign_block()`-API, signierter 4-Spalten-Anker, Append-Only-Trigger-Check, Epochen-Sortierung; Spalten `trace_id`/`session_id`/`correlation_id` (+ Indizes); 5 Nebenketten HMAC-gehärtet; Passkey-Resource-Binding |
| `780d796a` | D01, D04, D12 | Leere HTTP-200-Antworten → `RuntimeError`; echte Kostenberechnung; `ZeroEgressBlockedError` re-raised; `structured_output_enforcer` fail-closed; AST-Blocker gegen `__import__`/`eval`/`exec`/Dunder |
| `ef63e16a` | D02, D05, D07, D08, D14 | `cancelled`/`paused`/`delegation_depth`/`replan_count`/`failure_reason` über SQLite-Reloads erhalten; atomares `cancel_and_reset_scope()`; globales Tages-Kosten-Cap; Chairman-Hoheit (400 bei unbekanntem ID), `NO_CONSENSUS` ohne Decision-Event; `try/finally` nach `acquire_slot` |
| `69e01562` | D03 | Divergierende PK-Kollisionen brechen mit `DATENVERLUST` ab; 28→3-Konsolidierung auch unter `FULL_TENANT_ISOLATION`; `resolve_db()` ohne stillen Fallthrough |

## Strang B — Masse (Commits auf `audit-fixes-mass`)

| Commit | Domänen | Inhalt |
|---|---|---|
| `f424ccf0`/`7ad1c1f9` | D09 | CI: `continue-on-error`/`|| true` entfernt; hartes Ruff-Gate (E9/F63/F7/F82); `ARCHON_TEST_DB_ISOLATION=1` in allen Test-Jobs; lokaler Runner mit Pytest/Build/pip-audit/bandit |
| `a5095beb`/`74b0af7c` | D04, D03 | 19 RBAC-Wraeper zentralisiert; `erp.py`: `company_id` aus Tenant-Kontext, abweichende Werte → 403 (nach RBAC) |
| `1a6653de` | D15 | **`souls/` versioniert** (490 Artefakte DE+EN + SHA-256-Manifest), Generatoren + 2 CI-Drift-Gates; Negativ-Abgrenzungen in allen 70 Profilen; EU-AI-Act HIGH_RISK 2 → 26; keine erfundenen SOUL-Hashes |
| `388f03cb` | D15 | Manifest-Hash über normalisierte Zeilenenden; `.gitattributes` `souls/** text eol=lf` |
| `64bd85cf` | D10, D03 | `time.sleep(86400)`-Scheinworker aus beiden Compose-Dateien entfernt; `backup_archon.py` sichert Tenant-DBs; Litestream `watch: true` |
| `8726cb1b` | D01 | War-Room: UNKNOWN + `evaluation_failed` statt erfundenem MEDIUM, fail-closed; Eval-Suite-Endpoint mit RBAC |
| `dbfdf0b0` | D16 | `backend/trace_context.py` (W3C traceparent, contextvars), `TraceContextMiddleware`, Audit-Korrelation, OmniRoute-Header, Doku-Korrektur |
| `7406fca` | Doku | `.gitignore`-Ausnahme: alle 16 Domänenberichte + Gesamt- und Statusbericht sind jetzt versioniert |
| `B7` | D08 | `api_provider.collect_keys()` korrekt mit 30-s-TTL-Cache + Lock + Invalidierung nach `deploy_keys()` — kein Profil-.env-Scan pro Dispatch mehr |

*(Die Commit-Hashes können nach dem Rebase abweichen — maßgeblich ist `git log audit-fixes-mass`.)*

## Verifikation
- **40 kombinierte Regressionstests grün** (`tests/test_core_a1…a4`, `test_audit_b2…b5`), `.ci_venv`, `ARCHON_TEST_DB_ISOLATION=1`.
- `py_compile` über alle geänderten Module, YAML-Parse von `ci.yml`/`litestream.yml`/beiden Compose-Dateien.
- `souls/build_souls_ssot.py --check`: 490/490 Artefakte hash-konsistent.

## Offene Punkte (ausdrücklich noch NICHT behoben)
1. **D16:** Trace-Propagation über alle 18 Systemgrenzen (n8n, Hermes, PocketBase, MCP, SSE, Outbox, `to_thread`) und echter OTel-Collector/Langfuse-Export mit Sampling.
2. **D08 (Rest):** Performance-Hotpaths (`chat.py` SQLite-Writes via `to_thread`, `SELECT *`/`fetchall()` ohne `LIMIT`, Frontend-Virtualisierung der 832 Templates). Der `api_provider.py`-Key-Cache ist behoben.
3. **D11/D14:** Pydantic-Handoffs ohne stille Truncation; `NO_CONSENSUS`-Tie-Breaking vollständig; Vier-Augen-Ersteller-Abgleich.
4. **D10:** Produktiv-Deploy-Pfad (Ansible nutzt weiterhin `docker-compose.dev.yml` mit `--reload`); externer Dead-Man-Switch; RPO/RTO.
5. **Laufzeit-Caches:** `.hermes/profiles/` und `data/hermes_profiles/` müssen im Haupt-Repo einmalig mit `python scripts/sync_soul_modes.py --mode compact` aus der neuen SSOT regeneriert werden (gitignorierte Caches, nicht im Worktree sichtbar).
6. **skip-worktree:** `agent_profiles.json`, `roles.json`, `settings.json`, `config/kanban_meta.json` bleiben lokal geschützt (73 lokale vs. 70 GitHub-Profile). Neue allgemeine Rollen in `roles.json` werden nicht automatisch gepusht.

## Dokumentation
- `docs/system/LLM_TRACING_LANGFUSE_GUIDE.md`: Abschnitt 0 beschreibt jetzt den echten Ist-Zustand statt des alten OTel-Claims.
- Dieses Dokument ist die verbindliche Fix-Wellen-Übersicht; die 16 Einzelberichte liegen als `2026-11-24_d01…d16_*.md` im selben Verzeichnis.
