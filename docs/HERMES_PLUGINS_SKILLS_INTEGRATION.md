# Hermes Marketplace Plugins & Skills — Integration in Archon OS

Dieses Dokument beschreibt die in Archon OS übernommenen Skills und MCP-Server aus dem Hermes Marketplace (`hermes-agent.nousresearch.com/marketplace`), deren Profil-Zuweisung in `agent_profiles.json` sowie die notwendigen Voraussetzungen auf dem Server.

---

## 1. Übernommene Skills (`.agents/skills/`)

| Skill | Quelle | Zweck |
|---|---|---|
| `hermes-agent` | `NousResearch/hermes-agent` | Hermes Agent konfigurieren, erweitern und orchestrieren |
| `sdlc-review` | `NousResearch/hermes-agent` | Kanban-Handoffs prüfen und verifizierte Ergebnisse routen |
| `simplify-code` | `NousResearch/hermes-agent` | Paralleler 4-Agenten-Cleanup von Code-Änderungen |
| `claude-code` | `NousResearch/hermes-agent` | Coding-Tasks an Claude Code CLI delegieren |
| `codex` | `NousResearch/hermes-agent` | Coding-Tasks an OpenAI Codex CLI delegieren |
| `kinocut` | `KyaniteLabs/kinocut` | Lokaler Videoschnitt mit FFmpeg über den Kinocut-MCP-Server |
| `kinocut-repurpose` | `KyaniteLabs/kinocut` | Short-Form-Repurposing bestehender Videos |
| `pay` | `solana-foundation/pay` | API-Discovery & Pay-per-Request (HTTP 402 / x402 / MPP) in Stablecoins |
| `patsnap-search` | `NousResearch/hermes-labs-plugins` | Patent- und Literatursuche (WIPO/EPO/USPTO, PubMed, arXiv, Legal-Lifecycle) |
| `canonry` | `Canonry/canonry` | Answer Engine Optimization (AEO/GEO) & AI-Crawler-Readiness |
| `penthera` | `danoszz/penthera` | Offline, regelbasierter Security-Check (Repo, Dependencies, Agent-/MCP-Config) |
| `opendockit` | `hyeonsang010716/OpenDocKit` | Lokale Konvertierung von PDF, Word, PowerPoint, Excel, CSV, HTML & E-Mail in Markdown |
| `seo`, `seo-audit`, `seo-geo`, `seo-technical`, `seo-schema`, `seo-content` | `yuzushi-dev/hermes-seo` | Kern-SEO-Workflow-Skills (Technical SEO, Schema, GEO, Content, Audit) |

---

## 2. MCP-Server-Konfiguration (`.mcp.json`)

In der Repository-Root liegt `.mcp.json` mit sechs MCP-Servern:
- **`kinocut`** (`stdio`): `uvx kinocut==2.0.1`
- **`pay`** (`streamable-http`): `https://connect.pay.sh/mcp` (OAuth-Login, kein lokales Wallet erforderlich)
- **`pay-cli`** (`stdio`): `pay mcp` (`PAY_FORCE_ELICITATION=1`, lokales Wallet über Pay CLI)
- **`patsnap`** (`streamable-http`): `https://connect.patsnap.com/2b0355/logic-mcp` (Header `apikey: ${PATSNAP_API_KEY}`)
- **`canonry`** (`stdio`): `canonry-mcp` (alternativ Remote: `https://mcp.canonry.ai/mcp`)
- **`opendockit`** (`stdio`): `uvx --python >=3.12 --from opendockit[mcp]==0.3.13 opendockit-mcp` (`OPENDOCKIT_MCP_ROOTS`)

Für Hermes auf dem Server können dieselben Server in `~/.hermes/config.yaml` unter `mcp_servers:` eingetragen werden:

```yaml
mcp_servers:
  kinocut:
    command: uvx
    args: ["kinocut==2.0.1"]
  pay:
    url: https://connect.pay.sh/mcp
  pay-cli:
    command: pay
    args: ["mcp"]
    env:
      PAY_FORCE_ELICITATION: "1"
  patsnap:
    url: https://connect.patsnap.com/2b0355/logic-mcp
    headers:
      apikey: "${PATSNAP_API_KEY}"
  canonry:
    command: canonry-mcp
  opendockit:
    command: uvx
    args: ["--python", ">=3.12", "--from", "opendockit[mcp]==0.3.13", "opendockit-mcp"]
    env:
      OPENDOCKIT_MCP_ROOTS: "${OPENDOCKIT_MCP_ROOTS}"
```

