# 🧠 ANTIGRAVITY BRAIN & SYSTEM HANDOFF (UBUNTU WORKSTATION)

> **Zweck:** Dieses Dokument dient als vollständiger Wissenstransfer ("Brain Handoff") für Antigravity auf deiner neuen Ubuntu 24.04 Workstation. Es enthält alle Systemprinzipien, Arbeitsweisen, Nutzerpräferenzen, Lösungsarchitekturen und den Skill-Katalog.

---

## 👤 1. Nutzer-Profil & Arbeitsweise (Wer ich bin & wie wir arbeiten)

* **Rolle & Vision:** Architekt und Erbauer eines hochgradig modularen, autonomen Agentic Operating Systems (Archon OS).
* **Fokus:** Echte, funktionierende Multi-Agenten-Systeme (Hermes, Paperclip, n8n, PocketBase, Custom Sub-Agents) mit praxistauglichen UIs und lokaler Inferenz.
* **UI & UX Standards:**
  * **100% Viewport-Höhe (`100vh`):** Keine verschwendeten Header-Leisten oder Titlebars. Jede Ansicht (Mission Control, Master Chat, Agentenprofile, AI Mastermind, Automatisierung, CRM) nutzt die volle Bildschirmhöhe.
  * **CSS Live Studio:** Schnelles Live-Tuning von UI-Farben und Tailwind-Styles via `Alt + S` und Paletten-Button unten links in der Seitenleiste.
  * **Saubere Icons & Emojis:** Keine störenden Standard-Emojis in Menütiteln, wenn saubere Lucide-Icons vorhanden sind.
  * **Konkrete Fakten statt Phrasen:** Immer direkte Fakten, exakte Pfade, Statusmeldungen und funktionierenden Code liefern.

---

## ✍️ 2. Kommunikations- & Schreibregeln (Avoid-AI-Writing)

Für alle Antworten von Antigravity gelten strenge Regeln:

1. **Natürliche, menschliche Stimme:** Aktive Sprache, abwechslungsreiche Satzstrukturen, direkt auf den Punkt.
2. **Verbotene AI-Buzzwords (Tier 1):**
   * *Niemals verwenden:* delve, leverage, robust, comprehensive, cutting-edge, paradigm, tapestry, realm, nestled, vibrant, thriving, at its core, serves as, boasts.
   * *Verbotene Füllwörter / Übergänge:* moreover, furthermore, additionally, notably, in conclusion, it is important to note that.
3. **Keine Chatbot-Floskeln:** Keine unterwürfigen Einleitungen wie *"Großartige Frage!"*, *"Sicherlich!"*, *"Ich hoffe, das hilft!"*.

---

## 🏛️ 3. Die 7 Kern-Säulen von Archon OS / Antigravity 2.0

1. **Kernel & Scheduling:**
   * Persistenter Daemon, asynchroner Asyncio Event-Loop, Watchdog-Loop alle 30 Sekunden für hängende Tasks.
2. **Process Model:**
   * Jeder autonome Agent ist ein isolierter OS-Prozess mit deklarativem Manifest (`manifests/`, `agent_profiles.json`).
   * Task-Zustände: `pending` -> `in_progress` -> `completed` / `failed` mit automatischem Crash-Recovery.
3. **Device Driver (MCP Server Ecosystem):**
   * Dynamische Anbindung von Tools und APIs über das Model Context Protocol (`scripts/archon_crm_mcp.py`, `mcp__*`).
4. **Filesystem & Memory Layer:**
   * SQLite im **WAL-Modus** (`agent_os.db`, `agentic_memory.db`) für blockierungsfreie Schreibzugriffe.
   * Standard-Tabellen: `tasks`, `conversations`, `learnings`, `kv_store`, `user_profile`.
5. **Hardware Abstraction & Multi-Provider Routing:**
   * Dynamisches Routing über `core_dispatcher.py` (Lokales Ollama via GPU, OpenRouter, Anthropic, Groq).
6. **Governance & Zero-Trust Security:**
   * RBAC, Human-in-the-Loop (HITL) für destruktive Befehle, manipulationssichere Audit-Logs.
7. **Selbst-Evolution (Runtime Skills):**
   * Dynamisches Laden und Registrieren neuer Fähigkeiten im Verzeichnis `skills/`.

---

## 🎛️ 4. Die 427 Skills-Bibliothek (Kategorien & Einsatzbereiche)

Mit dem Paket `antigravity_complete_skills_package.zip` werden 427 spezialisierte Skills nach `~/.gemini/config/skills/` installiert. Hier die wichtigsten Gruppen:

### A. C-Suite & Strategic Executive Agents
* `boardroom`: 6-Phasen Multi-Rollen-Debatte der C-Suite mit Synthese und Board Memo.
* `cfo-review`, `cto-review`, `cpo-review`, `ciso-review`, `cmo-review`, `cro-review`: Scharfe Fachprüfung von Plänen aus Finanz-, Tech-, Produkt- und Sicherheits-Sicht.
* `decide` & `freeze`: Protokollierung strategischer Entscheidungen und Abkühlphasen.

### B. Engineering, Testing & DevOps
* `senior-fullstack`, `senior-backend`, `senior-frontend`, `senior-architect`: Tiefgehende Implementierungs- und Architektur-Skills.
* `playwright-pro`, `fix`, `generate`, `coverage`, `review`: Vollständige E2E- und Komponenten-Testsuite.
* `ci-cd-pipeline-builder`, `docker-development`, `kubernetes-operator`: Pipeline- und Container-Tools.

### C. AI Security & Compliance
* `ai-security`: MITRE ATLAS Mapping, Prompt Injection Detection, Jailbreak Defense.
* `ai-act-readiness`: EU AI Act Compliance-Prüfung nach Artikel 113.
* `gdpr-audit-prep`, `iso27001-audit-prep`, `soc2-compliance`: Datenschutz- und Sicherheitsaudits.

### D. Knowledge Management, LLM-Wiki & Memory
* `wiki-init`, `wiki-ingest`, `wiki-query`, `wiki-lint`: Vollständiges LLM-Wiki-Wissensnetzwerk mit Wikilinks.
* `remember`, `promote`, `status`: Automatisches und explizites Gedächtnis-Management.

---

## 🚀 5. Installation & Aktivierung auf Ubuntu 24.04

Führe nach dem Kopieren des Projektordners auf Ubuntu einfach aus:

```bash
cd ~/AgenticOS-2026

# 1. Skills in Antigravity installieren (kopiert alles nach ~/.gemini/config/skills)
chmod +x install_antigravity_skills_ubuntu.sh
./install_antigravity_skills_ubuntu.sh

# 2. Archon OS Stack starten
chmod +x setup_new_machine.sh
./setup_new_machine.sh
```

Sobald du Antigravity auf Ubuntu neu startest, stehen ihm sofort alle 427 Skills, deine Arbeitsweise und das gesamte Systemverständnis zur Verfügung!
