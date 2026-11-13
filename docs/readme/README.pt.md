<div align="center">

![Archon OS](../system/screenshots/archon_logo.png)

# ARCHON AGENTIC OS (2026)

**Sistema Operacional Multi-Agente Auto-Hospedado para Fundadores, Equipes e Especialistas de Domínio**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Agents: 70 Specialists](https://img.shields.io/badge/Specialists-70%20in%208%20Domains-emerald.svg)](../../agent_profiles.json)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](../../requirements.txt)
[![Docker Ready](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED.svg)](../../docker-compose.yml)

[🇬🇧 English](../../README.md) · [🇩🇪 Deutsch](../../README.de.md) · [🇪🇸 Español](README.es.md) · [🇫🇷 Français](README.fr.md) · **🇵🇹 Português** · [🇷🇺 Русский](README.ru.md) · [🇯🇵 日本語](README.ja.md) · [🇰🇷 한국어](README.ko.md) · [🇨🇳 中文](README.zh.md) · [🇮🇹 Italiano](README.it.md) · [🇳🇱 Nederlands](README.nl.md)

[🤖 Protocolo de Instalação via Agente IA](../../INSTALL_AGENT.md) | [🗺️ Roadmap](../system/ROADMAP_2026.md)

</div>

---

O Archon OS substitui chatbots isolados por um **Sistema Operacional Agêntico** persistente e auto-hospedado. Ele coordena **70 especialistas em 8 domínios principais**, conduz debates estruturados no **AI Boardroom com 55 frameworks**, une **roteamento local Zero-Egress** com **log de auditoria SHA-256 (GoBD / ISO 27001)** e integra **Obsidian Second Brain**, **n8n**, **Telegram** e um módulo **CRM & ERP *(Alpha)***.

> **Status de localização:** A interface suporta 11 idiomas (`en`, `de`, `es`, `fr`, `pt`, `it`, `nl`, `ru`, `ja`, `ko`, `zh`). Os arquivos `SOUL.md` e metodologias estão atualmente em alemão; a tradução está em andamento ([Roadmap M31](../system/ROADMAP_2026.md)).

---

## Fundamentos Obrigatórios (Os 4 Pilares)

| Componente | Papel no Archon OS | Como é instalado |
|---|---|---|
| **1. Docker** *(Desktop / Engine v2)* | Executa Archon OS, Hermes Agent, AnythingLLM, Chroma e Socket Proxy em contêineres isolados | Instalação oferecida via `winget` (Windows), `brew` (macOS) ou `get.docker.com` (Linux) |
| **2. Hermes Agent** *(`nousresearch/hermes-agent`)* | Runtime autônomo de agentes, gateway de sessão (porta `8644`) e integração Telegram | Baixado e iniciado automaticamente pelo Docker Compose junto ao Archon OS |
| **3. AnythingLLM + Chroma** *(RAG Vetorial)* | Alimenta **Biblioteca Central → RAG** (`http://localhost:3001`) com busca semântica | Baixado e iniciado automaticamente no perfil padrão `Standard` |
| **4. Obsidian** *(App Desktop + Vault)* | Segundo Cérebro em Markdown (`/opt/data/obsidian`) para relatórios, fichas e grafos | Pastas criadas automaticamente em `./obsidian_vault`; **Obsidian Desktop** oferecido na instalação |

---

## Instalação (2 Formas)

### Opção A: Instalar com seu Agente IA (1 Prompt)
Abra este repositório no **Antigravity**, **Claude Code**, **OpenAI Codex**, **Cursor** ou **Windsurf** e envie:
```text
Read INSTALL_AGENT.md and set up Archon OS on my machine. Run the pre-flight check first and ask me the 6 discovery questions before installing.
```

### Opção B: Instalador Interativo 1-Clique
- **Windows:** Clique duas vezes em **`setup.bat`** (executa [setup.ps1](../../setup.ps1) com assistente guiado para Docker, Obsidian, Ollama, chaves API e rede). Uso diário: `start.bat` e `stop.bat`.
- **Linux e macOS:**
  ```bash
  git clone https://github.com/michaelbeatman/Archon-Os.git
  cd Archon-Os
  chmod +x install.sh && ./install.sh
  ```
  *(Use `./install.sh --yes` para instalação não interativa).*

---

## Prévia do Sistema

| Mission Control & Operations | Frota de 70 Especialistas (`SOUL.md`) |
|---|---|
| ![Mission Control](../system/screenshots/mission_control.png) | ![Agent Fleet](../system/screenshots/kader.png) |
| **AI Boardroom (Debate Multi-Agente)** | **Org-Chart & Teams** |
| ![AI Boardroom Debate](../system/screenshots/boardroom_debate.png) | ![Org-Chart](../system/screenshots/org.png) |

---

## A Frota de 70 Especialistas (8 Domínios)

1. **Estratégia, Liderança e Vida (12):** Orquestração, Copiloto CEO, decisões M&A, OKRs., síntese entre domínios e verificação final
2. **Comércio, Compras e E-Commerce (7):** Cadeia de suprimentos, estoque, negociação, Shopify.
3. **Direito, Impostos, Finanças e Seguros (11):** Contratos, LGPD/GDPR, patentes, holding fiscal, crédito *(Modal de aviso regulatório obrigatório)*.
4. **Imobiliário e Construção (7):** Avaliação DCF, licenças, ESG/KfW, engenharia de obras *(Modal de aviso técnico obrigatório)*.
5. **Criação, Mídia e Conteúdo (8):** Copywriting, roteiros de vídeo, keynotes, UI/UX.
6. **Vendas, CRM, Marketing e Growth (11):** Prospecção B2B, pricing, SEO/GEO, mídia paga, retenção.
7. **Tecnologia, Software, Dados e QA (8):** Arquitetura Fullstack, DevOps/CloudSec, tuning de BD, testes automatizados.
8. **Medicina, Química, Ciência e Engenharia (6):** Consultoria clínica, regulação EU-MDR, química/REACH, biotecnologia, síntese científica *(Modal regulatório obrigatório)*.

---

## Segurança, Privacidade e Aviso Legal

- **Rede segura por padrão:** Vinculado a `127.0.0.1:8501`. Ative autenticação multiusuário (`auth.enabled = true`) antes de liberar `ARCHON_BIND_IP=0.0.0.0` na rede local.
- **Sem aconselhamento profissional:** Análises jurídicas, fiscais, médicas ou de engenharia são apenas apoio interno e não substituem profissionais licenciados ([LICENSE](../../LICENSE)).
- **Avatares sintéticos:** Todos os 301 retratos em `static/avatars/` são gerados por IA (Gemini Nano Banana 2) e não retratam pessoas reais ([THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md)).
---

### Manuals & Documentation (PDF)
- **User & Company Manual:** [Português PDF (2.0 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_PT.pdf) | [English PDF (97 pp., 1.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.pdf) | [Deutsch PDF (97 S., 1.9 MB)](../system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf)
- **Complete Feature List (v0.5.1):** [Português PDF (795K)](../system/ARCHON_OS_FEATURELISTE_2026_PT.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_FEATURE_LIST_2026_EN.pdf) | [Deutsch PDF (34 S., 0.7 MB)](../system/ARCHON_OS_FEATURELISTE_2026.pdf)
- **AI Boardroom (55 Frameworks):** [Português PDF (769K)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_PT.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_EN.pdf) | [Deutsch PDF (32 S., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf)
