# Archiv — Toolchain-Artefakte, 25.11.2026

Verschoben im Rahmen der **Artefakt-Bereinigung vor dem ersten Push**
(siehe `audit_reports/HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md` §7 und
`audit_reports/HANDOFF_PREPUSH_REMEDIATION_2026-11-25.md` §4).

**Es wurde NICHTS gelöscht.** Alle Dateien liegen hier und können einzeln
zurückkopiert werden. Es wurde **kein `git add`, kein Commit und kein Push**
im Hauptbaum ausgeführt. Der Worktree-Branch `s1-god-objects` blieb unberührt.

## Inhalt

| Datei | Grund |
|---|---|
| `importlinter.ALT-root_package-SINGULAR` | Alt-Config mit dem bekannten Fehler `root_package = archon` (**Singular**) → `exit 1 / No matches for ignored import` (`ANALYSIS_GOD_OBJECTS.md §1.3`). Nur 2 `ignore_imports`, gehört zum Code-Stand `2ee92706`. **Die gültige Config liegt committet im Worktree-Branch `s1-god-objects` (`ee18373a`)** mit `root_packages = archon, backend` und **leeren** `ignore_imports`. |
| `mypy_full_stdout.txt` | ~23 KB Scan-Log eines früheren mypy-Laufs; `--txt-report` crasht mypy 2.4.1 intern (`HANDOFF_HY4_DEBUG §1`). Kein Gate-Ergebnis. |
| `tool_scans/` | 10 Scan-Logs, ~9 MB. `detect_secrets.txt` ~8 MB, `semgrep.txt` 18 B, teils `"NOT EXECUTED"` von fehlgeschlagenen Agentenläufen. **Nicht als echte Scanner-Ergebnisse zählen** (`HANDOFF_HY4_DEBUG §3`, `INVARIANTS §1`). Das verlässliche Äquivalent war `audit_secrets.py --all` = 0 Funde. |
| `run_fast_scans.ps1`, `run_remaining_scans.ps1`, `run_static_toolchain.ps1` | Lokale Dev-Toolchain mit **relativen** `.venv\Scripts`-Pfade und `lint-imports`-Aufruf. Funktioniert nur im Hauptbaum, nicht im Worktree (dort gibt es keine Venvs). Archiviert, weil sie gegen die veraltete Config liefen und die ungueltigen Scan-Logs erzeugt haben. |

## Rückgängig (Beispiele)

```powershell
$m = 'C:\.Antigravity-projekte\AgenticOS-2026'
$a = Join-Path $m 'audit_reports\_archiv_2026-11-25_artefakte'
Copy-Item (Join-Path $a 'run_static_toolchain.ps1') (Join-Path $m 'scripts\run_static_toolchain.ps1')
Copy-Item (Join-Path $a 'run_remaining_scans.ps1')  (Join-Path $m 'scripts\run_remaining_scans.ps1')
Copy-Item (Join-Path $a 'run_fast_scans.ps1')       (Join-Path $m 'scripts\run_fast_scans.ps1')
Copy-Item (Join-Path $a 'tool_scans')               (Join-Path $m 'audit_reports\tool_scans') -Recurse
Copy-Item (Join-Path $a 'mypy_full_stdout.txt')     (Join-Path $m 'audit_reports\mypy_full_stdout.txt')
```

**Achtung beim Zurückholen der Alt-`.importlinter`:** sie passt zum alten
Code-Stand `2ee92706`. Wenn du `lint-imports` im Hauptbaum brauchst, nimm
stattdessen die **committete** Version aus dem Worktree:
`C:\Users\micha\.local\share\opencode\worktree\b1d671\god-objects\.importlinter`
— aber beachte, dass deren leere `ignore_imports` zum alten Code (23 Paare)
nicht passt und dort rot würde. Linter-Läufe gehören in den Worktree.

## Bewusst NICHT angetastet

