# W2-D — Audit-Vollständigkeit (Dispatch-Proof)

**Datum:** 26.11.2026 · **Welle:** W2 Security · **Befunde:** D05-H1 (HIGH), D05-M1 (MED, Querschnitt)
**Soll:** `audit_reports/00_SOLL_SPEC.md` §2.5 · **Nachweis:** `audit_reports/domain_05.md` Befund 1/3 · `audit_reports/GEWICHTETE_BEFUNDLISTE.md` Nr. 27/40

---

## 1. Ausgangslage

`evaluate_and_gate_llm_dispatch()` und `enforce_egress_firewall_for_url()` schrieben ausschließlich im **geblockten** Pfad (`_record_blocked_proof`). Alle echten Produktionspfade mit HTTP-Response blieben beweis-los:

| Pfad | vorher | Befundstelle |
|---|---|---|
| Groq / OpenAI / Gemini-Transkription | `client.post(...)` → Rückgabe ohne Audit-Call | `backend/voice_pipeline.py:100-172` |
| Injection-Klassifikator | `urlopen(req)` → Verdict ohne Audit-Call | `local_security_guard.py:219-240` |
| Output-Judge | `urlopen(req)` → Score ohne Audit-Call | `local_security_guard.py:320-340` |
| Research-Synthese v1 | `urlopen(req)` → kein Gate, kein Proof | `research_engine.py:441-453` |
| Research-Reflexion v2 | `safe_http_json(...POST...)` → nur Egress-Firewall | `research_engine_v2.py:324-362` |
| TTS (edge-tts) | externer Dispatch ohne Proof | `backend/voice_pipeline.py:224-232` |

Netto-Effekt: `provider`, `model`, `target_endpoint`/`target_host`, `egress_zone` und `data_category` dieser Calls waren im GoBD-Ledger nicht nachvollziehbar — §2.5 fordert aber „ausgeführt **und** blockiert".

---

## 2. Zentraler Helper (D05-H1 + D05-M1)

**Datei:** `backend/llm_egress_guard.py`

Neu:

- `class AuditDispatchError(RuntimeError)` — dedizierter, hart fail-closed Fehlertyp (erbt `RuntimeError`, damit bestehende Fail-Closed-Pfade unverändert greifen).
- `audit_dispatch_sync(...)` — zentraler Proof-Schreiber. Pflichtparameter `provider`, `model`, `target_endpoint`; optional `agent_id`, `http_status`, `data_category`, `zero_egress_active`, `completed`, `error_code`, `reason`, `task_id`, `trace_id`, `extra`, `audit_logger`.
  - Erfolg (`completed=True`, HTTP 2xx/3xx) → `log_completed_llm_dispatch()` → `record_llm_dispatch(action="llm_call_dispatched")`.
  - Fehler / leerer Body (`completed=False`, HTTP-Fehler, Transportfehler) → `_record_blocked_proof()` mit `action="llm_dispatch_empty_response"` bzw. `"llm_dispatch_failed"` und `error_code` (`LLM_EMPTY_RESPONSE`, `LLM_HTTP_<status>`, `LLM_TRANSPORT_ERROR`, …).
  - `target_host` und `egress_zone` werden deterministisch über `sanitize_llm_endpoint(target_endpoint)` abgeleitet und zusätzlich in `extra` mitgeführt.
  - **D05-M1:** Jeder Audit-Schreibfehler wird geloggt **und** als `AuditDispatchError`/`RuntimeError("audit_write_failed: …")` eskaliert — nie nur geloggt.
- `audit_dispatch_async(...)` delegiert jetzt an `audit_dispatch_sync(...)` (weiterhin über `_AUDIT_DISPATCH_LOCK` + `asyncio.to_thread`), sodass auch asynchrone Aufrufer die harte Eskalation erben. Signatur kompatibel zu allen bestehenden Aufrufern (`agent_router.py`, `image_generate.py`, `notebook_engine.py`).
- Bestehender Helper `log_completed_llm_dispatch` bleibt unverändert erhalten.

---

## 3. Call-Sites — Proof direkt nach der HTTP-Response

