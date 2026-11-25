# FIX W5-C — Obsolete Tests der Archon-OS-Remediation (Scope C)

**Datum:** 25.11.2026 · **Scope:** zwei diagnostizierte Testfehler aus der Restliste in
`audit_reports/fix_w4_d2_residuals.md` §3/§4. **Basis:** `FIX_VERIFICATION_LOG.md`,
`MASTER_PLAN.md` §0/§1.4, `fix_w4_d2_residuals.md` §3/§4.

**Exklusives Ownership (nur diese Dateien):**
- `tests/test_fix_batch11.py`
- `tests/test_fix_w1_d_tenant_ledger.py`

Keine Produktivdatei wurde geändert. Kein echter Code-Bug gefunden — beide Fehler waren
obsolete Test-Erwartungen nach W1-A (Audit-Actor) bzw. W4-B (tenant-präfigierter
Dedup-Hash). Es gab daher nichts an Production zu eskalieren.

**Datenisolierung:** Alle Läufe mit `ARCHON_DATA_DIR` auf frischen Verzeichnissen unter
`C:\Users\micha\AppData\Local\Temp\opencode\archon_w5_c_*`. Kein Test lief gegen `./data`.
`NEVER_DO_LIST` eingehalten.

---

## 1. Geänderte Tests

| Test | Ursache (diagnostiziert) | Änderung |
|---|---|---|
| `tests/test_fix_batch11.py::test_n11_boardroom_debate_ids_collision_free` | `KeyError: 'history_id'`. Der Endpoint ruft `save_boardroom_history_item(hist_entry, actor_id=actor_id)` (W1-A Audit-Event mit verifiziertem Session-Actor). Der 1-Argument-Lambda-Mock warf `TypeError`, der Endpoint verschluckte ihn im `except Exception` und setzte nie `res["history_id"]`. | Mock auf `_fake_save(item, **kwargs)` umgestellt (akzeptiert `actor_id` und weitere neue Kwargs). Die bestehende Kollisionsfreiheits-Assertion `hist_id1 != hist_id2` bleibt; ergänzt um `len(saved_history) == 2` und unterschiedliche `saved_history[*]["id"]`, damit die Eindeutigkeit auch in der persistierten Historie geprüft wird. Nicht gelöscht, nicht geskippt. |
| `tests/test_fix_w1_d_tenant_ledger.py::test_event_mesh_dedup_is_tenant_scoped` | Erwartete den Roh-Key `tenant_a::idem-identical`. Seit W4-B verwirft `ingest_inbound_event()` senderkontrollierte `idempotency_key`/`correlation_id` aus dem Payload und leitet den Key als tenant-präfigierten SHA-256-Hash ab (`tenant_a::19d0dc…`). | Assertions auf die neue Semantik umgestellt: genau zwei Dedup-Einträge, paarweise verschieden; je genau ein Key mit Präfix `tenant_a::` / `tenant_b::`; 64-hex-SHA-256-Suffix (Struktur/Länge statt hart codiertem Hash); keine Roh-Keys im Digest; der Duplicate-Pfad meldet den gespeicherten Key des eigenen Tenants. Die Verhaltensassertions bleiben unverändert: beide Tenants werden nicht unterdrückt, innerhalb von A greift Dedup weiterhin. Nicht gelöscht, nicht geskippt. |

---

## 2. Verifikationskette nach §0

| Mechanik | Produzent | Konsument | Effekt | Verifikation |
|---|---|---|---|---|
| Boardroom-History-ID | `api_run_boardroom` → `hist_entry["id"] = f"deb_{time}_{uuid4()[:6]}"` → `_persist_boardroom_result_sync` (Mock akzeptiert `actor_id`) | `res["history_id"]` → Assertion im Test | Zwei Debatten in derselben Sekunde → zwei verschiedene IDs, zwei persistierte Einträge | `test_n11_boardroom_debate_ids_collision_free` ✅ |
| Event-Mesh-Dedup | `EventMesh.ingest_inbound_event` → `sha256(canonical(tenant, channel, event_type, payload))` → `_tenant_key` | `event_mesh_dedup.dedup_key` + Duplicate-Pfad → Assertion im Test | Gleiche Payload-Keys über Tenants → diferentes Key, kein Cross-Tenant-Suppress; innerhalb eines Tenants weiterhin `duplicate` | `test_event_mesh_dedup_is_tenant_scoped` ✅ |

---

## 3. Verifikation (ausgeführt)

- `.ci_venv\Scripts\python.exe -m compileall -q tests/test_fix_batch11.py tests/test_fix_w1_d_tenant_ledger.py` → **Exit 0**.
- Reproduktion vor dem Fix (frisches `ARCHON_DATA_DIR`): **2 failed** — exakt `KeyError: 'history_id'` und
  `assert 'tenant_a::idem-identical' in ['tenant_a::19d0dc…', 'tenant_b::158504…']`.
- Nach dem Fix, beide betroffenen Dateien (frisches `ARCHON_DATA_DIR`): **13 passed**.
- Finaler gezielter Lauf der beiden diagnostizierten Tests (erneut frisches `ARCHON_DATA_DIR`): **2 passed**.

**Hinweis:** `pwsh.exe` war bei zwei Gelegenheiten kurzzeitig gesperrt
(`Zugriff verweigert (os error 5)`), wie bereits in `fix_w4_d2_residuals.md` §4 dokumentiert.
Nach Wiederholung liefen alle Befehle erfolgreich. `python` im PATH ist der Microsoft-Store-Stub;
verwendet wurde `.ci_venv\Scripts\python.exe` (Python 3.11.15).

---

## 4. Außerhalb Ownership / Eskalation

- Die übrigen in `fix_w4_d2_residuals.md` §4 gelisteten Restfehler
  (`test_audit_b1_b8_blockers`, `test_fix_w4_a_tracing`, `test_graceful_shutdown`,
  `test_jev_router`, `test_reaudit_stage15`, `test_reaudit_stage7`,
  `test_show_hn_blockers`) bleiben bei ihren jeweiligen Ownern — nicht angefasst.
- Kein Produktivcode-Bug festgestellt; kein Eingriff in `archon/routers/boardroom.py`
  oder `backend/event_mesh.py` nötig oder vorgenommen.
