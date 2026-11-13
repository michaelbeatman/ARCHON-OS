<div align="center">

![Archon OS](../system/screenshots/archon_logo.png)

# ARCHON AGENTIC OS (2026)

**Sistema Operativo Multi-Agente Autoalojado para Fundadores, Equipos y Especialistas de Dominio**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Agents: 70 Specialists](https://img.shields.io/badge/Specialists-70%20in%208%20Domains-emerald.svg)](../../agent_profiles.json)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](../../requirements.txt)
[![Docker Ready](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED.svg)](../../docker-compose.yml)

[🇬🇧 English](../../README.md) · [🇩🇪 Deutsch](../../README.de.md) · **🇪🇸 Español** · [🇫🇷 Français](README.fr.md) · [🇵🇹 Português](README.pt.md) · [🇷🇺 Русский](README.ru.md) · [🇯🇵 日本語](README.ja.md) · [🇰🇷 한국어](README.ko.md) · [🇨🇳 中文](README.zh.md) · [🇮🇹 Italiano](README.it.md) · [🇳🇱 Nederlands](README.nl.md)

[🤖 Protocolo de Instalación para Agentes IA](../../INSTALL_AGENT.md) | [🗺️ Hoja de Ruta (Roadmap)](../system/ROADMAP_2026.md)

</div>

---

Archon OS reemplaza los chatbots aislados por un **Sistema Operativo Agéntico** persistente y autoalojado. Coordina **70 especialistas de dominio en 8 áreas principales**, ejecuta debates estructurados en el **AI Boardroom con 55 marcos de decisión**, combina **enrutamiento de IA local Zero-Egress** con un **registro de auditoría SHA-256 (GoBD / ISO 27001)** y conecta directamente tu **Obsidian Second Brain**, **n8n**, **Telegram** y un módulo nativo de **CRM y ERP *(Alpha)***.

> **Estado de localización:** La interfaz principal soporta 11 idiomas (`en`, `de`, `es`, `fr`, `pt`, `it`, `nl`, `ru`, `ja`, `ko`, `zh`). Los archivos `SOUL.md` y metodologías del Boardroom están actualmente en alemán; la localización multilingüe está en curso ([Roadmap M31](../system/ROADMAP_2026.md)).

---

## Pilares Fundamentales (4 Componentes Esenciales)

| Componente | Rol en Archon OS | Cómo se instala |
|---|---|---|
| **1. Docker** *(Desktop / Engine v2)* | Ejecuta Archon OS, Hermes Agent, AnythingLLM, Chroma y Socket Proxy en contenedores aislados | Instalación guiada mediante `winget` (Windows), `brew` (macOS) o `get.docker.com` (Linux) |
| **2. Hermes Agent** *(`nousresearch/hermes-agent`)* | Runtime autónomo de agentes, gateway de sesiones (puerto `8644`) y puente Telegram | Descargado e iniciado automáticamente por Docker Compose junto a Archon OS |
| **3. AnythingLLM + Chroma** *(Vector RAG)* | Impulsa **Biblioteca Central → RAG** (`http://localhost:3001`) con búsqueda semántica | Descargado e iniciado automáticamente en el stack predeterminado `Standard` |
| **4. Obsidian** *(App Desktop + Vault)* | Segundo Cerebro persistente en Markdown (`/opt/data/obsidian`) para informes y grafos | Carpetas inicializadas en `./obsidian_vault`; instalación de **Obsidian Desktop** ofrecida automáticamente |

---

## Instalación (2 Formas)

### Opción A: Instalar con tu Agente IA (1 Prompt)
Abre este repositorio en **Antigravity**, **Claude Code**, **OpenAI Codex**, **Cursor** o **Windsurf** y envía este prompt:
```text
Read INSTALL_AGENT.md and set up Archon OS on my machine. Run the pre-flight check first and ask me the 6 discovery questions before installing.
```

### Opción B: Instalador Interactivo de 1 Clic
- **Windows:** Doble clic en **`setup.bat`** (inicia [setup.ps1](../../setup.ps1) con detección automática de Docker, Obsidian, Ollama, claves API y perfil de red). Para uso diario: `start.bat` y `stop.bat`.
- **Linux y macOS:**
  ```bash
  git clone https://github.com/michaelbeatman/ARCHON-OS.git
  cd ARCHON-OS
  chmod +x install.sh && ./install.sh
  ```
  *(Usa `./install.sh --yes` para instalación desatendida con valores predeterminados).*

---

## Vista Previa del Sistema

| Mission Control & Operations | Flota de 70 Especialistas (`SOUL.md`) |
|---|---|
| ![Mission Control](../system/screenshots/mission_control.png) | ![Agent Fleet](../system/screenshots/kader.png) |
| **AI Boardroom (Debate Multi-Agente)** | **Org-Chart & Teams** |
| ![AI Boardroom Debate](../system/screenshots/boardroom_debate.png) | ![Org-Chart](../system/screenshots/org.png) |

---

## Flota de 70 Especialistas (8 Dominios)

1. **Estrategia, Dirección y Vida (12):** Orquestador, Copiloto CEO, Decisiones M&A, OKRs., síntesis transversal y verificación final
2. **Comercio, Compras y E-Commerce (7):** Cadena de suministro, stock, negociación con proveedores, Shopify.
3. **Derecho, Impuestos, Finanzas y Seguros (11):** Contratos, GDPR, patentes, holding fiscal, financiación *(Diálogo de advertencia legal obligatorio)*.
4. **Inmobiliaria y Construcción (7):** Valoración DCF, permisos, ESG/KfW, dirección de obra *(Diálogo de advertencia técnica obligatorio)*.
5. **Creación, Medios y Contenido (8):** Copywriting, guiones de vídeo, discursos, diseño UI/UX.
6. **Ventas, CRM, Marketing y Growth (11):** Prospección B2B, pricing, SEO/GEO, anuncios de pago, retención.
7. **Tecnología, Software, Datos y QA (8):** Arquitectura Fullstack, DevOps/CloudSec, optimización BD, pruebas automatizadas.
8. **Medicina, Química, Ciencia e Ingeniería (6):** Asesoría clínica, regulación EU-MDR, química/REACH, biotecnología, síntesis científica *(Diálogo regulatorio obligatorio)*.

---

## Seguridad, Privacidad y Aviso Legal

- **Red segura por defecto:** Enlazado a `127.0.0.1:8501`. Activa la autenticación multiusuario (`auth.enabled = true`) antes de habilitar `ARCHON_BIND_IP=0.0.0.0` en LAN.
- **Sin asesoramiento profesional regulado:** Los resultados de las áreas legales, fiscales, médicas, químicas o de construcción son solo apoyo interno y no sustituyen a profesionales colegiados ([LICENSE](../../LICENSE)).
- **Avatares sintéticos:** Todos los 301 retratos en `static/avatars/` fueron generados artificialmente (Gemini Nano Banana 2) y no representan personas reales ([THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md)).
---

### Manuals & Documentation (PDF)
- **User & Company Manual:** [Español PDF (2.1 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_ES.pdf) | [English PDF (97 pp., 1.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.pdf) | [Deutsch PDF (97 S., 1.9 MB)](../system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf)
- **Complete Feature List (v0.5.2.1):** [Español PDF (826K)](../system/ARCHON_OS_FEATURELISTE_2026_ES.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_FEATURE_LIST_2026_EN.pdf) | [Deutsch PDF (34 S., 0.7 MB)](../system/ARCHON_OS_FEATURELISTE_2026.pdf)
- **AI Boardroom (55 Frameworks):** [Español PDF (773K)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_ES.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_EN.pdf) | [Deutsch PDF (32 S., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf)
