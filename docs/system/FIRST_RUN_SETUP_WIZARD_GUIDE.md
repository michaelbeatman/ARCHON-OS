# First-Run Setup Wizard & Onboarding Guide (EN / DE)

> **Milestone 30 — Interactive First-Run Web Setup Wizard & CLI Bootstrap**
> Modules: `backend/onboarding_wizard.py` · `archon/routers/onboarding.py` · `static/js/onboarding_wizard.js` · `./install.sh` · `setup.ps1`

---

## Part I — English Guide

### 1. Overview & Two-Layer Onboarding Architecture

Archon OS provides a two-stage onboarding flow designed for both first-time self-hosters and power users:

1. **Layer 1 — Host CLI Installer (`./install.sh` on Linux/macOS, `setup.bat` / `setup.ps1` on Windows):**
   - Verifies or installs core host foundations (**Docker Engine / Docker Desktop**, **Obsidian Desktop + Vault directory**, local **Ollama / LM Studio** detection).
   - Generates unique per-instance cryptographic secrets (`OMNIROUTE_INITIAL_PASSWORD`, `HERMES_SESSION_TOKEN`, `N8N_USER_MANAGEMENT_JWT_SECRET`, etc.) in `.env`.
   - Pulls/builds multi-arch (`amd64` / `arm64`) containers, launches the stack on localhost (`127.0.0.1:8501` by default), and verifies health.
2. **Layer 2 — Interactive Web First-Run Setup Wizard (`onboarding_wizard.js` + `/api/onboarding/*`):**
   - Automatically opens in the browser on the first visit to `http://localhost:8501` when `onboarding.completed` and `onboarding.dismissed` are both `false`.
   - Automatically **suppressed** when Read-Only Live-Demo Mode is active (`ARCHON_DEMO_MODE=true|1|yes`).
   - Guides administrators through 4 structured steps with live provider latency checks, hardened `0600` `.env` persistence, and specialist domain activation.

---

### 2. CLI Bootstrap Reference (`./install.sh` & `setup.ps1`)

#### Linux & macOS (`./install.sh`)

```bash
chmod +x install.sh
./install.sh          # Interactive guided setup
./install.sh --yes    # Non-interactive bootstrap with .env.example defaults
```

#### Windows (`setup.bat` / `setup.ps1`)

- **Interactive GUI/Console Launch:** Double-click `setup.bat` (or right-click `setup.ps1` → *Run with PowerShell*).
- **Unattended / CI Mode:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -NonInteractive
```

---

### 3. The 4-Step Web First-Run Setup Wizard

#### Step 1: Company & Primary Tenant Profile
Configures master entity data used across corporate letterheads, invoices, contracts, and AI Boardroom syntheses:
- **Fields:** `company_name` (required), `legal_form`, `address`, `tax_id`, `vat_id`, `iban`, `bic`, `currency` (`EUR`, `USD`, `GBP`, `CHF`), and workspace/directive `language` (`en` or `de`).
- **Persistence:** Atomically saved to `data/tenants/primary/company_profile.json`, `settings.json`, `agent_workspace/settings.json`, and `ARCHON_LANGUAGE` in `.env`.

#### Step 2: AI Providers, Live Connectivity Probe & Zero-Egress Routing
Configures cloud and local inference backends:
- **Supported Providers (8):**
  - **HTTPS Cloud:** `openrouter`, `openai`, `anthropic`, `gemini`, `groq`
  - **Local / Self-Hosted Router:** `ollama` (`http://localhost:11434`), `lm_studio` (`http://localhost:1234/v1`), `omniroute` (`http://localhost:20128/v1`)
- **SSRF-Safe Live Probe ("Test Connection"):**
  - Cloud providers enforce `https://` strictly against their canonical API hostnames (`openrouter.ai`, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `api.groq.com`).
  - Local providers allow only loopback/container-host targets (`localhost`, `127.0.0.1`, `::1`, `host.docker.internal`, or dedicated service hostname). Private RFC1918 subnets, cloud metadata endpoints (`169.254.169.254`), URL-embedded credentials, redirects, and sensitive ports (`2375`, `22`, etc.) are blocked before any socket opens.
  - Displays a live badge with round-trip latency (`ms`) and detected model count (`5s` timeout).
