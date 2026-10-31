# Archon OS – Litestream SQLite Live-Replikation & Disaster Recovery

*Stand: Oktober 2026 | Resilienz-Architektur & Pillar 4*

---

## 1. Übersicht & Zielsetzung

Archon OS setzt für seine Kernprozesse auf SQLite-Datenbanken im Write-Ahead-Logging-Modus (WAL):
- `kanban.db`: Task-Queue, Status und Delegation (Single Source of Truth)
- `state.db`: Sitzungshistorie und Token-Kontexte
- `agentic_memory.db`: Langzeitgedächtnis (Learnings, User-Profile, KV-Store)

Während traditionelle Dump-Backups (`backup_to_nas.py`) einmal täglich laufen und im Fehlerfall bis zu 24 Stunden Datenverlust bedeuten können, repliziert **Litestream** jede Transaktion kontinuierlich im Sekundentakt auf ein Replikationsziel (lokales Dateisystem, NAS-Freigabe oder MinIO/S3-Bucket).

---

## 2. Architektur & Konfiguration

Die Konfiguration liegt unter [`config/litestream.yml`](file:///c:/.Antigravity-projekte/AgenticOS-2026/config/litestream.yml):

```yaml
dbs:
  - path: /opt/data/kanban.db
    replicas:
      - type: file
        path: /opt/litestream_replicas/kanban.db
        sync-interval: 5s
        retention: 72h

  - path: /opt/data/state.db
    replicas:
      - type: file
        path: /opt/litestream_replicas/state.db
        sync-interval: 10s
        retention: 72h

  - path: /app/data/agentic_memory.db
    replicas:
      - type: file
        path: /opt/litestream_replicas/agentic_memory.db
        sync-interval: 10s
        retention: 72h
```

---

## 3. Betrieb & Diagnose

### 3.1 Bereitschafts- und WAL-Prüfung
Über das bereitgestellte Management-Skript kann jederzeit geprüft werden, ob alle Datenbanken integer und im WAL-Modus sind:
```bash
python scripts/litestream_manager.py --check
```

### 3.2 WAL-Modus aktivieren (falls nötig)
```bash
python scripts/litestream_manager.py --enable-wal
```

### 3.3 Replikations-Container starten
In `docker-compose.yml` ist der Litestream-Dienst unter dem Profil `replication` hinterlegt:
```bash
docker compose --profile replication up -d litestream
```

---

## 4. Wiederherstellung im Notfall (Restore)

Sollte eine Datenbank korrumpieren oder gelöscht werden:
```bash
# Wiederherstellung des letzten konsistenten Stands für kanban.db
docker run --rm \
  -v C:/Users/micha/.hermes:/opt/data \
  -v C:/.Antigravity-projekte/AgenticOS-2026/data/litestream_replicas:/opt/litestream_replicas \
  litestream/litestream:0.3.13 restore \
  -replica /opt/litestream_replicas/kanban.db \
  /opt/data/kanban.db
```
Nach Abschluss ist der exakte Stand bis auf wenige Sekunden vor dem Ausfall verlustfrei wiederhergestellt.
