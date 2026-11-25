#!/usr/bin/env python3
import os

# Read the base English index.html
with open("site/index.html", "r", encoding="utf-8") as f:
    base_html = f.read()

# Language configurations
langs = {
    "de": {"name": "Deutsch", "html_lang": "de"},
    "zh": {"name": "中文", "html_lang": "zh-CN"},
    "ja": {"name": "日本語", "html_lang": "ja"},
    "ko": {"name": "한국어", "html_lang": "ko"},
    "ru": {"name": "Русский", "html_lang": "ru"},
    "fr": {"name": "Français", "html_lang": "fr"},
    "es": {"name": "Español", "html_lang": "es"},
    "it": {"name": "Italiano", "html_lang": "it"},
    "nl": {"name": "Nederlands", "html_lang": "nl"},
    "pt": {"name": "Português", "html_lang": "pt"},
}

# Create minimal redirect pages for non-English languages
for code, cfg in langs.items():
    if code == "de":
        continue  # We'll handle German separately
    
    html = f'''<!doctype html>
<html lang="{cfg["html_lang"]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Archon OS — Self-Hosted Multi-Agent OS</title>
<meta name="description" content="Archon OS is a self-hosted, MIT-licensed multi-agent business operating system built on Hermes Agent.">
<link rel="canonical" href="https://michaelbeatman.github.io/ARCHON-OS/{code}/">
<link rel="alternate" hreflang="en" href="https://michaelbeatman.github.io/ARCHON-OS/">
<link rel="alternate" hreflang="de" href="https://michaelbeatman.github.io/ARCHON-OS/de/">
<link rel="alternate" hreflang="zh" href="https://michaelbeatman.github.io/ARCHON-OS/zh/">
<link rel="alternate" hreflang="ja" href="https://michaelbeatman.github.io/ARCHON-OS/ja/">
<link rel="alternate" hreflang="ko" href="https://michaelbeatman.github.io/ARCHON-OS/ko/">
<link rel="alternate" hreflang="ru" href="https://michaelbeatman.github.io/ARCHON-OS/ru/">
<link rel="alternate" hreflang="fr" href="https://michaelbeatman.github.io/ARCHON-OS/fr/">
<link rel="alternate" hreflang="es" href="https://michaelbeatman.github.io/ARCHON-OS/es/">
<link rel="alternate" hreflang="it" href="https://michaelbeatman.github.io/ARCHON-OS/it/">
<link rel="alternate" hreflang="nl" href="https://michaelbeatman.github.io/ARCHON-OS/nl/">
<link rel="alternate" hreflang="pt" href="https://michaelbeatman.github.io/ARCHON-OS/pt/">
<link rel="alternate" hreflang="x-default" href="https://michaelbeatman.github.io/ARCHON-OS/">
<meta http-equiv="refresh" content="0; url=https://michaelbeatman.github.io/ARCHON-OS/">
</head>
<body>
<p>Redirecting to English version... <a href="https://michaelbeatman.github.io/ARCHON-OS/">Archon OS</a></p>
</body>
</html>'''
    with open(f"site/{code}/index.html", "w", encoding="utf-8") as f:
        f.write(html)

print("Created 9 language redirect pages")

# Now create German version (full translation)
# We'll do this by modifying the base HTML
de_html = base_html