- **`audit_reports/fix_d2_mypy.md`** — Zeile 90-91 zitiert das Legacy-Salt-Literal
  `ARCHON_OS_API_KEY_SALT_<REDACTED>` aus `fix_w2_a_security.md:143`. Laut
  Handoff §7 eine **Orchestrator-Entscheidung** („Doku vs. Scanner-Regex");
  wurde daher nicht geändert.
  **Wichtiger Befund:** `scripts/audit_secrets.py:146` nutzt `git ls-files`,
  scannt also **ausschließlich getrackte** Dateien. Alle `??`-Artefakte wurden
  von `audit_secrets --all` **nie geprüft** — die „0 Funde"-Meldungen bezogen
  sich nur auf getrackte Dateien. Vor einem `git add` dieser Dokumente muss
  das Zitat bewusst bewertet werden (Doku-Ausnahme oder Regex-Anpassung).
- **`audit_reports/HANDOFF_GOD_OBJECTS_F4F3_2026-11-25.md`**,
  **`HANDOFF_GOD_OBJECTS_FINAL_2026-11-25.md`**,
  **`HANDOFF_PREPUSH_REMEDIATION_2026-11-25.md`**, **`INVARIANTS.md`**,
  **`S1_IMPORT_DEBT_DETAIL.md`** — bleiben bewusst `??` im Hauptbaum
  (Handoff §1: Zeitdokumente, gehören nicht in die Worktree-Commits).
  Sie sind die einzige Dokumentation derImport-Schuld-Arbeit.

## Doku-Verweise auf die archivierten Skripte

Der Referenz-Check fand **nur historische Dokumentations-Verweise**, keine
aktiven Code-Referenzen (kein Import, kein Aufruf aus Produktivcode):

- `audit_reports/ANALYSIS_GOD_OBJECTS.md:152, :268, :612`
- `audit_reports/fix_doc_toolchain.md:26`
- `audit_reports/HANDOFF_ANTIGRAVITY_2026-11-25.md:3`
- `audit_reports/HANDOFF_PREPUSH_REMEDIATION_2026-11-25.md:145`

Diese Zeitdokumente wurden **bewusst nicht editiert** (`INVARIANTS §4`:
historische Einträge bleiben unangetastet). Wer die lokalen Scans wieder
braucht, holt die Skripte mit den `Copy-Item`-Befehlen oben zurück.

## Ergebnis der Bereinigung

Vorher: **11** `??` im Hauptbaum.
Nachher: **7** `??` — die fünf Dokumentationsdateien, `fix_d2_mypy.md`
(bewusste Owner-Entscheidung) **und das Archiv-Verzeichnis selbst**.
Das ist erwartbar: das neu angelegte Archiv ist ebenfalls untracked.

Worktree `s1-god-objects @ ee18373a` blieb **sauber und unberührt**, kein
`git add`, kein Commit, kein Push.

**Zusätzlicher Befund (aufgeklärt, kein Alarm):**
`git status` im Hauptbaum meldet zwei getrackte `M`-Dateien:
`audit_reports/HANDOFF_HY4_DEBUG_2026-11-25.md` und
`audit_reports/PROPOSAL_3b_MODULARITY.md`. Der Diff zeigt **ausschließlich
Hy4's Doku-Korrekturen aus der Analyse-Phase** („Korrektur 2 (Hy4)" zur
`root_packages`-Ursache, neuer §4b „S1-Status / DELEGATED", die
pip-audit-Korrektur „kein Bump nötig"). Sie waren bereits beim ersten Read
dieser Session vorhanden und sind **vorbestehend** (`HANDOFF §0.1`:
„Working Tree dirty: ~180 `M` + ~40 `??`"). Sie gehören zu
`main @ 2ee92706`, **nicht** zum Branch `s1-god-objects`, und wurden bewusst
**weder restauriert noch committet**. Der Archivierungs-Schritt hat sie nur
gelesen, nicht verändert. Siehe `HANDOFF_PREPUSH_REMEDIATION_2026-11-25.md` §13.
