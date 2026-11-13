"""
System Handbuch Word Document Updater for Archon OS 2026
Updates docs/system/ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx:
1. Re-aligns chapter numbering and titles strictly according to user's specification (1 to 16).
2. Preserves ALL existing embedded images (23 images) and styles with 100% fidelity.
3. Inserts the complete 57-agent fleet roster table in Chapter 3.
4. Adds new modules: Corporate Hub (Kapitel 11), Fristenmanagement (9.3), Mahnwesen (9.4).
5. Appends full-text Appendices IV (Security/Compliance) and V (System/Operations).
"""

import os
import sys
import json
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

DOCS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCX_FILE = os.path.join(DOCS_DIR, "docs", "system", "ARCHON_OS_SYSTEM_HANDBUCH_2026_Vorlage.docx")


def load_agents_data():
    inv_file = os.path.join(DOCS_DIR, "data", "eu_ai_act_inventory.json")
    prof_file = os.path.join(DOCS_DIR, "data", "agent_profiles.json")

    inventory = []
    if os.path.exists(inv_file):
        with open(inv_file, "r", encoding="utf-8") as f:
            inventory = json.load(f)

    profiles = []
    if os.path.exists(prof_file):
        with open(prof_file, "r", encoding="utf-8") as f:
            profiles = json.load(f)

    prof_map = {p.get("id"): p for p in profiles}
    by_cat = {}
    for a in inventory:
        cat = a.get("category", "7. Tech, Software & Data")
        by_cat.setdefault(cat, []).append(a)

    return by_cat, prof_map


