# Fix-Log D4 — Frontend / v2-Capabilities (Phase 3 Nachlauf)

> Agent: Delegations-Agent D4 (Phase 3 Nachlauf) · Datum: 2026-11-25 ·
> Arbeitsverzeichnis: `C:\.Antigravity-projekte\AgenticOS-2026` ·
> **Kein Commit, kein Push.** Shell (`pwsh.exe: Zugriff verweigert`) blockiert —
> nur `read`, `edit`, `write`, `grep`, `glob` verwendet.
> G-05 beachtet: kein God-Object-Refactoring; `AuthModal.tsx` blieb unangetastet,
> der Fokus-Trap wurde lokal kopiert statt extrahiert. A9-Tracing unverändert.

## Gelöste Punkte (6)

### 1. Art.-50-Dialog (aus A6) — minimale, ehrliche Komponente ✅

**Neu:** `frontend/src/components/ClientApprovalPortal.tsx`

- Nicht wegklickbar: kein Schließen-Button, kein Backdrop-`onClick`, Escape wird
  per `preventDefault()` abgefangen statt zu schließen, Tab-Falle im Dialog,
  Initialfokus auf die Bestätigungs-Checkbox, `role="dialog"` + `aria-modal="true"`
  + `aria-labelledby`.
- Zeigt den KI-Transparenzhinweis (Art. 50) explizit an; die Entscheidung wird
  erst nach zwingender Checkbox-Bestätigung (und bei Annahme nach expliziter
  AGB-Bestätigung) freigegeben.
- Sendet an `POST /api/v2/portal/decisions` (Browser-Pfad
  `/api/archon/api/v2/portal/decisions` via `archonFetch`):
  `token`, `ai_disclosure_shown: true`, `ai_disclosure_token`,
  `ai_disclosure_nonce`, `ai_disclosure_session`, `decision`, `terms_accepted`,
  `comment`, optional `password`.
- Die Challenge-Werte werden **nicht erfunden**: sie kommen als Prop
  `ClientDisclosureChallenge` aus dem verifizierten Ergebnis von
  `backend.client_approval_portal.verify_share_access(..., issue_disclosure_challenge=True,
  disclosure_session=...)`. Die Engine dreht dort Nonce/Session und gibt
  `ai_disclosure_token`/`ai_disclosure_nonce`/`ai_disclosure_session` zurück.

