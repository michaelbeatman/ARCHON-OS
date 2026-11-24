# Fix-Report C — MED-Funde F-045, F-046, F-048, F-050, F-051

> Stand: 24.11.2026 · Scope: nur `backend/workflow_dag_runner.py`, `local_memory_bridge.py`,
> `scripts/archon_crm_mcp.py`, `scripts/garbage_collector.py`, `scripts/installer_build/build_export.py`.
> Nicht committen (parallel laufende Agenten bearbeiten andere Dateien).

## Änderungen

| ID | Datei | Fix |
|---|---|---|
| **F-045** | `backend/workflow_dag_runner.py` | Neuer Helper `_raw_output_status()` (None / Blank-String → `error`, sonst `success`). `_exec_with_retry_and_timeout()` wrapped Nicht-Dict-Outputs nicht mehr pauschal als `success`: `None`/leerer String → `{"status":"error","error":"executor returned non-dict/empty","node_id":...}` (Retry/DLQ greift), nicht-leere Nicht-Dict-Werte → `{"status":"success","result":res}`. `_shape_upstream_output()` übernimmt den Status aus dem Raw-Output auch in den Nicht-Dict-Zweigen (`none`/`artifact_only`/`summary`) statt `"success"` zu defaulten. Dict-Zweige unverändert (`raw_out.get("status","success")`). |
| **F-046** | `local_memory_bridge.py` | Neue statische `_decode_checkpoint_state()`: bei `JSONDecodeError`/`TypeError`/`ValueError` → `state=None`, `checkpoint_error="corrupt_state_json"`, `resume_blocked=True`, `logger.error`. Ersetzt die stillen `except: d["state"]={}` in `get_workflow_checkpoint()` und `list_workflow_checkpoints()`. `save_workflow_checkpoint()` verweigert mit `status="resumed"` bei `resume_blocked` die Aufgabe (gibt `False` zurück, loggt Fehler, `state_json` bleibt unverändert) → Resume blockiert. Gesunde Checkpoints werden weiterhin normal dekodiert. |
| **F-048** | `scripts/archon_crm_mcp.py` | `import logging` + Logger. Die `except Exception: pass`-Lücke um `scan_prompt_injection()` ist ersetzt durch `logger.error(...)`, `sec_status="unknown"`, `quarantined=True` und Ersetzung des Inhalts durch einen Quarantäne-Platzhalter (Fail-Closed). Zusätzlich wird `verdict="blocked"` des Scanners ebenfalls als `quarantined=True` markiert (weak `suspicious` bleibt redigiert). Neues Feld `"quarantined"` im Mail-Eintrag. Kein Fail-Open-Flag eingeführt. |
| **F-050** | `scripts/garbage_collector.py` | `import logging` + `logger`, `failed_deletions`-Zähler. Die beiden nackten `except: pass` → `except OSError as exc:` mit `logger.warning(...)` und Zähler. Abschlussmeldung enthält jetzt `; N fehlgeschlagene Loeschungen`. Kein `BaseException`-Catch mehr. |
| **F-051** | `scripts/installer_build/build_export.py` | `import sys` + `import logging` + `logger`, `failed_files`-Liste. Nacktes `except: pass` im Obsidian-Markdown-Scrub → `except (OSError, ValueError) as exc:` mit `logger.error(...)` und `failed_files.append(p)`. Bei Fehlern: Abschlussmeldung `Export mit N fehlerhaften Dateien abgeschlossen` + Dateiliste + `sys.exit(1)` (kritischer Export-Inhalt, Fail-Closed). Kein `BaseException`-Catch. |

## Verifikation

1. **Syntax:** `.ci_venv\Scripts\python.exe -m py_compile` auf allen 5 Dateien → Exit 0.
2. **Dry-Runs** (Harness im erlaubten Temp-Verzeichnis, nicht im Repo; 13/13 Checks grün):
   - `F-045`: Executor → `None` ergibt `status=error`/`error="executor returned non-dict/empty"`; Nicht-Dict-String → `success`+`result`; `_shape_upstream_output` liefert für `None`/`""` in `none`/`summary`/`artifact_only` `status=error`, für `"text"` `success`, Dict-Input bleibt unverändert.
   - `F-046`: Temp-DB mit gültigem Checkpoint (`state` normal, `resume_blocked=False`); direkt injiziertes korruptes `state_json` → `get`/`list` liefern `state=None` + `checkpoint_error="corrupt_state_json"` + `resume_blocked=True`; `save_workflow_checkpoint(..., status="resumed")` → `False`, `state_json` unverändert (Resume blockiert).
   - `F-048`: Gemocktes Outlook mit realem `local_security_guard` → Injection-Mail (`ignore previous instructions` + `you are now`) ergibt `security_status="blocked"`, `quarantined=True`, `[REDACTED_INJECTION]` im Text; simulierter Scanner-Fehler → `security_status="unknown"`, `quarantined=True`, Platzhalter statt Klartext.
   - `F-050`: AST-Check keine `except ... type=None`; Runtime mit monkeypatchtem `os.remove` (OSError) → `failed_deletions=1`, Zähler in der Abschlusszeile, `WARNING`-Log.
   - `F-051`: AST-Check keine nackten `except`; der echte `scrub_content`-Block aus der Quelle mit einer invaliden UTF-8-Datei ausgeführt → `failed_files=[bad.md]`, `logger.error`, `sys.exit(1)`-Pfad vorhanden.

## Hinweise

- Keine Datei außerhalb des Besitz-Scopes verändert; `git status` zeigt parallel laufende Änderungen anderer Agenten (unberührt).
- Der Volllauf von `build_export.py` wurde bewusst **nicht** gestartet (`DEST_DIR` wird per `shutil.rmtree` gelöscht) — stattdessen wurde der geänderte Try-Block per AST-Extraktion gegen eine echte fehlerhafte Datei ausgeführt.
- `F-049` (`core_dispatcher.py`) und alle HIGH-Funde liegen bei anderen Agenten und sind hier nicht enthalten.
- Resistenz-Hinweis F-046: Der Resume-Endpoint `archon/routers/operations_dag.py:77-90` (fremder Besitz) prüft den Rückgabewert von `save_workflow_checkpoint()` nicht. Der beschädigte Checkpoint wird zwar nicht überschrieben (Speicher-Ebene blockiert), die HTTP-Antwort lautet aber weiterhin `success`. Für volle Ehrlichkeit muss der Endpoint `cp["resume_blocked"]` auswerten und `409` zurückgeben — bitte an den Besitzer von `operations_dag.py` nachtragen.
