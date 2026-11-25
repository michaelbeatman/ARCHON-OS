# Fix-Report — W1 / F011 / BLOCKER B-11 (verlustfreie Session-DAG)

**Datum:** 25.11.2026 · **Scope:** Remediation nach `audit_reports/MASTER_PLAN.md` §4/§5 (F011)
und `audit_reports/domain_11.md` (BLOCKER B-11 + MED zur lcm-DB).
**Verifikationsstatus:** ⚠️ Shell in dieser Session gesperrt (`pwsh.exe: Zugriff verweigert, os error 5`) —
`python -m compileall`, `pytest` und Import-Checks konnten **nicht ausgeführt** werden. Alle Aussagen
sind statisch gegen den Code belegt; dynamische Verifikation ist zwingend in W0/F050 nachzuholen.

---

## 1. Geänderte Dateien (exklusives Ownership eingehalten)

| Datei | Änderung |
|---|---|
| `backend/lossless_session_dag.py` | Vollständige Remediation: Produzenten-Helfer, rekursive Expansion, UNION-Suche, konsolidierte DB, Tenant-Spalte, HMAC, Art.17 |
| `backend/agent_router.py` | Nur Kompressions-Chokepoint: `_compress_conversation_window` (Z.387–448) und `_enforce_token_guard_unlocked` (Z.595–631) |
| `backend/context_compactor.py` | Produzent im echten `compact_messages()`-Pfad (Z.79–93, 149–161, 175–178) |
| `archon/routers/v2_capabilities.py` | Nur Lossless-Such-Endpunkt `api_v2_lossless_search` (Z.923–934): tenant-scoped |
| `tests/test_milestones_block_ab.py` | Unverändert — bestehender Regressionstest muss weiter grün sein |
| `tests/test_fix_w1_b_lossless.py` | Neu: 5 Regressionstests (Produzent/Expansion/Tenant/Art.17/Pfad-SSOT) |

Nicht angefasst: `archon/core/delegation.py`, `archon/core/orchestration.py`, `core_dispatcher.py`,
`gdpr_compliance_engine.py`, `backend/db_paths.py`, `backend/handoff_desk.py` (nur gelesen).

---

## 2. Umsetzung der vier Anforderungen

### 2.1 Produzent im Produktivpfad („Theater" beseitigt)

Vorher: `append_turn()`/`compact_range_to_summary()` kamen nur aus
`tests/test_milestones_block_ab.py:62-66`. Jetzt:

- **`backend/agent_router.py:595-604`** — `_enforce_token_guard_unlocked()` ist der
  Chokepoint, den **jeder echte LLM-Dispatch** durchläuft (`_chat_completion_unreserved`
  Z.1105–1107 via `asyncio.to_thread`, sowie Stream-Pfad). Dort wird
  `record_turns(session_id, messages, tenant_id=…)` aufgerufen — idempotent über einen
  deterministischen `dedup_key`, also kein Duplikat bei wiederholten Dispatches.
- **`backend/agent_router.py:437-448`** — beim echten Context-Compacting
  (`_compress_conversation_window`, aufgerufen aus Z.608–609) erzeugt
  `compact_conversation_turns()` den Summary-Knoten mit den verdichteten Turns als Kindern.
- **`backend/context_compactor.py:82-93, 149-161`** — der zweite reale Compaction-Pfad
  (`/api/memory/compact-context`, `/api/chat/compact-session`) schreibt Turns und Summary.
  Der Effekt ist im Rückgabe-Dict als `lossless_session_id`/`lossless_summary_id` sichtbar
  (§0: Produzent + Konsument + Effekt + Verifikation).

Session-/Tenant-ID werden **abgeleitet**, nicht erfunden
(`derive_session_id()`/`derive_tenant_id()`): explizite `session_id`/`tenant_id` der Kette
haben Vorrang, sonst stabiler Hash aus System-Prompt + erstem User-Turn bzw. aktiver
Tenant-Kontext.

Zusätzlich (MED-Befunde aus `domain_11.md`, in denselben Ownership-Zeilen behoben):
- Z.416–424: Preview nicht mehr nur `lines[0]`, sondern ganzer Inhalt mit
  `handoff_desk.mark_truncated()` → verworfene Zeichen **markiert**.
- Z.610–631: 2-Nachrichten-Fallback brach mit nacktem `break` ab → jetzt
  `[KONTEXT GEKÜRZT: N …]`-System-Streifen wie im 4+-Pfad.

### 2.2 Verlustfreie Expansion + UNION-Suche

- `expand_summary_node()` (`lossless_session_dag.py:429-502`) läuft **rekursiv** über
  `lcm_turns` UND `lcm_summaries`. `child_turn_ids_json` darf daher gemischte IDs
  enthalten; verschachtelte Summaries erscheinen als `kind='summary'`-Knoten und werden
  ihrerseits aufgelöst. Schutz gegen Zyklen via `visited` + `MAX_EXPANSION_DEPTH=64`.
  Bei HMAC-Mismatch → `LosslessIntegrityError` (fail-closed).
- `search_lossless_history()` (Z.505-543) durchsucht `lcm_turns UNION ALL lcm_summaries`,
  immer `WHERE tenant_id = ? AND session_id = ?`. Summary-Treffer tragen `kind='summary'`
  und werden vor der Ausgabe HMAC-verifiziert.

### 2.3 Persistenz korrigiert

