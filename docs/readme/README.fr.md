<div align="center">

![Archon OS](../system/screenshots/archon_logo.png)

# ARCHON AGENTIC OS (2026)

**Système d'Exploitation Multi-Agents Auto-Hébergé pour Fondateurs, Équipes et Spécialistes Métier**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Agents: 70 Specialists](https://img.shields.io/badge/Specialists-70%20in%208%20Domains-emerald.svg)](../../agent_profiles.json)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](../../requirements.txt)
[![Docker Ready](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED.svg)](../../docker-compose.yml)

[🇬🇧 English](../../README.md) · [🇩🇪 Deutsch](../../README.de.md) · [🇪🇸 Español](README.es.md) · **🇫🇷 Français** · [🇵🇹 Português](README.pt.md) · [🇷🇺 Русский](README.ru.md) · [🇯🇵 日本語](README.ja.md) · [🇰🇷 한국어](README.ko.md) · [🇨🇳 中文](README.zh.md) · [🇮🇹 Italiano](README.it.md) · [🇳🇱 Nederlands](README.nl.md)

[🤖 Protocole d'Installation par Agent IA](../../INSTALL_AGENT.md) | [🗺️ Feuille de Route (Roadmap)](../system/ROADMAP_2026.md)

</div>

---

Archon OS remplace les chatbots isolés par un **Système d'Exploitation Agentique** persistant et auto-hébergé. Il orchestre **70 spécialistes dans 8 domaines principaux**, organise des débats structurés dans l'**AI Boardroom selon 55 frameworks**, associe un **routage IA local Zero-Egress** à un **journal d'audit SHA-256 (GoBD / ISO 27001)** et connecte **Obsidian Second Brain**, **n8n**, **Telegram** ainsi qu'un module **CRM & ERP *(Alpha)***.

> **État de la traduction :** L'interface supporte 11 langues (`en`, `de`, `es`, `fr`, `pt`, `it`, `nl`, `ru`, `ja`, `ko`, `zh`). Les profils `SOUL.md` et méthodologies sont actuellement en allemand ; la localisation est en cours ([Roadmap M31](../system/ROADMAP_2026.md)).

---

## Socle Technique Obligatoire (Les 4 Piliers)

| Composant | Rôle dans Archon OS | Méthode d'installation |
|---|---|---|
| **1. Docker** *(Desktop / Engine v2)* | Exécute Archon OS, Hermes Agent, AnythingLLM, Chroma et Socket Proxy en conteneurs isolés | Proposé automatiquement via `winget` (Windows), `brew` (macOS) ou `get.docker.com` (Linux) |
| **2. Hermes Agent** *(`nousresearch/hermes-agent`)* | Runtime agent autonome, passerelle de sessions (port `8644`) et interface Telegram | Téléchargé et démarré automatiquement par Docker Compose avec Archon OS |
| **3. AnythingLLM + Chroma** *(RAG Vectoriel)* | Alimente **Bibliothèque Centrale → RAG** (`http://localhost:3001`) par recherche sémantique | Téléchargé et démarré automatiquement dans la pile par défaut `Standard` |
| **4. Obsidian** *(App Desktop + Coffre)* | Second Cerveau Markdown persistant (`/opt/data/obsidian`) pour rapports et dossiers | Dossiers initialisés dans `./obsidian_vault` ; installation d'**Obsidian Desktop** proposée automatiquement |

---

## Installation (2 Méthodes)

### Option A : Installation via votre Agent IA (1 Prompt)
Ouvrez ce dépôt dans **Antigravity**, **Claude Code**, **OpenAI Codex**, **Cursor** ou **Windsurf** et collez :
```text
Read INSTALL_AGENT.md and set up Archon OS on my machine. Run the pre-flight check first and ask me the 6 discovery questions before installing.
```

### Option B : Installateur Interactif 1-Clic
- **Windows :** Double-cliquez sur **`setup.bat`** (lance [setup.ps1](../../setup.ps1) : vérification Docker/Obsidian/Ollama, langue, clés API, exposition réseau). Au quotidien : `start.bat` et `stop.bat`.
- **Linux & macOS :**
  ```bash
  git clone https://github.com/michaelbeatman/ARCHON-OS.git
  cd ARCHON-OS
  chmod +x install.sh && ./install.sh
  ```
  *(Utilisez `./install.sh --yes` pour une installation non interactive).*

---

## Aperçu du Système

| Mission Control & Operations | Flotte de 70 Spécialistes (`SOUL.md`) |
|---|---|
| ![Mission Control](../system/screenshots/mission_control.png) | ![Agent Fleet](../system/screenshots/kader.png) |
| **AI Boardroom (Débat Multi-Agents)** | **Org-Chart & Teams** |
| ![AI Boardroom Debate](../system/screenshots/boardroom_debate.png) | ![Org-Chart](../system/screenshots/org.png) |

---

## La Flotte des 70 Spécialistes (8 Domaines)

1. **Stratégie, Direction & Vie (12) :** Orchestration, Copilote CEO, décisions M&A, OKRs., synthèse inter-domaines et vérification finale
2. **Commerce, Achats & E-Commerce (7) :** Chaîne logistique, prévisions de stock, négociation fournisseurs, Shopify.
3. **Droit, Fiscalité, Finance & Assurance (11) :** Contrats, RGPD, brevets, holdings fiscales, financement *(Modale d'avertissement réglementaire obligatoire)*.
4. **Immobilier & Construction (7) :** Évaluation DCF, permis, ESG/KfW, gestion de chantier *(Modale d'avertissement technique obligatoire)*.
5. **Création, Médias & Contenu (8) :** Copywriting, scripts vidéo, discours, design UI/UX.
6. **Ventes, CRM, Marketing & Growth (11) :** Prospection B2B, pricing, SEO/GEO, publicité payante, rétention.
7. **Tech, Logiciel, Data & QA (8) :** Architecture Fullstack, DevOps/CloudSec, tuning BDD, tests automatisés.
8. **Médecine, Chimie, Sciences & Ingénierie (6) :** Conseil clinique, réglementation EU-MDR, chimie/REACH, pharma/biotech, synthèse scientifique *(Modale réglementaire obligatoire)*.

---

## Sécurité, Confidentialité & Avertissement Légal

- **Réseau sécurisé par défaut :** Écoute uniquement sur `127.0.0.1:8501`. Activez l'authentification multi-utilisateurs (`auth.enabled = true`) avant d'exposer `ARCHON_BIND_IP=0.0.0.0` sur le réseau local.
- **Aucun conseil professionnel réglementé :** Les productions juridiques, fiscales, financières, médicales ou techniques ne remplacent pas un professionnel agréé ([LICENSE](../../LICENSE)).
- **Avatars synthétiques :** Les 301 portraits dans `static/avatars/` sont générés par IA (Gemini Nano Banana 2) et ne représentent aucune personne réelle ([THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md)).
---

### Manuals & Documentation (PDF)
- **User & Company Manual:** [Français PDF (2.1 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_FR.pdf) | [English PDF (97 pp., 1.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.pdf) | [Deutsch PDF (97 S., 1.9 MB)](../system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf)
- **Complete Feature List (v0.5.2.1):** [Français PDF (801K)](../system/ARCHON_OS_FEATURELISTE_2026_FR.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_FEATURE_LIST_2026_EN.pdf) | [Deutsch PDF (34 S., 0.7 MB)](../system/ARCHON_OS_FEATURELISTE_2026.pdf)
- **AI Boardroom (55 Frameworks):** [Français PDF (770K)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_FR.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_EN.pdf) | [Deutsch PDF (32 S., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf)