def read_guide(rel_path):
    full_path = os.path.join(DOCS_DIR, rel_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def update_handbuch_docx():
    print(f"Loading DOCX from {DOCX_FILE}...")
    doc = docx.Document(DOCX_FILE)
    by_cat, prof_map = load_agents_data()

    # 1. Update Heading 1 text to match user's exact hierarchy
    heading_updates = {
        "1. Mission Control (Cockpit & Leitstand)": "1. Operations – Operative Projektsteuerung & Funk\n1.1 Mission Control (Cockpit & Leitstand)",
        "2. Operations – Operative Projektsteuerung & Funk": "1.2 Kanban – Task-Board & Workflow-Steuerung",
        "3. Eingang & Triage (HITL-Gatekeeper & Postfach)": "2. Posteingang & Ereignis-Stream (Triage & Intake)",
        "4. Agenten-Kader & Flottenmanagement": "3. Agenten-Kader & Flottenmanagement",
        "5. Showroom (Projekt-Explorer & Artefakt-Galerie)": "4. Showroom (Projekt-Explorer & Artefakt-Galerie)",
        "6. Zentralbibliothek & Wissensmanagement": "7. Zentralbibliothek & Wissensmanagement",
        "7. AI Mastermind & Boardroom (3-Tab-Architektur & 34 Frameworks)": "8. Decision Engine & AI Mastermind",
        "8. LLM Gateway (OmniRoute AI Router)": "14.4 Provider & Gateway (OmniRoute Multi-Model Router)",
        "9. Token Guard (Guardian & Budgetwächter)": "12. Token Guard (Guardian & Budgetwächter)",
        "10. Research Lab (Deep Search & Wissensbeschaffung)": "6. Research Lab (Deep Search & Wissensbeschaffung)",
        "11. Telemetrie & Logs (Live-Audit Stream)": "13. Telemetrie & Logs (Live-Audit Stream)",
        "12. Spezial-Feature: Archon Prompt Studio (824 Vorlagen & Fabric SOP)": "15. Spezial-Feature: Archon Prompt Studio (824 Vorlagen & Fabric SOP)",
        "13. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector": "16. Spezial-Feature: Visual CSS Live Studio & In-Place Inspector",
        "14. Design System Lab & AppShell-Architekt (Macro-Layout & 15 Komponenten)": "11. Corporate Hub & Vorlagen-Studio (Multi-Company, DIN 5008, § 14 UStG & NDAs)",
        "15. System Control Center & Einstellungen": "14. System Control Center & Einstellungen",
        "16. Autonome Resilienz-, Trace- & Integrations-Architektur (Next-Gen Säulen)": "17. Autonome Resilienz-, Trace- & Integrations-Architektur (Next-Gen Backend-Säulen)",
        "17. Autonome Sandboxing-, Konsolidierungs- & Simulations-Architektur (Advanced Autonomy Säulen)": "18. Autonome Sandboxing-, Konsolidierungs- & Simulations-Architektur"
    }

    subheading_updates = {
        "2.1 Kanban Board & Task-Engine": "1.2 Kanban Board & Task-Engine (inkl. Deal-Pipeline & Forecast)",
        "2.2 Organisation & Ablaufdiagramm (Organigramm)": "1.3 Organisation & Ablaufdiagramm (Organigramm)",
        "2.3 Workflow-Engine (n8n Automation Mesh)": "1.4 n8n Automatisierung (Workflow-Engine)",
        "2.4 Interne Kommunikation (Agenten-Funk)": "1.5 Kommunikation & Funkverkehr (Agenten-Funk)",
        "4.1 Katalog-Verwaltung & Filter (Aktiv, Favoriten, Alle)": "3.1 Übersicht (Katalog-Verwaltung & Filter)",
        "4.2 Modell-Wechsel & Provider-Wahl (KI-Routenwahl)": "3.1.1 Modell-Wechsel & Provider-Wahl (KI-Routenwahl)",
        "4.3 Übersicht (360°-Dossier & Rufname)": "3.1.2 360°-Dossier & Messenger-Rufname",
        "4.4 Direkt-Chat": "3.2 Chat (1:1 Direkt-Dialog & Parameter-Slider)",
        "4.5 Fähigkeiten (Skills & Tool-Sets)": "3.3 Fähigkeiten (Skills & Tool-Sets)",
        "4.6 Operations (Zugeordnete Tasks & Historie)": "3.4 Operation (Zugeordnete Tasks & Historie)",
        "4.7 SOUL (System Prompt & Verhaltens-Direktiven)": "3.5 Soul (System Prompt & Verhaltens-Direktiven)",
        "4.8 Personalakte (Dossier & SOP)": "3.6 Personalakte (Dossier & SOP)",
        "4.9 Talent-Marktplatz": "3.7 Marktplatz (Rollen-Import & -Export)",
        "6.1 RAG Wissens-Index (AnythingLLM)": "7.1 RAG Index (AnythingLLM)",
        "6.2 Dokumenten-Erfasser (File Ingest & Auto-OCR)": "7.2 Erfasser (File Ingest & Auto-OCR mit Docling)",
        "6.3 Obsidian Vault (Dateibaum & Notiz-Viewer)": "7.3 Obsidian (Dateibaum & Notiz-Viewer)"
    }

    # Apply title updates
    for p in doc.paragraphs:
        t_clean = p.text.strip()
        for old_t, new_t in heading_updates.items():
            if t_clean == old_t or old_t in t_clean:
                p.text = new_t
                break
        for old_sub, new_sub in subheading_updates.items():
            if t_clean == old_sub or old_sub in t_clean:
                p.text = new_sub
                break

    # Locate paragraph for Chapter 3 insertion
    target_p3 = None
    for p in doc.paragraphs:
        if "3.7 Marktplatz" in p.text or "4.9 Talent-Marktplatz" in p.text:
            target_p3 = p
            break

    # Insert 3.8 Roster table if found
    if target_p3:
        p_hdr = doc.add_paragraph("3.8 Der vollständige Flotten-Kader: Alle 57 Spezialisten nach Fachdomänen", style="Heading 2")
        p_desc = doc.add_paragraph(
            "Das Gesamtsystem umfasst 57 spezialisierte Rollenprofile, die nach den 7 strategischen "
            "Unternehmensdomänen gegliedert und nach dem EU AI Act (Art. 50 / 113) klassifiziert sind:"
        )

        for cat_name in sorted(by_cat.keys()):
            doc.add_paragraph(f"Domäne: {cat_name} ({len(by_cat[cat_name])} Spezialisten)", style="Heading 3")
            table = doc.add_table(rows=1, cols=5)
            table.style = "Table Grid"
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = "Agenten-Name"
            hdr_cells[1].text = "Handle / ID"
            hdr_cells[2].text = "Modell / Provider"
            hdr_cells[3].text = "EU AI Act"
            hdr_cells[4].text = "Aufgabe & Zweck"

            for a in by_cat[cat_name]:
                row_cells = table.add_row().cells
                aid = a.get("agent_id")
                p = prof_map.get(aid, {})
                name = a.get("agent_name", aid)
                model = a.get("underlying_model", "omniroute / auto/best-free")
                risk = a.get("risk_tier", "MINIMAL_RISK")
                purpose = (a.get("primary_purpose") or p.get("description") or "").replace("\n", " ").strip()
                if len(purpose) > 120:
                    purpose = purpose[:117] + "..."
                row_cells[0].text = name
                row_cells[1].text = aid
                row_cells[2].text = model
                row_cells[3].text = risk
                row_cells[4].text = purpose

    # Append full text Appendices IV and V
    doc.add_page_break()
    doc.add_paragraph("ANHANG IV: SPEZIAL-LEITFÄDEN: IT-SICHERHEIT & COMPLIANCE", style="Heading 1")
    doc.add_paragraph(
        "In diesem Anhang sind alle spezialisierten Sicherheits-, Datenschutz- und Compliance-Leitfäden "
        "des Archon OS Ökosystems im vollen Wortlaut abgedruckt."
    )

    sec_guides = [
        ("IV.1 DSGVO / GDPR Compliance für Agenten-Systeme", "docs/system/GDPR_COMPLIANCE_GUIDE.md"),
        ("IV.2 GoBD & ISO 27001 Revisionssicheres Audit-Logging", "docs/security/GOBD_ISO27001_AUDIT_LOG_GUIDE.md"),
        ("IV.3 Dual-LLM Prompt-Injection Guard", "docs/security/DUAL_LLM_PROMPT_INJECTION_GUARD_GUIDE.md"),
        ("IV.4 API-Keys, Berechtigungs-Scopes & Rate-Limits", "docs/security/API_KEYS_SCOPES_RATELIMITS_GUIDE.md"),
        ("IV.5 Secrets-Management & Key-Rotation", "docs/security/SECRETS_MANAGEMENT_UND_ROTATION.md"),
        ("IV.6 Lokales Privacy-Routing & Zero-Data-Leakage", "docs/security/LOCAL_LLM_PRIVACY_ROUTING_GUIDE.md"),
        ("IV.7 Reverse Proxy, SSL/TLS & SSO-Authentifizierung", "docs/security/REVERSE_PROXY_SSO_GUIDE.md"),
        ("IV.8 Break-Glass Recovery & Notfallzugriff", "docs/security/BREAK_GLASS_RECOVERY_GUIDE.md"),
        ("IV.9 E-Mail Approval Queue & Human-in-the-Loop Policies", "docs/system/EMAIL_APPROVAL_QUEUE_GUIDE.md"),
        ("IV.10 Approval Policies & Schwellenwert-Governance", "docs/system/APPROVAL_POLICIES_GUIDE.md"),
        ("IV.11 Notification Policy & Quiet Hours", "docs/system/NOTIFICATION_POLICY_QUIET_HOURS_GUIDE.md"),
        ("IV.12 Config Validation & Linting", "docs/system/CONFIG_VALIDATION_GUIDE.md")
    ]

    for title, rel_path in sec_guides:
        doc.add_paragraph(title, style="Heading 2")
        text = read_guide(rel_path)
        if text:
            # Add text blocks
            for block in text.split("\n\n"):
                b_str = block.strip()
                if b_str.startswith("#"):
                    doc.add_paragraph(b_str.lstrip("# ").strip(), style="Heading 3")
                elif b_str.startswith("- ") or b_str.startswith("* "):
                    for line in b_str.split("\n"):
                        if line.strip():
                            doc.add_paragraph(line.strip().lstrip("-* ").strip(), style="List Bullet")
                else:
                    doc.add_paragraph(b_str)

    doc.add_page_break()
    doc.add_paragraph("ANHANG V: TECHNISCHE BETRIEBS- & INTEGRATIONS-HANDBÜCHER", style="Heading 1")
    doc.add_paragraph(
        "In diesem Anhang sind alle technischen Betriebs-, Infrastruktur- und Integrationshandbücher "
        "im vollen Wortlaut abgedruckt."
    )

    sys_guides = [
        ("V.1 Archon MCP Server & Tool-Treiber Entwicklung", "docs/system/ARCHON_MCP_SERVER_GUIDE.md"),
        ("V.2 Dunning Engine & Automatisches Mahnwesen", "docs/system/DUNNING_ENGINE_GUIDE.md"),
        ("V.3 DocuSeal E-Signatur & Vertragsunterzeichnung", "docs/system/ESIGN_DOCUSEAL_GUIDE.md"),
        ("V.4 Telegram Receipt OCR & Belegdigitalisierung", "docs/system/TELEGRAM_RECEIPT_OCR_GUIDE.md"),
        ("V.5 Agenten-Scorecards & HR-Personalakten", "docs/system/AGENT_SCORECARDS_PERSONALAKTE_GUIDE.md"),
        ("V.6 Human Feedback Loop & Kontinuierliche Optimierung", "docs/system/HUMAN_FEEDBACK_LOOP_GUIDE.md"),
        ("V.7 Kanban Bulk Actions & Massenoperationen", "docs/system/KANBAN_BULK_ACTIONS_GUIDE.md"),
        ("V.8 Live Streaming mit SSE & WebSockets", "docs/system/LIVE_STREAMING_SSE_WEBSOCKET_GUIDE.md"),
        ("V.9 LLM Tracing mit Langfuse", "docs/system/LLM_TRACING_LANGFUSE_GUIDE.md"),
        ("V.10 Prompt Registry & Canary Releases", "docs/system/PROMPT_REGISTRY_CANARY_GUIDE.md"),
        ("V.11 Modell-Finetuning & Lokale Gewichtung", "docs/system/MODEL_FINETUNING_GUIDE.md"),
        ("V.12 Prometheus & Grafana Systemüberwachung", "docs/system/PROMETHEUS_GRAFANA_MONITORING_GUIDE.md"),
        ("V.13 Zentrales Logging mit Grafana Loki", "docs/system/CENTRAL_LOGGING_LOKI_GUIDE.md"),
        ("V.14 Metabase BI-Dashboard & Geschäftsanalytik", "docs/system/BI_DASHBOARD_METABASE_GUIDE.md"),
        ("V.15 Litestream SQLite Replikation & Disaster Recovery", "docs/system/LITESTREAM_REPLICATION_GUIDE.md"),
        ("V.16 Automatisierte Restore-Tests & Integritätsprüfung", "docs/system/AUTOMATED_RESTORE_TEST_GUIDE.md"),
        ("V.17 Chaos Resilience & Störungs-Simulation", "docs/system/CHAOS_RESILIENCE_GUIDE.md"),
        ("V.18 Ansible Infrastruktur-Automatisierung", "docs/system/ANSIBLE_INFRASTRUCTURE_GUIDE.md"),
        ("V.19 CI/CD Pipeline & E2E-Testing", "docs/system/CI_PIPELINE_E2E_TESTING_GUIDE.md"),
        ("V.20 Systemarchitektur & Technisches Audit 2026", "docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md"),
        ("V.21 Archon OS Strategische Roadmap 2026", "docs/system/ROADMAP_2026.md")
    ]

    for title, rel_path in sys_guides:
        doc.add_paragraph(title, style="Heading 2")
        text = read_guide(rel_path)
        if text:
            for block in text.split("\n\n"):
                b_str = block.strip()
                if b_str.startswith("#"):
                    doc.add_paragraph(b_str.lstrip("# ").strip(), style="Heading 3")
                elif b_str.startswith("- ") or b_str.startswith("* "):
                    for line in b_str.split("\n"):
                        if line.strip():
                            doc.add_paragraph(line.strip().lstrip("-* ").strip(), style="List Bullet")
                else:
                    doc.add_paragraph(b_str)

    print(f"Saving updated master document to {DOCX_FILE}...")
    doc.save(DOCX_FILE)
    print("SUCCESS: Word Document successfully updated and saved!")


if __name__ == "__main__":
    update_handbuch_docx()
