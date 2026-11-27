# Audit-Sanierung Welle W5 / Partition A — Bericht

> **Datum:** 27.11.2026 · **Partition:** W5-A · **Branch:** `main` · **Basis-HEAD:** `65e0f4d9`
> **Status:** statisch editiert, **nicht committet** (Koordinator verifiziert und committet zentral).

## 1. Scope und Regeln

Bearbeitet wurden ausschließlich die freigegebenen Dateien:

| Datei | Änderung |
|---|---|
| `backend/workflow_scheduler.py` | D06-H1: tenant-aware Wartungsschleife, per-Tenant-Retention |
| `backend/event_mesh.py` | D06-H1: `process_outbox(tenant_id=…)` wirklich tenant-scoped, DLQ-Enqueue mit Tenant |
| `backend/dead_letter_queue.py` | D06-H1: `_ensure_db(tenant_id=…)`, alle Manager-Methoden reichen Tenant durch |
| `core_dispatcher.py` | D06-M1: Container-Hop mit Firewall **und** Sanitizer, `is_local` aus SSOT |
| `tests/test_w5_a_tenant_dispatch.py` | neu: 6 Regressionstests (Produktivkonsument geprüft) |
| `audit_reports/w5_a_report.md` | neu: dieser Bericht |

**NEVER_DO_LIST beachtet:** kein PostgreSQL/DSN/Migration, kein Coroutine-/Event-Replay, keine eigene Content-Domäne. Keine fremden Dateien angefasst, keine Secrets in Tests (neutrales `ghp_…`-Format statt `sk-…`), kein `# noqa` ergänzt, kein `git add`/Commit.

Die vorhandenen **W4-Fixes in `core_dispatcher.py` bleiben unverändert erhalten**: `hired_`-Guard (Zeile ~970), 3-Tier-SOUL-Konsument im Dispatch-Kontext (~1450–1560), Audit-Pfade. Die Änderungen betreffen ausschließlich die Zeilen ~541–700 (Gate/Container-Hop).

## 2. Fix-Tabelle

| ID | Krit/Gew | Fund | Code-Fix | Verifikation im Produktivpfad |
|---|---|---|---|---|
| **D06-H1** | HIGH 9 | 30-s-Drainer lief ohne `tenant_id` nur im aktiven Mandanten; Sekundärmandanten wurden nie zugestellt. | **Scheduler:** neue Funktionen `_integration_tenant_ids()`, `_run_integration_maintenance_for_tenant()`, `run_integration_maintenance_cycle()`. Der 30-s-Loop ruft jetzt genau diesen Zyklus; er läuft über alle physisch vorhandenen Mandantenverzeichnisse (`tenant_context.tenants_base_dir`), bindet je Iteration den Request-Mandanten (`set_request_tenant`/`reset_request_tenant` in `try/finally`) und übergibt `tenant_id` explizit an Outbox, DLQ und Retention. Fehler einer Stufe/Mandant blockieren die anderen nicht. **Outbox:** `process_outbox()` ist jetzt Wrapper, der den Kontext für die gesamte Laufzeit bindet (EffectLedger, CAS-Claims, DLQ-Enqueue inkl. `tenant_id=tid`). **DLQ:** `_ensure_db(tenant_id)` löst die DB im expliziten Mandanten auf; `claim_next`/`complete`/`fail`/`enqueue_task`/`replay_job`/`list_dlq` reichen ihn durch. **Retention:** `purge_integration_retention(tenant_id=…)` nutzt `db_paths.resolve_tenant_db` statt der Default-DB; der 30-Min-Throttle ist jetzt **pro Mandant** (Dict statt globalem Timestamp), damit Tenant B nicht als „throttled" verworfen wird. Telemetrie `scheduler_cycle` enthält `tenant_ids` und aggregierte Werte. | Outbox-Zeile in Tenant B wird im echten Zyklus durch den echten `process_outbox`-Konsumenten zugestellt (`status=delivered`, kein Bleed nach A). DLQ-Job in B wird geclaimt, Handler ausgeführt, Status `completed`. Retention löscht alte Zeilen in **beiden** Tenants. |
| **D06-M1** | MED 7 | Container-Hop (Hermes/Odysseus/OpenClaw) rief nur die Egress-Firewall, sendete den Payload unmaskiert. | `_gate_container_dispatch()` leitet `is_local` jetzt identisch zu `_audited_post()` aus `sanitize_llm_endpoint(url)` (`ep_zone == LOCAL_ON_PREM`), `gate.routed_to_local` und lokalen Provider-Namen ab und gibt es im Gate-Dict zurück. `_dispatch_to_container_endpoint()` ruft vor dem POST `sanitize_outbound_llm_payload(payload, agent_id, session_id, is_local)` und sendet `json=safe_payload`. Für OpenClaw wird `task` vor der Sanitierung auf das vom Sanitizer behandelte Feld `prompt` gespiegelt und danach zurückgeführt (Original-Payload bleibt unmutiert). Kein doppelter/logischer Widerspruch: Firewall läuft unverändert im Gate, Maskierung ergänzend im Hop. Audit-Eintrag trägt `extra.secret_mask_applied`. | Alle drei Provider-Hops zeigen im abgefangenen POST-Body das maskierte Äquivalent; lokale Loopback-Zone bleibt bewusst unverändert. Gate-Test prüft `is_local=False` für internes Gateway, `True` für Loopback. |

