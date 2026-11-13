# Business Intelligence Dashboard (Metabase) in Archon OS

Dieses Handbuch beschreibt die Einrichtung und Nutzung von Metabase als visuelle BI- und Analytics-Plattform für Archon OS.

---

## 1. Architektur & Ports

Metabase läuft als containerisierter Dienst im Docker-Compose-Netzwerk `agentic_mesh`:

- **Container-Name:** `metabase-bi`
- **Profil:** `bi` / `analytics`
- **Host-Port:** `http://localhost:3030` (Container-Port 3000)
- **Persistenz:** Docker Volume `metabase_data` unter `/metabase-data/metabase.db`
- **Datenbank-Mounts:** Read-Only Mount von `/opt/data` für `kanban.db` und PocketBase

---

## 2. Starten des Dienstes

```bash
# Metabase starten
docker compose --profile bi up -d metabase

# Logs und Initialisierung prüfen
docker compose --profile bi logs -f metabase

# Dienst stoppen
docker compose --profile bi stop metabase
```

Nach dem ersten Start unter `http://localhost:3030` den initialen Admin-Benutzer anlegen.

---

## 3. Datenbank-Anbindung in Metabase

### A. Archon Kanban & Task-Analytics
- **Datenbanktyp:** SQLite
- **Dateipfad:** `/opt/data/kanban.db`

### B. Agentic Memory & Receipts
- **Datenbanktyp:** SQLite
- **Dateipfad:** `/opt/data/agentic_memory.db`

---

## 4. Vorgefertigte SQL-Abfragen für Dashboard-Cards

### 1. Durchsatz: Erledigte Tasks nach Team & Tag (Kanban)
```sql
SELECT 
    date(completed_at) AS tag,
    assignee,
    COUNT(*) AS erledigte_aufgaben
FROM tasks
WHERE status = 'done' AND completed_at IS NOT NULL
GROUP BY tag, assignee
ORDER BY tag DESC
LIMIT 30;
```

### 2. Task-Verteilung nach Status (Mission Control Pie-Chart)
```sql
SELECT 
    status,
    COUNT(*) AS anzahl
FROM tasks
GROUP BY status;
```

### 3. Monatliche Ausgaben nach Kategorie (Receipts / Belege)
```sql
SELECT 
    strftime('%Y-%m', receipt_date) AS monat,
    category AS kategorie,
    ROUND(SUM(amount_gross), 2) AS summe_eur,
    COUNT(*) AS anzahl_belege
FROM receipts
GROUP BY monat, category
ORDER BY monat DESC;
```

### 4. Top-Händler nach Ausgabenvolumen
```sql
SELECT 
    merchant AS haendler,
    COUNT(*) AS anzahl_einkaeufe,
    ROUND(SUM(amount_gross), 2) AS gesamtbetrag_eur
FROM receipts
GROUP BY merchant
ORDER BY gesamtbetrag_eur DESC
LIMIT 10;
```