Suche nach einer bestehenden Komponente (`grep portal|decision|share|
submit_client_decision|client_approval|ai_disclosure` in `frontend/**` und
`static/**`) ergab **keinen** Client-Portal-Konsumenten (nur
`static/views/agent_profiles_view.html` „Karriereportal" und
`SettingsModal.tsx` „portal.azure.com" — beides fachfremd). Daher neue
Komponente. Einbau/Einbindung siehe DELEGATED.

### 2. `api_v2_flightlog_check` (aus A8) ✅

Datei: `archon/routers/v2_capabilities.py:234-288`

- Signatur `def api_v2_flightlog_check(request: Request, run_id: str)` — der
  client-kontrollierte Query-Param `final_status` ist **entfernt**. Mit
  `?final_status=failed` konnte vorher die Silent-Failure-Erkennung abgeschaltet
  werden.
- `require_admin_or_503(request)` ergänzt (vorher fehlte der Rollenzaun auf dieser
  GET-Route).
- `final_status` jetzt aus der Persistenz: `get_workflow_run(run_id)["status"]`
  (`workflow_runs`), Fallback auf `dag_run_complete.args_json.status` aus
  `flight_events` (read-only SQLite via `resolve_db('flightlog.db')`).
  `completed`/`paused`/leer → konservativ `success` abgebildet (der Detektor
  flaggt nur aus der Erfolgsannahme), `failed`/`blocked`/`cancelled` bleiben
  stehen. `final_output` wird aus den persistierten Node-Outputs gebildet.
- Äußerer Status: `status = "blocked" if diag.get("silent_failure") else "success"`
  statt pauschalem `"success"`.
- Keine neue Tabelle, keine Migration, kein erfundener Endpunkt; Fehler beim
  Lesen werden gedebugged, nicht verschluckt (Detektor läuft weiter fail-closed).

### 3. `submit_client_decision` Nonce/Session-Durchreichung (aus A8/A6) ✅ — verified

Datei: `archon/routers/v2_capabilities.py:616-635, 903-945`

- `ClientDecisionSubmitRequest` trägt `ai_disclosure_nonce` (Z.632) und
  `ai_disclosure_session` (Z.633) bereits (A6).
- Der Router reicht beide an `backend.client_approval_portal.submit_client_decision()`
  durch (Z.933-934) und verlangt unabhängig davon `ai_disclosure_shown` +
  `ai_disclosure_token` (Z.911 → HTTP 403).
- **Kein Edit nötig** — Kompatibilität mit dem neuen Dialog (Punkt 1) ist
  vollständig gegeben: der Dialog sendet genau diese Felder.

### 4. `MediaBoardView.tsx` — XSS im Druck-Pfad + Fokus-Traps (aus A1) ✅

Datei: `frontend/src/components/MediaBoardView.tsx`

- `getBildUrl()` (Z.24): `new URL()` + nur noch `https:` für externe Werte;
  `data:`, `javascript:`, `http:` und schemalose Fremdwerte werden abgewiesen.
  PB-Dateinamen werden ausschließlich über `pb.files.getURL()` aufgelöst und
  deren Schema (http/https) geprüft.
- `handlePrint()`: kein interpoliertes HTML mehr — Aufbau via
  `doc.createElement` / `setAttribute` / `textContent`; `onload` als Property
  statt Inline-Attribut; `data.title`-Äquivalent (`rec.titel`/`rec.notiz`) kann
  nicht mehr in Markup entkommen. Hilfsfunktion `escHtml` entfällt (unerforderlich).
- Lokaler Hook `useFocusTrap()` (Z.65), direkt aus `AuthModal.tsx` kopiert:
  Initialfokus, Tab-Falle, Escape, Fokus-Restore. Verdrahtet für
  Hinzufügen-Formular (Z.164, `role="dialog"`, `aria-modal="true"`,
  `aria-labelledby="media-form-title"`) und Lightbox
  (Z.165, `aria-labelledby="media-lightbox-title"`).
- Bestehende D-24-Cleanups (Timer/Streams) blieben unverändert.

### 5. `static/index.html` — drei unescape Interpolationen (aus A1) ✅

- `:7294` → `escapeHtml(data.title)` (zusätzlich `pages_count`,
  `chunks_indexed` mitescape).
- `:6242` → `escapeHtml(err.message || err)`.
- `:7342` → `escapeHtml(e.message)`.
- Entspricht dem etablierten Muster `:5095` / `:7137`; `escapeHtml` ist in
  `:2472-2481` definiert und escapt `& < > " '`.

### 6. `archon-api.ts` — HITL-Tracing (aus A8/A9) ✅ — verified, kein Edit

- `decideHitl()` (Z.188-208) legt denselben geforkten `traceparent`
  (`forkActiveTraceparent() || createTraceparent()`) in **Header und Body**;
  `tracestate` ebenfalls in beiden. A9-Arbeit unverändert.
- Root-Fallback `searchParams.set('traceparent', createTraceparent())` bleibt in
  `frontend/src/lib/useArchonEvents.ts:46` erhalten (A9-Vertrag).
- `withTraceHeaders()` / `tracedFetch()` in `archon-api.ts` unverändert.

## DELEGATED (1 Block)

| Ziel | Inhalt | Grund |
|---|---|---|
| Host-Owner / A1-App (Next.js-Route + `static/index.html`) | `ClientApprovalPortal` in eine echte Client-Freigabe-Seite einbauen und die Challenge aus `verify_share_access(..., issue_disclosure_challenge=True, disclosure_session=...)` beziehen. Dafür braucht es einen echten Challenge-Endpoint (z. B. einen GET auf `/api/v2/portal/links/{token}/challenge`, der genau diese Engine-Funktion aufruft) — **nicht** erfunden, daher hier nicht angelegt. | `frontend/**` und `static/**` enthalten **keine** Client-Portal-Seite und der Router hat nur `/api/v2/portal/links` (Erzeugung) und `/api/v2/portal/decisions` (Entscheidung), aber **keinen** Endpoint, der `verify_share_access()` mit `issue_disclosure_challenge=True` aufruft. Einbau in eine unbekannte Host-Route wäre G-03-Theater; der reine Endpunkt wäre eine neue, sicherheitsrelevante API außerhalb des Auftrags („keine erfundenen Endpunkte"). Bis dahin ist der Flow wie von A6 gefordert `not_configured` — serverseitig hoch gesichert, aber nicht bedienbar. |

## Verifikation / Einschränkung

- Alle Edits per `read`/`grep` auf exakte Strings, Verdrahtung und Syntax geprüft.
- Shell/blockiert: kein `pytest`, `tsc`, `ruff`, `mypy` — wie in A1/A6/A8/A9.
- Keine Secrets, keine neuen Endpunkte, keine DB-Migration, kein Commit/Push.
- A9-Tracing-Pfade (`decideHitl`, `useArchonEvents`, `withTraceHeaders`,
  PocketBase-Hooks) wurden nicht verändert.

**Summe: 6 resolved | 1 delegated**