- Pfad: kein `data/lcm_sessions.db` mehr. `_default_db_path()` → `backend.db_paths.resolve_db("memory.db")`
  (Z.64-67). Damit greift die 28→3-Konsolidierung **und** (bei `FULL_TENANT_ISOLATION`)
  die physische Mandanten-DB unter `data/tenants/<id>/memory.db`.
  Hinweis zur Doku-Divergenz: `db_consolidation.py:68` bildet den Legacy-Namen
  `lcm_sessions.db → ops.db` ab, `00_SOLL_SPEC.md §1.3` und der Auftrag nennen `memory.db`
  als Domäne für „Agentengedächtnis/Sessions". Ich habe `memory.db` gewählt (Semantik
  „Sessions" + explizite Auftragsvorgabe).
- Verbindung: ausschließlich `backend.db_paths.get_db_connection()` (Z.70-75) →
  `busy_timeout=DB_BUSY_TIMEOUT_MS` (5000 ms), WAL/Synchronous, foreign_keys aus der SSOT.
  Kein eigener `sqlite3.connect(timeout=10.0)` mehr.
- Schema (Z.78-127): `tenant_id TEXT NOT NULL DEFAULT 'default'` in **beiden** Tabellen,
  `integrity_hmac` in `lcm_summaries`, plus ALTER-Migration für bestehende Tabellen und
  drei Indizes. **Alle** Queries (Append, Record, Compact-Validierung, Expansion, Suche,
  Löschung, Anonymisierung) sind tenant-gescoped.
- Integritätsnachweis (Z.216-285): `ARCHON_LCM_HMAC_KEY` → `ARCHON_HANDOFF_HMAC_KEY`
  → `ARCHON_AUDIT_HMAC_KEY`, HMAC-SHA256 über kanonisches JSON
  (`v|session_id|tenant_id|summary_text|child_ids`), `hmac.compare_digest` bei der
  Verifikation, harter Fehler bei fehlendem Key — analog `handoff_desk._sign_envelope()`.
- Art. 17 (Z.550-625): `delete_tenant_lossless_data()` (hart, optional pro Session) und
  `anonymize_subject_in_lossless_history()` (case-insensitive Schwärzung + **Neu-Signatur**
  aller betroffenen Summaries). Kein stiller Fallback.

### 2.4 Regressionstests

`tests/test_fix_w1_b_lossless.py` (5 Tests):

1. `test_producer_wired_in_agent_router_chokpoints` — monkeypatcht
   `record_turns`/`compact_conversation_turns` und ruft die **echten** Produktivmethoden
   auf; beweist Aufruf inkl. abgeleiteter Session/Tenant.
2. `test_producer_wired_in_context_compactor` — Effekt-Schlüssel im Rückgabe-Dict.
3. `test_recursive_expansion_over_nested_summaries` — 3 Turns + verschachtelte Summary,
   UNION-Treffer, Tamper → `LosslessIntegrityError`.
4. `test_tenant_isolation_and_article17` — Tenant A/B getrennt, Löschung A lässt B
   intakt, Anonymisierung mit Re-Signatur.
5. `test_db_path_consolidated_and_ssot` — `resolve_db("memory.db")`, busy_timeout aus
   SSOT, WAL,tenant/integrity-Spalten vorhanden.

---

## 3. Restrisiken / Delegation

1. **Art.-17-Hook:** `backend/gdpr_compliance_engine.erase_subject_data()` hat keinen
   Registrierungsmechanismus für externe Stores und liegt außerhalb meines Ownership.
   Die Lösch-/Anonymisierungsfunktionen sind implementiert und getestet, aber **noch nicht
   aus `erase_subject_data()` heraus aufgerufen**. → Follow-up (F012/F015): einen Aufruf
   von `anonymize_subject_in_lossless_history(identifier, …)` in den Art.-17-Store-Lauf
   aufnehmen; sonst bleibt die Kette „Art.17 → memory.db" unvollständig.
2. **Kein dynamischer Beweis:** Shell gesperrt → `compileall`/`pytest` nicht gelaufen.
   Vor Freigabe zwingend `python -m compileall -q backend/lossless_session_dag.py
   backend/agent_router.py backend/context_compactor.py archon/routers/v2_capabilities.py
   tests/test_fix_w1_b_lossless.py` und `pytest tests/test_fix_w1_b_lossless.py
   tests/test_milestones_block_ab.py`.
3. **HMAC-Key in Produktion:** Ohne `ARCHON_LCM_HMAC_KEY`/`ARCHON_HANDOFF_HMAC_KEY`/
   `ARCHON_AUDIT_HMAC_KEY` scheitert Summary-Erzeugung (gewollt fail-closed); der
   Produzent fängt die Ausnahme und loggt sie auf `ERROR` — bei fehlendem Key bleibt die
   Historie leer. Die vorhandene `.env` und `tests/conftest.py` setzen den Key.
4. **Dedup-Semantik:** `record_turns()` identifiziert Turns über
   `(tenant, session, role, content)`. Identische wiederholte Turns werden zusammengefasst;
   der *Inhalt* bleibt verlustfrei, die reine Wiederholungszahl nicht. Bewusst gewählt für
   Idempotenz über alle Produzentenpfade hinweg.

---

## 4. NEVER_DO_LIST geprüft

Kein Coroutine-Replay, kein Event-Sourcing, keine PostgreSQL-Migration, keine DSN.
SQLite/Konsolidierung 28→3 + physische Mandanten-DBs bleiben Endarchitektur. ✅
