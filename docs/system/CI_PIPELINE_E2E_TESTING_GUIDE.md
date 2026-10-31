# CI-Pipeline & End-to-End Lifecycle Testsuite

## Überblick
Archon OS verfügt über eine lückenlose Qualitäts- und Regressionspipeline, die sowohl **lokal** vor jedem Commit/Push (`scripts/run_ci_suite.py`) als auch **automatisiert in GitHub Actions** (`.github/workflows/ci.yml`) ausgeführt werden kann.

Sie prüft alle Ebenen des Systems: von der Konfigurationsvalidität und dem Schutz sensibler Zugangsdaten bis hin zum vollständigen End-to-End Lebenszyklus (Telegram -> Triage-Inbox -> Task -> Delegation -> Fan-in-Synthese -> Robert-Freigabe).

---

## 1. Die 6 Qualitätstore (Quality Gates)

```
[Lokaler Entwickler / GitHub Push]
                 │
                 ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Gate 1: Pre-Flight Config Validator                       │
 │  Prüft settings.json, agent_profiles.json, teams.json       │
 └──────────────────────────────┬──────────────────────────────┘
                                │ (Pass)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Gate 2: Secrets- & Zero-Leak Audit                         │
 │  Scannt alle 5.400+ Dateien auf Keys, Token & Hashes        │
 └──────────────────────────────┬──────────────────────────────┘
                                │ (Pass)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Gate 3: Security-Guard Unit-Tests                          │
 │  25 Prompt-Injection-Muster, Delimiter-Sanitization         │
 └──────────────────────────────┬──────────────────────────────┘
                                │ (Pass)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Gate 4: Router Unit-Tests                                  │
 │  Verifiziert Provider- & Modell-Routing-Entscheidungen      │
 └──────────────────────────────┬──────────────────────────────┘
                                │ (Pass)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Gate 5: End-to-End Lifecycle & MCP                         │
 │  Vollständiger Governance-Durchlauf + Prompt-Registry/MCP   │
 └──────────────────────────────┬──────────────────────────────┘
                                │ (Pass)
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │  Gate 6: Docker Compose Validierung                         │
 │  Syntax-, Volume- und Ressourcenlimit-Prüfung               │
 └─────────────────────────────────────────────────────────────┘
```

---

## 2. Der E2E Lifecycle-Test (`tests/test_e2e_lifecycle.py`)

Die End-to-End Suite bildet den gesamten operativen Ablauf eines realen Geschäftsauftrags ab:

1. **`test_01_telegram_to_inbox_triage`:** Eingehende Telegram-Nachricht landet als strukturierte JSON-Datei im Triage-Posteingang.
2. **`test_02_inbox_to_kanban_task`:** Automatische Extraktion und Anlage einer Aufgabe im Operations Kanban (`status = 'ready'`, Priorität 3).
3. **`test_03_delegation_and_subtasking`:** Robert zerlegt die Aufgabe und delegiert an spezialisierte Fachagenten (`status = 'in_progress'`).
4. **`test_04_fanin_synthesis_and_marker`:** Lisa bündelt Teilberichte und setzt den Pflicht-Marker `SYNTHESE-BEREIT`.
5. **`test_05_robert_review_and_freigabe`:** Roberts 4-Augen-Kontrakt: Nur wenn Zeile 1 mit `FREIGABE` beginnt, wechselt der Status auf `done`.
6. **`test_06_prompt_registry_versioning_and_rollback`:** Erzeugt Prompt-Versionen, berechnet Unified Diff, setzt Canary-Traffic und rollt bei Bedarf sofort auf v1 zurück.
7. **`test_07_metrics_collector_prometheus`:** Prüft standardkonforme Generierung aller Prometheus-Metriken.
8. **`test_08_mcp_server_protocol_execution`:** Prüft Werkzeugkatalog und synchrone Ausführung des Archon MCP-Servers.

---

## 3. Lokale Ausführung

Die gesamte Pipeline kann jederzeit lokal mit einem einzigen Befehl gestartet werden:

```bash
# Alle 6 Tore nacheinander ausführen
python scripts/run_ci_suite.py

# Optional: Bei erstem Fehler sofort abbrechen
python scripts/run_ci_suite.py --fail-fast
```

---

## 4. GitHub Actions CI Workflow

In `.github/workflows/ci.yml` ist der automatisierte Ablauf für Pull Requests und Pushes auf `main` / `master` konfiguriert:
- Matrix-Build auf Python 3.11
- Ausführung aller Teststufen in getrennten Jobs mit klaren Statusmeldungen
- Blockiert Merges bei Sicherheitsfunden, Regressionsbrüchen oder fehlerhafter Docker-Konfiguration