- **Secret Hygiene:** API keys are written via `utils.secret_files.write_secret_file` with strict `0600` file permissions. Blank or masked (`••••••••`) inputs preserve previously stored keys untouched.
- **Zero-Egress Toggle (`privacy.zero_egress`):** Keeps sensitive financial, legal, HR, and CRM data strictly on local models (`Ollama` / `LM Studio`).

#### Step 3: Channels & Obsidian Second Brain Vault
Configures optional external bridges:
- **Obsidian Vault:** Sets `ARCHON_OBSIDIAN_DIR` and `obsidian.vault_path` (default `./obsidian_vault`).
- **Email (IMAP / SMTP):** Stores host, port, and username metadata in `settings.json` while keeping `SMTP_PASSWORD` strictly in `.env` (`0600`).
- **Telegram Executive Bridge:** Stores `TELEGRAM_BOT_TOKEN` in `.env` (`0600`), `TELEGRAM_CHAT_ID`, and supports an optional live `getMe` verification check.

#### Step 4: Specialist Domain Activation (8 Domains / 70 Specialists)
Lets you enable all 8 specialist departments (70 specialists) or focus on selected domains:
1. Strategy, Leadership & Executive Planning (12)
2. Commerce, Procurement & Supply Chain (7)
3. Legal, Tax, Finance & Compliance (11)
4. Real Estate, Architecture & Construction (7)
5. Brand, Creative, Media & Content (8)
6. Sales, CRM, Marketing & Growth (11)
7. Engineering, Cloud, Security & Data (8)
8. Medicine, Biotech, Science & R&D (6)

Upon completion, active domain flags are persisted and `sync_soul_modes.apply_soul_mode(mode="compact", lang=language)` is triggered safely in a non-blocking `try` guard.

---

### 4. REST API Endpoints & Security Model

All endpoints are mounted via `archon/routers/onboarding.py` with router-level `Depends(forbid_viewer_writes)` and explicit admin verification on all mutating endpoints when Multi-User Authentication is enabled.

| Method | Endpoint | Auth / RBAC | Description |
|---|---|---|---|
| `GET` | `/api/onboarding/status` | Authenticated / Single-User | Returns `auto_open`, `language`, `zero_egress`, boolean-only `detected_providers` (**never** raw secret values), sanitized `channels`, and the 8 specialist domains summary. |
| `POST` | `/api/onboarding/test-provider` | Admin required (403 for `viewer` / non-admin) | Runs SSRF-validated 5s models/tags probe (`{provider, api_key, base_url}`) → returns `{ok, provider, latency_ms, models_detected, detail}`. |
| `POST` | `/api/onboarding/complete` | Admin required (403 for `viewer` / non-admin) | Validates all 4 steps up-front, atomically writes tenant profile, `.env` (`0600`), and both `settings.json` files, marks `onboarding.completed = True`. |
| `POST` | `/api/onboarding/skip` | Admin required (403 for `viewer` / non-admin) | Sets `onboarding.dismissed = True` so power users are not prompted again on reload. |

#### Re-Opening the Wizard Anytime
Administrators can re-open the wizard from any view or browser console via:

```javascript
window.openArchonSetupWizard();
// Jump directly to a specific step (0..3):
window.openArchonSetupWizard({ step: 1 });
```

---
---

## Teil II — Deutsches Handbuch

### 1. Überblick & Zweistufige Onboarding-Architektur

Archon OS kombiniert einen System-Installer für den Host mit einem interaktiven Browser-Assistenten für den Erststart:

1. **Stufe 1 — CLI-Installer (`./install.sh` unter Linux/macOS, `setup.bat` / `setup.ps1` unter Windows):**
   - Prüft bzw. installiert die Host-Grundlagen (**Docker Engine / Docker Desktop**, **Obsidian Desktop + Vault-Ordner**, Erkennung lokaler **Ollama / LM Studio**-Instanzen).
   - Erzeugt instanzspezifische Zufalls-Secrets in `.env` und startet den Container-Stack standardmäßig lokal gebunden (`127.0.0.1:8501`).
