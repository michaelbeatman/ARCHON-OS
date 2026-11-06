# Handover — neue Session

**Stand:** 2026-11-06 · Branch `refactor/critical-hardening` · live deployt

---

## Copy-Paste für die neue Session

```
Projekt: Archon OS, /mnt/raid/AgenticOS-2026 (Docker, Port 8501).
Lies zuerst docs/REFACTOR_STAND_2026-11-06.md — das ist der komplette Stand.
Branch: refactor/critical-hardening (live deployt, 15 Commits).
Arbeite auf diesem Branch weiter, niemals direkt auf main.
Nach jeder Änderung: Routen-Parität prüfen (514), pytest, dann deployen.
Nächster Punkt: archon/core/orchestration.py (siehe Abschnitt 7 im Dokument).
Sprache: Deutsch. Erst messen, dann behaupten.
```

---

## Die 5 Fakten, die man kennen muss

1. **`main.py` = 12.184 Zeilen, 514 Routen.** 202 Routen liegen in
   `archon/routers/` (19 Module), 7 Core-Module in `archon/core/`.
2. **Das Paket heißt `archon`** — nicht `app`. `app.py` existiert im Repo
   (Streamlit) und würde das Paket verschatten.
3. **Container läuft aus `docker-compose.dev.yml`** (Projekt `archon`,
   `--reload`). Änderungen an `docker-compose.yml` greifen **nicht**.
4. **Routen-Parität ist Pflicht.** Skript steht im Dokument (Abschnitt 6):
   514 vorher = 514 nachher, 0 fehlend, 0 neu.
5. **`.venv` hat pytest.** `pytest`, `pytest-asyncio`, `httpx` sind dort
   nachinstalliert. System-Python hat kein pip.

---

## Deploy in 3 Zeilen

```bash
cd /mnt/raid/AgenticOS-2026
docker compose -f docker-compose.dev.yml -p archon up -d --force-recreate archon
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8501/health
```

---

## Nächste Schritte (Reihenfolge)

| # | Aufgabe | Warum | Aufwand |
|---|---|---|---|
| 1 | `archon/core/orchestration.py` | Synthese-/Staffing-Kern (`_execute_mission_control_task` → `_fan_in` → `_run_synthesis_cascade` → `_finalize`) aus `main.py` lösen — **mit Tests**, nicht per Automatik | 1 Tag |
| 2 | 163× `except Exception: pass` → Logging | Stille Fehler sind der Grund, warum Mechaniken unbemerkt sterben (siehe SSE-Vorfall) | 2–3 h |
| 3 | Hardcodierte Pfade (`/opt/data` …) → Config-Schicht | Voraussetzung für Multi-Tenant/Portabilität (~300 Stellen) | 1–2 Tage |
| 4 | Type Hints / mypy (~30 % → 80 %) | Absicherung der 19 Router beim weiteren Umbau | 1 Tag |

---

## Fallstricke (haben in dieser Session Zeit gekostet)

- **Namensbindung nach jedem Verschieben prüfen.** `_SSE_SUBSCRIBERS` blieb
  beim Core-Split aus dem Import → SSE-Stream 500, Live-Updates tot.
  Test `test_core_names_are_bound_in_main` fängt das jetzt.
- **Keine Kaskaden-Extraktion.** Ein automatischer Schnitt mit „allen
  unbenutzten Helfern" riss die Auth-Middleware mit (378 → 274 Routen).
  Nur explizit benannte Helfer verschieben.
- **Pydantic-Modelle** müssen im Router-Modul liegen, sonst startet der Router
  nicht — und das äußert sich nur als Warnung, die Routen fehlen still.
- **Secrets werden beim Schreiben von einer Schutzschicht maskiert.** Testdaten
  für Secrets zur Laufzeit zusammensetzen, nicht als Literal in die Datei.
- **`Depends()` gibt es hier nicht** — Auth läuft über Middleware.

---

## Verifikation nach jeder Änderung

```bash
.venv/bin/python -m pytest tests/ -q --no-header -p no:cacheprovider   # 112 passed, 4 skipped
docker exec ARCHON-OS python /app/scripts/bench_routes.py              # Median ~73 ms
```

Rollback: `git checkout main` (Ausgangsstand), Backup `main.py.pre-hardening.bak`.