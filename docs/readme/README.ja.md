<div align="center">

![Archon OS](../system/screenshots/archon_logo.png)

# ARCHON AGENTIC OS (2026)

**創業者・チーム・専門領域向けのセルフホスト型マルチエージェントOS**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../LICENSE)
[![Agents: 70 Specialists](https://img.shields.io/badge/Specialists-70%20in%208%20Domains-emerald.svg)](../../agent_profiles.json)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB.svg)](../../requirements.txt)
[![Docker Ready](https://img.shields.io/badge/Docker-Compose%20Ready-2496ED.svg)](../../docker-compose.yml)

[🇬🇧 English](../../README.md) · [🇩🇪 Deutsch](../../README.de.md) · [🇪🇸 Español](README.es.md) · [🇫🇷 Français](README.fr.md) · [🇵🇹 Português](README.pt.md) · [🇷🇺 Русский](README.ru.md) · **🇯🇵 日本語** · [🇰🇷 한국어](README.ko.md) · [🇨🇳 中文](README.zh.md) · [🇮🇹 Italiano](README.it.md) · [🇳🇱 Nederlands](README.nl.md)

[🤖 AIエージェント導入プロトコル](../../INSTALL_AGENT.md) | [🗺️ ロードマップ](../system/ROADMAP_2026.md)

</div>

---

Archon OSは、単発のチャットボットを置き換える永続的なセルフホスト型 **Agentic Operating System** です。**8つのコア領域・70名の専門エージェント**を統合し、**55の意思決定フレームワークに基づくAIボードルーム討論**、**Zero-EgressローカルAIルーティング**、改ざん検知可能な **SHA-256監査ログ（GoBD / ISO 27001）**、そして **Obsidian Second Brain**・**n8n**・**Telegram**・ネイティブ **CRM & ERP *(Alpha)*** モジュールを連携します。

> **ローカライズ状況:** UIは9言語（`en`, `de`, `es`, `fr`, `pt`, `ru`, `ja`, `ko`, `zh`）に対応しています。専門エージェントの `SOUL.md` やボードルーム手法は現在ドイツ語で記述されており、多言語化を順次進めています（[Roadmap M31](../system/ROADMAP_2026.md)）。

---

## 必須基盤モジュール（Archonの4本柱）

| コンポーネント | Archon OSでの役割 | インストール方法 |
|---|---|---|
| **1. Docker** *(Desktop / Engine v2)* | Archon OS、Hermes Agent、AnythingLLM、Chroma、Socket Proxy を隔離コンテナで実行 | `winget`（Windows）、`brew`（macOS）、`get.docker.com`（Linux）経由で導入ガイド |
| **2. Hermes Agent** *(`nousresearch/hermes-agent`)* | 自律エージェント実行基盤、セッションゲートウェイ（ポート `8644`）、Telegram連携 | Docker ComposeがArchon OSと同時に自動取得・起動 |
| **3. AnythingLLM + Chroma** *(ベクトルRAG)* | **中央ライブラリ → RAG**（`http://localhost:3001`）のセマンティック検索を提供 | 既定の `Standard` スタックで自動取得・起動 |
| **4. Obsidian** *(デスクトップアプリ + Vault)* | レポート・人事ファイル・知識グラフを保持するMarkdownセカンドブレイン | `./obsidian_vault` を自動初期化し、**Obsidian Desktop** の導入を提案 |

---

## インストール方法（2通り）

### 方法A：AIエージェントによる1プロンプト導入
**Antigravity**、**Claude Code**、**OpenAI Codex**、**Cursor**、または **Windsurf** でこのリポジトリを開き、次のプロンプトを実行してください：
```text
Read INSTALL_AGENT.md and set up Archon OS on my machine. Run the pre-flight check first and ask me the 6 discovery questions before installing.
```

### 方法B：対話式ワンクリック・インストーラー
- **Windows:** **`setup.bat`** をダブルクリック（[setup.ps1](../../setup.ps1) がDocker・Obsidian・Ollama・APIキー・ネットワーク設定を案内）。日常起動は `start.bat`、停止は `stop.bat`。
- **Linux / macOS:**
  ```bash
  git clone https://github.com/michaelbeatman/Archon-Os.git
  cd Archon-Os
  chmod +x install.sh && ./install.sh
  ```
  *（`./install.sh --yes` で既定値による自動インストールが可能）*

---

## システムプレビュー

| Mission Control & Operations | 70名の専門エージェント艦隊 (`SOUL.md`) |
|---|---|
| ![Mission Control](../system/screenshots/mission_control.png) | ![Agent Fleet](../system/screenshots/kader.png) |
| **AI Boardroom（マルチエージェント討論）** | **Org-Chart & Teams** |
| ![AI Boardroom Debate](../system/screenshots/boardroom_debate.png) | ![Org-Chart](../system/screenshots/org.png) |

---

## 70名の専門エージェント（8コアドメイン）

1. **戦略・経営・ライフプラン (12):** 全体統括、CEOコパイロット、M&A意思決定、OKR、ドメイン横断の統合と最終検証も担当
2. **商業・調達・Eコマース (7):** サプライチェーン、在庫予測、仕入交渉、Shopify
3. **法務・税務・財務・保険 (11):** 契約審査、GDPR、特許、持株会社税務、資金調達 *（法的免責警告モーダル必須）*
4. **不動産・建築・開発 (7):** DCF評価、建築許認可、ESG/KfW、施工管理 *（技術免責警告モーダル必須）*
5. **クリエイティブ・メディア (8):** コピーライティング、動画脚本、講演原稿、UI/UX
6. **営業・CRM・マーケティング (11):** B2B営業、価格戦略、SEO/GEO、広告運用、顧客維持
7. **テック・ソフトウェア・データ・QA (8):** フルスタック開発、DevOps/CloudSec、DB最適化、テスト自動化
8. **医療・化学・科学・エンジニアリング (6):** 臨床分析、EU-MDR薬事、化学/REACH、バイオ、学術文献統合 *（規制警告モーダル必須）*

---

## セキュリティ・プライバシー・免責事項

- **安全なネットワーク既定値:** 初期設定は `127.0.0.1:8501` に限定。LAN公開（`ARCHON_BIND_IP=0.0.0.0`）を行う前にマルチユーザー認証（`auth.enabled = true`）を有効化してください。
- **専門資格助言の非代替:** 法務・税務・金融・医療・建築に関する出力は内部判断支援用であり、有資格専門家による助言を代替しません（[LICENSE](../../LICENSE)）。
- **合成アバター:** `static/avatars/` 内の301点の人物画像はAI生成（Gemini Nano Banana 2）による架空ポートレートです（[THIRD_PARTY_LICENSES.md](../../THIRD_PARTY_LICENSES.md)）。
---

### Manuals & Documentation (PDF)
- **User & Company Manual:** [日本語 PDF (2.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_JA.pdf) | [English PDF (97 pp., 1.9 MB)](../system/ARCHON_OS_SYSTEM_MANUAL_2026_EN.pdf) | [Deutsch PDF (97 S., 1.9 MB)](../system/ARCHON_OS_SYSTEM_HANDBUCH_2026.pdf)
- **Complete Feature List (v0.5.1):** [日本語 PDF (1.4 MB)](../system/ARCHON_OS_FEATURELISTE_2026_JA.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_FEATURE_LIST_2026_EN.pdf) | [Deutsch PDF (34 S., 0.7 MB)](../system/ARCHON_OS_FEATURELISTE_2026.pdf)
- **AI Boardroom (55 Frameworks):** [日本語 PDF (1.1 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_JA.pdf) | [English PDF (31 pp., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026_EN.pdf) | [Deutsch PDF (32 S., 0.7 MB)](../system/ARCHON_OS_BOARDROOM_FRAMEWORKS_2026.pdf)
