# Chaos- & Resilienz-Testing in Archon OS

Dieses Handbuch beschreibt die Chaos-Engineering- und Resilienz-Test-Suite (`scripts/chaos_tester.py`), mit der unvorhergesehene Ausfälle, Datenbankkonflikte und Container-Crashs automatisiert simuliert und verifiziert werden.

---

## 1. Testumfang

Die Suite prüft vier kritische Resilienz-Dimensionen des Agentic OS:

1. **SQLite Concurrency & Lock Resilience:**
   - Erzeugt extreme Nebenläufigkeit (8 Threads, jeweils 50 Transaktionen) gegen `kanban.db`.
   - Misst Durchschnitts- und Maximallatenzen in Millisekunden.
   - Verifiziert, dass der Write-Ahead-Log (WAL-Mode) Lock-Fehler vollständig verhindert.
2. **Container Discovery & Health:**
   - Scannt alle aktiven Container (`ARCHON-OS`, `hermes`, `docker-socket-proxy`, `omniroute`, etc.).
   - Prüft, ob kritische Kernkomponenten laufen und Ports korrekt gemappt sind.
3. **Simulated Container Restart & Recovery:**
   - Führt im Live-Modus einen kontrollierten Crash/Restart eines Hilfsdienstes (`hermes-dashboard-proxy`) durch.
   - Misst die Zeit bis zur vollständigen Wiederherstellung des `running`-Zustands (SLA < 15 Sekunden).
4. **Watchdog Supervisor Responsiveness:**
   - Validiert die ständige Überwachung durch den Hintergrund-Watchdog (30-Sekunden-Intervall).
   - Prüft Vorhandensein und Beschreibbarkeit der Alarmprotokolle (`archon_alarms.json`).

---

## 2. CLI-Ausführung

```bash
# Zerstörungsfreier Simulationsmodus (dry-run, default)
python scripts/chaos_tester.py --dry-run

# Echter Resilienztest inklusive Container-Restart
python scripts/chaos_tester.py --live
```

Die Ergebnisse werden automatisch in `data/chaos_test_results.json` protokolliert.

---

## 3. REST-API-Schnittstellen

Unter `/api/operations/chaos` stehen zwei Endpunkte bereit:

### `POST /api/operations/chaos/run`
Startet die Suite remote (z. B. aus CI/CD oder dem Operations Dashboard).

```json
// Request Body
{
  "dry_run": true
}

// Response
{
  "status": "success",
  "chaos_results": {
    "timestamp": "2026-10-31T04:20:00Z",
    "dry_run": true,
    "tests_run": 4,
    "tests_passed": 4,
    "tests_failed": 0,
    "details": {
      "db_concurrency": {
        "status": "passed",
        "threads": 8,
        "total_operations": 400,
        "errors_count": 0,
        "avg_latency_ms": 1.25,
        "max_latency_ms": 8.41
      },
      "container_health": {
        "status": "passed",
        "running_containers_count": 11,
        "missing_essential": []
      },
      "container_restart": {
        "status": "passed",
        "recovery_time_sec": 1.84,
        "current_status": "running"
      },
      "watchdog_supervisor": {
        "status": "passed",
        "supervisor_interval_sec": 30
      }
    }
  }
}
```

### `GET /api/operations/chaos/results`
Ruft die Ergebnisse des letzten Testlaufs als Audit-Nachweis ab.
