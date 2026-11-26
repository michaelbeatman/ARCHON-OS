# Archon OS — Produkt- und Funktionsbeschreibung (Bewerbungsreferenz)

**Archon OS** ist ein selbstgehostetes **Agentic Operating System**: eine lokale Control-Plane, die auf dem Hermes-Agenten-Runtime von Nous Research aufbaut und aus einzelnen Chat-Assistenten ein durchgängiges Business-Betriebssystem macht. Die Anwendung läuft vollständig auf der eigenen Infrastruktur, orchestriert **71 Agenten-Profile** über 8 Domänen und verbindet Agenten-Orchestrierung, Wissensverwaltung, Business-Operations und Governance in einer Oberfläche.

---

## Deutsche Fassung

### Produktprofil

- **Multi-Agenten-Orchestrierung:** 71 Agentenprofile mit dreistufigen `SOUL.md`-Prompts (Compact / Pro / Full), sodass Tokens nur für die tatsächlich benötigte Domäne aufgewendet werden. Aufgaben laufen als strukturierte Workflows mit Delegation, Fan-in/Synthese, HITL-Gates und persistenten Checkpoints — nicht als Einmal-Antworten.
- **AI Boardroom:** 80 strukturierte Entscheidungsframeworks über 9 Kategorien (OKR, Pre-Mortem, Six Thinking Hats, …) für isolierte Multi-Perspektiven-Debatten mit Kritik-Runde und Synthesis. Ergebnisse werden revisionssicher im Obsidian-Vault und in der Decision-Engine archiviert.
- **Kosten- und Provider-Steuerung:** Model-Routing zwischen lokalen Modellen (Ollama, LM Studio) und Cloud-Providern (OpenRouter, OmniRoute, Groq, OpenAI, Anthropic, Mistral), Vorab-Kostenabschätzung und Budget-Limits pro Rolle/Task, Bandit-basiertes Modell-Feedback und semantischer Cache.
- **Datensouveränität:** Zero-Egress-Gate und Privacy-Router mit Fail-Closed-Hard-Block für Finanz-, Vertrags- und CRM-Daten, wenn das lokale Modell offline ist; isolierte Worker-Container ohne Internet-Route; lokale RAG-Indexierung über Obsidian-Vault sowie AnythingLLM/Chroma.
- **Business-Operations:** Kanban mit Vier-Augen-Freigaben, E-Mail-Triage, CRM und ERP-Suite (Angebote, Verträge, Rechnungen, Forderungen), Treasury, Kalender, Zeiterfassung und n8n-/Telegram-Integration.
- **Bedienung & Erweiterung:** Next.js-16-/React-19-Cockpit mit Echtzeit-SSE, Prompt Studio mit 832 Vorlagen, MCP-Gateway, Plugin-Marktplatz, Undo-/Replay-Fähigkeiten und 11 UI-Sprachen; durchgängig zweisprachig (DE/EN) inklusive Setup-Assistent.

### Compliance & Governance (eigenes Kapitel)

- **GoBD / revisionssichere Buchführung:** HMAC-SHA256-Hashkette über jedem Audit-Block inklusive externem Anker, Manipulationserkennung und Startprüfung; für jeden LLM-Dispatch werden Provider, Modell, Ziel-Host und Endpunkt als Nachweisblock signiert. Beleg-Nummernkreise sind atomar und pro Mandant getrennt; jeder Mandantenwechsel wird protokolliert.
- **1-Klick-Verfahrensdokumentation:** Ein abhängigkeitsfreier Pure-Python-PDF-Generator erzeugt aus dem Live-Zustand ein mehrseitiges, seitenummeriertes Prüfer-PDF mit Mandantenstamm, IKS, Hashketten-Status, Zero-Egress-Nachweis, KI-Systemregister und Unterschriftsblock. Jeder Abruf wird mit Dokument-ID und PDF-SHA-256 im Audit-Log erfasst.
- **DSGVO Art. 17:** Physisch getrennte SQLite-Datenbanken je Gesellschaft (Holding / GmbH / SPV) mit eigenen Nummernkreisen; Anonymisierung läuft über den autoritativen DB-Resolver und schließt VARCHAR-, JSON- und CLOB-Felder ein, während GoBD-relevante Belegtabellen geschützt bleiben.
- **EU AI Act (VO 2024/1689):** Compliance-Engine mit präziser Risikoklassifizierung — `HIGH_RISK` (Art. 6 / Anhang III, z. B. HR-Recruiter) mit obligatorischem Vier-Augen-HITL, `SPECIFIC_TRANSPARENCY` (Art. 50, z. B. Outreach/PR) mit KI-Offenlegungspflicht, `MINIMAL_RISK` (Art. 95). Jede Agenten-Aktivierung prüft Guardrails, Audit-Kette und SOUL-Hash-Pinning.
- **Art. 4 KI-Kompetenzregister:** Verwaltung eingewiesener Bediener und Aufsichtskräfte inklusive Rolle, Schulungsmodul, Gültigkeit und Zertifikats-SHA-256; jede Änderung erzeugt einen signierten Audit-Block.
- **HITL & Zugriffsschutz:** WebAuthn/Passkey-bestätigte Einmal-Freigaben, die an konkrete Aktion und Ressource gebunden sind; rollenbasierte Zugriffskontrolle, signierte Tool-Warrants für privilegierte Aktionen, Secret-Masking vor jedem externen Dispatch und PII-Scrubbing.

