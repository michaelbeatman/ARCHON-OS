# Vorschlag 3b — Importzyklen & God-Objects (minimal-invasiv, nicht ausgeführt)

**Status:** Analyse + Staging-Plan. **Kein Code geändert.** Auftrag aus `HANDOFF_FINAL_2026-11-25.md` Punkt 3b: „schlage einen minimal-invasiven Split vor, führe ihn aber nur durch, wenn danach das komplette Final-Gate zu 100 % grün bleibt."

> **Korrektur/Nachtrag 25.11.2026 (Fremd-Analyse, nur lesend):** Die ursprüngliche Tabelle vermischt drei Problemklassen und nutzt veraltete Zeilenzahlen. Real im aktuellen Working Tree:
>
> | Klasse | Problem | Betroffene |
> |---|---|---|
> | **A** | Große Dateien | Telegram-Patch 11.233 (unverändert), `operations_api.py` **4.512** (statt ~3.923), `core_dispatcher.py` **3.804** (**fehlt im ursprünglichen Report!**), `main.py` **3.638**, `workflow_dag_runner.py` **3.036** |
> | **B** | Komplexitäts-Ausreißer (radon CC, ~60 Blöcke Rang F) | `workflow_dag_runner.py:1211 default_agent_node_executor` **CC 246**, Telegram `:6873` 158, `gdpr_compliance_engine.py:673 erase_subject_data` 147, `archon/routers/hermes_config.py:287` 138, `delegation.py:1383` 135, `orchestration.py:1385` 116 — **kommt in S1–S4 überhaupt nicht vor** |
> | **C** | Importverflechtung | `backend`→`archon` **81** Importzeilen (41 top-level), `archon`→`backend` **634** (27 top-level) = **715 real** statt der dokumentierten „~80 reziprok"; der Zyklus `delegation.py`↔`operations_api.py` ist weiterhin aktiv |
>
> `.importlinter` war **fehlkonfiguriert**: falsch war `root_package` (Singular). Korrekt ist `root_packages` (**Plural**, import-linter v2.17, vgl. `forbidden.py:257-259`, `use_cases.py:436-441`) mit `archon` **und** `backend` als internen Paketen; `include_external_packages = False` bleibt richtig. Das erklärt `exit 1 / No matches for ignored import`. Die Aussage „Importe offenbar bereits aufgelöst" im Handoff war falsch — korrekte Config würde ~26 Verstöße melden. Die korrigierte Config entsteht in Hy4s Worktree; die alte Datei im Hauptbaum bleibt bewusst untracked.
>
> **Konsequenz:** S1–S4 müssen um Klasse B (CC-246-Block) und `core_dispatcher.py` ergänzt werden; die Reihenfolge neu: grünes Final-Gate + Commit → Worktree → Analyse-Dossier → S1 (korrigierte Contract-Config) → B-Teilzerlegung mit Characterization-Tests → A/S2–S4.

## 1. Befundbasis (Domäne 09, `-`-Zeilen unverändert dokumentiert)

| Datei | Zeilen | Problem |
|---|---:|---|
| `scripts/patches/hermes_telegram_adapter.py` | 11.233 | Vendor-Patch, per Read-Only-Bind-Mount auf Hermes-Adapter gelegt; nicht als Modul testbar, nicht versionierbar, nur `compileall`-Syntax geprüft |
| `main.py` | 3.393 | Lifespan-Hooks, Auth-Gates, Health-Checks, hunderte Router-Registrierungen und Business-Logik in einer Datei |
| `backend/operations_api.py` | ~3.923 | Monolith mit ≥30 Foreign-Router-Importen |
| `archon`↔`backend` | ~80 reziproke Importzeilen | Zyklus-Kandidat: `backend/operations_api.py:99` lazy `archon.core.delegation.DelegationPayload` ↔ `archon/core/delegation.py:725` lazy `backend.operations_api._get_kanban_connection` |

## 2. Risiko-Einschätzung

Ein Umbau dieser Dateien berührt genau die Pfade, die in W0–W5 gehärtet wurden (Lifespan-Fail-Fast, `/livez`, RBAC, Delegation, Kanban). Ein „Blind-Umbau" würde den grünen Stand (`bd9209be` + nachfolgende Commits, 2342+ grüne Tests) gefährden. Deshalb: **Staging, ein Schritt pro Commit, je Schritt Full-Gate.**

## 3. Staging-Plan (Reihenfolge)

| Schritt | Maßnahme | Akzeptanzkriterium | Risiko |
|---|---|---|---|
| S1 | Import-Richtungsregel festschreiben: `backend/**` darf `archon.routers.*` **nicht** importieren; gemeinsame Verträge (z. B. `DelegationPayload`, `_get_kanban_connection`) in `archon/core/contracts.py` oder `backend/contracts.py` heben; Import-Linter-Gate in CI | Kein `from archon.routers` in `backend/**`; `mypy`/`compileall`/Tests grün | mittel |
| S2 | `main.py`: Lifespan-/Background-Loops → `archon/services/lifecycle.py`; Middleware/Auth → `archon/middleware/`; Router-Registrierung → `archon/routers/__init__.py`. Ziel < 300 Zeilen reine App-Komposition | `/livez`, `/readyz`, Fail-Fast-Hooks, Shutdown-Timeout unverändert grün; Full-Suite 0 rot | hoch |
| S3 | `backend/operations_api.py` entlang bereits existierender `operations_*`-Router weiter aufteilen (nur holes Modul, keine Logikänderung) | Alle 30+ Foreign-Router-Importe aufgelöst; Full-Suite 0 rot | mittel |
| S4 | Telegram-Patch in `scripts/patches/telegram/*.py` zerlegen, schlanker `register(ctx)`-Entry; Hermes-Image-Version im Manifest pinzen; Smoke-Test gegen echte Adapter-API als CI-Gate | Patch testbar + versionierbar; Adapter-Smoke grün | hoch |

## 4. Empfehlung

**S1 jetzt als Plan dokumentieren, S2–S4 nicht ohne explizite Freigabe ausführen.** Der Nutzen (Wartbarkeit) ist real, aber nicht betriebskritisch; das Risiko (Rückfall in fail-open oder Router-404) ist hoch. Die 24/7-Zielsetzung ist mit dem aktuellen Stand bereits erfüllt (0 BLOCKER, 0 HIGH, grünes Gate).

## 5. NEVER_DO_LIST

Kein Coroutine-Replay, keine PostgreSQL-Migration. Die obigen Splits ändern weder Persistenz- noch Replay-Architektur.