# Update meta tags for German
replacements = {
    'lang="en"': 'lang="de"',
    '<title>Archon OS \u2014 Self-Hosted Multi-Agent OS with Zero-Egress, Budget Control & Passkey HITL</title>': '<title>Archon OS \u2014 DSGVO-konformer, Zero-Egress Multi-Agent Business OS</title>',
    'content="Archon OS is a self-hosted, MIT-licensed multi-agent operating system built on Hermes Agent. Features 70 specialist roles, atomic token budget reservations, Zero-Egress local routing, WebAuthn Passkey approvals, and a SHA-256 hash-chained audit log."': 'content="Archon OS ist ein selbstgehostetes, DSGVO- und EU AI Act-konformes Multi-Agenten-Business-OS auf Basis von Hermes Agent. Features: fail-closed Zero-Egress lokales Routing, 70 Spezialisten-Rollen, Atomic BudgetBank Kostenlimits, WebAuthn Passkey-Freigaben, GoBD-bereite SHA-256 Audit-Logs."',
    'content="Archon OS, self-hosted multi-agent framework, AI agent governance, zero-egress LLM routing, OmniRoute, Hermes Agent, WebAuthn passkey HITL, LLM cost control, AI audit log, open source AI workspace"': 'content="Archon OS, DSGVO-konforme KI-Agenten, DSGVO Multi-Agenten OS, Zero-Egress LLM-Routing, EU AI Act Compliance, GoBD KI Audit-Log, selbstgehostetes Multi-Agenten-Framework, KI-Agenten-Governance, OmniRoute, Hermes Agent, WebAuthn Passkey HITL, LLM-Kostenkontrolle"',
    'content="Michael Keller"': 'content="Michael Keller"',
    'href="https://michaelbeatman.github.io/ARCHON-OS/"': 'href="https://michaelbeatman.github.io/ARCHON-OS/de/"',
    'content="Archon OS \u2014 Self-Hosted Multi-Agent OS with Governance & Zero-Egress"': 'content="Archon OS \u2014 DSGVO-konformer Multi-Agent Business OS mit Governance & Zero-Egress"',
    'content="70 specialist agent profiles, atomic pre-dispatch budget control, local-first Zero-Egress routing, Passkey HITL approvals, and SHA-256 tamper-evident audit logs. MIT licensed."': 'content="70 Spezialisten-Profile, atomare Pre-Dispatch Budgetkontrolle, lokales Zero-Egress-Routing, Passkey HITL-Freigaben und SHA-256 manipulationssichere Audit-Logs. MIT-lizenziert."',
    'content="Archon OS \u2014 Self-Hosted Multi-Agent Workspace (MIT)"': 'content="Archon OS \u2014 Selbstgehosteter Multi-Agenten Workspace (MIT)"',
    'content="Self-hosted multi-agent OS with atomic budget control, Zero-Egress routing, Passkey HITL gates, and SHA-256 audit logs."': 'content="Selbstgehostetes Multi-Agenten OS mit atomarer Budgetkontrolle, Zero-Egress-Routing, Passkey HITL-Gates und SHA-256 Audit-Logs."',
    # Hero section
    'A multi-agent workspace that runs on your own server.': 'Ein Multi-Agenten-Workspace, der auf Ihrem eigenen Server l\u00e4uft.',
    'Archon OS extends Hermes Agent into a business operating system: 70 specialist agent profiles across 8 domains, structured debates for decisions, per-model cost control, local-first routing and a hash-chained audit log. Your documents, your Obsidian vault, your models.': 'Archon OS erweitert Hermes Agent zu einem Business-Betriebssystem: 70 spezialisierte Agenten-Profile \u00fcber 8 Dom\u00e4nen, strukturierte Debatten f\u00fcr Entscheidungen, pro-Modell Kostenkontrolle, lokales Routing und ein hash-gekettetes Audit-Log. Ihre Dokumente, Ihr Obsidian Vault, Ihre Modelle.',
    'View on GitHub': 'Auf GitHub ansehen',
    'Deutsches README': 'Deutsches README',
    'Quick start': 'Quick Start',
    # Badges
    'v0.5.7.7 \u00b7 pre-1.0': 'v0.5.7.8 \u00b7 pre-1.0',
    'MIT license': 'MIT Lizenz',
    '70 specialists \u00b7 8 domains': '70 Spezialisten \u00b7 8 Dom\u00e4nen',
    '55 decision frameworks': '55 Entscheidungs-Frameworks',
    'Docker amd64 / arm64': 'Docker amd64 / arm64',
    '11 languages': '11 Sprachen',
    # Sections
    'Inside the cockpit': 'Inside the cockpit',
    'Mission Control dashboard': 'Mission Control Dashboard',
    'Mission Control \u2014 live telemetry, token sparkline & HITL board': 'Mission Control \u2014 Live-Telemetrie, Token-Sparkline & HITL-Board',
    'Agent fleet overview': 'Agenten-Flotten-\u00dcbersicht',
    'Agent fleet \u2014 specialist profiles, OmniRoute binding & live feed': 'Agenten-Flotte \u2014 Spezialisten-Profile, OmniRoute-Bindung & Live-Feed',
    'AI Boardroom debate': 'AI Boardroom Debatte',
    'AI Boardroom \u2014 multi-perspective debate with framework & slots': 'AI Boardroom \u2014 Multi-Perspektiven-Debatte mit Framework & Slots',
    'Visual multi-agent workflow builder': 'Visueller Multi-Agenten Workflow-Builder',
    'Workflows \u2014 visual multi-agent DAG editor with HITL gates': 'Workflows \u2014 visueller Multi-Agenten DAG-Editor mit HITL-Gates',
    'Integrated n8n automation': 'Integrierte n8n-Automation',
    'n8n Automation \u2014 embedded webhook pipelines inside Operations': 'n8n Automation \u2014 eingebettete Webhook-Pipelines in Operations',
    'Org chart and hierarchy': 'Organigramm und Hierarchie',
    'Org hierarchy \u2014 interactive flowchart & approval boundaries': 'Organigramm-Hierarchie \u2014 interaktives Flussdiagramm & Freigabe-Grenzen',
    'What it does': 'Was es kann',
    'AI Boardroom': 'AI Boardroom',
    'Decisions run as isolated multi-perspective debates with critic cross-examination and synthesis, across 55 frameworks from OKR to Pre-Mortem.': 'Entscheidungen laufen als isolierte Multi-Perspektiven-Debatten mit Kritiker-Kreuzverh\u00f6r und Synthese, \u00fcber 55 Frameworks von OKR bis Pre-Mortem.',
    'OmniRoute cost control': 'OmniRoute Kostenkontrolle',
    'A central switchboard routes every request to local (Ollama, LM Studio) or cloud models. Budgets are checked before dispatch and attributed per model and per task.': 'Eine zentrale Weiche leitet jede Anfrage an lokale (Ollama, LM Studio) oder Cloud-Modelle weiter. Budgets werden vor Dispatch gepr\u00fcft und pro Modell und Task attribuiert.',
    'Zero-Egress routing': 'Zero-Egress-Routing',
    'Finance, contract and CRM work stays on local models. Worker containers run in an internal Docker network with no internet route. Fails closed, not open.': 'Finanzen, Vertr\u00e4ge und CRM-Arbeiten bleiben auf lokalen Modellen. Worker-Container laufen in einem internen Docker-Netzwerk ohne Internet-Route. Fail-closed, nicht offen.',
    'Tamper-evident audit log': 'Manipulationssicheres Audit-Log',
    'A SHA-256 hash-chained log records every dispatch, including provider, model and host. Records cannot be altered unnoticed.': 'Ein SHA-256 hash-gekettetes Log erfasst jeden Dispatch, inklusive Provider, Modell und Host. Eintr\u00e4ge k\u00f6nnen nicht unbemerkt ver\u00e4ndert werden.',
    'Obsidian vault + RAG': 'Obsidian Vault + RAG',
    'Your vault is the knowledge base. Documents and scans are OCR-read, converted to Markdown and indexed into AnythingLLM/Chroma \u2014 locally.': 'Ihr Vault ist die Wissensbasis. Dokumente und Scans werden per OCR eingelesen, in Markdown konvertiert und in AnythingLLM/Chroma indexiert \u2014 lokal.',
    'Kanban with approval gates': 'Kanban mit Freigabe-Gates',
    'Tasks move through a four-eyes gate: approve, reject with a reason, or escalate on expiry. Email triage, CRM and an ERP suite (alpha) sit on top.': 'Tasks durchlaufen ein Vier-Augen-Gate: genehmigen, ablehnen mit Begr\u00fcndung oder eskalieren bei Timeout. E-Mail-Triage, CRM und ERP-Suite (Alpha) oben drauf.',
    '24/7 liveness & self-healing': '24/7 Liveness & Self-Healing',
    'An async event-loop heartbeat feeds <code>/livez</code> (503 on stall) and Docker auto-restart, backed by an optional external dead-man-switch webhook.': 'Ein asynchroner Event-Loop-Heartbeat speist <code>/livez</code> (503 bei Stillstand) und Docker Auto-Restart, unterst\u00fctzt durch optionalen externen Dead-Man-Switch-Webhook.',
    'Hardened & traced': 'Geh\u00e4rtet & Getraced',
    'SSRF and prompt-injection guards, distributed trace IDs across agent calls, and batched UI rendering for large prompt catalogs.': 'SSRF- und Prompt-Injection-Guards, verteilte Trace-IDs \u00fcber Agenten-Aufrufe, gebatchtes UI-Rendering f\u00fcr große Prompt-Kataloge.',
    'Telegram, Email & CRM': 'Telegram, E-Mail & CRM',
    'Triage incoming emails and Telegram messages into Kanban tasks, sync contacts, and manage quotes and contracts in one workspace.': 'Eingehende E-Mails und Telegram-Nachrichten in Kanban-Tasks triagieren, Kontakte synchronisieren, Angebote und Vertr\u00e4ge in einem Workspace verwalten.',
    # v0.5.7 features
    'Passkey / WebAuthn HITL': 'Passkey / WebAuthn HITL',
    'High-risk approvals (payments, budget overruns, destructive actions) require cryptographic signatures via Windows Hello, Touch ID, or hardware passkeys. Models cannot forge approvals.': 'Hochrisiko-Freigaben (Zahlungen, Budget-\u00dcberschreitungen, destruktive Aktionen) erfordern kryptografische Signaturen via Windows Hello, Touch ID oder Hardware-Passkeys. Modelle k\u00f6nnen Freigaben nicht f\u00e4lschen.',
    'Atomic BudgetBank & Signed Warrants': 'Atomic BudgetBank & Signierte Warrants',
    'Token and cost budgets are reserved transactionally before execution (BEGIN IMMEDIATE). Privileged tools require time-bound HMAC-SHA256 warrants.': 'Token- und Kostenbudgets werden transaktional vor Execution reserviert (BEGIN IMMEDIATE). Privilegierte Tools erfordern zeitlich begrenzte HMAC-SHA256 Warrants.',
    'Crash-Safe Effect-Ledger': 'Crash-Sicherer Effect-Ledger',
    'External side effects are tracked in a transactional ledger with idempotency keys and mandatory reconciliation after unknown states \u2014 preventing duplicate actions.': 'Externe Seiteneffekte werden in einem transaktionalen Ledger mit Idempotency-Keys und verpflichtender Reconciliation nach unbekannten Zust\u00e4nden verfolgt \u2014 verhindert doppelte Aktionen.',
    # Fleet table
    'The 70-specialist fleet \u2014 8 domains': 'Die 70-Spezialisten-Flotte \u2014 8 Dom\u00e4nen',
    'Domain': 'Dom\u00e4ne',
    'Count': 'Anzahl',
    'Focus': 'Fokus',
    'Strategy, Leadership & Life': 'Strategie, Leadership & Leben',
    'CEO copilot, OKRs, M&A decisions, cross-domain synthesis and final QA': 'CEO-Copilot, OKRs, M&A-Entscheidungen, dom\u00e4nen-\u00fcbergreifende Synthese & finales QA',
    'Law, Tax, Finance & Insurance': 'Recht, Steuern, Finanzen & Versicherungen',
    'Contracts, GDPR, IP, holdings, debt financing \u2014 with a mandatory legal/tax warning dialog': 'Vertr\u00e4ge, DSGVO, IP, Holdings, Fremdfinanzierung \u2014 mit obligatorischem Rechts/Steuer-Warn-Dialog',
    'Sales, CRM, Marketing & Growth': 'Vertrieb, CRM, Marketing & Wachstum',
    'B2B outreach, pricing, SEO/GEO, paid ads, retention': 'B2B-Outreach, Pricing, SEO/GEO, Paid Ads, Retention',
    'Creation, Media & Content': 'Kreation, Medien & Content',
    'Copywriting, video scripts, keynotes, UI/UX brand design': 'Copywriting, Video-Skripte, Keynotes, UI/UX Brand Design',
    'Tech, Software, Data & QA': 'Technik, Software, Daten & QA',
    'Fullstack architecture, DevOps/CloudSec, database tuning, test automation': 'Fullstack-Architektur, DevOps/CloudSec, DB-Tuning, Testautomatisierung',
    'Commerce, Procurement & E-Commerce': 'Handel, Beschaffung & E-Commerce',
    'Supply chain, inventory forecasting, vendor negotiation, Shopify': 'Lieferkette, Bestandsprognose, Lieferantenverhandlung, Shopify',
    'Real Estate & Construction': 'Immobilien & Bauwesen',
    'DCF valuation, zoning/BauGB, ESG/KfW, construction management': 'DCF-Bewertung, BauGB/Zonierung, ESG/KfW, Bauprojektmanagement',
    'Medicine, Chemistry, Science & Engineering': 'Medizin, Chemie, Wissenschaft & Engineering',
    'Clinical advisor, EU-MDR, REACH, pharma \u2014 regulated-domain guardrails': 'Klinischer Berater, EU-MDR, REACH, Pharma \u2014 regulierte-Dom\u00e4nen-Guardrails',
    # Install
    'Install': 'Installation',
    'Full stack': 'Full Stack',
    'Six containers: Archon OS, Hermes Agent, AnythingLLM, Chroma, OmniRoute, Docker socket proxy.': 'Sechs Container: Archon OS, Hermes Agent, AnythingLLM, Chroma, OmniRoute, Docker Socket Proxy.',
    'Zero-key demo': 'Zero-Key Demo',
    'Read-only showcase without API keys and token cost, for a first look.': 'Read-only Showcase ohne API-Keys und Token-Kosten, f\u00fcr den ersten Blick.',
    'Interactive installers': 'Interaktive Installer',
    '<code>setup.ps1</code> for Windows, <code>install.sh</code> for Linux/macOS, or a structured onboarding prompt for your AI coding agent (<a href="https://github.com/michaelbeatman/ARCHON-OS/blob/main/INSTALL_AGENT.md">INSTALL_AGENT.md</a>).': '<code>setup.ps1</code> f\u00fcr Windows, <code>install.sh</code> f\u00fcr Linux/macOS, oder ein strukturierter Onboarding-Prompt f\u00fcr deinen KI-Coding-Agent (<a href="https://github.com/michaelbeatman/ARCHON-OS/blob/main/INSTALL_AGENT.md">INSTALL_AGENT.md</a>).',
    # Why Archon OS
    'Why Archon OS?': 'Warum Archon OS?',
    'Built for commercial accountability, not toy demos. Unlike prompt-chaining libraries that leave cost caps, data egress, and approval boundaries to custom glue code, Archon OS enforces budget reservations, local-only routing for sensitive data, Passkey approvals, and SHA-256 audit trails out of the box \u2014 on 3 consolidated SQLite WAL databases (<code>ops.db</code>, <code>business.db</code>, <code>memory.db</code>).': 'Entwickelt f\u00fcr kommerzielle Verantwortung und DSGVO-Konformit\u00e4t, nicht f\u00fcr Spielzeug-Demos. Im Gegensatz zu Prompt-Chaining-Bibliotheken, die Kostenlimits, Daten-Egress und Compliance-Grenzen an benutzerdefinierten Klebecode delegieren, setzt Archon OS fail-closed Zero-Egress lokales Routing, Atomic BudgetBank Reservierungen, WebAuthn Passkey-Freigaben, EU AI Act / GoBD Dokumentation und SHA-256 Audit-Trails out of the box durch \u2014 auf 3 konsolidierten SQLite WAL Datenbanken (<code>ops.db</code>, <code>business.db</code>, <code>memory.db</code>).',
    # Honest status
    'Honest status': 'Ehrlicher Status',
    'Pre-1.0. Interfaces and config keys change between releases. The ERP/CRM module is alpha, multi-user role enforcement is still being hardened, and specialist output is decision support, not licensed advice. Issues and PRs are welcome.': 'Pre-1.0. Interfaces und Config-Keys \u00e4ndern sich zwischen Releases. Das ERP/CRM-Modul ist Alpha, Multi-User-Rollen-Erzwingung wird noch geh\u00e4rtet, und Spezialisten-Output ist Entscheidungsunterst\u00fctzung, keine lizenzierte Beratung. Issues und PRs sind willkommen.',
    # Documentation
    'Documentation (English & Deutsch)': 'Dokumentation (Deutsch & Englisch)',
    'Document (EN / DE)': 'Dokument (DE / EN)',
    'Scope': 'Umfang',
    'User & Company Manual (EN, 97 pp.)': 'User & Company Manual (EN, 97 pp.)',
    'Systemhandbuch (DE, 97 S.)': 'Systemhandbuch (DE, 97 S.)',
    'Installation, chapters 1\u201319, five use cases, encryption/GDPR overview, A\u2013Z glossary': 'Installation, Kapitel 1\u201319, f\u00fcnf Use Cases, Verschl\u00fcsselung/DSGVO-\u00dcberblick, A\u2013Z Glossar',
    'Complete Feature List (EN)': 'Complete Feature List (EN)',
    'Featureliste (DE)': 'Featureliste (DE)',
    'Full module catalog, demo mode, first-run wizard, FinOps, security': 'Voller Modulkatalog, Demo-Modus, First-Run-Wizard, FinOps, Security',
    'AI Boardroom: 55 Frameworks (EN)': 'AI Boardroom: 55 Frameworks (EN)',
    '55 Frameworks (DE)': '55 Frameworks (DE)',
    'All 55 decision-engine methodologies, indexed': 'Alle 55 Decision-Engine-Methodologien, indexiert',
    'Roadmap M0\u2013M74': 'Roadmap & Meilensteine (M0\u2013M112+)',
    'Complete milestone plan including governance, prompt compression & approval gates': 'Voller Meilensteinplan inkl. Governance, Prompt-Kompression & Approval-Gates',
    # Footer
    'Built on <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a> by Nous Research': 'Aufgebaut auf <a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a> von Nous Research',
    'Repository': 'Repository',
    'MIT License': 'MIT Lizenz',
    'Disclaimer': 'Disclaimer',
    'Third-party licenses': 'Drittanbieter-Lizenzen',
}

