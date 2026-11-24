# Archon OS – Litestream SQLite Live-Replikation & Disaster Recovery

*Stand: Oktober 2026 (aktualisiert: Litestream v0.5.1, Konsolidierung 28→3) | Resilienz-Architektur & Pillar 4*

---

## 1. Übersicht & Zielsetzung

Archon OS setzt für seine Kernprozesse auf SQLite-Datenbanken im Write-Ahead-Logging-Modus (WAL). Seit der aktiven Konsolidierung 28 → 3 (`data/.db_consolidated.json`) sind die drei domänenisolierten Datenbanken die primären Replikationsziele:

- `ops.db`: Operative Steuerung, Kanban-Tasks, Workflows, Audit & Security (ehem. `kanban.db`, `state.db`, `agent_os.db`, …)
- `business.db`: CRM, ERP, Deals, Verträge, Treasury & Content (ehem. `erp.db`, `crm.db`, `deals.db`, `contracts.db`, …)
- `memory.db`: Langzeitgedächtnis, User-Profile, KV-Store, OTel-Traces, Prompt-Registry & GDPR-Audit (ehem. `agentic_memory.db`)

Zusätzlich bleiben zwei Pfade der **Hermes-Runtime** gesichert (legitime Legacy-Pfade, keine Archon-Anwendungs-DBs):

- `/opt/data/kanban.db`: Hermes-Kanban- und Agenten-State
- `/opt/data/state.db`: Hermes-Sitzungshistorie und Token-Kontexte

Die physisch isolierten Mandanten-DBs unter `data/tenants/<id>/` (`erp.db`, `kanban.db`, `crm.db`, `contracts.db`, `deals.db`) werden über die Directory Replication erfasst (siehe Abschnitt 2).

Während traditionelle Dump-Backups (`backup_to_nas.py`) einmal täglich laufen und im Fehlerfall bis zu 24 Stunden Datenverlust bedeuten können, repliziert **Litestream** jede Transaktion kontinuierlich im Sekundentakt auf ein Replikationsziel (lokales Dateisystem, NAS-Freigabe oder MinIO/S3-Bucket).

---

## 2. Architektur & Konfiguration (Litestream v0.5.1)

Die Konfiguration liegt unter [`config/litestream.yml`](../../config/litestream.yml); der Replikations-Container nutzt `litestream/litestream:0.5.1` (siehe `docker-compose.yml`). Die folgende Beispielkonfiguration entspricht der realen Datei:

```yaml
# Litestream Continuous SQLite Replication Configuration for Archon OS
# Docs: https://litestream.io/reference/config/
#
# Die 28->3-Konsolidierung ist AKTIV (data/.db_consolidated.json). Die drei
# konsolidierten DBs sind die primären Replikationsziele. Die Hermes-Runtime
# (/opt/data = ./.hermes) schreibt weiterhin kanban.db / state.db — diese
# bleiben zusaetzlich gesichert.
#
# TENANT_DBS: repliziert via Directory Replication (Litestream >= 0.5).
# FULL_TENANT_ISOLATION defaultet auf "1", d.h. alle Mandanten-DBs liegen unter
# /app/data/tenants/<tid>/*.db. Der `dir:`-Eintrag unten erfasst mit
# `pattern: "*.db"` und `recursive: true` alle Tenant-DBs beim Start (neue
# Tenant-DBs nach Neustart; `watch: true` wäre optional möglich). Das
# Replikat-Feld heisst in v0.5 `replica:` (singular);
# das `replicas:`-Array der 5 Bestandseinträge lädt mit genau einem Eintrag
# weiter (deprecated), bleibt hier aber bewusst unverändert.
#
# v0.5-Migration: `retention` ist kein Replikat-Feld mehr und wird dort
# ignoriert. Die gewünschten 72h sind deshalb im globalen `snapshot`-Block
# unten wirksam; die `retention: 72h` in den Replikaten sind nur noch
# Dokumentation im gewohnten Stil der Bestandseinträge.
#
# scripts/automated_restore_test.py meldet FAILED, wenn Tenant-DBs existieren,
# aber weder ein expliziter Tenant-Pfad noch ein `dir:`-Eintrag konfiguriert ist.
snapshot:
  retention: 72h

dbs:
  # --- Konsolidierte Archon-Domaenen (Phase 2.1, aktiv) ---
  - path: /app/data/ops.db
    replicas:
      - type: file
        path: /opt/litestream_replicas/ops.db
        sync-interval: 5s
        retention: 72h

  - path: /app/data/business.db
    replicas:
      - type: file
        path: /opt/litestream_replicas/business.db
        sync-interval: 5s
        retention: 72h

  - path: /app/data/memory.db
    replicas:
      - type: file
        path: /opt/litestream_replicas/memory.db
        sync-interval: 10s
        retention: 72h

  # --- Hermes-Runtime (/opt/data = ./.hermes Mount) ---
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

  # --- Tenant-DBs: Directory Replication (Litestream >= 0.5) ---
  # Erfasst data/tenants/<tid>/*.db rekursiv beim Start. Neu angelegte Tenant-
  # DBs werden beim Litestream-Neustart übernommen (optional `watch: true` für
  # automatische Erkennung). `replica:` (singular) ist die v0.5-Syntax.
  - dir: /app/data/tenants
    pattern: "*.db"
    recursive: true
    replica:
      type: file
      path: /opt/litestream_replicas/tenants
      sync-interval: 5s
      retention: 72h   # v0.5: global wirksam via snapshot.retention (s. oben)
```

Wesentliche Punkte der v0.5-Migration:

- `replica:` (Singular) ist die Syntax für neue Einträge; die fünf Bestandseinträge nutzen weiterhin `replicas:` mit genau einem Eintrag (deprecated, aber kompatibel).
- `retention` ist kein Replikat-Feld mehr. Die gewünschten 72 h sind im globalen `snapshot`-Block wirksam; die `retention: 72h` in den Bestandseinträgen bleiben als Dokumentation im gewohnten Stil.
- `dir: /app/data/tenants` mit `pattern: "*.db"` und `recursive: true` erfasst alle Mandanten-DBs beim Start. Neu angelegte Tenant-DBs werden beim Litestream-Neustart übernommen (`watch: true` wäre optional möglich).
- [`scripts/automated_restore_test.py`](../../scripts/automated_restore_test.py) meldet `FAILED`, wenn Tenant-DBs existieren, aber weder ein expliziter Tenant-Pfad noch ein `dir:`-Eintrag konfiguriert ist.

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

Sollte eine Datenbank korrumpieren oder gelöscht werden, Beispiel für die konsolidierte `ops.db`:

```bash
# Wiederherstellung des letzten konsistenten Stands für ops.db
docker run --rm \
  -v ./data:/app/data \
  -v ./data/litestream_replicas:/opt/litestream_replicas \
  litestream/litestream:0.5.1 restore \
  -replica /opt/litestream_replicas/ops.db \
  /app/data/ops.db
```

Für `business.db` und `memory.db` entsprechend die Pfade ersetzen (`/opt/litestream_replicas/business.db` bzw. `/opt/litestream_replicas/memory.db`). Die Hermes-Legacy-Ziele `/opt/data/kanban.db` und `/opt/data/state.db` werden aus ihren eigenen Replikaten `/opt/litestream_replicas/kanban.db` und `/opt/litestream_replicas/state.db` wiederhergestellt. Tenant-DBs liegen unter `/opt/litestream_replicas/tenants`.

Nach Abschluss ist der exakte Stand bis auf wenige Sekunden vor dem Ausfall verlustfrei wiederhergestellt.
