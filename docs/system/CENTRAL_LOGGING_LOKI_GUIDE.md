# Zentrale Log-Aggreation mit Grafana Loki & Promtail in Archon OS

Dieses Handbuch beschreibt die Einrichtung und den Betrieb der zentralen Log-Infrastruktur für alle 11 Container und Hintergrunddienste von Archon OS.

---

## 1. Architekturüberblick

Bisher wurden Logs fragmentiert in einzelnen Container-Puffern oder Dateien unter `/opt/data/logs` abgelegt. Mit Loki und Promtail werden alle Logs gebündelt und durchsuchbar gemacht:

```
[Docker Container Stdout/Stderr]  ---\
[Archon Watchdog & Daemon Logs]   ----> [Promtail Agent] ----> [Grafana Loki] <---- [Grafana UI :3001]
[Litestream & Backup Engine]      ---/     (:9080)               (:3100)            (Explore / Dashboards)
```

- **Promtail:**
  - Liest Docker-Container-Streams über den Docker-Socket (`/var/run/docker.sock`).
  - Überwacht Logdateien in `/opt/data/logs/*.log`.
  - Extrahiert Log-Level (`INFO`, `WARNING`, `ERROR`) und Logger-Namen per Regex-Pipeline.
- **Grafana Loki:**
  - Speichert Log-Streams indiziert nach Labels (`container`, `stream`, `level`, `job`).
  - Bietet LogQL für Volltext- und Muster-Filterung.
  - Verwaltet 7 Tage Retention mit automatischem TSDB-Compactor.
- **Grafana Integration:**
  - Vorkonfigurierte Datenquelle `Loki` (`http://loki:3100`) via `config/grafana/datasources/datasources.yml`.

---

## 2. Konfigurationsdateien

- **`config/loki/loki-config.yml`:**
  Definiert Port 3100, TSDB Schema v13, Compactor-Intervall 10 Min und 168h Aufbewahrungsfrist.
- **`config/promtail/promtail-config.yml`:**
  Definiert zwei Scrape-Jobs:
  1. `archon-file-logs`: Überwacht `/opt/data/logs/*.log`.
  2. `docker-containers`: Dynamische Service Discovery aller Docker-Container.
- **`config/grafana/datasources/datasources.yml`:**
  Registriert Prometheus und Loki als Standard-Datenquellen in Grafana.

---

## 3. Betrieb & Start

Um die Logging-Dienste neben dem regulären Stack zu starten:

```bash
# Startet Loki und Promtail im Hintergrund
docker compose --profile logging up -d loki promtail

# Status prüfen
docker compose --profile logging ps loki promtail

# Loki Healthcheck abfragen
curl http://localhost:3100/ready
```

---

## 4. LogQL-Abfragebeispiele im Grafana Explore

Im Grafana-Menü unter **Explore** die Datenquelle **Loki** wählen:

- **Alle Fehler über alle Container:**
  ```logql
  {job="docker-containers"} |= "ERROR"
  ```

- **Logs des Watchdog-Daemons:**
  ```logql
  {job="archon-files"} |= "watchdog"
  ```

- **OmniRoute / Dispatcher Latenzen und Status:**
  ```logql
  {container="ARCHON-OS"} |= "OperationsAPI"
  ```