### Technologien

Python 3.12/3.13 · FastAPI · Pydantic v2 · asyncio · SQLite (WAL, CAS, Leases) · HMAC-SHA256 / WebAuthn · Next.js 16 · React 19 · TypeScript · Docker · GitHub Actions · Prometheus/OTel · Obsidian · n8n · MCP.

---

## English Version

### Product Profile

- **Multi-agent orchestration:** 71 agent profiles with three-tier `SOUL.md` prompts (Compact / Pro / Full) so tokens are spent only where domain expertise is needed. Work runs as structured workflows with delegation, fan-in/synthesis, HITL gates and persistent checkpoints — not one-shot answers.
- **AI Boardroom:** 80 structured decision frameworks across 9 categories (OKR, Pre-Mortem, Six Thinking Hats, …) for isolated multi-perspective debates with a critique prompt and deterministic synthesis; results are archived tamper-evidently in the Obsidian vault and the decision engine.
- **Cost & provider control:** routing between local models (Ollama, LM Studio) and cloud providers (OpenRouter, OmniRoute, Groq, OpenAI, Anthropic, Mistral), upfront cost estimation, per-role/per-task budgets, bandit-based model feedback and a semantic cache.
- **Data sovereignty:** zero-egress gate and privacy router with fail-closed hard block for finance, contract and CRM data when the local model is offline; worker containers on an internal Docker network with no internet route; local RAG indexing via Obsidian vault and AnythingLLM/Chroma.
- **Business operations:** Kanban with four-eyes approvals, email triage, CRM and an ERP suite (offers, contracts, invoices, receivables), treasury, calendar, time tracking and n8n/Telegram integration.
- **UX & extensibility:** Next.js 16 / React 19 cockpit with real-time SSE, Prompt Studio with 832 templates, MCP gateway, plugin marketplace, replay capabilities and 11 UI locales; consistently bilingual (DE/EN) including a setup wizard.

### Compliance & Governance

- **GoBD / tamper-evident accounting:** HMAC-SHA256 hash chain over every audit block with an external anchor, manipulation detection and a startup key check; every LLM dispatch is signed with provider, model, target host and endpoint proof. Document number ranges are atomic and tenant-specific; every tenant switch is logged.
- **One-click procedural documentation:** a dependency-free pure-Python PDF generator produces a multi-page, paginated auditor document from live state — company master data, internal control system, hash-chain status, zero-egress evidence, AI system register and signature block. Each export is recorded with document ID and PDF SHA-256 in the audit log.
- **GDPR Art. 17:** physically separated SQLite databases per company (holding / operating GmbH / SPV) with dedicated number ranges; erasure runs through the authoritative DB resolver and covers VARCHAR, JSON and CLOB fields while GoBD-relevant document tables remain protected.
- **EU AI Act (Reg. 2024/1689):** compliance engine with precise risk classification — `HIGH_RISK` (Art. 6 / Annex III, e.g. HR recruiter) with mandatory four-eyes HITL, `SPECIFIC_TRANSPARENCY` (Art. 50, e.g. outreach/PR) with AI disclosure duty, `MINIMAL_RISK` (Art. 95). Every agent activation checks guardrails, audit chain and SOUL hash pinning.
- **Art. 4 AI literacy register:** management of trained operators and supervisors including role, training module, validity and certificate SHA-256; every change creates a signed audit block.
- **HITL & access control:** WebAuthn/passkey one-time proofs bound to a concrete action and resource, RBAC, signed tool warrants for privileged actions, secret masking before every external dispatch and PII scrubbing.

### Stack

Python 3.12/3.13 · FastAPI · Pydantic v2 · asyncio · SQLite (WAL, CAS, leases) · HMAC-SHA256 / WebAuthn · Next.js 16 · React 19 · TypeScript · Docker · GitHub Actions · Prometheus/OTel · Obsidian · n8n · MCP.

---

## Kennzahlen / Key Figures

| Merkmal | Wert |
|---|---|
| Agentenprofile | 71 (in 8 Domänen) |
| Boardroom-Frameworks | 80 (in 9 Kategorien) |
| Prompt-Templates | 832 |
| UI-Sprachen | 11 |
| Domänen | 8 |
| Konsolidierte WAL-DBs | 3 (`ops.db`, `business.db`, `memory.db`) |
| Docker-Services | 7 Standard-Container (bis 24 mit Profilen) |

**Technische Detaildokumentation:** `docs/system/EU_AI_ACT_GOBD_COMPLIANCE_GUIDE.md` · `docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md` · `README.md`
