# Fix M-B — echte MyPy-Typfehler in `backend/**` (25.11.2026)

> Punkt aus dem Full-Run `audit_reports/mypy_full_stdout.txt`; Grundlage `mypy.ini`
> und die Methodik aus `audit_reports/fix_d2_mypy.md`.
> **Exklusives Datei-Ownership eingehalten:** nur die 10 zugewiesenen Dateien in
> `backend/**`. Keine Änderung an `utils/**`, `scripts/**`, `data/**`, Tests,
> `mypy.ini` oder Doku ausser diesem Report.

## 1. Zahlen (exakt)

| Metrik | Vorher | Nachher |
|---|---:|---:|
| MyPy-Fehler in den 10 Ownership-Dateien | **23** | **0** |
| Geänderte Dateien | — | **10** (28 Insertions / 15 Deletions) |
| Echte Annotationen / Narrowing / cast | — | **22** Fehlerstellen |
| Gezielte codierte Ignores mit Begründung | — | **1** (`attr-defined`, AF_UNIX) |
| Entfernte verwaiste Ignores | — | **1** (`unused-ignore`, Supervisor-Cache) |

Die 23 Fehlerstellen verteilen sich exakt wie assigned:
`calendar_sync_blocker.py` (6), `demo_mode.py` (4), `model_routing.py` (3),
`qr_girocode.py` (3), `hermes_updater.py` (2), `mcts_engine.py` (1),
`research_sources.py` (1), `settings_json.py` (1), `supervisor_rollover.py` (1),
`telegram_gateway_v2.py` (1).

## 2. Auflösung pro Datei

| Datei | Fehler | Fix |
|---|---:|---|
| `backend/calendar_sync_blocker.py` | 6 | `else:` → `elif le is not None and re_ is not None:`. Die UID stammt aus der Vereinigung beider Maps, daher sind in diesem Pfad beide Karten belegt; die explizite Prüfung ist für MyPy sichtbar und im erreichbaren Pfad wirkungslos. |
| `backend/demo_mode.py` | 4 | `raw_deals: List[Dict[str, Any]]` (reine Typangabe). **Keine Schutzlogik verändert** — der Demo-Security-Guard (Hard-Block-Prefixe, 403-Pfade) bleibt unangetastet; `weighted_value` wird weiterhin aus denselben Werten berechnet. |
| `backend/model_routing.py` | 3 | `from typing import Any, Dict` + `cfg: Dict[str, Any]` in `load_config()` (löst `append` auf `object` und die Index-Zuweisung). `max(scores, key=scores.get)` → `key=lambda k: scores[k]` (äquivalent, aber nicht überladen). |
| `backend/qr_girocode.py` | 3 | Loop-Variable `b` → `blk` beim Interleaving. Das `b` aus `for b in raw` (Bytes → `int`) ist im selben Funktionsscope gebunden und kollidierte mit `List[int]`. **Rein namensbasiert — keine QR-/Girocode-Werte, keine Reihenfolge geändert.** |
| `backend/hermes_updater.py` | 2 | `_cache_lock_time: float = 0` (`now = time.time()` ist float). Ein gezielter `# type: ignore[attr-defined]` an `socket.AF_UNIX` mit Begründung: Linux-only Docker-Socket, Windows-Stubs von typeshed kennen das Attribut nicht. |
| `backend/mcts_engine.py` | 1 | `cast("MCTSNode", self.parent)` in `ucb1()`. `ucb1` wird nur auf Kindknoten gerufen; `cast` ist zur Laufzeit ein No-op und ändert keine MCTS-Werte. |
| `backend/research_sources.py` | 1 | `TRUST_TIERS: Dict[str, Dict[str, Any]]`. Reine Typangabe an der Registry; alle Tier-Werte (`level`, `weight`, `name`, …) bleiben identisch. |
| `backend/settings_json.py` | 1 | `loader: Optional[Callable[[], Dict[str, Any]]]`. Der einzige Loader-Aufrufer (`autonomy_settings.load_all_settings`) ist parameterlos; die alte Annotation war falsch, der Aufruf `loader()` war korrekt. Keine Laufzeitänderung. |
| `backend/supervisor_rollover.py` | 1 | Verwaisten `# type: ignore[return-value]` entfernt: `_load() -> tuple` akzeptiert die `object`-Werte des Caches, der Ignore war unter `warn_unused_ignores = True` toter Code. |
| `backend/telegram_gateway_v2.py` | 1 | Rückgabe `Optional[Dict[str, Any]]` statt `Optional[Dict[str, str]]`, weil `approved` bewusst ein `bool` ist (Test `cb["approved"] is True`). Reine Annotationsänderung, kein Wertewechsel zu `"true"`. |

## 3. Verifikation (selbst ausgeführt, 25.11.2026)

| Gate | Kommando | Ergebnis |
|---|---|---|
| MyPy (10 Dateien) | `.venv\Scripts\mypy.exe --config-file mypy.ini --no-pretty backend/calendar_sync_blocker.py backend/demo_mode.py backend/model_routing.py backend/qr_girocode.py backend/hermes_updater.py backend/mcts_engine.py backend/research_sources.py backend/settings_json.py backend/supervisor_rollover.py backend/telegram_gateway_v2.py` | **Success: no issues found in 10 source files** |
| Syntax | `.venv\Scripts\python.exe -m compileall -q backend` | **Exit 0**, keine Ausgabe |
| Full-Suite | `.ci_venv\Scripts\python.exe -m pytest tests/ -q --tb=short` | **2342 passed, 16 skipped, 2 warnings in 290.06 s** |

`ARCHON_DATA_DIR` war ausschliesslich ein frisches
`C:\Users\micha\AppData\Local\Temp\opencode\archon-m-backend-types-<PID>`.
`./data/**` wurde nicht beschrieben. Der neue Ignore ist codiert
(`[attr-defined]`) und direkt im Code begründet; `warn_unused_ignores = True`
und `warn_redundant_casts = True` bleiben erfüllt.

## 4. Bemerkungen

1. Die vier `demo_mode.py`-Fehler betreffen ausschliesslich die Demo-Datengenerierung,
   nicht den Security-Guard. Es wurde keine Blockier-, 403- oder Egress-Regel geändert.
2. Die drei `qr_girocode.py`-Fehler waren ein Variablen-Scope-Konflikt (`b`: `int`
   aus den Bytes vs. `List[int]` aus den RS-Blöcken). Der Fix ist eine Umbenennung;
   encoding, Interleaving-Reihenfolge und damit der QR-Inhalt sind unverändert.
3. Der einzige Ignore (`hermes_updater.py:113`) ist plattformbedingt: der Code läuft
   unter Linux gegen `/var/run/docker.sock`; Windows-Stubs liefern `AF_UNIX` nicht.
   Ein `getattr`-Fallback wäre eine Laufzeitänderung und wurde bewusst nicht gewählt.
4. Keine Pauschal-Pragmas, keine `mypy.ini`-Änderung, keine neuen Module.