for en, de in replacements.items():
    de_html = de_html.replace(en, de)

# Add hreflang tags to head
hreflang_tags = '''
<link rel="alternate" hreflang="en" href="https://michaelbeatman.github.io/ARCHON-OS/">
<link rel="alternate" hreflang="de" href="https://michaelbeatman.github.io/ARCHON-OS/de/">
<link rel="alternate" hreflang="zh" href="https://michaelbeatman.github.io/ARCHON-OS/zh/">
<link rel="alternate" hreflang="ja" href="https://michaelbeatman.github.io/ARCHON-OS/ja/">
<link rel="alternate" hreflang="ko" href="https://michaelbeatman.github.io/ARCHON-OS/ko/">
<link rel="alternate" hreflang="ru" href="https://michaelbeatman.github.io/ARCHON-OS/ru/">
<link rel="alternate" hreflang="fr" href="https://michaelbeatman.github.io/ARCHON-OS/fr/">
<link rel="alternate" hreflang="es" href="https://michaelbeatman.github.io/ARCHON-OS/es/">
<link rel="alternate" hreflang="it" href="https://michaelbeatman.github.io/ARCHON-OS/it/">
<link rel="alternate" hreflang="nl" href="https://michaelbeatman.github.io/ARCHON-OS/nl/">
<link rel="alternate" hreflang="pt" href="https://michaelbeatman.github.io/ARCHON-OS/pt/">
<link rel="alternate" hreflang="x-default" href="https://michaelbeatman.github.io/ARCHON-OS/">'''

# Insert hreflang tags before </head>
de_html = de_html.replace('</head>', hreflang_tags + '\n</head>')

with open("site/de/index.html", "w", encoding="utf-8") as f:
    f.write(de_html)

print("Created German version with hreflang tags")
PYEOF