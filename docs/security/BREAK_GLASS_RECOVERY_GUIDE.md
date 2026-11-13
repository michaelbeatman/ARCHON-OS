# Verschlüsselter Notfallzugang (Break-Glass Protocol)

Dieses Dokument beschreibt das Notfall- und Katastrophen-Verfahren (Disaster Recovery) von Archon OS (`scripts/break_glass_recovery.py`).

---

## 1. Zweck & Szenario

Fällt der Hauptbetreiber unerwartet aus (Krankheit, Nichterreichbarkeit) oder sind Container-Services und Web-Frontends nach einem Systemcrash nicht mehr erreichbar, muss ein bevollmächtigter Notfall-Operator oder Vertrauensperson in der Lage sein:
1. Alle kritischen Konfigurationen, API-Keys (`.env`) und Datenbank-Passwörter einzusehen.
2. Das System auf Kommandozeilenebene ohne laufende Docker-Container vollständig wiederherzustellen.

Gleichzeitig dürfen diese vertraulichen Daten im Normalbetrieb nicht im Klartext auf der Festplatte liegen.

---

## 2. Kryptografisches Design (Zero Dependencies)

Das Break-Glass-Verfahren nutzt ausschließlich Module der Python 3 Standardbibliothek (`hashlib`, `hmac`, `secrets`, `os`, `zipfile`). Es benötigt weder OpenSSL-Binaries noch externe Third-Party-Pakete wie `cryptography`.

### Sicherheitsmerkmale:
- **Schlüsselableitung:** PBKDF2-HMAC-SHA256 mit 200.000 Runden und kryptografisch sicherem 16-Byte-Salt.
- **Verschlüsselung:** Deterministic Keystream Cipher (CTR-Modus über HMAC-SHA256) gegen die archivierten Zieldateien.
- **Integritätsschutz (Authenticated Encryption):** Authentifizierungs-Tag über den gesamten Ciphertext verhindert Manipulationen.
- **Notfall-Masterkey:** Ein 256-Bit Hex-Schlüssel (64 Zeichen), der bei der Initialisierung generiert und im Notfall-Kit hinterlegt wird.

---

## 3. Dateistruktur des Notfall-Tresors

- **Tresor-Datei:** `data/backups/break_glass_vault.enc` (verschlüsseltes Archiv).
  - Enthält: `.env`, `config/`, alle SQLite-Datenbanken (`agent_os.db`, `agentic_memory.db`, `kanban.db`, `state.db`).
- **Anleitung für den Notfall:** `data/backups/BREAK_GLASS_RECOVERY_KIT.md` (Notfall-Handbuch zum Ausdrucken und Verwahren im physischen Panzerschrank).

---

## 4. Durchführung der Notfall-Wiederherstellung

Im Notfall benötigt der Operator lediglich ein Terminal auf dem Host-System mit installiertem Python 3.

### Schritt 1: Status des Tresors prüfen
```bash
python scripts/break_glass_recovery.py --status
```

### Schritt 2: Entschlüsselung und Entpacken
```bash
python scripts/break_glass_recovery.py --restore --key <DEIN_64_STELLIGER_NOTFALLSCHLÜSSEL>
```
*Optionales Zielverzeichnis angeben:*
```bash
python scripts/break_glass_recovery.py --restore --key <KEY> --target-dir ./recovered_system
```

Das Skript prüft das HMAC-Integritäts-Tag. Ist der Schlüssel korrekt, werden alle geschützten Konfigurationen und Datenbanken unmittelbar extrahiert.

### Schritt 3: Aktualisierung des Notfall-Tresors
Nach wesentlichen Konfigurationsänderungen oder API-Key-Rotationen:
```bash
python scripts/break_glass_recovery.py --init
```
*Hinweis:* Nach einer Neu-Initialisierung muss der neue Schlüssel ausgedruckt und die alte Notfallanleitung vernichtet werden.

---

## 5. Web-Interface Integration

In den Systemeinstellungen (**System Control Center** -> **Abschnitt 15: Notfallzugang & Break-Glass**) kann der Operator:
- Das Datum der letzten Tresor-Aktualisierung einsehen.
- Die Integrität des Archivs prüfen.
- Bei Bedarf einen neuen Notfall-Tresor mit einem Klick erzeugen.
