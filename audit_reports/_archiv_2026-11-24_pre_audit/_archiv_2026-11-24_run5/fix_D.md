# Fix-Report D — Domäne 9 (MED-Funde F-063 … F-071)

Datum: 24.11.2026 · Kein Commit · Nur freigegebene Dateien geändert.

| ID | Status | Änderung |
|---|---|---|
| F-063 | FIXED | `Dockerfile`, `backend/Dockerfile`, `frontend/Dockerfile`: `FROM …@sha256:` mit echten **Multi-Arch-Index-Digests**. Keine erfundenen Werte (siehe Herkunft unten). |
| F-064 | FIXED | `frontend/Dockerfile`: `RUN npm ci || npm install` → hartes `RUN npm ci`. |
| F-065 | FIXED (Metadaten) | `requirements.lock.txt`: 3.12-Kommentar durch ehrlichen 3.13-Runtime-Header ersetzt; kein Regenerieren ohne Netz, kein Hash/Version angefasst. |
| F-068 | FIXED | `crm/page.tsx`: `dangerouslySetInnerHTML` erhält nur noch Output des gemeinsamen Sanitizers. |
| F-069 | FIXED | `DesignEditorTab.tsx`: identischer Sanitizer-Pfad. |
| F-070 | FIXED | `ci.yml`, Job `validate-and-audit`: harte Steps `YAML-Parse-Gate (yaml.safe_load)` und `Restore-Test-Gate (5/5)`. |
| F-071 | FIXED | `pages.yml`: alle vier Actions per 40-Zeichen-Commit-SHA + `# vX`-Kommentar gepinnt. |

**Neu angelegt (von F-068/F-069 ausdrücklich gefordert):** `frontend/src/lib/sanitizeSvg.ts` (SSOT, Strict-Whitelist: erlaubte SVG-Tags/Attribute, alle `on*`, `script`/`foreignObject`/`iframe`, `javascript:`/`data:`/`vbscript:`, `style`/`srcdoc`/Formular-Attribute und Fremd-`url(...)` entfernt; Fail-Closed ohne `<svg>`-Root, kein DOM, keine neue Dependency) und `frontend/src/lib/sanitizeSvg.test.mjs` (7 Regressionstests inkl. `<svg onload=alert(1)>`).

**Herkunft der Pin-Werte (keine Erfindungen):**
- `python:3.13-slim` → `sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90` (Index, `3.13.18-slim-trixie`), aufgelöst via `docker buildx imagetools inspect python:3.13-slim`, anschliesslich mit `@sha256:`-Ref erneut aufgelöst.
- `node:22-alpine` → `sha256:1314fb30ec37592d5845e5a160d522c0e680972aa534549940b8d73bde88481a` (Index, alpine 3.24), identisch verifiziert.
- `actions/checkout` → `11d5960a…` aus `ci.yml:16` übernommen. `configure-pages` → `983d7736d9b0ae728b81ab479565c72886d7745b` (v5), `upload-pages-artifact` → `56afc609e74202658d3ffba0e8f6dda462b719fa` (v3), `deploy-pages` → `d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e` (v4), jeweils via `git ls-remote … refs/tags/vX` aufgelöst.

**Verifikation (alle grün):**
- `npx tsc --noEmit` in `frontend/` → Exit 0. (`node --check` ist auf `.tsx` nicht anwendbar; TS-Pfad geprüft.)
- `node --test frontend/src/lib/sanitizeSvg.test.mjs` → 7/7 passed, 0 failed.
- `yaml.safe_load` über alle 7 Workflow-/Compose-YAMLs via `.ci_venv\Scripts\python.exe` → 7/7 OK; Strukturcheck bestätigt beide neuen CI-Steps in `validate-and-audit`.
- Restore-Gate lokal mit identischer Schritt-Logik probelaufen: `EXIT 0`, `overall_status=PASSED`, `5/5` Details (ops/business/memory/pb_data + TENANT_REPLICATION). Die Fixtures werden im CI-Runner deterministisch erzeugt; Quelle ist ausschliesslich ein frisches Backup-Artefakt, nie eine Live-DB.
- `docker compose -f docker-compose.yml config --quiet` und `docker compose config --quiet` → Exit 0.
- `git diff` bestätigt: `backend/Dockerfile` Zeilen 5–9 (F-062-Lockfile-Fix eines anderen Agents) unverändert.

**Hinweise / Restrisiken:**
- F-065: Der Lockfile-Kommentar benennt die 3.12-Herkunft jetzt ehrlich und verweist auf den 3.13-Runtime-Nachweis; eine echte `pip-compile`-Neuerzeugung in 3.13 bleibt ohne Netzwerk ausstehend (explizit nicht simuliert).
- `docker-compose.override.yml` ist allein stehend kein gültiges Compose-Projekt (fehlende image/build-Angabe) — vorbestehend, nicht Teil dieses Auftrags; `docker compose config` (Default-Merge) ist grün.
- Nicht commitet, keine Python-Dateien in `archon/`, `backend/`, `main.py`, `scripts/` oder `static/` angefasst.
