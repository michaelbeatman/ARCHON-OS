## VERFÜGBARE SYSTEM-COMMANDS

### 1. E-Mail-Sync ausführen
Wenn der Nutzer "Starte E-Mail-Sync" oder "Gleiche Mails ab" sagt:
Führe im Terminal aus: `python scripts/archon_crm_mcp.py --get-contacts` und `python scripts/archon_crm_mcp.py --fetch-mails` und verarbeite die Mails gemäß den festgelegten Matching-Regeln.

### 2. LinkedIn-Archiv importieren
Wenn der Nutzer "Importiere LinkedIn Archiv" sagt:
Führe aus: `python scripts/import_linkedin_archive.py <PFAD_ZUR_CONNECTIONS_CSV>`

### 3. Telegram-Sessions synchronisieren & prüfen
Wenn der Nutzer "Synchronisiere Telegram", "Telegram reparieren" oder "Telegram prüfen" sagt:
Führe im Terminal aus: `python scripts/sync_telegram_sessions.py --fix` (bzw. `--check` für reine Diagnose) und stelle sicher, dass Archon OS auf die Profil-Datenbank zugreift.

### 4. AI Boardroom-Debatte starten
Wenn der Nutzer oder ein Agent ("Robert", "Micha", "Default") eine komplexe Entscheidung, Risikoabwägung oder ein Brainstorming untersuchen soll:
Führe im Terminal aus: `python scripts/trigger_boardroom_debate.py --task "<FRAGESTELLUNG>" --framework "<FRAMEWORK>" --budget "<free|cheap|balanced|premium>"`
Das Ergebnis wird automatisch im Obsidian Vault und in der Decision-Engine-Historie (`/api/boardroom/history`) archiviert.
