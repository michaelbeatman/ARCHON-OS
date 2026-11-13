---
name: telegram-session-sync
description: Diagnostiziert, synchronisiert und repariert Telegram-Bot-Sitzungen zwischen Handy, Hermes-Gateway und Archon OS UI.
---

# Telegram Session Sync & Repair Skill

Dieses Skill diagnostiziert, synchronisiert und entstört die Telegram-Kommunikation zwischen dem Telegram-Bot (@Beatman_bot / Profil `telegram_bot`), dem Hermes Gateway-Daemon und der Archon OS Web-Benutzeroberfläche.

## Wann dieses Skill verwendet wird
- Wenn Telegram-Nachrichten auf dem Smartphone ankommen, aber im Archon OS Chat/Agenten-Profil nicht sichtbar sind.
- Wenn der Eindruck von „2 verschiedenen Sessions“ oder Session-Splitting entsteht.
- Wenn das Hermes Telegram-Gateway auf `fatal` oder `disconnected` steht.
- Wenn neue Nachrichten im UI nicht synchronisiert werden oder phantom-leere Sprechblasen auftreten.

---

## Architektur & Hintergrund

1. **Multi-Profile-Datenbank-Architektur von Hermes:**
   - Web- und Master-Chat-Sessions liegen standardmäßig in der Root-Datenbank: `~/.hermes/state.db` (im Container gemountet unter `/opt/data/state.db`).
   - Das autonome Profil `telegram_bot` besitzt eine **eigene, isolierte SQLite-Datenbank**:
     `~/.hermes/profiles/telegram_bot/state.db` (bzw. `/opt/data/profiles/telegram_bot/state.db`).
   - Alle echten Telegram-Nachrichten (über Long-Polling via Hermes-Agent) landen primär in dieser Profil-Datenbank.

2. **Gefahr von Session-Splitting:**
   - Wenn im Archon OS Web-UI eine Nachricht an `telegram_bot` geschickt wurde, erstellte das Backend früher eine gleichnamige Session in der Root-Datenbank.
   - Dadurch entstanden zwei Instanzen derselben Session-ID. Suchte das Backend in der Root-DB zuerst, wurden die echten Handy-Nachrichten der Profil-DB maskiert.
   - **Lösung:** `_find_db_for_session()` in `main.py` priorisiert immer die Datenbank mit der höheren Nachrichtenanzahl und neuester Aktivität.

---

## Befehle & Werkzeuge

### 1. Diagnose & Prüfung ausführen
```bash
python scripts/sync_telegram_sessions.py --check
```
Prüft:
- Status des Telegram-Gateways (`connected`, `fatal`, `unknown`).
- Anzahl der Sessions in Root-DB und `telegram_bot`-Profil-DB.
- Erkennt doppelte Session-IDs (Splits).
- Listet die aktivste Telegram-Session mit den letzten Nachrichten auf.

### 2. Automatische Reparatur & Bereinigung
```bash
python scripts/sync_telegram_sessions.py --fix
```
- Löscht Phantom-Kopien aus der Root-DB, wenn in der Profil-DB mehr oder identische Nachrichten vorliegen.
- Stellt sicher, dass Archon OS transparent auf die Master-Profil-Datenbank zugreift.

### 3. Gateway-Neustart (falls Telegram disconnected ist)
```bash
docker restart hermes-agent
```
Startet den Polling-Dienst neu und lädt frische Tokens aus der Konfiguration.

---

## Checkliste bei Störungen

| Symptom | Ursache | Maßnahme |
| :--- | :--- | :--- |
| **Nachrichten auf Handy da, im Archon UI fehlen sie** | Archon las Root-DB statt `telegram_bot/state.db` | `python scripts/sync_telegram_sessions.py --fix` ausführen und Browser-Tab neu laden (`Strg + F5`). |
| **Bot reagiert auf Handy nicht** | Gateway gestoppt oder Token ungültig | `cat ~/.hermes/gateway_state.json` prüfen. Falls Status `fatal`: Token in `docker-compose.hermes.yml` und `~/.hermes/profiles/telegram_bot/.env` prüfen, dann `docker restart hermes-agent`. |
| **Session-Nummer im Chat weicht ab** | LLM-Halluzination bei interner Tool-Abfrage | Die wahre Session-ID per Skript (`--check`) auslesen und im Archon Session-Dropdown auswählen. |
