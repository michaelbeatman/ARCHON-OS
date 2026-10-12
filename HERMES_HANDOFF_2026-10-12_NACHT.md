# HERMES HANDOFF — 12.10.2026 (Nacht, nach Sidecar-Fix + Kleinkram)

> Eingehendes Handout: `HERMES_HANDOFF_2026-10-12_ABEND.md` (HEAD 88cbaaa + Handout-Commit).
> **Dieses Dokument ist der aktuelle Stand.** Alle 4 Klein-Punkte abgearbeitet bzw. entschieden.

## 0) Regeln (User-Vorgaben, unbeugsam)

- **Deutsch.** Bei Architektur-Entscheidungen VOR dem Bauen `clarify` (Empfehlung first).
- **Engine-DB `kanban.db` READ-ONLY** — lesen ja, schreiben nur über API/UI-Pfade.
  `state.db` = `/opt/data/state.db`.
- JS-Edits: `patch`-Tool + `node --check`. Python: `py_compile` + Health-URL nach Restart.
- Nach JS-/CSS-/View-Edits: **Buster** in `static/index.html` erhöhen.
- Keine Secrets/Token in Texten. Testspuren nach Tests entfernen. **Löschen erst nach Clarify.**
- **Zuerst Skill laden:** `projects/archon-os-debug`.

## 1) Umgebung

- Projekt: `C:\.Antigravity-projekte\AgenticOS-2026`, Branch `main`, **HEAD `7ad20eb`**,
  remote `github.com/michaelbeatman/Agentic-Archon-Os` synchron (gepusht). Tree sauber.
- Container: ARCHON-OS:8501, hermes, n8n:5678 (bewusst draußen), omniroute:20128, CRM:3005.
- Board: **6 aktive Tasks** (5-Teiler 11.10. + 1 Message, alle `done`), **6 archivierte**
  (echte Inhalte, bewusst behalten). `total_tasks: 6`.

## 2) HEUTE FERTIG (Commit `7ad20eb`, mit Belegen)

| Punkt | Was | Beleg |
|---|---|---|
| 1 Sidecar-Schreibsperre | **NEU `backend/kanban_sidecar.py`** = einziger Besitzer von `config/kanban_meta.json` (`threading.Lock` + atomar Temp+fsync+`os.replace`). Endpoint + Pipeline schreiben beide darüber | Race-Test: 8 parallele POSTs → 8/8 erhalten; Same-Task-Merge (obsidian+decision) verliert keinen Schlüssel; Testspuren per API entfernt; Health 200, Log 0 Errors |
| 1 Recherche | **2. Schreiber war `post_task_pipeline.write_project_folder_artifact`** (direkter Dateizugriff) — jetzt auf `update_kanban_meta` umgestellt. `main.py` schreibt NUR via Selbst-API → Endpoint (abgedeckt) | grep über `backend/ + main.py`: keine direkten Writes mehr |
| 2 mcapp-Reste | `mcapp-projekt-e2e-fanin` + `mcapp-projekt-loop-e2e` aus Sidecar entfernt | Verwaist verifiziert: kein Kanban-/MC-Task, kein Obsidian-Ordner. Sidecar = exakt die 6 Board-Tasks |
| 3 Archiv-Test-Tasks | **15 Test-/E2E-Tasks gepurgt** (`hermes kanban archive --rm`, User-Clarify „nur Test-Tasks“) | Archiv 21→6; Rest = echte Inhalte (SWOT, LinkedIn-Hook, GTM, Audio-Studie, Bullets, Content-Gründe) |
| 3 Grenzfall | `t-51a1e3` („Synthese freigeben“) per DB-Read geprüft: Fan-in-E2E-Rest (Lisa, kein result, 0 Links/Kommentare) → mit purged | SELECT auf `/opt/data/kanban.db` (read-only) |

## 3) OFFEN (klein, bewusst nicht angefasst)

1. **Adapter-Antworttexte** (`reply_text` im Hermes-Adapter) nutzen noch `parse_mode="Markdown"`
   mit Backtick-Quotes — funktioniert, gleicher 400-Risikopfad → bei Gelegenheit auf HTML.
2. `hermes kanban show <id>` crasht auf Anzeige-Bug (`created_at` str vs int in `_fmt_ts`,
   hermes_cli/kanban.py:49) — kosmetisch, nur CLI-Anzeige, nicht Archon.
3. Roberts 6 Projektordner vom 11.10. in EINEN zusammenlegen? User-Entscheidung weiter offen.

## 4) Strukturell (aus ABEND-Handout, weiter unberührt)

- Zwei parallele Task-Welten (Mission-Control vs. kanban.db) zusammenführen,
- Fan-in-Race (`_fan_in_maybe_start_synthesis`: load→check→set→save ohne Atomarität),
- „Marker-Kontrakt“ (Lisas `SYNTHESE-BEREIT` wird nie geprüft),
- Fragile ROBERT-Freigabe-Erkennung (`"FREIGABE" in erste`).

## 5) Stellen/Dateien

- `backend/kanban_sidecar.py` (NEU: `_LOCK`, `load_kanban_meta`, `_write_atomic`, `update_kanban_meta`).
- `backend/operations_api.py`: `_load/_save` delegieren; Endpoint validiert VOR dem Lock,
  Mutationen als Closures in `update_kanban_meta` (ein Lock pro POST genügt, da Key-Merge).
- `backend/post_task_pipeline.py`: Sidecar-Block nutzt `update_kanban_meta` (Lazy-Import, kein Zyklus).
- Lock = prozessweit (ein Schreiberprozess ARCHON-OS); Hermes schreibt den Sidecar nie.