| Datei | Funktion | Proof-Aufruf | Category | Erfolg | Fehler/leer |
|---|---|---|---|---|---|
| `backend/voice_pipeline.py` | `transcribe_audio_bytes` (Groq) | `_audit_voice_dispatch(...)` nach `client.post` | `voice_transcription` | ✓ | ✓ |
| `backend/voice_pipeline.py` | `transcribe_audio_bytes` (OpenAI) | `_audit_voice_dispatch(...)` nach `client.post` | `voice_transcription` | ✓ | ✓ |
| `backend/voice_pipeline.py` | `transcribe_audio_bytes` (Gemini) | `_audit_voice_dispatch(...)` nach `client.post` | `voice_transcription` | ✓ | ✓ |
| `backend/voice_pipeline.py` | `synthesize_speech` (edge-tts) | `_audit_voice_dispatch(...)` nach `communicate.save` | `voice_tts` | ✓ | ✓ |
| `local_security_guard.py` | `scan_prompt_injection` | `_audit_classifier_dispatch(...)` nach `urlopen` | `security_classification` | ✓ | ✓ (`LLM_CLASSIFIER_ERROR`) |
| `local_security_guard.py` | `validate_ai_output` | `_audit_classifier_dispatch(...)` nach `urlopen` | `security_judge` | ✓ | ✓ (`LLM_JUDGE_ERROR`) |
| `research_engine.py` | `query_omniroute_synthesis` | `audit_dispatch_sync(...)` nach `urlopen` | `research_synthesis` | ✓ | ✓ (`LLM_SYNTHESIS_ERROR`) |
| `research_engine_v2.py` | `_chat` (Reflexion) | `audit_dispatch_sync(...)` nach `safe_http_json` | `research_reflection` | ✓ | ✓ (`LLM_REFLECTION_ERROR`) |

Alle Pfade besitzen eine `except`-Klausel, die `AuditDispatchError` **vor** dem allgemeinen `except Exception` bedingt weiterreicht (`raise`). Damit kann kein Auditfehler mehr als „Klassifikatorfehler", „Reflexion nicht möglich" oder Heuristik-Fallback getarnt werden.

Die geblockten Gate-Pfade (`_record_blocked_proof`, `enforce_egress_firewall_for_url`) bleiben unverändert und schreiben weiterhin ihren eigenen Proof — es entsteht keine proof-lose Lücke beim Fallback auf den nächsten Cloud-Provider.

---

## 4. Nicht angefasst (fremder Dateibesitz)

- `backend/agent_router.py:1396` (Receipt-Schreibfehler nur `logger.warning`) — gehört einem anderen Agenten.
- `backend/fleet_self_healing.py:249-285` (`status: 'success'` trotz `audit_write_failed`) — gehört einem anderen Agenten.

Für beide gilt: Der zentrale Helper eskaliert Auditfehler jetzt hart als `RuntimeError`. Die jeweiligen Aufrufer müssen ihre Schreibpfade auf `audit_dispatch_sync` bzw. `audit_log._require_audit_event()` umstellen; dieser Report erhebt dafür **keinen** Abschlussanspruch.

---

## 5. Tests

**Datei:** `tests/test_w2_d_dispatch_proof.py` (neu, 17 Testfunktionen / 20 pytest-Fälle durch Parametrisierung)

Abgedeckt:

1. Helper: vollständiger Success-Proof inkl. `target_host`/`egress_zone`/`data_category`.
2. Helper: Empty-Body- und HTTP-Fehler-Proofs (`llm_dispatch_empty_response` / `llm_dispatch_failed`, `LLM_HTTP_503`).
3. Helper: Auditfehler → `RuntimeError(match="audit_write_failed")` (sync **und** async).
4. Voice: Groq-Erfolg, leerer Body, Transportfehler, Auditfehler nicht verschluckt.
5. Security Guard: Klassifikator SAFE/empty, Judge-Erfolg, Auditfehler nicht verschluckt.
6. Research v1: Synthese Erfolg/Empty, Auditfehler nicht verschluckt.
7. Research v2: Reflexion Erfolg/Transportfehler.
8. **AST-Chokepoint-Check:** Jede der geprüften LLM-Funktionen, die `post`/`urlopen`/`safe_http_json` aufruft, muss im selben Funktions-Scope auch einen Proof-Aufruf enthalten. Zusätzlich separater TTS-Check.

Alle Tests arbeiten ausschließlich mit gemockten HTTP-Responses und gemockten Audit-Writes — **kein** Netzwerk, **kein** Replay, **keine** PostgreSQL-/SQLite-Abhängigkeit (NEVER_DO_LIST beachtet).

---

## 6. Verifikationsstatus

Die Shell in dieser Subagent-Session stellt **keine Python-Interpreter** bereit (`python`/`python3` → WindowsApps-Stub ohne Installation). `py_compile` und `pytest` konnten daher hier **nicht** ausgeführt werden. Der Koordinator bitte:

```
python -m pytest tests/test_w2_d_dispatch_proof.py -q
python -m pytest tests/test_audit_b1_b8_blockers.py tests/test_reaudit_stage5.py tests/test_reaudit_stage13.py tests/test_med2_e_services.py tests/test_research_engine.py -q
```

Statisch geprüft: Importketten (`backend.llm_egress_guard` ↔ `backend.audit_log` / `backend.privacy_router` ↔ `local_security_guard` / `research_engine`) sind zyklusfrei; alle geänderten `except`-Klauseln sind konsistent; keine fremden Dateien verändert, keine Commits erstellt.
