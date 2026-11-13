"""
backend/demo_mode.py
Milestone 47 — "Zero-Install" Read-Only Live-Demo Mode (`ARCHON_DEMO_MODE=true`).

Designed for safe public hosting (Show HN / Product Hunt / public evaluation on a
5 EUR VPS) with zero RCE/0-day surface, zero disk persistence, and zero LLM token cost:

1. Pure pass-through ASGI middleware when `ARCHON_DEMO_MODE` is unset/false.
2. Hard 403 (`demo_blocked`) on all dangerous execution, container, raw-config,
   updater, and reverse-proxy/egress paths regardless of HTTP method.
3. Instant deterministic 200 OK simulation (`zero_token_cost=True`) on demo-safe
   interactive preview POST endpoints (QuickChat, Master Chat, Agent Chat,
   AI Boardroom run/stream, Prompt Studio template render).
4. Strict 403 (`demo_read_only`) on all remaining mutating HTTP methods
   (`POST`, `PUT`, `DELETE`, `PATCH`).
5. Rich bilingual (`en` / `de`) enterprise showcase dataset for
   "Mittelstand Muster Precision GmbH" / "Mittelstand Muster GmbH" plus
   `seed_demo_workspace()` for ephemeral `tmpfs` container boot.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

DEMO_REPO_URL = "https://github.com/michaelbeatman/ARCHON-OS"

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})

# Dangerous execution, container control, secret config, updater, and SSRF/proxy
# prefixes blocked across ALL HTTP methods (GET, POST, PUT, DELETE, PATCH, etc.).
DEMO_HARD_BLOCKED_PREFIXES: Tuple[str, ...] = (
    "/api/sandbox",
    "/api/v1/container",
    "/api/docker",
    "/api/v1/system/update",
    "/api/system/update",
    "/api/hermes/raw_config",
    "/n8n-proxy",
    "/omniroute-proxy",
    "/api/proxy",
)

# Mutating HTTP verbs blocked by default in read-only demo mode unless explicitly
# handled by the deterministic zero-token preview simulator below.
DEMO_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})

# Exact POST endpoints allowed for deterministic zero-egress interactive previews.
DEMO_SAFE_CHAT_PATHS = frozenset({
    "/api/quickchat",
    "/api/quickchat/send",
    "/api/v1/quickchat/send",
    "/api/chat",
    "/api/chat/send",
    "/api/chat/stream",
    "/api/agent-chat",
    "/api/agent-chat/send",
    "/api/v1/agent/chat",
})

DEMO_SAFE_BOARDROOM_PATHS = frozenset({
    "/api/boardroom/run",
    "/api/boardroom/stream",
})


def is_demo_mode() -> bool:
    """Return True when ARCHON_DEMO_MODE is enabled via environment variable."""
    return os.environ.get("ARCHON_DEMO_MODE", "").strip().lower() in _TRUTHY_VALUES


def normalize_demo_lang(lang: Optional[str] = None) -> str:
    """Normalize requested language code to 'de' or 'en' (default 'en')."""
    raw = (lang or os.environ.get("ARCHON_LANGUAGE") or "en").strip().lower()
    if raw.startswith("de"):
        return "de"
    return "en"


def _gobd_hash_preview(seed: str) -> str:
    """Generate a deterministic GoBD SHA-256 Merkle hash preview string."""
    digest = hashlib.sha256(f"archon-gobd-2026::{seed}".encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}...{digest[-8:]}"


# ---------------------------------------------------------------------------
# Specialist Metadata for Deterministic Chat & Showcase
# ---------------------------------------------------------------------------

_SPECIALIST_META: Dict[str, Dict[str, str]] = {
    "default": {
        "name_en": "Hermes Orchestrator (Root)",
        "name_de": "Hermes Orchestrator (Root)",
        "role_en": "Supreme System Orchestrator & Dispatcher",
        "role_de": "Zentraler System-Orchestrator & Root Dispatcher",
        "focus_en": "multi-agent task decomposition, 4-eyes governance routing, and cross-domain synthesis",
        "focus_de": "Multi-Agenten-Aufgabenzerlegung, 4-Augen-Governance-Routing und domänenübergreifende Synthese",
    },
    "executive_decision_architect": {
        "name_en": "Robert — Executive Decision Architect",
        "name_de": "Robert — Executive Decision Architect",
        "role_en": "C-Level Strategy & Capital Allocation Lead",
        "role_de": "C-Level Strategie- & Kapitalallokations-Architekt",
        "focus_en": "first-principles capital allocation, asymmetric ROI modeling, and 90-day execution roadmaps",
        "focus_de": "First-Principles-Kapitalallokation, asymmetrische ROI-Modellierung und 90-Tage-Umsetzungspläne",
    },
    "finance_lead": {
        "name_en": "Clara — Chief Financial Analyst",
        "name_de": "Clara — Chief Financial Analyst (CFO-Office)",
        "role_en": "DCF Valuation, Unit Economics & Liquidity Control",
        "role_de": "DCF-Bewertung, Deckungsbeitragsrechnung & Liquiditätssteuerung",
        "focus_en": "EBITDA margin bridge, working-capital discipline, CAPEX payback, and DATEV/GoBD cost control",
        "focus_de": "EBITDA-Margenbrücke, Working-Capital-Disziplin, CAPEX-Amortisation und DATEV/GoBD-Kostenkontrolle",
    },
    "commercial_jurist_contracts": {
        "name_en": "Dr. Henrik Vogt — Commercial & Regulatory Jurist",
        "name_de": "Dr. Henrik Vogt — Wirtschaftsjurist & EU-AI-Act Auditor",
        "role_en": "B2B Contracts, GDPR/DSGVO & EU AI Act Compliance",
        "role_de": "B2B-Vertragsrecht, DSGVO & EU-AI-Act-Compliance",
        "focus_en": "EU AI Act risk classification (Art. 6 / Art. 50), GDPR Art. 28 DPAs, liability caps, and GoBD auditability",
        "focus_de": "EU-AI-Act-Risikoklassifizierung (Art. 6 / Art. 50), DSGVO-AVV nach Art. 28, Haftungshöchstgrenzen und GoBD-Prüfsicherheit",
    },
    "red_team_challenger": {
        "name_en": "Viktor — Adversarial Red-Team Challenger",
        "name_de": "Viktor — Adversarial Red-Team Challenger",
        "role_en": "Pre-Mortem Stress Testing & Security Failure Analysis",
        "role_de": "Pre-Mortem-Stresstests & Sicherheits-/Fehlermodus-Analyse",
        "focus_en": "single-point-of-failure elimination, prompt-injection defense, SLA tail-risks, and operational circuit breakers",
        "focus_de": "Eliminierung von Single-Points-of-Failure, Prompt-Injection-Abwehr, SLA-Ausfallrisiken und operative Circuit-Breaker",
    },
    "senior_fullstack_engineer": {
        "name_en": "Lukas — Principal Fullstack & Systems Engineer",
        "name_de": "Lukas — Principal Fullstack & Systems Engineer",
        "role_en": "Sovereign On-Prem Architecture, FastAPI & Zero-Egress AI",
        "role_de": "Souveräne On-Prem-Architektur, FastAPI & Zero-Egress-KI",
        "focus_en": "local Ollama + OmniRoute failover, SQLite WAL tenant isolation, deterministic CI gates, and hardened Docker runtime",
        "focus_de": "lokales Ollama + OmniRoute-Failover, SQLite-WAL-Mandantentrennung, deterministische CI-Gates und gehärtete Docker-Laufzeit",
    },
    "tax_holding_advisor": {
        "name_en": "Dr. Miriam Stein — Tax & Holding Structuring Advisor",
        "name_de": "Dr. Miriam Stein — Steuer- & Holding-Strukturberaterin",
        "role_en": "Corporate Tax, R&D Tax Credit (FZulG) & DATEV Compliance",
        "role_de": "Unternehmenssteuerrecht, Forschungszulage (FZulG) & DATEV-Compliance",
        "focus_en": "German R&D tax subsidy (§ 35a FZulG), GoBD Merkle archiving, and holding liquidity optimization",
        "focus_de": "Forschungszulagengesetz (FZulG), GoBD-Merkle-Archivierung und Holding-Liquiditätsoptimierung",
    },
    "devops_cloud_sec_specialist": {
        "name_en": "Nora — DevSecOps & Infrastructure Lead",
        "name_de": "Nora — DevSecOps & Infrastruktur-Spezialistin",
        "role_en": "Zero-Trust Containers, NIS-2 & TISAX Hardening",
        "role_de": "Zero-Trust-Container, NIS-2 & TISAX-Härtung",
        "focus_en": "read-only container rootfs, capability dropping, network segmentation, and TISAX AL3 audit readiness",
        "focus_de": "schreibgeschützte Container-Rootfs, Capability-Dropping, Netzwerksegmentierung und TISAX-AL3-Auditreife",
    },
    "growth_hacker_lead": {
        "name_en": "Elena — B2B Industrial Growth & Pipeline Lead",
        "name_de": "Elena — B2B Industrial Growth & Pipeline Lead",
        "role_en": "DACH/Benelux Key Account Expansion & ABM",
        "role_de": "DACH/Benelux Key-Account-Expansion & Account-Based Marketing",
        "focus_en": "technical OEM buyer enablement, RFQ turnaround acceleration, and high-margin service attach rates",
        "focus_de": "technisches OEM-Buyer-Enablement, schnellere RFQ-Angebotserstellung und hochmargige Wartungsverträge",
    },
}


# ---------------------------------------------------------------------------
# Rich Bilingual Showcase Dataset ("Mittelstand Muster GmbH")
# ---------------------------------------------------------------------------

def _build_company_data(lang: str) -> Dict[str, Any]:
    is_de = lang == "de"
    return {
        "id": "mittelstand-muster-gmbh",
        "name": "Mittelstand Muster GmbH" if is_de else "Mittelstand Muster Precision GmbH",
        "legal_name": "Mittelstand Muster Präzisionstechnik GmbH",
        "brand_subtitle": (
            "CNC-Sensorik & Industrielle KI-Qualitätsprüfung · Stuttgart (Baden-Württemberg)"
            if is_de
            else "CNC Sensor Systems & Industrial AI Quality Inspection · Stuttgart, Germany"
        ),
        "industry": (
            "Präzisionsmaschinenbau, MedTech- & Automotive-Zulieferung (ISO 9001 / TISAX AL3)"
            if is_de
            else "Precision Mechatronics, MedTech & Automotive Tier-2 Supply (ISO 9001 / TISAX AL3)"
        ),
        "headquarters": "Stuttgart-Vaihingen, DE",
        "employees": 145,
        "annual_revenue_eur": 28_400_000,
        "ebitda_margin_pct": 14.8,
        "vat_id": "DE298410573",
        "datev_consultant_no": "48291",
        "datev_client_no": "10420",
        "active_specialists": 70,
        "active_domains": 8,
        "zero_egress_active": True,
    }


def _build_telemetry_metrics(lang: str) -> Dict[str, Any]:
    is_de = lang == "de"
    return {
        "mode": "zero_egress_hybrid",
        "demo_token_cost_eur": 0.0,
        "local_ollama_share_pct": 78.4,
        "omniroute_smart_free_share_pct": 21.6,
        "cloud_egress_pii_bytes": 0,
        "monthly_llm_api_spend_eur": 14.80,
        "monthly_saas_cost_avoided_eur": 4620.00,
        "annual_net_savings_eur": 55_262.40,
        "local_models_active": [
            "ollama/qwen2.5-coder:32b-instruct-q4_K_M",
            "ollama/llama3.3:70b-instruct-q4_0",
        ],
        "router_combos_active": [
            "omniroute/strict-free-tier-combo",
            "omniroute/eu-sovereign-reasoning",
        ],
        "gobd_merkle_chain_status": "VALID",
        "gobd_verified_documents": 1248,
        "four_eyes_gates_enforced": 19,
        "summary_note": (
            "78,4 % aller Fertigungs-, ERP- und Vertragsanalysen laufen 100 % lokal über Ollama (Zero-Egress); "
            "21,6 % unkritische Marktrecherchen routet OmniRoute kostenoptimiert (4.620 €/Monat SaaS-Ersparnis)."
            if is_de
            else "78.4% of all CAD/RFQ, ERP, and legal workflows run 100% locally via Ollama (Zero-Egress); "
            "21.6% non-sensitive market research routes via OmniRoute cost-guard (€4,620/mo SaaS seat savings)."
        ),
    }


def _build_boardroom_debate(lang: str) -> Dict[str, Any]:
    is_de = lang == "de"
    if is_de:
        task = (
            "Strategische Expansion Benelux/Nordics 2026 & EU-AI-Act-Audit für die autonome "
            "Angebotskalkulation (RFQ-zu-ERP) bei der Mittelstand Muster GmbH (Budget: 420.000 €)"
        )
        phases = [
            {
                "phase": 1,
                "stage_code": "framing",
                "title": "Phase 1 — Strategisches Framing & Zielarchitektur",
                "agent_id": "executive_decision_architect",
                "agent_handle": "@executive_decision_architect",
                "agent_name": "Robert (Executive Decision Architect)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "Zerlegt das Vorhaben in zwei gekoppelte Werthebel: (A) Markteintritt Benelux/ASML-Zuliefercluster "
                    "für hochmargige Reinraum-Sensorik (+3,4 Mio. € Pipeline) und (B) Verkürzung der technischen "
                    "RFQ-Angebotsdurchlaufzeit von 6,5 Werktagen auf 4 Stunden durch lokale KI-Vorprüfung mit verpflichtendem "
                    "4-Augen-Freigabe-Gate im Archon-Cockpit."
                ),
            },
            {
                "phase": 2,
                "stage_code": "financial_model",
                "title": "Phase 2 — CAPEX/OPEX-Modellierung & Unit Economics",
                "agent_id": "finance_lead",
                "agent_handle": "@finance_lead",
                "agent_name": "Clara (Finance Lead)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "Validiert 420.000 € Gesamtinvestition (165.000 € On-Prem GPU-/Prüfzellen-Hardware, 135.000 € "
                    "Benelux-Vertriebsaufbau, 120.000 € Liquiditätspuffer). Durch +27 % höhere RFQ-Trefferquote und "
                    "55.260 €/Jahr eingesparte Cloud-SaaS-Lizenzen (Ollama + OmniRoute statt 70 Einzellizenzen) liegt "
                    "der Kapitalwert (NPV, 36 Monate, 8 % WACC) bei +1,18 Mio. €; Amortisation nach 11,4 Monaten."
                ),
            },
            {
                "phase": 3,
                "stage_code": "legal_compliance",
                "title": "Phase 3 — EU AI Act, DSGVO & GoBD-Rechtsprüfung",
                "agent_id": "commercial_jurist_contracts",
                "agent_handle": "@commercial_jurist_contracts",
                "agent_name": "Dr. Henrik Vogt (Commercial Jurist)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "Stuft die KI-gestützte RFQ-Kalkulation als NICHT-Hochrisiko nach Anhang III EU AI Act ein, "
                    "sofern sicherheitskritische MedTech-/Bauteilfreigaben weiterhin menschlich gezeichnet werden "
                    "(Art. 14 Human Oversight via Archon 4-Augen-Gate). TISAX-Kundenzeichnungen verlassen dank "
                    "`PRIVACY_ZERO_EGRESS=true` niemals das Stuttgarter Werksnetz; jedes erzeugte Angebot erhält "
                    "einen GoBD-konformen SHA-256-Merkle-Beleghash."
                ),
            },
            {
                "phase": 4,
                "stage_code": "red_team",
                "title": "Phase 4 — Adversarial Pre-Mortem & Red-Team-Stresstest",
                "agent_id": "red_team_challenger",
                "agent_handle": "@red_team_challenger",
                "agent_name": "Viktor (Red-Team Challenger)",
                "model": "omniroute/eu-sovereign-reasoning",
                "summary": (
                    "Identifiziert drei kritische Ausfallvektoren: (1) fehlerhafte Rohstoffzuschläge bei Titan/Edelstahl "
                    "aus veralteten PDF-Preislisten -> gelöst durch Live-ERP-Margenuntergrenze (min. 31 % DB I); "
                    "(2) indirekte Prompt-Injection in fremden Einkaufs-PDFs -> gelöst durch isolierten Dokumenten-Parser "
                    "ohne Tool-Rechte; (3) Lieferengpass bei Reinraum-Dichtungen -> Dual-Sourcing-Klausel vor Go-Live Pflicht."
                ),
            },
            {
                "phase": 5,
                "stage_code": "technical_architecture",
                "title": "Phase 5 — Technische Zielarchitektur & ERP-Integration",
                "agent_id": "senior_fullstack_engineer",
                "agent_handle": "@senior_fullstack_engineer",
                "agent_name": "Lukas (Senior Fullstack Engineer)",
                "model": "ollama/qwen2.5-coder:32b-instruct-q4_K_M",
                "summary": (
                    "Spezifiziert den lokalen Inferenz-Stack (2× RTX 6000 Ada On-Prem mit Ollama `qwen2.5-coder:32b` & "
                    "`llama3.3:70b`, OmniRoute als Circuit-Breaker), strikte SQLite-WAL-Mandantentrennung unter "
                    "`data/tenants/mittelstand-muster-gmbh/erp.db` und deterministischen DATEV-Buchungsstapel-Export."
                ),
            },
            {
                "phase": 6,
                "stage_code": "chairman_synthesis",
                "title": "Phase 6 — Chairman-Synthese, Beschlussvorlage & ROI-Matrix",
                "agent_id": "executive_decision_architect",
                "agent_handle": "@executive_decision_architect",
                "agent_name": "Chairman Synthese (@executive_decision_architect)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "EINSTIMMIGE FREIGABE UNTER AUFLAGEN (Conditional GO): Tranche 1 (180.000 €) startet sofort für "
                    "On-Prem-RFQ-Automatisierung + ASML/MedTech-Pilotangebote; Tranche 2 (240.000 €) wird automatisch "
                    "freigeschaltet, sobald >= 450.000 € qualifizierte Benelux-Auftragseingänge mit >= 32 % Rohertrag vorliegen."
                ),
            },
        ]
        roi_table = [
            {
                "metric": "RFQ-Durchlaufzeit (Technisches B2B-Angebot)",
                "baseline_2025": "6,5 Werktage",
                "archon_target_2026": "3,8 Stunden (inkl. 4-Augen-Gate)",
                "impact": "-92 % Durchlaufzeit",
            },
            {
                "metric": "Monatliche KI- & SaaS-Lizenzkosten (70 Profile)",
                "baseline_2025": "4.634,80 € / Monat (Cloud-Seats)",
                "archon_target_2026": "14,80 € / Monat (Ollama + OmniRoute)",
                "impact": "55.262 € / Jahr Ersparnis",
            },
            {
                "metric": "Zusätzlicher Deckungsbeitrag Benelux/MedTech (Jahr 1)",
                "baseline_2025": "0 € (nur DACH-Bestand)",
                "archon_target_2026": "+685.000 € DB I",
                "impact": "Amortisation in 11,4 Monaten",
            },
            {
                "metric": "DSGVO / TISAX / EU-AI-Act Cloud-Datenabfluss",
                "baseline_2025": "Hoch (US-Cloud-Wrapper)",
                "archon_target_2026": "0 Bytes (Zero-Egress On-Prem)",
                "impact": "100 % Audit- & GoBD-konform",
            },
        ]
        synthesis_md = (
            "### Vorstandsbeschluss: **FREIGABE UNTER AUFLAGEN (Conditional GO — 90-Tage-Plan)**\n\n"
            "1. **Sofortmaßnahme (Woche 1–4):** Inbetriebnahme der lokalen Zero-Egress-RFQ-Pipeline "
            "(`@senior_fullstack_engineer`) mit harter ERP-Mindestmargensperre von **31,0 % DB I** (`@finance_lead`).\n"
            "2. **Governance & EU AI Act (Woche 2–5):** Verankerung des verpflichtenden **4-Augen-Freigabe-Gates** "
            "vor jedem Angebotsversand > 15.000 € netto sowie SHA-256-GoBD-Belegversiegelung (`@commercial_jurist_contracts`).\n"
            "3. **Red-Team-Auflage (vor Tranche 2):** Isolierter PDF-Sanitizer gegen indirekte Prompt-Injection "
            "und Dual-Sourcing-Rahmenvertrag für Reinraum-Elastomere (`@red_team_challenger`).\n\n"
            "| Kennzahl | Ist-Zustand (2025) | Ziel mit Archon OS (2026) | Wirtschaftlicher Effekt |\n"
            "|---|---|---|---|\n"
            + "\n".join(
                f"| **{r['metric']}** | {r['baseline_2025']} | {r['archon_target_2026']} | **{r['impact']}** |"
                for r in roi_table
            )
        )
    else:
        task = (
            "2026 Benelux/Nordics Strategic Expansion & EU AI Act Automation Audit for "
            "Autonomous RFQ-to-ERP Quoting at Mittelstand Muster Precision GmbH (€420k Budget)"
        )
        phases = [
            {
                "phase": 1,
                "stage_code": "framing",
                "title": "Phase 1 — Strategic Framing & Value Decomposition",
                "agent_id": "executive_decision_architect",
                "agent_handle": "@executive_decision_architect",
                "agent_name": "Robert (Executive Decision Architect)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "Decomposes the initiative into two compounding levers: (A) Benelux/ASML mechatronics tier-2 "
                    "expansion for cleanroom sensor manifolds (€3.4M qualified pipeline) and (B) compressing engineering "
                    "RFQ quote turnaround from 6.5 business days to 3.8 hours using local AI costing guarded by "
                    "Archon's mandatory 4-eyes human approval gate."
                ),
            },
            {
                "phase": 2,
                "stage_code": "financial_model",
                "title": "Phase 2 — DCF, CAPEX/OPEX & Margin Bridge Modeling",
                "agent_id": "finance_lead",
                "agent_handle": "@finance_lead",
                "agent_name": "Clara (Finance Lead)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "Validates €420,000 total envelope (€165k on-prem GPU + optical inspection rig, €135k Benelux "
                    "technical sales onboarding, €120k working-capital reserve). Driven by +27% faster-quote win-rate "
                    "lift and €55,262/yr saved on per-seat AI SaaS licenses (local Ollama + OmniRoute), 36-month NPV "
                    "(8% WACC) reaches +€1.18M with full payback in 11.4 months."
                ),
            },
            {
                "phase": 3,
                "stage_code": "legal_compliance",
                "title": "Phase 3 — EU AI Act, GDPR & GoBD Audit Assessment",
                "agent_id": "commercial_jurist_contracts",
                "agent_handle": "@commercial_jurist_contracts",
                "agent_name": "Dr. Henrik Vogt (Commercial Jurist)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "Confirms AI-assisted RFQ costing falls outside EU AI Act Annex III High-Risk scope provided "
                    "safety-critical MedTech/CAD tolerances retain human sign-off (Art. 14 Human Oversight enforced "
                    "by Archon 4-eyes gate). Customer CAD files under TISAX AL3 never leave the Stuttgart plant "
                    "(`PRIVACY_ZERO_EGRESS=true`), and every issued ERP quote/invoice carries a GoBD SHA-256 Merkle hash."
                ),
            },
            {
                "phase": 4,
                "stage_code": "red_team",
                "title": "Phase 4 — Adversarial Pre-Mortem & Red-Team Stress Test",
                "agent_id": "red_team_challenger",
                "agent_handle": "@red_team_challenger",
                "agent_name": "Viktor (Red-Team Challenger)",
                "model": "omniroute/eu-sovereign-reasoning",
                "summary": (
                    "Surfaces three tail-risks and mandatory mitigations: (1) titanium/alloy spot-price drift in stale "
                    "PDF catalogs -> enforce hard ERP gross-margin floor (>= 31.0% contribution margin); "
                    "(2) indirect prompt injection embedded in external RFQ PDFs -> parse untrusted specs in a tool-less "
                    "extraction pass; (3) cleanroom elastomer supplier bottleneck -> dual-source framework agreement required."
                ),
            },
            {
                "phase": 5,
                "stage_code": "technical_architecture",
                "title": "Phase 5 — On-Premises Architecture & ERP Integration",
                "agent_id": "senior_fullstack_engineer",
                "agent_handle": "@senior_fullstack_engineer",
                "agent_name": "Lukas (Senior Fullstack Engineer)",
                "model": "ollama/qwen2.5-coder:32b-instruct-q4_K_M",
                "summary": (
                    "Specifies dual RTX 6000 Ada local Ollama cluster (`qwen2.5-coder:32b` + `llama3.3:70b`) paired with "
                    "OmniRoute circuit-breakers, physical per-tenant SQLite WAL isolation (`data/tenants/mittelstand-muster-gmbh/erp.db`), "
                    "and deterministic DATEV XML/CSV ledger export."
                ),
            },
            {
                "phase": 6,
                "stage_code": "chairman_synthesis",
                "title": "Phase 6 — Chairman Synthesis, Governance Resolution & ROI Table",
                "agent_id": "executive_decision_architect",
                "agent_handle": "@executive_decision_architect",
                "agent_name": "Chairman Synthesis (@executive_decision_architect)",
                "model": "ollama/llama3.3:70b-instruct",
                "summary": (
                    "UNANIMOUS CONDITIONAL GO: Release Tranche 1 (€180,000) immediately for on-prem zero-egress RFQ "
                    "automation and Benelux OEM pilot quotes; gate Tranche 2 (€240,000) on >= €450,000 signed Benelux "
                    "orders at >= 32% gross margin."
                ),
            },
        ]
        roi_table = [
            {
                "metric": "Engineering RFQ Quote Turnaround",
                "baseline_2025": "6.5 business days",
                "archon_target_2026": "3.8 hours (incl. 4-eyes gate)",
                "impact": "-92% lead time",
            },
            {
                "metric": "Monthly AI & Agent SaaS Spend (70 Specialists)",
                "baseline_2025": "€4,634.80 / mo (cloud seats)",
                "archon_target_2026": "€14.80 / mo (Ollama + OmniRoute)",
                "impact": "€55,262 / yr saved",
            },
            {
                "metric": "Year-1 Incremental Contribution Margin (Benelux)",
                "baseline_2025": "€0 (DACH baseline only)",
                "archon_target_2026": "+€685,000 gross margin",
                "impact": "11.4-month payback",
            },
            {
                "metric": "GDPR / TISAX AL3 / EU AI Act Cloud Data Egress",
                "baseline_2025": "High (external cloud wrappers)",
                "archon_target_2026": "0 bytes (Zero-Egress On-Prem)",
                "impact": "100% GoBD & audit compliant",
            },
        ]
        synthesis_md = (
            "### Board Resolution: **CONDITIONAL GO (90-Day Execution Charter)**\n\n"
            "1. **Immediate Deployment (Weeks 1–4):** Launch the local zero-egress RFQ-to-ERP pipeline "
            "(`@senior_fullstack_engineer`) with a hard ERP margin floor of **31.0% contribution margin** (`@finance_lead`).\n"
            "2. **Governance & EU AI Act Controls (Weeks 2–5):** Enforce mandatory **4-eyes human approval** "
            "prior to dispatching any quote > €15,000 net and seal all ERP documents with SHA-256 GoBD Merkle hashes (`@commercial_jurist_contracts`).\n"
            "3. **Red-Team Preconditions (Before Tranche 2):** Deploy tool-isolated PDF sanitization against "
            "indirect prompt injection and sign a secondary cleanroom elastomer supplier (`@red_team_challenger`).\n\n"
            "| KPI / Governance Dimension | 2025 Baseline | 2026 Archon OS Target | Verified Impact |\n"
            "|---|---|---|---|\n"
            + "\n".join(
                f"| **{r['metric']}** | {r['baseline_2025']} | {r['archon_target_2026']} | **{r['impact']}** |"
                for r in roi_table
            )
        )

    transcript_blocks = [
        f"#### {p['title']}\n**{p['agent_name']} (`{p['agent_handle']}` · `{p['model']}`)**\n\n{p['summary']}"
        for p in phases
    ]
    return {
        "id": "deb_m47_mittelstand_eu_ai_act",
        "timestamp": "2026-11-12T09:30:00",
        "date_display": "12.11.2026 · 09:30 Uhr" if is_de else "2026-11-12 · 09:30 CET",
        "task": task,
        "framework": "6-Phase Adversarial C-Level Boardroom (McKinsey + Pre-Mortem + EU AI Act)",
        "chairman": "Robert — Executive Decision Architect (@executive_decision_architect)",
        "chairman_id": "executive_decision_architect",
        "use_moa": True,
        "rounds": 6,
        "slots_count": 5,
        "participants": [
            "@executive_decision_architect",
            "@finance_lead",
            "@commercial_jurist_contracts",
            "@red_team_challenger",
            "@senior_fullstack_engineer",
        ],
        "slots": [
            {"id": "executive_decision_architect", "name": "Robert", "role": "Executive Decision Architect", "model": "ollama/llama3.3:70b-instruct"},
            {"id": "finance_lead", "name": "Clara", "role": "Finance Lead", "model": "ollama/llama3.3:70b-instruct"},
            {"id": "commercial_jurist_contracts", "name": "Dr. Henrik Vogt", "role": "Commercial Jurist & Contracts", "model": "ollama/llama3.3:70b-instruct"},
            {"id": "red_team_challenger", "name": "Viktor", "role": "Red-Team Challenger", "model": "omniroute/eu-sovereign-reasoning"},
            {"id": "senior_fullstack_engineer", "name": "Lukas", "role": "Senior Fullstack Engineer", "model": "ollama/qwen2.5-coder:32b-instruct-q4_K_M"},
        ],
        "phases": phases,
        "roi_table": roi_table,
        "transcript": "\n\n---\n\n".join(transcript_blocks),
        "synthesis": synthesis_md,
        "vault_file": "boardroom_debatte_mittelstand_muster_2026.md",
        "demo_mode": True,
        "zero_token_cost": True,
    }


def _build_kanban_tasks(lang: str) -> List[Dict[str, Any]]:
    is_de = lang == "de"
    rows = [
        {
            "id": "kan-m47-01",
            "status": "done",
            "priority": 3,
            "assignee": "commercial_jurist_contracts",
            "assignee_handle": "@commercial_jurist_contracts",
            "domain": "Legal & Governance",
            "title_en": "EU AI Act Art. 14 & Art. 50 Compliance Dossier for RFQ Automation",
            "title_de": "EU-AI-Act Art. 14 & Art. 50 Compliance-Dossier für RFQ-Automatisierung",
            "desc_en": "Completed risk classification, human-in-the-loop gate protocol, and TISAX AL3 zero-egress attestation.",
            "desc_de": "Risikoklassifizierung, 4-Augen-Gate-Protokoll und TISAX-AL3-Zero-Egress-Nachweis abgeschlossen.",
            "created_at": "2026-11-08T10:15:00",
        },
        {
            "id": "kan-m47-02",
            "status": "done",
            "priority": 3,
            "assignee": "finance_lead",
            "assignee_handle": "@finance_lead",
            "domain": "Finance & Controlling",
            "title_en": "36-Month CAPEX/EBITDA Sensitivity Model & 31% ERP Margin Floor",
            "title_de": "36-Monats-CAPEX/EBITDA-Modell & harte 31-%-ERP-Mindestmarge",
            "desc_en": "Verified 11.4-month payback and configured automated gross-margin guardrails in Mini-ERP.",
            "desc_de": "Amortisation von 11,4 Monaten verifiziert und automatische Deckungsbeitragssperre im Mini-ERP hinterlegt.",
            "created_at": "2026-11-09T14:20:00",
        },
        {
            "id": "kan-m47-03",
            "status": "review",
            "priority": 3,
            "assignee": "red_team_challenger",
            "assignee_handle": "@red_team_challenger",
            "domain": "Security & Red-Team",
            "title_en": "Adversarial Prompt-Injection Audit on External OEM RFQ PDFs",
            "title_de": "Adversarial Prompt-Injection-Audit für externe OEM-Anfrage-PDFs",
            "desc_en": "24 synthetic poisoned CAD/RFQ documents tested against tool-less extraction sandbox; awaiting 4-eyes sign-off.",
            "desc_de": "24 präparierte CAD/RFQ-Testdokumente gegen isolierte Extraktions-Pipeline geprüft; im 4-Augen-Review.",
            "created_at": "2026-11-10T11:05:00",
        },
        {
            "id": "kan-m47-04",
            "status": "review",
            "priority": 2,
            "assignee": "tax_holding_advisor",
            "assignee_handle": "@tax_holding_advisor",
            "domain": "Tax & GoBD",
            "title_en": "FZulG German R&D Tax Credit Application (€94,500 Subsidy Claim)",
            "title_de": "BSFZ-Antrag Forschungszulage FZulG (94.500 € Förderanspruch)",
            "desc_en": "Technical novelty narrative + time-tracking ledger prepared for BSFZ submission.",
            "desc_de": "Technische Neuheitsbegründung und Stundenbuchung für BSFZ-Bescheinigung finalisiert.",
            "created_at": "2026-11-10T16:40:00",
        },
        {
            "id": "kan-m47-05",
            "status": "in_progress",
            "priority": 3,
            "assignee": "senior_fullstack_engineer",
            "assignee_handle": "@senior_fullstack_engineer",
            "domain": "Engineering & AI Ops",
            "title_en": "On-Prem Ollama CAD-Tolerance Extractor -> DATEV/ERP Quote Connector",
            "title_de": "On-Prem Ollama CAD-Toleranz-Extraktor -> DATEV/ERP-Angebots-Connector",
            "desc_en": "Wiring structured JSON tolerance parsing (`qwen2.5-coder:32b`) into `erp_documents` draft quotes.",
            "desc_de": "Anbindung der lokalen JSON-Toleranzextraktion (`qwen2.5-coder:32b`) an `erp_documents`-Angebotsentwürfe.",
            "created_at": "2026-11-11T08:50:00",
        },
        {
            "id": "kan-m47-06",
            "status": "in_progress",
            "priority": 2,
            "assignee": "growth_hacker_lead",
            "assignee_handle": "@growth_hacker_lead",
            "domain": "B2B Sales & Expansion",
            "title_en": "Benelux Semiconductor & MedTech Tier-2 Key-Account Dossiers (Eindhoven)",
            "title_de": "Benelux Halbleiter- & MedTech-Key-Account-Dossiers (Cluster Eindhoven)",
            "desc_en": "Technical buyer mapping and bilingual ISO-14644 cleanroom capability deck for 12 target OEMs.",
            "desc_de": "Entscheider-Mapping und zweisprachiges ISO-14644-Reinraum-Kompetenzdossier für 12 Ziel-OEMs.",
            "created_at": "2026-11-11T13:10:00",
        },
        {
            "id": "kan-m47-07",
            "status": "todo",
            "priority": 2,
            "assignee": "devops_cloud_sec_specialist",
            "assignee_handle": "@devops_cloud_sec_specialist",
            "domain": "Infrastructure & NIS-2",
            "title_en": "Quarterly NIS-2 Backup Restore Drill & Litestream WAL Verification",
            "title_de": "Quartalsweiser NIS-2-Restore-Drill & Litestream-WAL-Prüfung",
            "desc_en": "Verify < 8 min RTO cold restore of encrypted tenant SQLite databases in air-gapped VLAN.",
            "desc_de": "Nachweis < 8 Min. RTO-Kaltstart-Wiederherstellung der verschlüsselten Mandanten-SQLite-DBs.",
            "created_at": "2026-11-12T07:30:00",
        },
        {
            "id": "kan-m47-08",
            "status": "backlog",
            "priority": 1,
            "assignee": "executive_decision_architect",
            "assignee_handle": "@executive_decision_architect",
            "domain": "Strategy & M&A",
            "title_en": "Q2/2027 Nordic Sensor Calibration Bolt-On Acquisition Screening",
            "title_de": "Q2/2027 M&A-Screening: Skandinavisches Kalibrierlabor (Bolt-On)",
            "desc_en": "Long-list evaluation of ISO-17025 accredited calibration labs in Gothenburg and Malmö.",
            "desc_de": "Longlist-Prüfung akkreditierter ISO-17025-Kalibrierlabore in Göteborg und Malmö.",
            "created_at": "2026-11-12T09:00:00",
        },
    ]

    result: List[Dict[str, Any]] = []
    for r in rows:
        title = r["title_de"] if is_de else r["title_en"]
        desc = r["desc_de"] if is_de else r["desc_en"]
        result.append({
            "id": r["id"],
            "title": title,
            "description": desc,
            "body": desc,
            "status": r["status"],
            "priority": r["priority"],
            "assignee": r["assignee"],
            "assignee_handle": r["assignee_handle"],
            "domain": r["domain"],
            "created_at": r["created_at"],
        })
    return result


def _build_crm_contacts(lang: str) -> List[Dict[str, Any]]:
    is_de = lang == "de"
    return [
        {
            "id": "crm-10001",
            "debtor_no": "10001",
            "company": "Aesculap MedTech Systems GmbH",
            "contact_name": "Dr.-Ing. Sabine Krämer",
            "role": "Leiterin Strategischer Einkauf" if is_de else "VP Strategic Procurement",
            "email": "s.kraemer@aesculap-demo.example",
            "city": "Tuttlingen",
            "country": "DE",
            "account_tier": "Enterprise A+",
            "annual_potential_eur": 640_000,
            "gdpr_opt_in": True,
            "rating": 5,
            "assigned_agent": "@executive_decision_architect",
        },
        {
            "id": "crm-10002",
            "debtor_no": "10002",
            "company": "Veldhoven Mechatronics Supply B.V.",
            "contact_name": "Pieter van der Berg",
            "role": "Lead Cleanroom Subsystem Buyer",
            "email": "p.vanderberg@veldhoven-mechatronics.example",
            "city": "Eindhoven",
            "country": "NL",
            "account_tier": "Strategic Expansion A+",
            "annual_potential_eur": 920_000,
            "gdpr_opt_in": True,
            "rating": 5,
            "assigned_agent": "@growth_hacker_lead",
        },
        {
            "id": "crm-10003",
            "debtor_no": "10003",
            "company": "Bosch Rexroth Antriebstechnik Partnerwerk",
            "contact_name": "Dipl.-Wirt.-Ing. Markus Bühler",
            "role": "Werksleiter Montageautomation" if is_de else "Plant Director Assembly Automation",
            "email": "m.buehler@rexroth-partner-demo.example",
            "city": "Lohr am Main",
            "country": "DE",
            "account_tier": "Core Key Account A",
            "annual_potential_eur": 510_000,
            "gdpr_opt_in": True,
            "rating": 5,
            "assigned_agent": "@senior_fullstack_engineer",
        },
        {
            "id": "crm-10004",
            "debtor_no": "10004",
            "company": "Carl Zeiss Industrial Metrology Partner AG",
            "contact_name": "Dr. Katharina Lindner",
            "role": "Head of Optical Sensor Integration",
            "email": "k.lindner@metrology-demo.example",
            "city": "Oberkochen",
            "country": "DE",
            "account_tier": "Core Key Account A",
            "annual_potential_eur": 430_000,
            "gdpr_opt_in": True,
            "rating": 4,
            "assigned_agent": "@finance_lead",
        },
        {
            "id": "crm-10005",
            "debtor_no": "10005",
            "company": "NordicFluidic Diagnostics AB",
            "contact_name": "Astrid Lindqvist",
            "role": "Supply Chain & Quality Director",
            "email": "a.lindqvist@nordicfluidic-demo.example",
            "city": "Gothenburg",
            "country": "SE",
            "account_tier": "Expansion B+",
            "annual_potential_eur": 310_000,
            "gdpr_opt_in": True,
            "rating": 4,
            "assigned_agent": "@commercial_jurist_contracts",
        },
        {
            "id": "crm-10006",
            "debtor_no": "10006",
            "company": "AlpinRail Antriebssysteme GmbH",
            "contact_name": "Ing. Lukas Gruber",
            "role": "Technischer Projekteinkauf" if is_de else "Technical Project Buyer",
            "email": "l.gruber@alpinrail-demo.example",
            "city": "Graz",
            "country": "AT",
            "account_tier": "Mid-Market B+",
            "annual_potential_eur": 275_000,
            "gdpr_opt_in": True,
            "rating": 4,
            "assigned_agent": "@growth_hacker_lead",
        },
    ]


def _build_deals(lang: str) -> List[Dict[str, Any]]:
    is_de = lang == "de"
    raw_deals = [
        {
            "id": "deal-m47-01",
            "title": (
                "ISO-6 Reinraum-Drucksensor-Manifolds (Jahresrahmenabruf)"
                if is_de
                else "ISO-6 Cleanroom Pressure Sensor Manifolds (Annual Frame Order)"
            ),
            "partner_name": "Veldhoven Mechatronics Supply B.V.",
            "contact_email": "p.vanderberg@veldhoven-mechatronics.example",
            "stage": "negotiation",
            "probability": 0.75,
            "deal_value": 380_000.0,
            "currency": "EUR",
            "expected_close_date": "2026-12-05",
            "assigned_agent": "@executive_decision_architect",
            "notes": (
                "EU-AI-Act- & TISAX-Audit bestanden; finale Haftungsobergrenze in Prüfung durch @commercial_jurist_contracts."
                if is_de
                else "Passed TISAX AL3 & zero-egress audit; final liability cap review by @commercial_jurist_contracts."
            ),
        },
        {
            "id": "deal-m47-02",
            "title": (
                "Endoskopie-Titan-Ventilblöcke Serie M8 (1.200 Stk.)"
                if is_de
                else "Endoscopy Titanium Valve Blocks Series M8 (1,200 Units)"
            ),
            "partner_name": "Aesculap MedTech Systems GmbH",
            "contact_email": "s.kraemer@aesculap-demo.example",
            "stage": "closed_won",
            "probability": 1.00,
            "deal_value": 248_500.0,
            "currency": "EUR",
            "expected_close_date": "2026-11-04",
            "assigned_agent": "@finance_lead",
            "notes": (
                "Auftrag gewonnen dank 3,5-Stunden-RFQ-Schnellkalkulation (34,6 % DB I)."
                if is_de
                else "Closed Won via 3.5-hour AI-assisted RFQ turnaround at 34.6% gross margin."
            ),
        },
        {
            "id": "deal-m47-03",
            "title": (
                "Optische Inline-Prüfzellen-Nachrüstung Werk II"
                if is_de
                else "Optical Inline Inspection Cell Retrofit Plant II"
            ),
            "partner_name": "Carl Zeiss Industrial Metrology Partner AG",
            "contact_email": "k.lindner@metrology-demo.example",
            "stage": "proposal",
            "probability": 0.50,
            "deal_value": 195_000.0,
            "currency": "EUR",
            "expected_close_date": "2026-12-18",
            "assigned_agent": "@senior_fullstack_engineer",
            "notes": (
                "Angebot ANG-2026-0418 versendet; technische Demo erfolgreich."
                if is_de
                else "Quote ANG-2026-0418 dispatched; technical benchmark validated."
            ),
        },
        {
            "id": "deal-m47-04",
            "title": (
                "Hydraulik-Präzisionsflansche inkl. 24/7 Predictive-SLA"
                if is_de
                else "Hydraulic Precision Flanges + 24/7 Predictive Maintenance SLA"
            ),
            "partner_name": "Bosch Rexroth Antriebstechnik Partnerwerk",
            "contact_email": "m.buehler@rexroth-partner-demo.example",
            "stage": "discovery",
            "probability": 0.25,
            "deal_value": 164_000.0,
            "currency": "EUR",
            "expected_close_date": "2027-01-22",
            "assigned_agent": "@growth_hacker_lead",
            "notes": (
                "CAD-Zeichnungssatz im lokalen Zero-Egress-Vault zur Toleranzprüfung."
                if is_de
                else "STEP/CAD drawing package ingested into local zero-egress vault for tolerance analysis."
            ),
        },
        {
            "id": "deal-m47-05",
            "title": (
                "Mikrofluidik-Dosierköpfe Pilotserie Skandinavien"
                if is_de
                else "Microfluidic Dosing Heads Pilot Lot Nordics"
            ),
            "partner_name": "NordicFluidic Diagnostics AB",
            "contact_email": "a.lindqvist@nordicfluidic-demo.example",
            "stage": "lead",
            "probability": 0.10,
            "deal_value": 112_000.0,
            "currency": "EUR",
            "expected_close_date": "2027-02-14",
            "assigned_agent": "@growth_hacker_lead",
            "notes": (
                "Erstkontakt über Messe-Lead-Workflow; NDA-Vorlage bereitgestellt."
                if is_de
                else "Inbound trade-fair lead; bilingual mutual NDA generated."
            ),
        },
    ]
    for d in raw_deals:
        d["weighted_value"] = round(d["deal_value"] * d["probability"], 2)
    return raw_deals


def _build_invoices(lang: str) -> List[Dict[str, Any]]:
    is_de = lang == "de"
    docs = [
        {
            "id": "RE-2026-1084",
            "doc_number": "RE-2026-1084",
            "doc_type": "invoice",
            "doc_type_label": "Rechnung" if is_de else "Invoice",
            "customer_name": "Aesculap MedTech Systems GmbH",
            "date": "2026-11-05",
            "amount_net": 124_250.00,
            "vat_rate": 19.0,
            "amount_gross": 147_857.50,
            "currency": "EUR",
            "status": "paid",
            "datev_account": "8400 / Deb. 10001",
            "gobd_sha256_preview": _gobd_hash_preview("RE-2026-1084|124250.00|DE298410573"),
        },
        {
            "id": "RE-2026-1089",
            "doc_number": "RE-2026-1089",
            "doc_type": "invoice",
            "doc_type_label": "Rechnung" if is_de else "Invoice",
            "customer_name": "Bosch Rexroth Antriebstechnik Partnerwerk",
            "date": "2026-11-08",
            "amount_net": 68_400.00,
            "vat_rate": 19.0,
            "amount_gross": 81_396.00,
            "currency": "EUR",
            "status": "open",
            "datev_account": "8400 / Deb. 10003",
            "gobd_sha256_preview": _gobd_hash_preview("RE-2026-1089|68400.00|DE298410573"),
        },
        {
            "id": "AB-2026-0742",
            "doc_number": "AB-2026-0742",
            "doc_type": "order_confirmation",
            "doc_type_label": "Auftragsbestätigung" if is_de else "Order Confirmation",
            "customer_name": "Aesculap MedTech Systems GmbH",
            "date": "2026-11-04",
            "amount_net": 124_250.00,
            "vat_rate": 19.0,
            "amount_gross": 147_857.50,
            "currency": "EUR",
            "status": "confirmed",
            "datev_account": "8400 / Deb. 10001",
            "gobd_sha256_preview": _gobd_hash_preview("AB-2026-0742|124250.00|DE298410573"),
        },
        {
            "id": "ANG-2026-0418",
            "doc_number": "ANG-2026-0418",
            "doc_type": "offer",
            "doc_type_label": "Angebot" if is_de else "Quote",
            "customer_name": "Carl Zeiss Industrial Metrology Partner AG",
            "date": "2026-11-10",
            "amount_net": 195_000.00,
            "vat_rate": 19.0,
            "amount_gross": 232_050.00,
            "currency": "EUR",
            "status": "sent",
            "datev_account": "8400 / Deb. 10004",
            "gobd_sha256_preview": _gobd_hash_preview("ANG-2026-0418|195000.00|DE298410573"),
        },
        {
            "id": "ANG-2026-0421",
            "doc_number": "ANG-2026-0421",
            "doc_type": "offer",
            "doc_type_label": "Angebot (EU Reverse-Charge)" if is_de else "Quote (Intra-EU Reverse Charge)",
            "customer_name": "Veldhoven Mechatronics Supply B.V.",
            "date": "2026-11-11",
            "amount_net": 380_000.00,
            "vat_rate": 0.0,
            "amount_gross": 380_000.00,
            "currency": "EUR",
            "status": "approval_gate",
            "datev_account": "8125 / Deb. 10002",
            "gobd_sha256_preview": _gobd_hash_preview("ANG-2026-0421|380000.00|NL-REVERSE-CHARGE"),
        },
    ]
    return docs


def get_demo_status(lang: str = "en") -> Dict[str, Any]:
    """Return current demo mode status, tenant summary, locked features, and GitHub repo URL."""
    norm_lang = normalize_demo_lang(lang)
    is_de = norm_lang == "de"
    company = _build_company_data(norm_lang)
    locked = (
        [
            "Code-Sandbox & Subprozess-Ausführung (/api/sandbox)",
            "Docker-Container-Steuerung & Logs (/api/v1/container, /api/docker)",
            "System-Updater & Selbstmodifikation (/api/v1/system/update)",
            "Roh-Konfiguration & API-Schlüssel (/api/hermes/raw_config)",
            "Reverse-Proxies & externer Netzwerk-Egress (/n8n-proxy, /omniroute-proxy, /api/proxy)",
            "Persistente Datenbank-, Vault- & Datei-Schreibzugriffe (POST/PUT/DELETE/PATCH)",
        ]
        if is_de
        else [
            "Code Sandbox & Subprocess Execution (/api/sandbox)",
            "Docker Container Lifecycle & Logs (/api/v1/container, /api/docker)",
            "System Self-Updater (/api/v1/system/update)",
            "Raw Configuration & Secret Editor (/api/hermes/raw_config)",
            "Reverse Proxies & External Egress (/n8n-proxy, /omniroute-proxy, /api/proxy)",
            "Persistent Database, Vault & File Mutations (POST/PUT/DELETE/PATCH)",
        ]
    )
    return {
        "demo_mode": is_demo_mode(),
        "read_only": True,
        "zero_token_cost": True,
        "zero_egress": True,
        "lang": norm_lang,
        "repo_url": DEMO_REPO_URL,
        "tenant": {
            "id": company["id"],
            "name": company["name"],
            "legal_name": company["legal_name"],
            "headquarters": company["headquarters"],
            "employees": company["employees"],
            "annual_revenue_eur": company["annual_revenue_eur"],
        },
        "locked_features": locked,
        "interactive_previews": [
            "/api/quickchat",
            "/api/chat",
            "/api/agent-chat",
            "/api/boardroom/run",
            "/api/templates/",
            "/api/demo/showcase",
        ],
        "banner_text": (
            "LIVE-DEMO-MODUS (Schreibgeschützt · Mittelstand Muster GmbH · Null Token-Kosten) — "
            "Auf GitHub klonen für volle autonome Ausführung"
            if is_de
            else "LIVE DEMO MODE (Read-Only · Mittelstand Muster GmbH · Zero Token Cost) — "
            "Clone on GitHub for full autonomous execution"
        ),
    }


def get_demo_showcase(lang: str = "en") -> Dict[str, Any]:
    """Return the complete bilingual showcase bundle for 'Mittelstand Muster GmbH'."""
    norm_lang = normalize_demo_lang(lang)
    company = _build_company_data(norm_lang)
    telemetry = _build_telemetry_metrics(norm_lang)
    company["telemetry"] = telemetry
    company["cost_guard"] = {
        "monthly_saas_saved_eur": telemetry["monthly_saas_cost_avoided_eur"],
        "monthly_api_spend_eur": telemetry["monthly_llm_api_spend_eur"],
        "local_ollama_pct": telemetry["local_ollama_share_pct"],
        "omniroute_pct": telemetry["omniroute_smart_free_share_pct"],
        "demo_live_cost_eur": 0.0,
    }
    debate = _build_boardroom_debate(norm_lang)
    kanban_tasks = _build_kanban_tasks(norm_lang)
    crm_contacts = _build_crm_contacts(norm_lang)
    deals = _build_deals(norm_lang)
    invoices = _build_invoices(norm_lang)

    return {
        "demo_mode": is_demo_mode(),
        "lang": norm_lang,
        "repo_url": DEMO_REPO_URL,
        "zero_token_cost": True,
        "company": copy.deepcopy(company),
        "telemetry": copy.deepcopy(telemetry),
        "boardroom_debates": [copy.deepcopy(debate)],
        "kanban_tasks": copy.deepcopy(kanban_tasks),
        "crm_contacts": copy.deepcopy(crm_contacts),
        "deals": copy.deepcopy(deals),
        "invoices": copy.deepcopy(invoices),
    }


# ---------------------------------------------------------------------------
# Deterministic Zero-Token Chat & Template Simulator
# ---------------------------------------------------------------------------

def build_demo_chat_response(prompt: str, agent_id: str = "default", lang: str = "en") -> str:
    """
    Generate a deterministic, specialist-flavored Markdown response with zero LLM
    egress and zero token cost. Always includes `[DEMO SIMULATION — Zero Token Cost]`.
    """
    norm_lang = normalize_demo_lang(lang)
    is_de = norm_lang == "de"
    clean_agent = (agent_id or "default").strip().lstrip("@") or "default"
    clean_prompt = (prompt or "").strip()
    excerpt = clean_prompt[:140] + ("..." if len(clean_prompt) > 140 else "")
    if not excerpt:
        excerpt = "Strategische Statusabfrage" if is_de else "Strategic status inquiry"

    meta = _SPECIALIST_META.get(clean_agent)
    if not meta:
        pretty_id = clean_agent.replace("_", " ").title()
        meta = {
            "name_en": f"{pretty_id} (@{clean_agent})",
            "name_de": f"{pretty_id} (@{clean_agent})",
            "role_en": "Archon OS Domain Specialist",
            "role_de": "Archon OS Fach-Spezialist",
            "focus_en": "structured enterprise execution, GoBD auditability, and zero-egress data sovereignty",
            "focus_de": "strukturierte Fachausführung, GoBD-Prüfsicherheit und Zero-Egress-Datensouveränität",
        }

    digest = hashlib.sha256(f"{clean_agent}|{norm_lang}|{clean_prompt}".encode("utf-8")).hexdigest()[:10]

    if is_de:
        return (
            f"> **[DEMO SIMULATION — Zero Token Cost]** · Deterministische Vorschau (`trace:{digest}` · `0,00 €` API-Kosten)\n\n"
            f"### {meta['name_de']}\n"
            f"**Rolle:** {meta['role_de']} · **Mandant:** *Mittelstand Muster GmbH*\n\n"
            f"**Analysierte Anfrage:** `{excerpt}`\n\n"
            f"1. **Fachliche Ersteinschätzung:** Aus Perspektive von `@{clean_agent}` ({meta['focus_de']}) greift hier "
            f"unser Stuttgarter Referenzmodell: 78,4 % lokale Ollama-Verarbeitung ohne Cloud-Datenabfluss, abgesichert "
            f"durch eine harte ERP-Mindestmarge von **31,0 % DB I**.\n"
            f"2. **Governance & EU AI Act:** Vor jeder externen Freigabe (Angebote > 15.000 €, Verträge, DATEV-Export) "
            f"erzwingt Archon OS ein **4-Augen-Freigabe-Gate** inklusive unveränderlichem SHA-256-GoBD-Beleghash.\n"
            f"3. **Vollversion lokal starten:** In dieser öffentlichen Live-Demo sind echte LLM-Aufrufe und "
            f"Schreibzugriffe gesperrt. Klonen Sie **[ARCHON-OS auf GitHub]({DEMO_REPO_URL})**, um alle 70 Spezialisten "
            f"mit Ollama, OmniRoute oder eigenen API-Keys produktiv auszuführen."
        )

    return (
        f"> **[DEMO SIMULATION — Zero Token Cost]** · Deterministic Live Preview (`trace:{digest}` · `€0.00` API spend)\n\n"
        f"### {meta['name_en']}\n"
        f"**Role:** {meta['role_en']} · **Tenant:** *Mittelstand Muster Precision GmbH*\n\n"
        f"**Evaluated Prompt:** `{excerpt}`\n\n"
        f"1. **Specialist Assessment:** Evaluating from `@{clean_agent}`'s mandate ({meta['focus_en']}), "
        f"this workflow maps directly to our sovereign reference stack: 78.4% local Ollama execution (`PRIVACY_ZERO_EGRESS=true`) "
        f"paired with a hard **31.0% contribution-margin guardrail** in Mini-ERP.\n"
        f"2. **Governance & Audit Trail:** Any external commitment (quotes > €15,000 net, legal DPAs, DATEV ledger export) "
        f"halts at Archon's **4-Eyes Human Approval Gate** and records an immutable SHA-256 GoBD Merkle hash.\n"
        f"3. **Run Full Autonomous Execution:** Live LLM egress and disk writes are disabled on this public showcase node. "
        f"Clone **[ARCHON-OS on GitHub]({DEMO_REPO_URL})** to run all 70 specialists locally with Ollama, OmniRoute, or your own keys."
    )


def _render_demo_template_preview(path: str, payload: Dict[str, Any], lang: str) -> Dict[str, Any]:
    """Deterministic, zero-write renderer for `/api/templates/...` POST previews."""
    norm_lang = normalize_demo_lang(lang)
    raw_values = payload.get("values")
    values: Dict[str, Any] = raw_values if isinstance(raw_values, dict) else {}
    raw_prompt = str(payload.get("prompt") or "").strip()
    parts = [p for p in path.strip("/").split("/") if p]
    slug = parts[2] if len(parts) >= 3 and parts[2] not in ("render", "optimize") else "enterprise-template"

    kv_lines = [f"- **{k}**: {v}" for k, v in sorted(values.items()) if str(v).strip()]
    vars_block = "\n".join(kv_lines) if kv_lines else (
        "- **Mandant**: Mittelstand Muster GmbH\n- **Ziel**: Zero-Egress RFQ- & Governance-Prüfung"
        if norm_lang == "de"
        else "- **Tenant**: Mittelstand Muster Precision GmbH\n- **Objective**: Zero-Egress RFQ & Governance Audit"
    )
    if raw_prompt:
        vars_block += f"\n- **Input**: {raw_prompt[:240]}"

    rendered = (
        f"# [DEMO SIMULATION — Zero Token Cost] Archon Prompt Studio (`{slug}`)\n\n"
        f"## Context & Parameters\n{vars_block}\n\n"
        f"## Execution Directive\n"
        f"1. Apply First-Principles analysis with explicit quantitative KPIs.\n"
        f"2. Enforce 4-Eyes Approval Gate and GoBD SHA-256 audit traceability.\n"
        f"3. Keep CAD/PII strictly on-premise (`PRIVACY_ZERO_EGRESS=true`)."
    )
    return {
        "status": "ok",
        "demo_mode": True,
        "zero_token_cost": True,
        "template_id": slug,
        "rendered_prompt": rendered,
        "optimized_prompt": rendered,
    }


# ---------------------------------------------------------------------------
# Ephemeral Workspace Seeder (for tmpfs Demo Containers)
# ---------------------------------------------------------------------------

def seed_demo_workspace(target_dir: str, lang: str = "en") -> Dict[str, Any]:
    """
    Pre-populate `boardroom_history.json` and `kanban_cards.json` inside `target_dir`
    so an ephemeral read-only demo container with `tmpfs` mounts boots with rich data.
    """
    norm_lang = normalize_demo_lang(lang)
    os.makedirs(target_dir, exist_ok=True)
    showcase = get_demo_showcase(norm_lang)

    boardroom_path = os.path.join(target_dir, "boardroom_history.json")
    kanban_path = os.path.join(target_dir, "kanban_cards.json")

    with open(boardroom_path, "w", encoding="utf-8") as fh:
        json.dump(showcase["boardroom_debates"], fh, indent=2, ensure_ascii=False)

    with open(kanban_path, "w", encoding="utf-8") as fh:
        json.dump(showcase["kanban_tasks"], fh, indent=2, ensure_ascii=False)

    return {
        "target_dir": target_dir,
        "lang": norm_lang,
        "boardroom_history_path": boardroom_path,
        "kanban_cards_path": kanban_path,
        "boardroom_count": len(showcase["boardroom_debates"]),
        "kanban_count": len(showcase["kanban_tasks"]),
    }


# ---------------------------------------------------------------------------
# Pure ASGI DemoModeMiddleware
# ---------------------------------------------------------------------------

def _matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _is_hard_blocked_path(path: str) -> bool:
    norm = path or "/"
    return any(_matches_prefix(norm, p) for p in DEMO_HARD_BLOCKED_PREFIXES)


def _detect_scope_lang(scope: Dict[str, Any], body_data: Optional[Dict[str, Any]] = None) -> str:
    if body_data and isinstance(body_data.get("lang"), str):
        return normalize_demo_lang(body_data["lang"])

    qs_bytes = scope.get("query_string") or b""
    if qs_bytes:
        parsed = parse_qs(qs_bytes.decode("latin-1", errors="ignore"))
        if "lang" in parsed and parsed["lang"]:
            return normalize_demo_lang(parsed["lang"][0])

    for k, v in scope.get("headers") or ():
        if k.lower() == b"accept-language":
            header_val = v.decode("latin-1", errors="ignore").strip().lower()
            if header_val.startswith("de") or ",de" in header_val:
                return "de"
            if header_val.startswith("en"):
                return "en"
    return normalize_demo_lang(None)


def _header_value(scope: Dict[str, Any], header_name: bytes) -> str:
    target = header_name.lower()
    for k, v in scope.get("headers") or ():
        if k.lower() == target:
            return v.decode("latin-1", errors="ignore")
    return ""


async def _read_json_body(receive: Callable[..., Any], max_bytes: int = 65_536) -> Dict[str, Any]:
    chunks: List[bytes] = []
    total = 0
    while True:
        message = await receive()
        msg_type = message.get("type")
        if msg_type == "http.disconnect":
            break
        body = message.get("body", b"")
        if body and total < max_bytes:
            take = body[: max_bytes - total]
            chunks.append(take)
            total += len(take)
        if not message.get("more_body", False):
            break
    if not chunks:
        return {}
    try:
        parsed = json.loads(b"".join(chunks).decode("utf-8", errors="ignore"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


async def _send_json(
    send: Callable[..., Any],
    status_code: int,
    payload: Dict[str, Any],
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        (b"content-type", b"application/json; charset=utf-8"),
        (b"content-length", str(len(body)).encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"x-archon-demo-mode", b"true"),
    ]
    await send({"type": "http.response.start", "status": status_code, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _send_sse(send: Callable[..., Any], events: List[Dict[str, Any]]) -> None:
    lines = [f"data: {json.dumps(ev, ensure_ascii=False)}\n\n" for ev in events]
    body = "".join(lines).encode("utf-8")
    headers = [
        (b"content-type", b"text/event-stream; charset=utf-8"),
        (b"cache-control", b"no-cache"),
        (b"x-accel-buffering", b"no"),
        (b"x-archon-demo-mode", b"true"),
    ]
    await send({"type": "http.response.start", "status": 200, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


class DemoModeMiddleware:
    """
    Pure ASGI guard for `ARCHON_DEMO_MODE=true`.

    - Zero overhead pass-through when `is_demo_mode()` is False.
    - Hard 403 (`demo_blocked`) on sandbox, container, docker, raw_config,
      system update, and reverse-proxy/egress routes across all HTTP methods.
    - Deterministic 200 OK simulation (`zero_token_cost=True`) on interactive
      chat, boardroom, and template preview POST routes (zero LLM calls, zero writes).
    - Strict 403 (`demo_read_only`) on all other POST, PUT, DELETE, PATCH requests.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if not is_demo_mode():
            await self.app(scope, receive, send)
            return

        scope_type = scope.get("type")
        if scope_type == "websocket":
            ws_path = scope.get("path", "")
            if _is_hard_blocked_path(ws_path):
                await send({"type": "websocket.close", "code": 1008})
                return
            await self.app(scope, receive, send)
            return

        if scope_type != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or "/"
        method = (scope.get("method") or "GET").upper()

        # 1. Hard-block dangerous exec / container / secret / proxy paths on ALL methods
        if _is_hard_blocked_path(path):
            lang = _detect_scope_lang(scope)
            msg = (
                f"Sicherheits-Sperre im Live-Demo-Modus: '{path}' ist öffentlich deaktiviert. "
                f"Für lokale Vollversion auf GitHub klonen: {DEMO_REPO_URL}"
                if lang == "de"
                else f"Live Demo security lock: '{path}' is disabled on the public showcase node. "
                f"Clone on GitHub for full local execution: {DEMO_REPO_URL}"
            )
            await _send_json(
                send,
                403,
                {
                    "status": "demo_blocked",
                    "demo_mode": True,
                    "error": "demo_blocked",
                    "detail": msg,
                    "message": msg,
                    "path": path,
                    "method": method,
                    "repo_url": DEMO_REPO_URL,
                },
            )
            return

        # 2. Intercept demo-safe interactive preview POSTs (zero egress, zero disk writes)
        if method == "POST":
            if path in DEMO_SAFE_CHAT_PATHS:
                payload = await _read_json_body(receive)
                lang = _detect_scope_lang(scope, payload)
                agent_id = str(
                    payload.get("agent_id")
                    or payload.get("profile_id")
                    or "default"
                )
                prompt = str(
                    payload.get("message")
                    or payload.get("prompt")
                    or payload.get("content")
                    or ""
                )
                reply_md = build_demo_chat_response(prompt=prompt, agent_id=agent_id, lang=lang)
                clean_id = agent_id.strip().lstrip("@") or "default"
                meta = _SPECIALIST_META.get(clean_id, {})
                agent_name = meta.get("name_de" if lang == "de" else "name_en", clean_id)

                # Browser SSE stream consumer support for /api/chat/stream unless caller requests JSON
                accept = _header_value(scope, b"accept").lower()
                if path == "/api/chat/stream" and "application/json" not in accept:
                    session_id = str(payload.get("session_id") or f"demo_{clean_id}")
                    await _send_sse(
                        send,
                        [
                            {"type": "delta", "delta": reply_md},
                            {"type": "done", "session_id": session_id, "demo_mode": True, "zero_token_cost": True},
                        ],
                    )
                    return

                await _send_json(
                    send,
                    200,
                    {
                        "status": "ok",
                        "demo_mode": True,
                        "zero_token_cost": True,
                        "agent_id": clean_id,
                        "agent_name": agent_name,
                        "reply": reply_md,
                        "content": reply_md,
                        "response": reply_md,
                        "duration": 0.01,
                        "timestamp": "DEMO",
                        "repo_url": DEMO_REPO_URL,
                    },
                )
                return

            if path in DEMO_SAFE_BOARDROOM_PATHS:
                payload = await _read_json_body(receive)
                lang = _detect_scope_lang(scope, payload)
                debate = _build_boardroom_debate(lang)
                custom_task = str(payload.get("task") or "").strip()
                if custom_task:
                    debate["requested_task"] = custom_task
                notice = "[DEMO SIMULATION — Zero Token Cost]"
                if notice not in debate["synthesis"]:
                    debate["synthesis"] = f"> **{notice}**\n\n" + debate["synthesis"]

                accept = _header_value(scope, b"accept").lower()
                if path == "/api/boardroom/stream" and "application/json" not in accept:
                    events: List[Dict[str, Any]] = [
                        {
                            "type": "agent_turn",
                            "round": p["phase"],
                            "agent_id": p["agent_id"],
                            "agent_name": p["agent_name"],
                            "content": p["summary"],
                        }
                        for p in debate["phases"]
                    ]
                    events.append({
                        "type": "done",
                        "transcript": debate["transcript"],
                        "synthesis": debate["synthesis"],
                        "history_id": debate["id"],
                        "demo_mode": True,
                        "zero_token_cost": True,
                    })
                    await _send_sse(send, events)
                    return

                await _send_json(
                    send,
                    200,
                    {
                        "status": "success",
                        "demo_mode": True,
                        "zero_token_cost": True,
                        "history_id": debate["id"],
                        "chairman": {"id": debate["chairman_id"], "name": debate["chairman"]},
                        "framework": debate["framework"],
                        "rounds": debate["rounds"],
                        "phases": debate["phases"],
                        "roi_table": debate["roi_table"],
                        "transcript": debate["transcript"],
                        "synthesis": debate["synthesis"],
                        "repo_url": DEMO_REPO_URL,
                    },
                )
                return

            if path.startswith("/api/templates/"):
                payload = await _read_json_body(receive)
                lang = _detect_scope_lang(scope, payload)
                await _send_json(send, 200, _render_demo_template_preview(path, payload, lang))
                return

        # 3. Block all remaining mutating verbs (POST, PUT, DELETE, PATCH)
        if method in DEMO_MUTATING_METHODS:
            lang = _detect_scope_lang(scope)
            msg = (
                f"Schreibgeschützter Live-Demo-Modus: '{method} {path}' wurde ohne Änderung verworfen. "
                f"Klonen Sie Archon OS auf GitHub für volle Ausführung: {DEMO_REPO_URL}"
                if lang == "de"
                else f"Read-only Live Demo Mode: '{method} {path}' was blocked without disk changes. "
                f"Clone Archon OS on GitHub for full autonomous execution: {DEMO_REPO_URL}"
            )
            await _send_json(
                send,
                403,
                {
                    "status": "demo_read_only",
                    "demo_mode": True,
                    "error": "demo_read_only",
                    "detail": msg,
                    "message": msg,
                    "path": path,
                    "method": method,
                    "repo_url": DEMO_REPO_URL,
                },
            )
            return

        # 4. Pass through safe read-only requests (GET, HEAD, OPTIONS)
        await self.app(scope, receive, send)
