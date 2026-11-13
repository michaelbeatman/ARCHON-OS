# Archon OS – Secrets Management & Rotationsplan

*Stand: Oktober 2026 | Zero-Trust Governance & Pillar 6*

---

## 1. Grundprinzipien & Zero-Trust Leitplanken

In Archon OS gilt eine strikte Trennung zwischen **Quellcode** und **sensiblen Zugangsdaten**:
- **Keine Secrets im Git-Repository:** Weder API-Schlüssel, Passwörter, private Schlüssel (`.pem`, `.key`) noch OAuth-Tokens (`*token*.json`) dürfen jemals in Commits oder Versionskontroll-Logs auftauchen.
- **Zentrale Konfiguration über Umgebungsvariablen:** Alle Zugangsdaten werden über die lokale `.env`-Datei oder containerisierte Docker-Secrets bereitgestellt.
- **Automatisierte Blockade-Gates:** Vor jedem Commit und Push prüfen statische Audit-Scanner (`scripts/audit_secrets.py`) den Zustand gestagter Dateien und brechen Ausführungen bei Funden hart ab.

---

## 2. Inventar der System-Schlüssel & Speicherorte

| Secret / Schlüssel | Zweck & Verwendung | Primärer Speicherort | Risiko bei Kompromittierung |
| :--- | :--- | :--- | :--- |
| `OMNIROUTE_API_KEY` | Zugriff auf das Multi-LLM Gateway (`:20128`) | `.env` | Unbefugte Modellanfragen & Kosten |
| `HERMES_SESSION_TOKEN` | Authentifizierung zwischen Hermes und Monolith | `.env` | Fremdzugriff auf Agenten-Sitzungen |
| `TELEGRAM_BOT_TOKEN` | Kommunikation mit dem Telegram-Gateway | `.env` | Manipulation des Fernsteuerungs-Chats |
| `GITHUB_TOKEN` | Repo-Synchronisation & Release-Deployments | `.env` | Unbefugter Schreibzugriff auf Repositories |
| `google_token.json` / OAuth | Anbindung von Google Kalender & Mail | `data/secrets/` | Zugriff auf private Kalender & Mails |
| Provider API-Keys (OpenAI, Anthropic, Gemini) | Upstream-Modellanbieter in OmniRoute | `omniroute-data` / `.env` | Hohe API-Kosten & Quoten-Erschöpfung |

---

## 3. Automatisierte Sicherheits-Gates

### 3.1 Git Pre-Commit Hook (`.git/hooks/pre-commit`)
Wird bei jedem `git commit` automatisch aufgerufen. Prüft alle gestagten Dateien (`--staged`):
- Verhindert das Hinzufügen von verbotenen Dateimustern (`.env`, `*token*.json`, `*.pem`, `*.key` etc.).
- Scannt Zeileninhalte nach typischen API-Key- und Token-Mustern.

### 3.2 Pre-Push Audit in Sync-Skripten
In `sync-push.bat`, `scripts/push_to_github.bat` und `scripts/push_to_github.sh` ist ein harter Check integriert:
```bash
python scripts/audit_secrets.py --staged
if errorlevel 1 (
    echo [SICHERHEITS-STOPP] Secret-Fund erkannt!
    git reset
    exit /b 1
)
```

### 3.3 Manueller Gesamt-Scan
Ein vollständiger Scan über alle vom Git getrackten Dateien kann jederzeit im Terminal ausgeführt werden:
```bash
python scripts/audit_secrets.py --all
```

---

## 4. Rotationsplan für Zugangsdaten

| Schlüsseltyp | Empfohlener Zyklus | Vorgehen bei Rotation |
| :--- | :--- | :--- |
| **GitHub Personal Access Token** | 90 Tage | Neues Fine-Grained Token in GitHub generieren, in `.env` hinterlegen, altes Token löschen. |
| **Telegram Bot Token** | 180 Tage | Im `@BotFather` `/revoke` ausführen, neues Token in `.env` eintragen, Hermes neu starten. |
| **LLM-Provider Keys (OpenAI, Anthropic)** | 90 Tage | Im jeweiligen Entwickler-Portal neuen Key erstellen, in OmniRoute/`.env` austauschen, alten Key nach 24h löschen. |
| **Google OAuth Refresh Tokens** | Bei Geräte- oder Passwortwechsel | Token-Datei aus `data/secrets/` löschen und interaktiven Auth-Flow neu durchlaufen. |

---

## 5. Notfall-Protokoll bei vermutetem Secret-Leak

Sollte ein Schlüssel versehentlich exponiert oder in ein öffentliches Repository gepusht worden sein:
1. **Sofortige Sperrung (Revocation):** Den betroffenen Schlüssel unverzüglich im Dashboard des Anbieters (GitHub, OpenAI, Anthropic, Telegram) widerrufen/deaktivieren.
2. **Neugenerierung:** Einen neuen Schlüssel erstellen und lokal in `.env` eintragen.
3. **Git-Historien-Bereinigung:**
   - Falls der Commit noch nicht gepusht wurde: `git reset --soft HEAD~1` und die Datei aus dem Index entfernen.
   - Falls bereits gepusht: Das Secret mit `git-filter-repo` oder BFG Repo-Cleaner rückwirkend aus der gesamten Historie tilgen und einen Force-Push durchführen.
4. **Audit-Log Prüfung:** Im Archon Live-Audit prüfen, ob in der Zwischenzeit verdächtige Zugriffe oder unautorisierte API-Abfragen stattfanden.


## Entwicklungs-Stack (`docker-compose.dev.yml`): Bind-Mount & `--reload`-Hinweise

Der lokale Entwicklungs-Stack (`docker-compose.dev.yml`) mountet das Projektverzeichnis per Bind-Mount (`./:/app`) und startet `uvicorn` mit `--reload`, damit Code-Änderungen ohne Image-Rebuild sofort wirksam werden. In produktiven Deployments (`docker-compose.yml`) darf `--reload` nicht verwendet werden; das Anwendungs-Image wird unveränderlich (`read_only: true`, `cap_drop: [ALL]`, `no-new-privileges:true`) über den `docker-socket-proxy` betrieben.