## 3. Regressionstests

Datei: `tests/test_w5_a_tenant_dispatch.py` (6 Tests, `asyncio_mode=auto`).

| Testname | Fund | Was geprüft wird |
|---|---|---|
| `test_gate_container_dispatch_derives_is_local_from_endpoint_zone` | D06-M1 | `is_local` aus `sanitize_llm_endpoint`: `hermes:9119` → `False`, `127.0.0.1:9119` → `True`; Firewall-Felder unverändert. |
| `test_container_hop_masks_secret_for_all_three_providers` | D06-M1 | Echte `dispatch_to_hermes`/`odysseus`/`openclaw` → abgefangener `httpx`-POST: Token maskiert, Feldform `messages`/`prompt`/`task`, Audit-Flag `secret_mask_applied=True`, Aufrufer-Payload unmutiert. |
| `test_container_hop_keeps_local_payload_unmasked` | D06-M1 | Loopback-URL: Payload bleibt unverändert, `secret_mask_applied=False`. |
| `test_secondary_tenant_outbox_is_delivered_in_scheduler_cycle` | D06-H1 | Zwei echte Mandanten-DBs; fällige Outbox-Zeile in **Tenant B** wird im Zyklus zugestellt (`delivered=1`, DB-Status `delivered`), Tenant A unbeührt. |
| `test_secondary_tenant_dlq_job_is_consumed_in_scheduler_cycle` | D06-H1 | DLQ-Job in B via Produktiv-`enqueue_task` geclaimt, registrierter Handler ausgeführt, Status `completed`. |
| `test_integration_retention_throttle_is_per_tenant` | D06-H1 | Alte Zeilen in A **und** B werden im selben Zyklus gelöscht — der Throttle darf B nicht nach A überspringen. |

Die Tests erzeugen ihre Mandantenverzeichnisse über `TenantContextManager` unter `tmp_path`; es wird keine echte `./data`-DB beschrieben. Secret-Placeholder: `TEST_TOKEN = "ghp_" + "A" * 30` (kein `sk-<Zeichen>`), erwartete Maske `[GESCHÜTZTER_GITHUB_TOKEN]`.

## 4. Risiken / Hinweise für den Koordinator

1. **Zentrale Verifikation nötig:** Subagent-Shell war gesperrt (`pwsh.exe: Zugriff verweigert`). Ruff (`--select E,F,I --ignore E501`), MyPy (`--config-file mypy.ini`) und `pytest tests/test_w5_a_tenant_dispatch.py` wurden **nicht** hier ausgeführt — bitte zentral mit `ARCHON_TEST_DB_ISOLATION=1` laufen lassen.
2. **Mandanten-Enumerierung:** Die Schleife nutzt die physisch vorhandenen Verzeichnisse unter `tenants_base_dir` (SSOT `tenant_context`). Ein Company-Eintrag ohne angelegtes Verzeichnis hat per Definition noch keine DB und wird daher nicht wartungspflichtig gehalten. Fallback `default` nur wenn keine Verzeichnisse existieren.
3. **Kontext-Propagation:** `asyncio.to_thread` kopiert den `contextvars`-Kontext; zusätzlich wird `tenant_id` explizit an alle Konsumenten übergeben. Beides ist absichtlich redundant (Robustheit bei Direktaufrufen), aber nicht widersprüchlich.
4. **Bestandsverträge:** Alle geänderten Signaturen sind kompatibel ergänzt (`tenant_id=None` bzw. neues Dict-Feld im Gate). `purge_integration_retention` ohne `tenant_id` nutzt weiterhin den monkeypatchbaren Default-Pfad (Bestandstest `test_purge_integration_retention_deletes_old_keeps_open` bleibt gültig). `_gate_container_dispatch` gab bereits ein Dict zurück; bestehende Mocks ohne `is_local` führen zu `False` (Maskierung) — das ist der sichere Default.
5. **OpenClaw-Feld:** Der Sanitizer kennt `task` nicht; die Spiegelung auf `prompt` erfolgt im Hop, nicht in `backend/llm_egress_guard.py` (gehört nicht zu dieser Partition). Bei einem Payload mit gleichzeitig `task` **und** `prompt` werden beide Felder separat über `prompt` gespiegelt bzw. deren sanitierter Wert übernommen.
6. **Kein Commit:** Wie vorgegeben wurde nichts gestaget/committet. Report-Datei benötigt beim Commit `git add -f` (`.gitignore:55` matcht `*report*`).

## 5. Kurzfassung

Beide Funde der Partition W5-A sind statisch behoben: der 30-s-Drainer wartet jetzt jeden Mandanten explizit (Outbox → DLQ → Retention, mit per-Tenant-Throttle und Telemetrie), und der Container-Hop wendet Firewall **und** Payload-Sanitizer an, wobei `is_local` zentral aus `sanitize_llm_endpoint` abgeleitet wird. Sechs Regressionstests decken den Produktivpfad inklusive Sekundärmandant und Maskierung ab. Verifikation und Commit erfolgen durch den Koordinator.