---

## 3. Profil-Zuweisung (`agent_profiles.json`)

| Profil-ID | Ergänzte Skills | Ergänzte Tools |
|---|---|---|
| `default` | `hermes-agent`, `sdlc-review`, `simplify-code` | `mcp` |
| `founder` | `hermes-agent`, `sdlc-review` | — |
| `agile_scrum_master` | `hermes-agent`, `sdlc-review` | — |
| `system_architect_orchestrator` | `hermes-agent`, `sdlc-review`, `simplify-code`, `claude-code`, `codex`, `penthera` | `mcp` |
| `senior_fullstack_engineer` | `sdlc-review`, `simplify-code`, `claude-code`, `codex` | — |
| `qa_test_engineer` | `sdlc-review`, `simplify-code`, `penthera` | — |
| `devops_cloud_sec_specialist` | `hermes-agent`, `sdlc-review`, `penthera` | — |
| `compliance_gdpr_auditor` | `penthera` | — |
| `video_script_architect` | `kinocut`, `kinocut-repurpose` | `mcp` |
| `content_repurposing_specialist` | `kinocut`, `kinocut-repurpose` | `mcp` |
| `procurement_sourcing_scout` | `pay` | `mcp` |
| `ecommerce_shopify_lead` | `pay` | `mcp` |
| `finance_lead` | `pay` | `mcp` |
| `ip_patent_analyst` | `patsnap-search` | `mcp` |
| `scientific_literature_synthesizer` | `patsnap-search` | `mcp` |
| `pharma_biotech_scientist` | `patsnap-search` | `mcp` |
| `chemistry_materials_specialist` | `patsnap-search` | `mcp` |
| `medtech_regulatory_lead` | `patsnap-search` | `mcp` |
| `seo_geo_specialist` | `canonry`, `seo`, `seo-audit`, `seo-geo`, `seo-technical`, `seo-schema`, `seo-content` | `mcp` |
| `gtm_launch_strategist` | `canonry` | `mcp` |
| `growth_hacker_lead` | `canonry`, `seo`, `seo-audit`, `seo-geo`, `seo-technical`, `seo-schema`, `seo-content` | `mcp` |
| `direct_response_copywriter` | `seo-content`, `seo-geo` | — |
| `default` | `+ opendockit` | `mcp` |
| `knowledge_librarian` | `opendockit` | `mcp` |
| `legal_counsel` | `opendockit` | `mcp` |
| `commercial_jurist_contracts` | `opendockit` | `mcp` |
| `finance_lead` | `+ opendockit` | `mcp` |
| `scientific_literature_synthesizer` | `+ opendockit` | `mcp` |

---

## 4. Server-Voraussetzungen (nach `git pull`)

Dateien in `.agents/skills/`, `.mcp.json`, `agent_profiles.json` und `docs/` kommen automatisch per `git pull` auf den Server. Folgende Laufzeit-Abhängigkeiten müssen auf dem Server zusätzlich vorhanden sein:

- **Für `kinocut`:** `uv` / `uvx` und `ffmpeg` auf `PATH`.
- **Für `opendockit`:** `uv` / `uvx` (Python >= 3.12) sowie `OPENDOCKIT_MCP_ROOTS` (erlaubte Verzeichnispfade) in `.env`.
- **Für `pay` (Hosted MCP):** OAuth-Anmeldung beim ersten Connect gegen `https://connect.pay.sh/mcp`.
- **Für `pay-cli` (Lokales Wallet):** Installierte `pay` CLI und konfiguriertes Wallet (inkl. Ausgabenlimits / HITL-Freigabe).
- **Für `claude-code` / `codex`:** Installierte `claude` bzw. `codex` CLI samt API-Zugang auf dem Server.
- **Für `patsnap`:** Umgebungsvariable `PATSNAP_API_KEY` in `.env` auf dem Server.
- **Für `canonry`:** Paket `canonry-mcp` installiert (oder Remote-Endpunkt `https://mcp.canonry.ai/mcp` mit OAuth nutzen).
- **Für `penthera` & `hermes-seo`:** Keine externen Pflicht-Dienste nötig (laufen als Skills).
