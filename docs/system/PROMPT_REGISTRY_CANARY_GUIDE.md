# Prompt-Registry mit Versionierung, 1-Click Rollback & Canary-Rollout

## Überblick
Vor Einführung der Prompt-Registry wurden Änderungen an System-Prompts direkt in `agent_profiles.json` überschrieben oder erzeugten unstrukturierte Backup-Dateien (`agent_profiles.json.bak.N`). 

Die Prompt-Registry (`backend/prompt_registry.py`) überführt das Prompt-Management in eine transaktionale SQLite-Architektur (`prompt_versions` in `agentic_memory.db`) und ergänzt:
1. **Lückenlose Versionierung:** Jede Änderung speichert den Prompt, das Modell, Ersteller, Zeitstempel und eine Commit-Nachricht.
2. **1-Click Rollback:** Ermöglicht die sofortige Wiederherstellung jedes historischen Stands unter Wahrung der Historie.
3. **Unified Diff:** Textueller Zeilenvergleich zwischen beliebigen Versionen (`difflib.unified_diff`).
4. **Canary-Rollout (Verkehrs-Splitting):** Weiterleitung eines definierbaren Prozentsatzes (z. B. 10 % oder 20 %) an eine neue Prompt-Version, basierend auf deterministischem Task-Hashing.
5. **Rückwärtskompatibilität:** Aktive Versionen werden synchron in `agent_profiles.json` gespiegelt.

---

## Datenbankschema

```sql
CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    version_num INTEGER NOT NULL,
    prompt TEXT NOT NULL,
    model TEXT,
    temperature REAL DEFAULT 0.7,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT DEFAULT 'manual',
    commit_message TEXT,
    is_active INTEGER DEFAULT 0,
    canary_percentage INTEGER DEFAULT 0,
    performance_score REAL DEFAULT 0.0,
    UNIQUE(agent_id, version_num)
);
```

---

## Funktionsweise des Canary-Routings

Beim Dispatch eines Agenten ruft der Kern-Dispatcher (`core_dispatcher.py`) die Funktion `prompt_registry.get_effective_prompt(agent_id, task_id)` auf:

1. **Canary-Prüfung:** Existiert für diesen Agenten eine Version mit `canary_percentage > 0`?
2. **Deterministisches Task-Routing:**
   $$\text{hash\_val} = \text{MD5}(\text{task\_id}) \pmod{100}$$
   Ist $\text{hash\_val} < \text{canary\_percentage}$, wird die Canary-Version geliefert. Dadurch erhält ein einzelner Task bei Wiederholungen stets dieselbe Version.
3. **Fallback:** Andernfalls wird die primär aktive Version (`is_active = 1`) genutzt.

---

## REST-API Schnittstellen

### 1. Versionen auflisten
```http
GET /api/operations/prompts/{agent_id}/versions
```
Liefert die Versionshistorie, aktive Flags, Canary-Prozentsätze und Längen.

### 2. Neue Version anlegen
```http
POST /api/operations/prompts/{agent_id}/versions
Content-Type: application/json

{
  "prompt": "Du agierst als...",
  "commit_message": "Präzisere Handlungsanweisungen für Risikoanalysen",
  "created_by": "robert_admin",
  "make_active": false,
  "canary_percentage": 10
}
```

### 3. Diff zwischen zwei Versionen anzeigen
```http
GET /api/operations/prompts/{agent_id}/diff?v1=1&v2=2
```
Liefert ein Unified Diff zur visuellen Inspektion im Dashboard oder Terminal.

### 4. 1-Click Rollback durchführen
```http
POST /api/operations/prompts/{agent_id}/rollback
Content-Type: application/json

{
  "target_version": 1,
  "reason": "Unerwartete Halluzinationen in v2 festgestellt"
}
```

### 5. Canary befördern (Promote to Stable)
```http
POST /api/operations/prompts/{agent_id}/promote
Content-Type: application/json

{
  "version": 2
}
```
Deaktiviert das Canary-Splitting und setzt v2 auf 100 % Traffic (`is_active = 1`).

---

## Zusammenspiel mit anderen Modulen
- `backend/prompt_optimizer.py`: Der automatische Prompt-Optimierer (DSPy-Prinzip) legt optimierte Varianten direkt als neue Version in der Registry an, anstatt Dateien zu manipulieren.
- `backend/eval_regression_runner.py`: Vor der Beförderung einer Canary-Version kann die Gold-Standard-Testsuite gegen beide Versionen ausgeführt werden.
- `core_dispatcher.py`: Holt den effektiven Prompt und übermittelt Version & Canary-Flag an den OpenTelemetry Tracer.
