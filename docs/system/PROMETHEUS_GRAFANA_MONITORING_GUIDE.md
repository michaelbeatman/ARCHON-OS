# Metriken, Observability & Alerting (Prometheus, Grafana, Uptime Kuma)

## Überblick
Archon OS stellt native Prometheus-konforme Metriken bereit und integriert ein umfassendes Überwachungs-Ökosystem bestehend aus:
1. **FastAPI Prometheus Exporter** (`/metrics` und `/api/operations/metrics`): Liefert Kennzahlen im Standard-Textformat (Version 0.0.4).
2. **REST Summary API** (`/api/operations/metrics/summary`): Aggregiertes JSON für Dashboards und externe Abfragen.
3. **Prometheus-Scraper** (`config/prometheus/prometheus.yml`): Kontinuierliche Erfassung aller 15s.
4. **Grafana Operations Dashboard** (`config/grafana/dashboards/archon_system_overview.json`): Visualisierung von Queue-Tiefe, Fehlerraten, Kosten und Task-Verteilung.
5. **Uptime Kuma**: Endpunkt- und Container-Überwachung mit Benachrichtigungen an den `NotificationHub`.

---

## 1. Verfügbare Metriken

| Metrik | Typ | Beschreibung |
|---|---|---|
| `archon_uptime_seconds` | Gauge | Betriebszeit des Archon OS Kernprozesses in Sekunden. |
| `archon_tasks_total{status="..."}` | Gauge | Anzahl Aufgaben im Operations Kanban aufgeschlüsselt nach Status (`ready`, `in_progress`, `review`, `done`, `blocked`, `archived`). |
| `archon_queue_depth` | Gauge | Anzahl anstehender, noch nicht bearbeiteter Aufgaben (`ready`). |
| `archon_agent_dispatches_total{status="..."}` | Counter | Kumulierte Agenten-Ausführungen (`ok` vs. `error`). |
| `archon_agent_error_rate_percent` | Gauge | Prozentuale Fehlerrate über alle LLM-Dispatches. |
| `archon_tokens_total` | Counter | Gesamtzahl verbrauchter Token (Prompt + Completion). |
| `archon_estimated_cost_usd` | Counter | Geschätzte LLM-Kosten in USD. |
| `archon_database_size_bytes{database="..."}` | Gauge | Dateigröße der SQLite-Dateien (`kanban_db`, `memory_db`, `state_db`) in Bytes. |
| `archon_system_cpu_percent` | Gauge | CPU-Auslastung des Wirts-/Containersystems. |
| `archon_system_memory_used_bytes` | Gauge | Belegter Arbeitsspeicher in Bytes. |

---

## 2. Abruf der Endpunkte

### Prometheus Exposition Text (0.0.4)
```bash
curl -s http://localhost:8501/metrics
```
**Beispielausgabe:**
```text
# HELP archon_tasks_total Gesamtzahl der Aufgaben im Kanban-Board nach Status.
# TYPE archon_tasks_total gauge
archon_tasks_total{status="ready"} 64
archon_tasks_total{status="in_progress"} 1
archon_tasks_total{status="done"} 14

# HELP archon_queue_depth Anzahl der anstehenden Aufgaben in der Queue (ready).
# TYPE archon_queue_depth gauge
archon_queue_depth 64
```

### JSON Summary API
```bash
curl -s http://localhost:8501/api/operations/metrics/summary
```

---

## 3. Prometheus & Grafana Starten

Die Dienste sind in `docker-compose.yml` unter dem Profil `monitoring` hinterlegt:

```bash
# Monitoring-Stack starten
docker compose --profile monitoring up -d prometheus grafana uptime-kuma
```

- **Prometheus UI:** `http://localhost:9090`
- **Grafana UI:** `http://localhost:3001` (Standard-Login: `admin` / `archon_admin_2026`)
- **Uptime Kuma:** `http://localhost:3002`

---

## 4. Automatisches Schwellenwert-Alerting

Der Kollektor (`backend/metrics_collector.py`) prüft bei Scrapes konfigurierte Schwellenwerte:
1. **Fehlerrate > 25%:** Löst einen `WARNING`-Alarm aus, falls mindestens 10 Dispatches stattfanden.
2. **Queue-Stau (> 50 Aufgaben in `ready`):** Informiert über akkumulierte Last.

Alle Alarme werden an den `NotificationHub` (`backend/notification_hub.py`) übergeben. Unter Einhaltung der konfigurierten **Ruhezeiten** (Quiet Hours) werden nicht-kritische Push-Nachrichten nachts gepuffert und erst im morgendlichen Standup-Digest zugestellt.
