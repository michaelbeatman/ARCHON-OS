<div align="center">

![Archon OS](../system/screenshots/archon_logo.png)

# ARCHON AGENTIC OS (2026)

**창업자, 팀 및 도메인 전문가를 위한 셀프 호스팅 멀티 에이전트 운영 체제**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Agents: 70 Specialists](https://img.shields.io/badge/Specialists-70%20in%208%20Domains-emerald.svg)](../../agent_profiles.json)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](../../requirements.txt)
[![Docker Ready](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED.svg)](../../docker-compose.yml)

[🇬🇧 English](../../README.md) · [🇩🇪 Deutsch](../../README.de.md) · [🇪🇸 Español](README.es.md) · [🇫🇷 Français](README.fr.md) · [🇵🇹 Português](README.pt.md) · [🇷🇺 Русский](README.ru.md) · [🇯🇵 日本語](README.ja.md) · **🇰🇷 한국어** · [🇨🇳 中文](README.zh.md) · [🇮🇹 Italiano](README.it.md) · [🇳🇱 Nederlands](README.nl.md)

[🤖 AI 에이전트 설치 프로토콜](../../INSTALL_AGENT.md) | [🗺️ 로드맵](../system/ROADMAP_2026.md)

</div>

---

Archon OS는 일회성 챗봇을 대체하는 영구적·셀프 호스팅 **Agentic Operating System**입니다. **8개 핵심 도메인 70명 전문가**를 오케스트레이션하고, **55개 프레임워크 기반 AI 보드룸 토론**, **Zero-Egress 로컬 AI 라우팅**, 위변조 검증 가능한 **SHA-256 감사 로그(GoBD / ISO 27001)**, 그리고 **Obsidian Second Brain**·**n8n**·**Telegram**·**CRM & ERP *(Alpha)*** 모듈을 하나로 연결합니다.

> **로컬라이제이션 현황:** UI는 9개 언어(`en`, `de`, `es`, `fr`, `pt`, `ru`, `ja`, `ko`, `zh`)를 지원합니다. 에이전트 `SOUL.md` 및 보드룸 방법론은 현재 독일어 기반이며 다국어 번역이 진행 중입니다([Roadmap M31](../system/ROADMAP_2026.md)).

---

## 필수 핵심 기반 (Archon 4대 구성 요소)

| 구성 요소 | Archon OS 내 역할 | 설치 방식 |
|---|---|---|
| **1. Docker** *(Desktop / Engine v2)* | Archon OS, Hermes Agent, AnythingLLM, Chroma 및 Socket Proxy를 격리 컨테이너로 실행 | `winget`(Windows), `brew`(macOS), `get.docker.com`(Linux) 통해 자동 안내 |
| **2. Hermes Agent** *(`nousresearch/hermes-agent`)* | 자율 에이전트 런타임, 세션 게이트웨이(포트 `8644`) 및 Telegram 연동 | Docker Compose가 Archon OS와 함께 자동 풀링 및 실행 |
| **3. AnythingLLM + Chroma** *(벡터 RAG)* | **중앙 라이브러리 → RAG**(`http://localhost:3001`) 시맨틱 문서 검색 제공 | 기본 `Standard` 스택에서 자동 풀링 및 실행 |
| **4. Obsidian** *(데스크톱 앱 + Vault)* | 리포트·인사 파일·지식 그래프를 저장하는 Markdown 세컨드 브레인 | `./obsidian_vault` 폴더 자동 초기화 및 **Obsidian Desktop** 설치 제안 |

---

## 설치 방법 (2가지)

### 방법 A: AI 에이전트로 1-프롬프트 설치
**Antigravity**, **Claude Code**, **OpenAI Codex**, **Cursor** 또는 **Windsurf**에서 이 저장소를 열고 아래 프롬프트를 입력하세요:
```text
Read INSTALL_AGENT.md and set up Archon OS on my machine. Run the pre-flight check first and ask me the 6 discovery questions before installing.
```

### 방법 B: 대화형 원클릭 설치 프로그램
- **Windows:** **`setup.bat`** 더블 클릭([setup.ps1](../../setup.ps1)이 Docker, Obsidian, Ollama, API 키, 네트워크 설정을 단계별로 안내). 일상 실행은 `start.bat`, 종료는 `stop.bat`.
- **Linux / macOS:**
  ```bash
  git clone https://github.com/michaelbeatman/Archon-Os.git
  cd Archon-Os
  chmod +x install.sh && ./install.sh
  ```
  *(`--yes` 옵션으로 기본값 기반 자동 설치 가능)*

---

## 시스템 미리보기

| Mission Control & Operations | 70명 전문가 플릿 (`SOUL.md`) |
|---|---|
| ![Mission Control](../system/screenshots/mission_control.png) | ![Agent Fleet](../system/screenshots/kader.png) |
| **AI Boardroom (멀티 에이전트 토론)** | **Org-Chart & Teams** |
| ![AI Boardroom Debate](../system/screenshots/boardroom_debate.png) | ![Org-Chart](../system/screenshots/org.png) |

---

## 70명 전문가 구성 (8개 핵심 도메인)

1. **전략·경영·라이프 플래닝 (12):** 총괄 오케스트레이션, CEO 코파일럿, M&A 의사결정, OKR, 도메인 간 통합 및 최종 검증 답당
2. **상거래·조달·이커머스 (7):** 공급망, 재고 예측, 공급사 협상, Shopify
3. **법률·세무·재무·보험 (11):** 계약 검토, GDPR, 특허, 지주회사 세무, 자금 조달 *(법적 고지 경고 모달 필수)*
4. **부동산·건설 개발 (7):** DCF 가치평가, 인허가, ESG/KfW, 현장 공정 관리 *(기술 고지 경고 모달 필수)*
5. **크리에이티브·미디어·콘텐츠 (8):** 카피라이팅, 영상 스크립트, 키노트, UI/UX 디자인
6. **영업·CRM·마케팅·그로스 (11):** B2B 아웃리치, 가격 정책, SEO/GEO, 퍼포먼스 광고, 리텐션
7. **기술·소프트웨어·데이터·QA (8):** 풀스택 아키텍처, DevOps/CloudSec, DB 튜닝, 테스트 자동화
8. **의학·화학·과학·엔지니어링 (6):** 임상 자문, EU-MDR 규제, 화학/REACH, 바이오테크, 문헌 합성 *(규제 고지 경고 모달 필수)*

---

## 보안, 개인정보 보호 및 법적 고지

- **안전한 네트워크 기본값:** 기본 바인딩은 `127.0.0.1:8501`입니다. LAN 공개(`ARCHON_BIND_IP=0.0.0.0`) 전 멀티유저 인증(`auth.enabled = true`)을 먼저 활성화하세요.
- **전문 자문 대체 불가:** 법률, 세무, 금융, 의료, 건축 도메인 출력은 내부 의사결정 보조용이며 공인 전문가 자문을 대체하지 않습니다([LICENSE](../../LICENSE)).
- **합성 아바타:** `static/avatars/`의 301개 인물 초상은 AI(Gemini Nano Banana 2)로 생성된 가상 이미지입니다([THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md)).
---

### Manuals & Documentation (PDF)
- **User & Company Manual:** [한국어 PDF (2.1 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_KO.pdf) | [English PDF (97 pp., 1.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.pdf) | [Deutsch PDF (97 S., 1.9 MB)](../system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf)
- **Complete Feature List (v0.5.1):** [한국어 PDF (944K)](../system/ARCHON_OS_FEATURELISTE_2026_KO.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_FEATURE_LIST_2026_EN.pdf) | [Deutsch PDF (34 S., 0.7 MB)](../system/ARCHON_OS_FEATURELISTE_2026.pdf)
- **AI Boardroom (55 Frameworks):** [한국어 PDF (733K)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_KO.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_EN.pdf) | [Deutsch PDF (32 S., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf)
