<div align="center">

![Archon OS](../system/screenshots/archon_logo.png)

# ARCHON AGENTIC OS (2026)

**Автономная мультиагентная операционная система с локальным хостингом для основателей, команд и экспертов**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Agents: 70 Specialists](https://img.shields.io/badge/Specialists-70%20in%208%20Domains-emerald.svg)](../../agent_profiles.json)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](../../requirements.txt)
[![Docker Ready](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED.svg)](../../docker-compose.yml)

[🇬🇧 English](../../README.md) · [🇩🇪 Deutsch](../../README.de.md) · [🇪🇸 Español](README.es.md) · [🇫🇷 Français](README.fr.md) · [🇵🇹 Português](README.pt.md) · **🇷🇺 Русский** · [🇯🇵 日本語](README.ja.md) · [🇰🇷 한국어](README.ko.md) · [🇨🇳 中文](README.zh.md) · [🇮🇹 Italiano](README.it.md) · [🇳🇱 Nederlands](README.nl.md)

[🤖 Протокол установки через ИИ-агента](../../INSTALL_AGENT.md) | [🗺️ Дорожная карта (Roadmap)](../system/ROADMAP_2026.md)

</div>

---

Archon OS заменяет разрозненные чат-боты единой саморазворачиваемой **агентной операционной системой**. Она координирует **70 профильных специалистов в 8 основных доменах**, проводит структурированные дебаты в **AI Boardroom по 55 фреймворкам**, объединяет **локальную маршрутизацию Zero-Egress** с **журналом аудита на базе хэш-цепочки SHA-256 (GoBD / ISO 27001)** и интегрируется с **Obsidian Second Brain**, **n8n**, **Telegram** и модулем **CRM и ERP *(Alpha)***.

> **Статус локализации:** Интерфейс поддерживает 11 языков (`en`, `de`, `es`, `fr`, `pt`, `it`, `nl`, `ru`, `ja`, `ko`, `zh`). Профили `SOUL.md` и методики Boardroom пока написаны на немецком языке; многоязычная локализация ведётся ([Roadmap M31](../system/ROADMAP_2026.md)).

---

## Базовый стек (4 ключевых модуля)

| Компонент | Роль в Archon OS | Как устанавливается |
|---|---|---|
| **1. Docker** *(Desktop / Engine v2)* | Запускает Archon OS, Hermes Agent, AnythingLLM, Chroma и Socket Proxy в изолированных контейнерах | Предлагается автоматически через `winget` (Windows), `brew` (macOS) или `get.docker.com` (Linux) |
| **2. Hermes Agent** *(`nousresearch/hermes-agent`)* | Автономный рантайм агентов, шлюз сессий (порт `8644`) и Telegram-мост | Скачивается и запускается автоматически через Docker Compose вместе с Archon OS |
| **3. AnythingLLM + Chroma** *(Векторный RAG)* | Обеспечивает работу **Центральная библиотека → RAG** (`http://localhost:3001`) | Скачивается и запускается автоматически в профиле `Standard` по умолчанию |
| **4. Obsidian** *(Desktop-приложение + Vault)* | Постоянный Markdown-архив знаний (`/opt/data/obsidian`) для отчётов и графа знаний | Папки создаются в `./obsidian_vault`; установка **Obsidian Desktop** предлагается автоматически |

---

## Установка (2 способа)

### Вариант А: Установка через вашего ИИ-агента (1 промпт)
Откройте репозиторий в **Antigravity**, **Claude Code**, **OpenAI Codex**, **Cursor** или **Windsurf** и отправьте:
```text
Read INSTALL_AGENT.md and set up Archon OS on my machine. Run the pre-flight check first and ask me the 6 discovery questions before installing.
```

### Вариант Б: Интерактивный установщик в 1 клик
- **Windows:** Дважды кликните **`setup.bat`** (запускает [setup.ps1](../../setup.ps1) с мастером настройки Docker, Obsidian, Ollama, API-ключей и сети). Для ежедневного запуска: `start.bat` и `stop.bat`.
- **Linux и macOS:**
  ```bash
  git clone https://github.com/michaelbeatman/ARCHON-OS.git
  cd ARCHON-OS
  chmod +x install.sh && ./install.sh
  ```
  *(Используйте `./install.sh --yes` для установки со значениями по умолчанию).*

---

## Обзор интерфейса

| Mission Control & Operations | Флот из 70 специалистов (`SOUL.md`) |
|---|---|
| ![Mission Control](../system/screenshots/mission_control.png) | ![Agent Fleet](../system/screenshots/kader.png) |
| **AI Boardroom (мультиагентные дебаты)** | **Org-Chart & Teams** |
| ![AI Boardroom Debate](../system/screenshots/boardroom_debate.png) | ![Org-Chart](../system/screenshots/org.png) |

---

## Флот из 70 специалистов (8 основных доменов)

1. **Стратегия, управление и жизнь (12):** Оркестрация, CEO-копилот, M&A-решения, OKR., междоменный синтез и финальная проверка
2. **Торговля, закупки и E-Commerce (7):** Цепочки поставок, прогнозирование запасов, переговоры, Shopify.
3. **Право, налоги, финансы и страхование (11):** Договоры, GDPR, патенты, холдинги, финансирование *(Обязательное диалоговое предупреждение)*.
4. **Недвижимость и строительство (7):** DCF-оценка, разрешения, ESG/KfW, управление стройкой *(Обязательное предупреждение по нормам)*.
5. **Креатив, медиа и контент (8):** Копирайтинг, видеосценарии, презентации, UI/UX-дизайн.
6. **Продажи, CRM, маркетинг и Growth (11):** B2B-аутрич, ценообразование, SEO/GEO, платная реклама, удержание.
7. **Технологии, разработка, данные и QA (8):** Fullstack-архитектура, DevOps/CloudSec, тюнинг БД, автотесты.
8. **Медицина, химия, наука и инженерия (6):** Клинический анализ, стандарты EU-MDR, химия/REACH, биотех, научный синтез *(Обязательное регуляторное предупреждение)*.

---

## Безопасность, приватность и правовой дисклеймер

- **Безопасная сеть по умолчанию:** Привязка только к `127.0.0.1:8501`. Перед открытием доступа в локальной сети (`ARCHON_BIND_IP=0.0.0.0`) включите многопользовательскую авторизацию (`auth.enabled = true`).
- **Не является профессиональной консультацией:** Ответы юридических, финансовых, медицинских и инженерных профилей не заменяют сертифицированных специалистов ([LICENSE](../../LICENSE)).
- **Синтетические аватары:** Все 301 портрет в `static/avatars/` сгенерированы ИИ (Gemini Nano Banana 2) и не изображают реальных людей ([THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md)).
---

### Manuals & Documentation (PDF)
- **User & Company Manual:** [Русский PDF (1.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_RU.pdf) | [English PDF (97 pp., 1.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.pdf) | [Deutsch PDF (97 S., 1.9 MB)](../system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf)
- **Complete Feature List (v0.5.2.1):** [Русский PDF (689K)](../system/ARCHON_OS_FEATURELISTE_2026_RU.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_FEATURE_LIST_2026_EN.pdf) | [Deutsch PDF (34 S., 0.7 MB)](../system/ARCHON_OS_FEATURELISTE_2026.pdf)
- **AI Boardroom (55 Frameworks):** [Русский PDF (568K)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_RU.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_EN.pdf) | [Deutsch PDF (32 S., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf)