2. **Stufe 2 — Interaktiver Web-Einrichtungsassistent (`onboarding_wizard.js` + `/api/onboarding/*`):**
   - Öffnet sich beim ersten Aufruf im Browser automatisch, solange weder `onboarding.completed` noch `onboarding.dismissed` gesetzt ist.
   - Wird im schreibgeschützten Live-Demo-Modus (`ARCHON_DEMO_MODE=true|1|yes`) **automatisch unterdrückt**.
   - Unterstützt durchgehend Deutsch (`de`) und Englisch (`en`) mit automatischer Spracherkennung (`localStorage.getItem('archon_lang') || navigator.language`) sowie direktem Sprachumschalter im Kopfbereich.

---

### 2. CLI-Installer Referenz (`./install.sh` & `setup.ps1`)

#### Linux & macOS (`./install.sh`)

```bash
chmod +x install.sh
./install.sh          # Geführte interaktive Installation
./install.sh --yes    # Unbeaufsichtigter Durchlauf mit Standardwerten
```

#### Windows (`setup.bat` / `setup.ps1`)

- **Interaktiver Start:** Doppelklick auf `setup.bat` (oder Rechtsklick auf `setup.ps1` → *Mit PowerShell ausführen*).
- **Unbeaufsichtigter Modus:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -NonInteractive
```

---

### 3. Die 4 Schritte des Web-Einrichtungsassistenten

1. **Unternehmen & Mandantenprofil:**
   - Erfasst `company_name` (Pflichtfeld), `legal_form`, `address`, `tax_id`, `vat_id`, `iban`, `bic`, `currency` (`EUR`, `USD`, `GBP`, `CHF`) sowie die Systemsprache (`de` | `en`).
   - Atomare Speicherung in `data/tenants/primary/company_profile.json`, `settings.json` und `agent_workspace/settings.json`.
2. **KI-Provider, Live-Latenztest & Zero-Egress:**
   - Unterstützt `openrouter`, `openai`, `anthropic`, `gemini`, `groq`, `ollama`, `lm_studio` und `omniroute`.
   - **SSRF-geschützter Verbindungstest („Verbindung testen"):** Prüft Erreichbarkeit, Antwortzeit in Millisekunden (`latency_ms`) und Anzahl verfügbarer Modelle (`5s` Timeout). Cloud-Provider erlauben ausschließlich `https://` gegen ihre offiziellen API-Domains; lokale Provider erlauben ausschließlich Loopback bzw. `host.docker.internal`.
   - **Sichere Secret-Ablage:** API-Schlüssel werden atomar mit Dateirechten `0600` in `.env` geschrieben; bestehende Schlüssel bleiben bei leeren oder maskierten Eingabefeldern unverändert erhalten.
   - **Zero-Egress (`privacy.zero_egress`):** Erzwingt lokale Verarbeitung vertraulicher Finanz-, Vertrags-, HR- und CRM-Daten.
3. **Kanäle & Obsidian-Vault:**
   - Konfiguriert den Pfad zum Obsidian-Vault (`./obsidian_vault`), IMAP/SMTP-Zugangsdaten (Passwort ausschließlich in `.env` mit `0600`) sowie Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` inkl. optionalem `getMe`-Test).
4. **Spezialisten-Domänen (8 Domänen / 70 Spezialisten):**
   - Aktiviert alle oder ausgewählte Fachbereiche und synchronisiert fehlertolerant die kompakten Direktiven über `sync_soul_modes.apply_soul_mode(mode="compact", lang=language)`.

---

### 4. API-Endpunkte & Rollenberechtigungen (RBAC)

- `GET /api/onboarding/status`: Liefert Einrichtungsstatus, Sprache, Domänenübersicht und boolesche Provider-Erkennung (`detected_providers` enthält **niemals** Klartext-Secrets).
- `POST /api/onboarding/test-provider`: Führt den Live-Verbindungstest durch (erfordert Admin-Rolle im Multi-User-Modus; Rolle `viewer` erhält `403 Forbidden`).
- `POST /api/onboarding/complete`: Speichert alle 4 Schritte nach vollständiger Vorab-Validierung atomar und setzt `onboarding.completed = True`.
- `POST /api/onboarding/skip`: Setzt `onboarding.dismissed = True`, sodass der Assistent beim Neuladen nicht erneut automatisch eingeblendet wird.
- **Erneutes Öffnen jederzeit:** `window.openArchonSetupWizard()` in der Oberfläche oder Browser-Konsole aufrufen.
