"""
backend/workflow_templates.py — Multi-Agent Workflow-Vorlagen-Registry & DAG-Materializer.

Verbindet vordefinierte und benutzerdefinierte Multi-Agent-DAG-Vorlagen
(Inspiriert von Sim / Statewright / OpenFlow) mit:
- `backend/workflow_dag_runner.py` (SQLite WAL DAG-State)
- `kanban.db` + `task_links` + `config/kanban_meta.json` (Kanban, DAW-Gantt & Dependency-Graph)
- Optionalen n8n-Webhook-Triggern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUSTOM_TEMPLATES_PATH = os.path.join(WORKSPACE_DIR, "config", "workflow_templates.json")
_FILE_LOCK = threading.Lock()
logger = logging.getLogger(__name__)

# Paket C / Datenverlust-Schutz: Wenn beim Laden der Custom-Templates ein
# Lese-/Parse-Fehler auftritt (korrupte JSON-Datei), wird dieses Flag gesetzt.
# save_workflow_template / delete_workflow_template verweigern dann den Schreib-
# zugriff (RuntimeError), damit sie die eventuell nur als leer gelesenen
# vorhandenen Daten nicht still mit einer leeren Liste ueberschreiben.
_CUSTOM_TEMPLATES_CORRUPT = False


def _builtin_templates() -> List[Dict[str, Any]]:
    return [
        {
            "id": "content_pipeline_weekly",
            "title": "Wiederkehrende Content-Pipeline",
            "category": "Marketing & Content",
            "description": "Mehrstufiger Redaktions-DAG: Trend-Recherche -> Artikel & Social Draft -> Anti-Slop QA -> HITL-Freigabe & optionaler n8n-Publish.",
            "schedule_hint": "0 8 * * 1",
            "n8n_webhook_hint": "",
            "inputs": [
                {"key": "topic", "label": "Thema / Fokus", "default": "Agentic AI Workflows im Mittelstand"},
                {"key": "channel", "label": "Zielkanal", "default": "LinkedIn + Blog"},
            ],
            "builtin": True,
            "nodes": [
                {
                    "id": "n1_trend",
                    "title": "Trend- & Quellen-Recherche: {{topic}}",
                    "type": "agent",
                    "agent_id": "research",
                    "tool_preset": "research",
                    "soul_mode": "analytical",
                    "prompt": "Recherchiere aktuelle Fakten, Zahlen und Praxisbeispiele zu '{{topic}}' fuer {{channel}}. Liefere 5 belastbare Thesen mit Quellen.",
                    "depends_on": [],
                    "require_hitl": False,
                },
                {
                    "id": "n2_draft",
                    "title": "Content-Draft erstellen ({{channel}})",
                    "type": "agent",
                    "agent_id": "writer",
                    "tool_preset": "minimal",
                    "soul_mode": "creative",
                    "prompt": "Erstelle anhand der Recherche zu '{{topic}}' einen praegnanten Beitrag fuer {{channel}} ohne KI-Floskeln.",
                    "depends_on": ["n1_trend"],
                    "require_hitl": False,
                },
                {
                    "id": "n3_qa",
                    "title": "Faktencheck & Anti-Slop QA",
                    "type": "agent",
                    "agent_id": "qa",
                    "tool_preset": "research",
                    "soul_mode": "strict",
                    "prompt": "Pruefe den Draft zu '{{topic}}' auf sachliche Korrektheit, Lesefluss und entferne generische Marketing-Floskeln.",
                    "depends_on": ["n2_draft"],
                    "require_hitl": False,
                },
                {
                    "id": "n4_publish",
                    "title": "Freigabe-Gate & Veroeffentlichung",
                    "type": "gate",
                    "agent_id": "executive_decision_architect",
                    "tool_preset": "minimal",
                    "soul_mode": "strict",
                    "prompt": "Menschliche Endfreigabe fuer '{{topic}}' ({{channel}}). Nach Freigabe optional via n8n-Webhook publizieren.",
                    "depends_on": ["n3_qa"],
                    "require_hitl": True,
                },
            ],
        },
        {
            "id": "deep_research_dossier",
            "title": "Deep-Research -> Parallel-Analyse -> Dossier",
            "category": "Strategie & Analyse",
            "description": "Fan-Out/Fan-In DAG: Ein Research-Agent definiert den Scope, Technik- und Markt-Agent analysieren parallel, dann Synthese & Abnahme.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [
                {"key": "topic", "label": "Untersuchungsgegenstand", "default": "Self-Hosted Multi-Agent Frameworks 2026"},
            ],
            "builtin": True,
            "nodes": [
                {
                    "id": "n1_scope",
                    "title": "Research-Scope & Leitfragen: {{topic}}",
                    "type": "agent",
                    "agent_id": "research",
                    "tool_preset": "research",
                    "soul_mode": "analytical",
                    "prompt": "Definiere den Untersuchungsrahmen und 6 Schluesselfragen fuer '{{topic}}'.",
                    "depends_on": [],
                    "require_hitl": False,
                },
                {
                    "id": "n2a_tech",
                    "title": "Technik- & Architektur-Deep-Dive",
                    "type": "fanout",
                    "agent_id": "engineer",
                    "tool_preset": "coding",
                    "soul_mode": "analytical",
                    "prompt": "Bewerte Architektur, Skalierbarkeit, Wartungsaufwand und Integrationsrisiken von '{{topic}}'.",
                    "depends_on": ["n1_scope"],
                    "require_hitl": False,
                },
                {
                    "id": "n2b_market",
                    "title": "Kosten-, Markt- & Risiko-Analyse",
                    "type": "fanout",
                    "agent_id": "analyst",
                    "tool_preset": "research",
                    "soul_mode": "strict",
                    "prompt": "Analysiere TCO, Wettbewerber, Lizenzrisiken und Business-Impact fuer '{{topic}}'.",
                    "depends_on": ["n1_scope"],
                    "require_hitl": False,
                },
                {
                    "id": "n3_synth",
                    "title": "Executive Dossier zusammenfuehren",
                    "type": "agent",
                    "agent_id": "writer",
                    "tool_preset": "minimal",
                    "soul_mode": "analytical",
                    "prompt": "Fuehre Technik- und Marktanalyse zu '{{topic}}' in ein entscheidungsreifes Dossier mit klarer Empfehlung zusammen.",
                    "depends_on": ["n2a_tech", "n2b_market"],
                    "require_hitl": False,
                },
                {
                    "id": "n4_gate",
                    "title": "Entscheidungs-Gate (HITL)",
                    "type": "gate",
                    "agent_id": "executive_decision_architect",
                    "tool_preset": "minimal",
                    "soul_mode": "strict",
                    "prompt": "Abschliessende Freigabe des Dossiers zu '{{topic}}' durch den Entscheider.",
                    "depends_on": ["n3_synth"],
                    "require_hitl": True,
                },
            ],
        },
        {
            "id": "lead_to_crm_offer",
            "title": "Lead-Recherche -> CRM-Qualifizierung -> Angebot",
            "category": "Vertrieb & CRM",
            "description": "Vertriebs-Pipeline mit 4 Instanzen: Firmen-Enrichment, ICP-Scoring, massgeschneiderter Angebotsentwurf und HITL-Versandfreigabe.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [
                {"key": "topic", "label": "Zielunternehmen / Lead", "default": "Musterbau GmbH"},
                {"key": "offer_focus", "label": "Leistungsfokus", "default": "KI-Prozessautomatisierung"},
            ],
            "builtin": True,
            "nodes": [
                {
                    "id": "n1_enrich",
                    "title": "Lead- & Firmen-Enrichment: {{topic}}",
                    "type": "agent",
                    "agent_id": "research",
                    "tool_preset": "research",
                    "soul_mode": "analytical",
                    "prompt": "Recherchiere Geschaeftsmodell, Groesse, aktuelle Initiativen und Ansprechpartner fuer '{{topic}}'.",
                    "depends_on": [],
                    "require_hitl": False,
                },
                {
                    "id": "n2_score",
                    "title": "ICP-Qualifizierung & Bedarfs-Check",
                    "type": "agent",
                    "agent_id": "analyst",
                    "tool_preset": "minimal",
                    "soul_mode": "strict",
                    "prompt": "Bewerte den Fit von '{{topic}}' fuer '{{offer_focus}}' (Budget-Signale, Schmerzpunkte, Einwaende).",
                    "depends_on": ["n1_enrich"],
                    "require_hitl": False,
                },
                {
                    "id": "n3_offer",
                    "title": "Angebotsentwurf & Anschreiben",
                    "type": "agent",
                    "agent_id": "writer",
                    "tool_preset": "minimal",
                    "soul_mode": "creative",
                    "prompt": "Erstelle ein konkretes Angebot plus kurzes Anschreiben an '{{topic}}' mit Fokus auf '{{offer_focus}}'.",
                    "depends_on": ["n2_score"],
                    "require_hitl": False,
                },
                {
                    "id": "n4_send_gate",
                    "title": "Versand-Freigabe (HITL)",
                    "type": "gate",
                    "agent_id": "executive_decision_architect",
                    "tool_preset": "minimal",
                    "soul_mode": "strict",
                    "prompt": "Pruefung von Konditionen und Freigabe vor Versand an '{{topic}}'.",
                    "depends_on": ["n3_offer"],
                    "require_hitl": True,
                },
            ],
        },
        {
            "id": "code_review_release",
            "title": "Feature-Audit -> Security & Tests -> Release",
            "category": "Engineering & QA",
            "description": "Paralleler Engineering-DAG: Code-Audit -> Security-Scan & Test-Check parallel -> Release-Freigabe.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [
                {"key": "topic", "label": "Modul / Branch / Feature", "default": "Workflow-DAG-Engine"},
            ],
            "builtin": True,
            "nodes": [
                {
                    "id": "n1_diff",
                    "title": "Code- & Architektur-Review: {{topic}}",
                    "type": "agent",
                    "agent_id": "engineer",
                    "tool_preset": "coding",
                    "soul_mode": "analytical",
                    "prompt": "Pruefe Aenderungen an '{{topic}}' auf Modularitaet, Fehlerbehandlung und API-Kompatibilitaet.",
                    "depends_on": [],
                    "require_hitl": False,
                },
                {
                    "id": "n2a_sec",
                    "title": "Security- & Auth-Pruefung",
                    "type": "fanout",
                    "agent_id": "security",
                    "tool_preset": "coding",
                    "soul_mode": "strict",
                    "prompt": "Pruefe '{{topic}}' auf Input-Validierung, Auth-Gates, Secret-Handling und Injection-Risiken.",
                    "depends_on": ["n1_diff"],
                    "require_hitl": False,
                },
                {
                    "id": "n2b_test",
                    "title": "Test-Coverage & Regression-Check",
                    "type": "fanout",
                    "agent_id": "qa",
                    "tool_preset": "coding",
                    "soul_mode": "strict",
                    "prompt": "Pruefe bestehende Tests fuer '{{topic}}' und identifiziere fehlende Edge-Case-Tests.",
                    "depends_on": ["n1_diff"],
                    "require_hitl": False,
                },
                {
                    "id": "n3_release",
                    "title": "Release-Freigabe (HITL)",
                    "type": "gate",
                    "agent_id": "executive_decision_architect",
                    "tool_preset": "minimal",
                    "soul_mode": "strict",
                    "prompt": "Finale Release-Entscheidung fuer '{{topic}}' auf Basis von Security- und QA-Befund.",
                    "depends_on": ["n2a_sec", "n2b_test"],
                    "require_hitl": True,
                },
            ],
        },
        {
            "id": "invoice_triage_approval",
            "title": "Rechnungseingang -> Pruefung -> Zahlungsfreigabe",
            "category": "Finanzen & Rechnungen",
            "description": "Posteingangs-Workflow: Belegdaten extrahieren, gegen Budget/Leistung pruefen und hinter einem Passkey-HITL-Gate zur Zahlung freigeben.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Rechnung / Lieferant", "default": "Eingangsrechnung"}],
            "builtin": True,
            "nodes": [
                {"id": "inv_extract", "title": "Belegdaten & Positionen extrahieren: {{topic}}", "type": "agent", "agent_id": "analyst", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Extrahiere Rechnungsnummer, Netto/Brutto, USt, IBAN und Leistungszeitraum aus '{{topic}}'.", "expected_output": "Strukturiertes JSON/Markdown mit Pruefsummen", "forbidden_actions": ["Keine Zahlungen, Bestellungen oder Vertraege ausloesen"], "depends_on": [], "require_hitl": False},
                {"id": "inv_check", "title": "Plausibilitaets- & Budget-Check", "type": "agent", "agent_id": "qa", "tool_preset": "research", "soul_mode": "strict", "prompt": "Pruefe Rechnung '{{topic}}' auf Dubletten, Rechenfehler und Budget-Rahmen.", "depends_on": ["inv_extract"], "require_hitl": False},
                {"id": "inv_pay_gate", "title": "Zahlungsfreigabe (Passkey-HITL)", "type": "gate", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Menschliche Zahlungsfreigabe fuer '{{topic}}' nach gepruefter Beleglage.", "depends_on": ["inv_check"], "require_hitl": True},
            ],
        },
        {
            "id": "monthly_cost_audit",
            "title": "Monatlicher KI-Kosten- & Budget-Audit",
            "category": "Finanzen & Rechnungen",
            "description": "Monatlicher Cron-Audit ueber Token-Verbrauch, Modell-Effizienz und Sparpotenziale mit Board-Zusammenfassung.",
            "schedule_hint": "0 8 1 * *",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Abrechnungsmonat", "default": "Aktueller Monat"}],
            "builtin": True,
            "nodes": [
                {"id": "cost_collect", "title": "Nutzungs- & Kostendaten sammeln ({{topic}})", "type": "agent", "agent_id": "analyst", "tool_preset": "research", "soul_mode": "analytical", "prompt": "Analysiere Token-Verbrauch, API-Kosten und Task-Erfolgsquoten fuer '{{topic}}'.", "depends_on": [], "require_hitl": False},
                {"id": "cost_opt", "title": "Routing- & Modell-Optimierung vorschlagen", "type": "agent", "agent_id": "engineer", "tool_preset": "minimal", "soul_mode": "analytical", "prompt": "Identifiziere teure Tasks fuer '{{topic}}' und schlage guenstigere lokale/Flash-Modelle vor.", "depends_on": ["cost_collect"], "require_hitl": False},
                {"id": "cost_report", "title": "CFO-Kurzbericht & Budget-Anpassung", "type": "gate", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Pruefe Einsparpotenziale fuer '{{topic}}' und gib neue Budget-Caps frei.", "depends_on": ["cost_opt"], "require_hitl": True},
            ],
        },
        {
            "id": "email_triage_reply",
            "title": "Posteingang: E-Mail-Triage -> Antwortentwurf",
            "category": "Posteingang & Support",
            "description": "Klassifiziert eingehende Mails, prueft Fakten im Wissensspeicher und erstellt einen geprueften Antwortentwurf vor dem Versand.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "E-Mail / Betreff", "default": "Kundenanfrage"}],
            "builtin": True,
            "nodes": [
                {"id": "mail_classify", "title": "Prioritaet & Anliegen klassifizieren: {{topic}}", "type": "agent", "agent_id": "analyst", "tool_preset": "minimal", "soul_mode": "analytical", "prompt": "Bestimme Dringlichkeit, Absender-Typ und Kernfrage fuer '{{topic}}'.", "depends_on": [], "require_hitl": False},
                {"id": "mail_draft", "title": "Praezisen Antwortentwurf formulieren", "type": "agent", "agent_id": "writer", "tool_preset": "research", "soul_mode": "creative", "prompt": "Schreibe eine klare, direkte Antwort zu '{{topic}}' ohne Floskeln.", "forbidden_actions": ["Keine externen E-Mails oder Nachrichten ohne Freigabe senden"], "depends_on": ["mail_classify"], "require_hitl": False},
                {"id": "mail_send_gate", "title": "Versand-Freigabe (HITL)", "type": "gate", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Antwort zu '{{topic}}' pruefen und zum Versand freigeben.", "depends_on": ["mail_draft"], "require_hitl": True},
            ],
        },
        {
            "id": "customer_escalation_sop",
            "title": "Kunden-Eskalation -> Ursachenanalyse -> Boardroom",
            "category": "Posteingang & Support",
            "description": "Bei kritischen Beschwerden: Parallel-Analyse durch Support & Technik, gefolgt von einer AI-Boardroom-Entscheidung.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Eskalations-Fall", "default": "Kritischer Vorfall"}],
            "builtin": True,
            "nodes": [
                {"id": "esc_facts", "title": "Sachverhalt & Chronologie sichern: {{topic}}", "type": "agent", "agent_id": "research", "tool_preset": "research", "soul_mode": "strict", "prompt": "Sammle alle Fakten, Logs und Zusagen zu '{{topic}}'.", "depends_on": [], "require_hitl": False},
                {"id": "esc_tech", "title": "Technische Ursache pruefen", "type": "fanout", "agent_id": "engineer", "tool_preset": "coding", "soul_mode": "analytical", "prompt": "Finde die technische Root-Cause fuer '{{topic}}'.", "depends_on": ["esc_facts"], "require_hitl": False},
                {"id": "esc_comm", "title": "Kulanz- & Kommunikationsoptionen", "type": "fanout", "agent_id": "writer", "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Formuliere 2 sachliche Loesungs- und Kulanzoptionen fuer '{{topic}}'.", "depends_on": ["esc_facts"], "require_hitl": False},
                {"id": "esc_board", "title": "AI Boardroom Krisen-Entscheidung", "type": "boardroom", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Entscheide im Boardroom ueber Massnahmen und Kulanz zu '{{topic}}'.", "depends_on": ["esc_tech", "esc_comm"], "require_hitl": True},
            ],
        },
        {
            "id": "seo_competitor_radar",
            "title": "Wettbewerber-Radar -> Gap-Analyse -> SEO-Briefing",
            "category": "Marketing & Content",
            "description": "Watchdog-getriggertes Monitoring: Sobald Wettbewerber neue Features/Artikel launchen, entsteht automatisch ein Gegen-Briefing.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Wettbewerber / Thema", "default": "Neues Wettbewerber-Update"}],
            "builtin": True,
            "nodes": [
                {"id": "seo_watch", "title": "Wettbewerber-Meldung auswerten: {{topic}}", "type": "research", "agent_id": "research", "tool_preset": "research", "soul_mode": "analytical", "prompt": "Analysiere die Meldung '{{topic}}' auf Produkt-, Preis- und SEO-Auswirkungen.", "depends_on": [], "require_hitl": False},
                {"id": "seo_gap", "title": "Eigene Differenzierung & Keywords", "type": "agent", "agent_id": "analyst", "tool_preset": "research", "soul_mode": "analytical", "prompt": "Leite 5 konkrete Keyword-Chancen und USPs gegenueber '{{topic}}' ab.", "depends_on": ["seo_watch"], "require_hitl": False},
                {"id": "seo_brief", "title": "Redaktions-Briefing erstellen", "type": "agent", "agent_id": "writer", "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Erstelle ein fertiges Artikel- & Kampagnen-Briefing auf Basis von '{{topic}}'.", "depends_on": ["seo_gap"], "require_hitl": False},
            ],
        },
        {
            "id": "youtube_video_repurpose",
            "title": "Video/Transkript -> Blog + LinkedIn + Newsletter Fan-Out",
            "category": "Marketing & Content",
            "description": "Verwandelt ein langes Video-Transkript oder Webinar parallel in 3 kanalfertige Formate plus Anti-Slop-QA.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Video-Thema / Transkript", "default": "Produkt-Demo & Walkthrough"}],
            "builtin": True,
            "nodes": [
                {"id": "vid_core", "title": "Kernaussagen & Zitate extrahieren: {{topic}}", "type": "agent", "agent_id": "research", "tool_preset": "minimal", "soul_mode": "analytical", "prompt": "Extrahiere die 7 staerksten Aussagen und Praxisbeispiele aus '{{topic}}'.", "depends_on": [], "require_hitl": False},
                {"id": "vid_blog", "title": "SEO-Fachartikel schreiben", "type": "fanout", "agent_id": "writer", "channel": "linkedin", "save_to_showroom": True, "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Schreibe einen strukturierten Fachartikel aus '{{topic}}'.", "depends_on": ["vid_core"], "require_hitl": False},
                {"id": "vid_li", "title": "LinkedIn-Carousel & Post", "type": "fanout", "agent_id": "writer", "channel": "linkedin", "save_to_showroom": True, "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Erstelle einen praegnanten LinkedIn-Post zu '{{topic}}'.", "depends_on": ["vid_core"], "require_hitl": False},
                {"id": "vid_nl", "title": "Newsletter-Ausgabe", "type": "fanout", "agent_id": "writer", "channel": "linkedin", "save_to_showroom": True, "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Formuliere einen kompakten Newsletter-Abschnitt zu '{{topic}}'.", "depends_on": ["vid_core"], "require_hitl": False},
                {"id": "vid_qa", "title": "Anti-Slop QA & Freigabe", "type": "gate", "agent_id": "qa", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Pruefe alle 3 Formate zu '{{topic}}' auf Ton, Fakten und Konsistenz.", "depends_on": ["vid_blog", "vid_li", "vid_nl"], "require_hitl": True},
            ],
        },
        {
            "id": "omnichannel_content_engine",
            "title": "Content-Maschine: Research -> LinkedIn + YouTube + 9:16 Shorts/TikTok + Anti-Slop -> Showroom",
            "category": "Marketing & Content",
            "description": "Vollstaendige Multi-Channel Content-Fabrik als DAG: Trend-Research -> Master-Brief -> parallele Ausspielung fuer LinkedIn, YouTube Longform, YouTube Shorts (9:16), TikTok (9:16) & X -> deterministisches Anti-Slop-Gate -> HITL-Freigabe & Showroom-Deliverable.",
            "schedule_hint": "0 8 * * 1,3,5",
            "n8n_webhook_hint": "",
            "inputs": [
                {"key": "topic", "label": "Kernthema / Quelle / Transkript", "default": "Multi-Agenten-Orchestrierung im Mittelstand"},
                {"key": "audience", "label": "Zielgruppe", "default": "Geschaeftsfuehrer, Gruender & Tech-Entscheider"},
            ],
            "builtin": True,
            "nodes": [
                {"id": "cm_research", "title": "Trend-, Fakten- & Hook-Recherche: {{topic}}", "type": "research", "agent_id": "research", "tool_preset": "research", "soul_mode": "analytical", "prompt": "Recherchiere belastbare Zahlen, Praxisbeispiele und 5 starke Kontrast-Hooks zu '{{topic}}' fuer {{audience}}.", "depends_on": [], "require_hitl": False},
                {"id": "cm_brief", "title": "Master-Storyline & Kernbotschaft", "type": "agent", "agent_id": "analyst", "tool_preset": "minimal", "soul_mode": "analytical", "prompt": "Verdichte die Recherche zu '{{topic}}' in ein Master-Briefing mit 1 Kernthese, 3 konkreten Belegen/Zahlen und klarem Call-to-Action.", "depends_on": ["cm_research"], "require_hitl": False},
                {"id": "cm_linkedin", "title": "LinkedIn Thought-Leadership & Carousel", "type": "fanout", "agent_id": "writer", "channel": "linkedin", "save_to_showroom": True, "max_revisions": 1, "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Erstelle einen LinkedIn-Post (Hook <= 180 Zeichen, konkrete Zahlen, 0 KI-Floskeln, starker CTA) plus 6-Slide-Carousel-Gliederung zu '{{topic}}'.", "depends_on": ["cm_brief"], "require_hitl": False},
                {"id": "cm_yt_long", "title": "YouTube Longform Skript & Kapitel (8-12 Min.)", "type": "fanout", "agent_id": "writer", "channel": "youtube_longform", "save_to_showroom": True, "max_revisions": 1, "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Schreibe ein YouTube-Longform-Skript zu '{{topic}}' inkl. 30-Sekunden-Retention-Hook, Kapitel-Timecodes, B-Roll-Hinweisen und 3 Thumbnail-Text-Ideen.", "depends_on": ["cm_brief"], "require_hitl": False},
                {"id": "cm_shorts_916", "title": "YouTube Shorts & TikTok 9:16 Clip-Matrix (3 Clips)", "type": "fanout", "agent_id": "writer", "channel": "youtube_shorts", "save_to_showroom": True, "max_revisions": 1, "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Zerlege '{{topic}}' in 3 eigenstaendige 9:16 Kurzvideo-Clips (30-45s fuer YouTube Shorts & TikTok) mit 2s-Visual-Hook, Timecodes, On-Screen-Captions und Loop-Ende.", "depends_on": ["cm_brief"], "require_hitl": False},
                {"id": "cm_x_thread", "title": "X / Threads 6-Teiler", "type": "fanout", "agent_id": "writer", "channel": "x_threads", "save_to_showroom": True, "max_revisions": 1, "tool_preset": "minimal", "soul_mode": "creative", "prompt": "Formuliere einen dichten 6-teiligen X-/Threads-Thread zu '{{topic}}' mit klarem Zahlen-Hook in Post 1 und CTA in Post 6.", "depends_on": ["cm_brief"], "require_hitl": False},
                {"id": "cm_slop_gate", "title": "Deterministisches Anti-AI-Slop Quality Gate", "type": "quality_gate", "agent_id": "qa", "channel": "linkedin", "min_quality_score": 70, "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Automatische Anti-Slop- & Hook-Pruefung ueber alle erzeugten Kanal-Assets.", "depends_on": ["cm_linkedin", "cm_yt_long", "cm_shorts_916", "cm_x_thread"], "require_hitl": False},
                {"id": "cm_hitl_release", "title": "Redaktions- & Publishing-Freigabe (HITL)", "type": "gate", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Finale Redaktionsfreigabe fuer alle Kanal-Deliverables zu '{{topic}}' vor Einplanung im Kalender / Publishing.", "depends_on": ["cm_slop_gate"], "require_hitl": True},
            ],
        },
        {
            "id": "rfp_proposal_factory",
            "title": "Ausschreibung (RFP) -> Technik & Kalkulation -> Angebot",
            "category": "Vertrieb & CRM",
            "description": "Zerlegt ein Lastenheft/RFP parallel in technische Machbarkeit und Aufwandskalkulation und baut ein abgabefertiges Angebot.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Ausschreibung / Kunde", "default": "Ausschreibung Digitalisierung"}],
            "builtin": True,
            "nodes": [
                {"id": "rfp_parse", "title": "Muss-Kriterien & Fristen extrahieren: {{topic}}", "type": "agent", "agent_id": "analyst", "tool_preset": "research", "soul_mode": "strict", "prompt": "Liste alle K.O.-Kriterien, Liefergegenstaende und Fristen aus '{{topic}}'.", "depends_on": [], "require_hitl": False},
                {"id": "rfp_tech", "title": "Technisches Loesungskonzept", "type": "fanout", "agent_id": "engineer", "tool_preset": "coding", "soul_mode": "analytical", "prompt": "Entwirf die passende Architektur fuer '{{topic}}'.", "depends_on": ["rfp_parse"], "require_hitl": False},
                {"id": "rfp_price", "title": "Aufwands- & Risiko-Kalkulation", "type": "fanout", "agent_id": "analyst", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Kalkuliere Personentage, Puffer und Risiken fuer '{{topic}}'.", "depends_on": ["rfp_parse"], "require_hitl": False},
                {"id": "rfp_doc", "title": "Angebots-Dossier zusammenstellen", "type": "agent", "agent_id": "writer", "tool_preset": "minimal", "soul_mode": "analytical", "prompt": "Erstelle das vollstaendige Angebotsdokument zu '{{topic}}'.", "depends_on": ["rfp_tech", "rfp_price"], "require_hitl": False},
                {"id": "rfp_gate", "title": "Abgabe-Freigabe (HITL)", "type": "gate", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Finale kaufmaennische Freigabe fuer '{{topic}}'.", "depends_on": ["rfp_doc"], "require_hitl": True},
            ],
        },
        {
            "id": "weekly_exec_briefing",
            "title": "Wochen-Briefing: Fortschritt + Radar + Boardroom",
            "category": "Strategie & Fuehrung",
            "description": "Montags-Routine per Cron: Verdichtet offene Risiken, Watchdog-Signale und KPIs zu einem kompakten Executive Briefing.",
            "schedule_hint": "0 7 * * 1",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Kalenderwoche / Fokus", "default": "Aktuelle Woche"}],
            "builtin": True,
            "nodes": [
                {"id": "wk_status", "title": "Kanban- & Projekt-Status sammeln ({{topic}})", "type": "agent", "agent_id": "analyst", "tool_preset": "research", "soul_mode": "analytical", "prompt": "Fasse erledigte Meilensteine, Blocker und offene Risiken fuer '{{topic}}' zusammen.", "depends_on": [], "require_hitl": False},
                {"id": "wk_board", "title": "Prioritaeten im AI Boardroom abwaegen", "type": "boardroom", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Bewerte Engpaesse und Top-3-Prioritaeten fuer '{{topic}}'.", "depends_on": ["wk_status"], "require_hitl": False},
                {"id": "wk_memo", "title": "Executive Memo ausgeben", "type": "agent", "agent_id": "writer", "tool_preset": "minimal", "soul_mode": "analytical", "prompt": "Erstelle ein 1-seitiges Montags-Briefing fuer '{{topic}}'.", "depends_on": ["wk_board"], "require_hitl": False},
            ],
        },
        {
            "id": "boardroom_risk_council",
            "title": "Strategie -> Research Lab -> AI Boardroom -> Plan",
            "category": "Strategie & Fuehrung",
            "description": "End-to-End Entscheidungs-Pipeline fuer komplexe Investitionen, Preismodelle oder Produkt-Pivots.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "Strategische Frage", "default": "Markteintritt / Preismodell"}],
            "builtin": True,
            "nodes": [
                {"id": "br_res", "title": "Faktenbasis im Research Lab: {{topic}}", "type": "research", "agent_id": "research", "tool_preset": "research", "soul_mode": "analytical", "prompt": "Recherchiere Marktdaten, Alternativen und Benchmarks zu '{{topic}}'.", "depends_on": [], "require_hitl": False},
                {"id": "br_deb", "title": "AI Boardroom Multi-Agent-Debatte", "type": "boardroom", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Fuehre eine Pro/Contra- und Risikoabwaegung zu '{{topic}}' durch.", "depends_on": ["br_res"], "require_hitl": False},
                {"id": "br_plan", "title": "90-Tage-Umsetzungsplan ableiten", "type": "agent", "agent_id": "analyst", "tool_preset": "minimal", "soul_mode": "analytical", "prompt": "Ueberfuehre den Boardroom-Beschluss zu '{{topic}}' in konkrete Meilensteine.", "depends_on": ["br_deb"], "require_hitl": False},
                {"id": "br_gate", "title": "Finale Vorstands-Freigabe", "type": "gate", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Verbindliche Freigabe des Umsetzungsplans zu '{{topic}}'.", "depends_on": ["br_plan"], "require_hitl": True},
            ],
        },
        {
            "id": "eu_ai_act_compliance_check",
            "title": "EU AI Act & DSGVO Konformitaets-Audit",
            "category": "Engineering & Compliance",
            "description": "Prueft ein KI-Feature oder einen Workflow auf Risikoklasse, Transparenzpflichten, DSGVO und Audit-Nachweise.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [{"key": "topic", "label": "KI-System / Feature", "default": "Neuer Agenten-Workflow"}],
            "builtin": True,
            "nodes": [
                {"id": "comp_map", "title": "Zweck & Datenfluesse erfassen: {{topic}}", "type": "agent", "agent_id": "analyst", "tool_preset": "research", "soul_mode": "strict", "prompt": "Dokumentiere Datenquellen, personenbezogene Daten und Autonomiegrad von '{{topic}}'.", "depends_on": [], "require_hitl": False},
                {"id": "comp_sec", "title": "Risikoklasse & Security-Audit", "type": "fanout", "agent_id": "security", "tool_preset": "coding", "soul_mode": "strict", "prompt": "Bewerte '{{topic}}' nach EU AI Act Risikoklassen, DSGVO Art. 6/22 und Prompt-Injection-Schutz.", "depends_on": ["comp_map"], "require_hitl": False},
                {"id": "comp_doc", "title": "Compliance-Nachweis & Massnahmen", "type": "agent", "agent_id": "qa", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Erstelle eine pruefbare Checkliste mit offenen Auflagen fuer '{{topic}}'.", "depends_on": ["comp_sec"], "require_hitl": False},
                {"id": "comp_gate", "title": "Datenschutz- / Compliance-Freigabe", "type": "gate", "agent_id": "executive_decision_architect", "tool_preset": "minimal", "soul_mode": "strict", "prompt": "Freigabe des Compliance-Berichts fuer '{{topic}}'.", "depends_on": ["comp_doc"], "require_hitl": True},
            ],
        },
        {
            "id": "dropshipping_end_to_end",
            "title": "Dropshipping: Product-Research -> Listing -> Social-Ads",
            "category": "E-Commerce & Dropshipping",
            "description": "Kompletter Launch-DAG: Winning-Product-Research, Marge/Zoll-Check, parallele Shop-Produktseite & Social-Media-Creatives (TikTok/Reels/Meta) plus HITL-Freigabe vor Live-Schaltung.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [
                {"key": "topic", "label": "Nische / Produktidee", "default": "Smart Home / Alltagshelfer"},
                {"key": "shop_platform", "label": "Shop-Plattform", "default": "Shopify + TikTok/Meta Ads"},
            ],
            "builtin": True,
            "nodes": [
                {
                    "id": "ds_research",
                    "title": "Product-Tracing & Trend-Research: {{topic}}",
                    "type": "research",
                    "agent_id": "research",
                    "tool_preset": "research",
                    "allowed_tools": ["web_search", "browser", "file_read"],
                    "forbidden_actions": ["Keine Zahlen, Zitate oder Quellen erfinden (nur belegte Fakten)"],
                    "soul_mode": "analytical",
                    "prompt": "Recherchiere 3 gefragte Produkte in der Nische '{{topic}}' inkl. Lieferanten-EK, Versanddauer (EU/DE-Lager bevorzugt), Bewertungen und Wettbewerber-VK.",
                    "expected_output": "Vergleichstabelle mit EK, VK, Lieferzeit, Lieferant und Nachfrage-Signalen",
                    "depends_on": [],
                    "require_hitl": False,
                },
                {
                    "id": "ds_margin",
                    "title": "Margen-, Zoll- & Markenrechts-Check",
                    "type": "agent",
                    "agent_id": "analyst",
                    "tool_preset": "minimal",
                    "allowed_tools": ["file_read", "web_search"],
                    "forbidden_actions": [
                        "Keine Zahlungen, Bestellungen oder Vertraege ausloesen",
                        "Keine Produkte mit Markenrechts-, CE- oder Sicherheitsrisiko freigeben",
                    ],
                    "soul_mode": "strict",
                    "prompt": "Kalkuliere fuer den Top-Kandidaten aus '{{topic}}' Netto-Marge nach EK, Versand, MwSt, Zahlungsgebuehren, Retourenquote (10%) und Ziel-CPA. Pruefe CE/Marken-Risiken.",
                    "expected_output": "Deckungsbeitrag pro Stueck, Break-Even-ROAS und klares Go/No-Go",
                    "depends_on": ["ds_research"],
                    "require_hitl": False,
                },
                {
                    "id": "ds_listing",
                    "title": "Shop-Platzierung & Produktseite ({{shop_platform}})",
                    "type": "fanout",
                    "agent_id": "writer",
                    "tool_preset": "minimal",
                    "allowed_tools": ["file_read", "file_write", "n8n_webhook"],
                    "forbidden_actions": ["Keine Produktivsysteme oder Live-Deployments ohne HITL-Gate aendern"],
                    "soul_mode": "creative",
                    "prompt": "Erstelle verkaufsstarke Produktseite fuer '{{topic}}' auf {{shop_platform}}: SEO-Titel, Nutzen-Bullets, FAQ, Versand-/Retourenhinweis und Varianten.",
                    "expected_output": "Fertiges Shop-Listing als Markdown/JSON fuer Shopify/WooCommerce",
                    "depends_on": ["ds_margin"],
                    "require_hitl": False,
                },
                {
                    "id": "ds_social",
                    "title": "Social-Media-Content & Ad-Creatives (Reels/TikTok)",
                    "type": "fanout",
                    "agent_id": "writer",
                    "tool_preset": "minimal",
                    "allowed_tools": ["file_read", "file_write", "n8n_webhook"],
                    "forbidden_actions": ["Keine externen E-Mails oder Nachrichten ohne Freigabe senden"],
                    "soul_mode": "creative",
                    "prompt": "Erstelle 3 Short-Video-Skripte (Hook 0-3s, Problem, Demo, CTA) plus Captions, Hashtags und Meta/TikTok-Ad-Copy fuer '{{topic}}'.",
                    "expected_output": "3 Video-Skripte + 3 Social-Posts + Ad-Copy-Set",
                    "depends_on": ["ds_margin"],
                    "require_hitl": False,
                },
                {
                    "id": "ds_launch_gate",
                    "title": "Launch-, Budget- & Social-Publish-Freigabe (HITL)",
                    "type": "gate",
                    "agent_id": "executive_decision_architect",
                    "tool_preset": "minimal",
                    "allowed_tools": ["n8n_webhook"],
                    "forbidden_actions": ["Keine Zahlungen, Bestellungen oder Vertraege ausloesen"],
                    "soul_mode": "strict",
                    "prompt": "Pruefe Kalkulation, Listing und Social-Creatives fuer '{{topic}}'. Nach Freigabe Shop-Listing & Social-Scheduler (optional via n8n-Webhook) aktivieren.",
                    "depends_on": ["ds_listing", "ds_social"],
                    "require_hitl": True,
                },
            ],
        },
        {
            "id": "dropshipping_order_fulfillment",
            "title": "Dropshipping: Bestelleingang -> Lieferant -> Tracking & Support",
            "category": "E-Commerce & Dropshipping",
            "description": "Laufender Order-Workflow (ideal fuer Posteingang-/Webhook-Trigger): Prueft neue Bestellungen, bereitet Lieferanten-Order vor, sendet Tracking-Update und fängt Reklamationen ab.",
            "schedule_hint": "",
            "n8n_webhook_hint": "",
            "inputs": [
                {"key": "topic", "label": "Bestell-Nr. / Kunden-Event", "default": "Neue Shop-Bestellung"},
            ],
            "builtin": True,
            "nodes": [
                {
                    "id": "ord_validate",
                    "title": "Bestellung & Zahlungsstatus pruefen: {{topic}}",
                    "type": "agent",
                    "agent_id": "analyst",
                    "tool_preset": "minimal",
                    "allowed_tools": ["crm_read", "file_read"],
                    "forbidden_actions": ["Keine Zahlungen, Bestellungen oder Vertraege ausloesen"],
                    "soul_mode": "strict",
                    "prompt": "Pruefe Bestelldaten, Lieferadresse, SKU-Verfuegbarkeit und Zahlungsstatus fuer '{{topic}}'.",
                    "expected_output": "Gepruefter Order-Datensatz inkl. Lieferanten-SKU",
                    "depends_on": [],
                    "require_hitl": False,
                },
                {
                    "id": "ord_supplier_gate",
                    "title": "Lieferanten-Bestellung & Einkauf freigeben (HITL)",
                    "type": "gate",
                    "agent_id": "executive_decision_architect",
                    "tool_preset": "minimal",
                    "allowed_tools": ["n8n_webhook"],
                    "forbidden_actions": ["Keine API-Keys, Passwoerter oder internen Secrets ausgeben"],
                    "soul_mode": "strict",
                    "prompt": "Gib die automatisierte Weiterleitung der Bestellung '{{topic}}' an den Lieferanten (z. B. via n8n/API) frei.",
                    "depends_on": ["ord_validate"],
                    "require_hitl": True,
                },
                {
                    "id": "ord_tracking",
                    "title": "Kunden-Tracking & Support-Nachricht vorbereiten",
                    "type": "agent",
                    "agent_id": "writer",
                    "tool_preset": "minimal",
                    "allowed_tools": ["crm_read", "email_send", "n8n_webhook"],
                    "forbidden_actions": ["Keine externen E-Mails oder Nachrichten ohne Freigabe senden"],
                    "soul_mode": "creative",
                    "prompt": "Erstelle eine klare Versandbestaetigung inkl. Sendungsverfolgung und proaktivem Lieferzeit-Hinweis fuer '{{topic}}'.",
                    "expected_output": "Versandfertige Kunden-E-Mail / WhatsApp-Vorlage",
                    "depends_on": ["ord_supplier_gate"],
                    "require_hitl": False,
                },
            ],
        },
    ]


def import_n8n_workflow_json(n8n_data: Dict[str, Any], title_override: Optional[str] = None) -> Dict[str, Any]:
    """Konvertiert ein n8n-Workflow-JSON (z. B. von n8n.io/workflows) in eine Archon OS DAG-Vorlage."""
    if not isinstance(n8n_data, dict) or not isinstance(n8n_data.get("nodes"), list):
        raise ValueError("invalid_n8n_json")

    raw_nodes = n8n_data.get("nodes") or []
    raw_conns = n8n_data.get("connections") or {}

    name_to_id: Dict[str, str] = {}
    nodes_by_id: Dict[str, Dict[str, Any]] = {}

    for idx, rn in enumerate(raw_nodes, start=1):
        if not isinstance(rn, dict):
            continue
        rname = str(rn.get("name") or f"Step {idx}")
        nid = _slugify(rname)
        if nid in nodes_by_id:
            nid = f"{nid}_{idx}"
        name_to_id[rname] = nid

        rtype = str(rn.get("type") or "").lower()
        pos = rn.get("position") if isinstance(rn.get("position"), list) else [60 + idx * 240, 120]
        x = max(20, int(round((float(pos[0]) if len(pos) > 0 else 60) / 20.0) * 20))
        y = max(20, int(round((float(pos[1]) if len(pos) > 1 else 120) / 20.0) * 20))

        agent_id = "research"
        node_type = "agent"
        tool_preset = "research"
        if "if" in rtype or "switch" in rtype or "merge" in rtype:
            node_type = "fanout"
            agent_id = "analyst"
        elif "wait" in rtype or "approval" in rtype or "human" in rtype:
            node_type = "gate"
            agent_id = "executive_decision_architect"
            tool_preset = "minimal"
        elif "code" in rtype or "function" in rtype or "execute" in rtype:
            agent_id = "engineer"
            tool_preset = "coding"
        elif "gmail" in rtype or "slack" in rtype or "mail" in rtype or "notion" in rtype:
            agent_id = "writer"
            tool_preset = "minimal"

        nodes_by_id[nid] = {
            "id": nid,
            "title": rname,
            "type": node_type,
            "agent_id": agent_id,
            "tool_preset": tool_preset,
            "soul_mode": "analytical",
            "prompt": f"Aus n8n-Node '{rn.get('type', 'node')}' importiert: Bearbeite '{rname}' fuer '{{{{topic}}}}'.",
            "depends_on": [],
            "require_hitl": node_type == "gate",
            "x": x,
            "y": y,
        }

    edges: List[Dict[str, Any]] = []
    if isinstance(raw_conns, dict):
        for src_name, conn_obj in raw_conns.items():
            src_id = name_to_id.get(src_name)
            if not src_id or not isinstance(conn_obj, dict):
                continue
            main_outputs = conn_obj.get("main") or []
            for branch in main_outputs:
                if not isinstance(branch, list):
                    continue
                for target_ref in branch:
                    if not isinstance(target_ref, dict):
                        continue
                    tgt_id = name_to_id.get(str(target_ref.get("node") or ""))
                    if tgt_id and tgt_id != src_id and tgt_id in nodes_by_id:
                        if src_id not in nodes_by_id[tgt_id]["depends_on"]:
                            nodes_by_id[tgt_id]["depends_on"].append(src_id)
                        # Paket C: 'full_output' wird zu 'full' normalisiert —
                        # der DAG-Runner kennt nur full|summary|artifact_only|none.
                        edges.append({"from": src_id, "to": tgt_id, "condition": "on_success", "data_mode": "full", "label": ""})

    title = str(title_override or n8n_data.get("name") or "Importierter n8n-Workflow").strip()
    return save_workflow_template({
        "title": title,
        "category": "Importierte Workflows (n8n)",
        "description": f"Importiert aus n8n JSON ({len(nodes_by_id)} Stationen).",
        "nodes": list(nodes_by_id.values()),
        "edges": edges,
    })


def _load_custom_templates() -> List[Dict[str, Any]]:
    global _CUSTOM_TEMPLATES_CORRUPT
    with _FILE_LOCK:
        if not os.path.exists(CUSTOM_TEMPLATES_PATH):
            return []
        try:
            with open(CUSTOM_TEMPLATES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            parsed: Optional[List[Dict[str, Any]]] = None
            if isinstance(data, list):
                parsed = [{**item, "builtin": False} for item in data if isinstance(item, dict) and item.get("id")]
        except Exception as exc:
            # Paket C: Datei existiert, ist aber unlesbar/korrupt -> NICHT still
            # [] zurueckgeben und den Store damit implizit loeschen. Stattdessen:
            # Kontext loggen, korrupte Datei einmalig sichern und Store als
            # korrupt markieren (save/delete blocken dann).
            _CUSTOM_TEMPLATES_CORRUPT = True
            logger.error(
                "Custom-Template-Store (%s) ist korrupt/unlesbar (%s: %s) — "
                "Template-Liste wird leer geliefert, aber Save/Delete sind blockiert, "
                "bis die Datei repariert ist.",
                CUSTOM_TEMPLATES_PATH,
                type(exc).__name__,
                exc,
            )
            corrupt_backup = CUSTOM_TEMPLATES_PATH + ".corrupt"
            if not os.path.exists(corrupt_backup):
                try:
                    with open(CUSTOM_TEMPLATES_PATH, "rb") as src, open(corrupt_backup, "wb") as dst:
                        dst.write(src.read())
                    logger.error("Korrupte Datei gesichert nach %s", corrupt_backup)
                except OSError as bk_exc:
                    logger.error(
                        "Backup der korrupten Datei nach %s fehlgeschlagen: %s",
                        corrupt_backup,
                        bk_exc,
                    )
            else:
                logger.error(
                    "Backup %s existiert bereits — bestehendes Backup nicht ueberschrieben.",
                    corrupt_backup,
                )
            return []
        # Datei lesbar -> korrupt-Marker zuruecksetzen (nach manueller Reparatur).
        _CUSTOM_TEMPLATES_CORRUPT = False
        return parsed or []


def _save_custom_templates(items: List[Dict[str, Any]]) -> None:
    # Paket C: Atomarer Schreibvorgang — Tempfile im selben Verzeichnis
    # (gleiches Filesystem) + os.replace, damit nie eine halbgeschriebene
    # Datei ohne Fallback zurueckbleibt.
    os.makedirs(os.path.dirname(CUSTOM_TEMPLATES_PATH), exist_ok=True)
    dirname = os.path.dirname(CUSTOM_TEMPLATES_PATH)
    with _FILE_LOCK:
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", delete=False, dir=dirname, suffix=".tmp"
            ) as tmp:
                json.dump(items, tmp, ensure_ascii=False, indent=2)
                tmp_path = tmp.name
            os.replace(tmp_path, CUSTOM_TEMPLATES_PATH)
            tmp_path = None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    logger.error("Temp-Datei %s konnte nicht entfernt werden.", tmp_path)


def list_workflow_templates() -> List[Dict[str, Any]]:
    from backend.workflow_monetization_catalog import get_monetization_templates

    builtins = _builtin_templates() + get_monetization_templates()
    customs = _load_custom_templates()
    by_id = {tpl["id"]: tpl for tpl in builtins}
    for custom in customs:
        by_id[custom["id"]] = custom
    return list(by_id.values())


def get_workflow_template(tpl_id: str) -> Optional[Dict[str, Any]]:
    for tpl in list_workflow_templates():
        if tpl["id"] == tpl_id:
            return tpl
    return None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (text or "").strip().lower()).strip("_")
    return slug or f"wf_{uuid.uuid4().hex[:8]}"


def save_workflow_template(payload: Dict[str, Any]) -> Dict[str, Any]:
    if _CUSTOM_TEMPLATES_CORRUPT:
        raise RuntimeError(
            "Custom-Template-Store korrupt — erst reparieren "
            f"(siehe {CUSTOM_TEMPLATES_PATH} + .corrupt-Backup); Speichern blockiert."
        )
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValueError("title_required")
    nodes = payload.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("nodes_required")

    tpl_id = _slugify(str(payload.get("id") or title))
    normalized_nodes: List[Dict[str, Any]] = []
    for idx, raw in enumerate(nodes, start=1):
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or f"step_{idx}").strip()
        ntype = str(raw.get("type") or "agent").strip().lower()
        valid_types = {"agent", "fanout", "gate", "quality_gate", "boardroom", "research", "media_render", "clip_matrix"}
        if ntype not in valid_types:
            try:
                from backend.workflow_node_plugins import is_workflow_node_plugin
                if not is_workflow_node_plugin(ntype):
                    ntype = "agent"
            except Exception:
                ntype = "agent"
        deps = raw.get("depends_on") or []
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.split(",") if d.strip()]
        node_obj = {
            "id": nid,
            "title": str(raw.get("title") or f"Schritt {idx}").strip(),
            "type": ntype,
            "agent_id": str(raw.get("agent_id") or "default").strip(),
            "tool_preset": str(raw.get("tool_preset") or "research").strip(),
            "allowed_tools": [str(t).strip() for t in (raw.get("allowed_tools") or []) if str(t).strip()],
            "forbidden_actions": [str(f).strip() for f in (raw.get("forbidden_actions") or []) if str(f).strip()],
            "soul_mode": str(raw.get("soul_mode") or "analytical").strip(),
            "reasoning_effort": str(raw.get("reasoning_effort") or "medium").strip(),
            "prompt": str(raw.get("prompt") or "").strip(),
            "expected_output": str(raw.get("expected_output") or "").strip(),
            "depends_on": [str(d).strip() for d in deps if str(d).strip()],
            "require_hitl": bool(raw.get("require_hitl") or ntype == "gate"),
            "max_retries": int(raw.get("max_retries") or 1),
            "timeout_sec": int(raw.get("timeout_sec") or 300),
        }
        for opt_str in ("channel", "model", "plugin_id"):
            if raw.get(opt_str):
                node_obj[opt_str] = str(raw[opt_str]).strip()
        if isinstance(raw.get("plugin_params"), dict):
            node_obj["plugin_params"] = dict(raw["plugin_params"])
        if raw.get("save_to_showroom") is not None:
            node_obj["save_to_showroom"] = bool(raw["save_to_showroom"])
        if raw.get("quality_gate") is not None:
            node_obj["quality_gate"] = bool(raw["quality_gate"])
        if raw.get("max_revisions") is not None and raw.get("max_revisions") != "":
            node_obj["max_revisions"] = int(raw["max_revisions"])
        if raw.get("min_quality_score") is not None and raw.get("min_quality_score") != "":
            node_obj["min_quality_score"] = int(raw["min_quality_score"])
        if raw.get("branches"):
            node_obj["branches"] = list(raw["branches"])
        if raw.get("quorum_min") is not None and raw.get("quorum_min") != "":
            node_obj["quorum_min"] = int(raw["quorum_min"])
        if raw.get("token_budget"):
            node_obj["token_budget"] = int(raw["token_budget"])
        if raw.get("cost_limit_usd") is not None and raw.get("cost_limit_usd") != "":
            node_obj["cost_limit_usd"] = float(raw["cost_limit_usd"])
        if raw.get("x") is not None and raw.get("y") is not None:
            node_obj["x"] = int(raw["x"])
            node_obj["y"] = int(raw["y"])
        normalized_nodes.append(node_obj)

    normalized_edges: List[Dict[str, Any]] = []
    for raw_e in payload.get("edges") or []:
        if not isinstance(raw_e, dict):
            continue
        efrom = str(raw_e.get("from") or "").strip()
        eto = str(raw_e.get("to") or "").strip()
        if not efrom or not eto:
            continue
        # Paket C: Legacy 'full_output' -> 'full' normalisieren (Runner kennt
        # nur full|summary|artifact_only|none); Default ist 'full'.
        raw_mode = str(raw_e.get("data_mode") or "full").strip()
        if raw_mode == "full_output":
            raw_mode = "full"
        normalized_edges.append({
            "from": efrom,
            "to": eto,
            "condition": str(raw_e.get("condition") or "on_success").strip(),
            "data_mode": raw_mode,
            "label": str(raw_e.get("label") or "").strip(),
        })

    tpl = {
        "id": tpl_id,
        "title": title,
        "category": str(payload.get("category") or "Eigene Workflows").strip(),
        "description": str(payload.get("description") or "").strip(),
        "header_image": str(payload.get("header_image") or "").strip()[:350000],
        "schedule_hint": str(payload.get("schedule_hint") or "").strip(),
        "n8n_webhook_hint": str(payload.get("n8n_webhook_hint") or "").strip(),
        "inputs": payload.get("inputs") if isinstance(payload.get("inputs"), list) else [{"key": "topic", "label": "Thema / Ziel", "default": ""}],
        "builtin": False,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }
    customs = [c for c in _load_custom_templates() if c.get("id") != tpl_id]
    customs.append(tpl)
    _save_custom_templates(customs)
    return tpl


def delete_workflow_template(tpl_id: str) -> bool:
    if _CUSTOM_TEMPLATES_CORRUPT:
        raise RuntimeError(
            "Custom-Template-Store korrupt — erst reparieren "
            f"(siehe {CUSTOM_TEMPLATES_PATH} + .corrupt-Backup); Loeschen blockiert."
        )
    customs = _load_custom_templates()
    filtered = [c for c in customs if c.get("id") != tpl_id]
    if len(filtered) == len(customs):
        return False
    _save_custom_templates(filtered)
    return True


def _render_vars(text: str, inputs: Dict[str, Any]) -> str:
    out = str(text or "")
    for k, v in (inputs or {}).items():
        out = out.replace(f"{{{{{k}}}}}", str(v or ""))
    return out


class _RejectAllRedirectsHandler(urllib.request.HTTPRedirectHandler):
    """Paket C / SSRF: lehnt HTTP-Redirects komplett ab.

    urllib wuerde 3xx-Redirects still folgen — dabei koennte der Ziel-Server
    einen internen Host (z.B. 169.254.169.254) zurueckgeben, den der initiale
    Egress-Check nie gesehen hat. Redirect-Requests werden deshalb abgebrochen
    (redirect_request -> None -> HTTPError fuer die Redirect-Antwort).
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        logger.error(
            "n8n-Webhook: Redirect abgelehnt (HTTP %s -> %s) — Egress-Guard prueft keine Redirect-Ziele.",
            code,
            newurl,
        )
        return None


def _trigger_n8n_webhook(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return {"triggered": False, "reason": "no_valid_url"}
    # Outbox + Idempotenz: ein Retry/Restart darf 'workflow_started' nicht
    # zweimal an n8n senden. SSRF/Redirect-Schutz steckt in safe_http_request.
    try:
        from backend.event_mesh import event_mesh

        safe_payload = dict(payload or {})
        safe_payload["idempotency_key"] = f"workflow-started:{safe_payload.get('run_id') or ''}"
        result = event_mesh.emit_outbound_event(url, "workflow_started", safe_payload, timeout=5.0)
    except Exception as exc:
        logger.error("n8n-Webhook ueber Outbox fehlgeschlagen: %s", exc)
        return {"triggered": False, "error": str(exc)}
    if result.get("status") == "duplicate":
        return {
            "triggered": False, "duplicate": True,
            "idempotency_key": result.get("idempotency_key"),
            "reason": "already_dispatched",
        }
    return {
        "triggered": result.get("status") == "delivered",
        "status_code": result.get("http_status"),
        "idempotency_key": result.get("idempotency_key"),
    }


def materialize_workflow_to_kanban(
    tpl_id: str,
    inputs: Optional[Dict[str, Any]] = None,
    cron_schedule: Optional[str] = None,
    n8n_webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    tpl = get_workflow_template(tpl_id)
    if not tpl:
        raise KeyError(f"Workflow template '{tpl_id}' not found")

    resolved_inputs: Dict[str, Any] = {}
    for inp in tpl.get("inputs") or []:
        key = inp.get("key")
        if key:
            resolved_inputs[key] = (inputs or {}).get(key) or inp.get("default") or ""
    for k, v in (inputs or {}).items():
        resolved_inputs[k] = v

    run_id = f"wf-{tpl_id[:12]}-{uuid.uuid4().hex[:6]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    from backend.operations_api import _get_active_kanban_db_path, _get_kanban_connection
    from backend.kanban_sidecar import update_kanban_meta

    # _get_kanban_connection erzwingt Schema-Init + task_links-Migration (kind/created_at)
    _get_kanban_connection().close()
    db_path = _get_active_kanban_db_path()

    node_to_task_id: Dict[str, str] = {}
    created_tasks: List[Dict[str, Any]] = []
    created_links: List[Dict[str, str]] = []

    for idx, node in enumerate(tpl.get("nodes") or [], start=1):
        node_to_task_id[node["id"]] = f"t-{uuid.uuid4().hex[:8]}"

    conn = sqlite3.connect(db_path, timeout=15)
    try:
        cur = conn.cursor()
        # Uebergeordnete Workflow-Run-Aufgabe (Project/Parent-Task im Kanban)
        wf_parent_title = f"[Workflow] {tpl['title']}"
        wf_parent_body = (
            f"Workflow-Run `{run_id}` (Template: `{tpl_id}`)\n\n"
            f"{tpl.get('description') or ''}\n\n"
            f"Stationen: {len(tpl.get('nodes') or [])}"
        ).strip()
        cur.execute(
            """
            INSERT OR IGNORE INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, project_id)
            VALUES (?, ?, ?, ?, 'in_progress', ?, 'Workflow-Studio', ?, ?)
            """,
            (run_id, wf_parent_title, wf_parent_body, "default", 15, now_iso, run_id),
        )
        cur.execute(
            "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
            (
                run_id,
                "created",
                json.dumps({"workflow_tpl": tpl_id, "workflow_run_id": run_id, "kind": "workflow_run"}),
                now_iso,
            ),
        )

        for idx, node in enumerate(tpl.get("nodes") or [], start=1):
            tid = node_to_task_id[node["id"]]
            title = _render_vars(node.get("title") or node["id"], resolved_inputs)
            prompt = _render_vars(node.get("prompt") or "", resolved_inputs)
            deps = node.get("depends_on") or []
            status = "todo" if not deps else "backlog"
            assignee = str(node.get("agent_id") or "default")
            require_hitl = bool(node.get("require_hitl") or node.get("type") == "gate")
            sections = [f"[Workflow: {tpl['title']} | Run: {run_id} | Typ: {node.get('type', 'agent')}]", prompt]
            if node.get("expected_output"):
                sections.append(f"[EXPECTED OUTPUT]\n{_render_vars(node['expected_output'], resolved_inputs)}")
            if node.get("allowed_tools"):
                sections.append(f"[ERLAUBTE TOOLS]\n{', '.join(node['allowed_tools'])}")
            if node.get("forbidden_actions"):
                sections.append("[VERBOTEN / GUARDRAILS]\n- " + "\n- ".join(node["forbidden_actions"]))
            body = "\n\n".join(s for s in sections if s).strip()

            cur.execute(
                """
                INSERT INTO tasks (id, title, body, assignee, status, priority, created_by, created_at, project_id, block_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tid, title, body, assignee, status, max(0, 10 - idx), "Workflow-Studio", now_iso, run_id, "hitl_gate" if require_hitl else None),
            )
            cur.execute(
                "INSERT OR IGNORE INTO task_links (parent_id, child_id, kind, created_at) VALUES (?, ?, 'subtask', ?)",
                (run_id, tid, now_iso),
            )
            cur.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    tid,
                    "created",
                    json.dumps({"workflow_tpl": tpl_id, "workflow_run_id": run_id, "node_id": node["id"], "assignee": assignee}),
                    now_iso,
                ),
            )
            created_tasks.append({
                "task_id": tid,
                "node_id": node["id"],
                "title": title,
                "assignee": assignee,
                "status": status,
                "type": node.get("type", "agent"),
            })

        for node in tpl.get("nodes") or []:
            child_tid = node_to_task_id[node["id"]]
            for dep_node_id in node.get("depends_on") or []:
                parent_tid = node_to_task_id.get(dep_node_id)
                if parent_tid:
                    cur.execute(
                        "INSERT OR IGNORE INTO task_links (parent_id, child_id, kind, created_at) VALUES (?, ?, 'blocks', ?)",
                        (parent_tid, child_tid, now_iso),
                    )
                    created_links.append({"parent_id": parent_tid, "child_id": child_tid})

        conn.commit()
    finally:
        conn.close()

    def _apply_wf_meta(meta: Dict[str, Any]) -> None:
        tasks_meta = meta.setdefault("tasks", {})
        for node in tpl.get("nodes") or []:
            tid = node_to_task_id[node["id"]]
            tmeta = tasks_meta.setdefault(tid, {})
            tmeta["workflow_tpl_id"] = tpl_id
            tmeta["workflow_run_id"] = run_id
            tmeta["workflow_node_id"] = node["id"]
            if node.get("soul_mode"):
                tmeta["soul_mode"] = node["soul_mode"]
            if node.get("reasoning_effort"):
                tmeta["reasoning_effort"] = node["reasoning_effort"]
            if node.get("tool_preset"):
                tmeta["tool_preset"] = node["tool_preset"]
            if node.get("allowed_tools"):
                tmeta["allowed_tools"] = node["allowed_tools"]
            if node.get("forbidden_actions"):
                tmeta["forbidden_actions"] = node["forbidden_actions"]
            if node.get("token_budget"):
                tmeta["token_budget"] = int(node["token_budget"])
            if node.get("cost_limit_usd") is not None:
                tmeta["cost_limit_usd"] = float(node["cost_limit_usd"])
            if node.get("require_hitl") or node.get("type") == "gate":
                tmeta["require_hitl"] = True
            if not (node.get("depends_on") or []) and cron_schedule:
                tmeta["cron_schedule"] = str(cron_schedule).strip()
            dep_tids = [node_to_task_id[d] for d in (node.get("depends_on") or []) if d in node_to_task_id]
            if dep_tids:
                tmeta["depends_on"] = dep_tids

    update_kanban_meta(_apply_wf_meta)

    webhook_target = (n8n_webhook_url or tpl.get("n8n_webhook_hint") or "").strip()
    n8n_result = _trigger_n8n_webhook(webhook_target, {
        "event": "workflow_started",
        "run_id": run_id,
        "template_id": tpl_id,
        "template_title": tpl["title"],
        "inputs": resolved_inputs,
        "tasks": created_tasks,
        "links": created_links,
    }) if webhook_target else {"triggered": False}

    return {
        "run_id": run_id,
        "template_id": tpl_id,
        "template_title": tpl["title"],
        "resolved_inputs": resolved_inputs,
        "created_tasks": created_tasks,
        "created_links": created_links,
        "n8n_result": n8n_result,
    }


# --- Echte Ausfuehrung: Materialisierung -> DAG-Runner (BRUCH-2-Fix) ---

_DAG_NODE_PASSTHROUGH_KEYS = (
    "agent_id", "depends_on", "allowed_tools", "forbidden_actions",
    "expected_output", "require_hitl", "token_budget", "cost_limit_usd",
    "max_retries", "timeout_sec", "soul_mode", "reasoning_effort",
    "tool_preset", "model", "channel", "save_to_showroom",
    "max_revisions", "min_quality_score", "quality_gate",
    "max_turns", "output_schema", "media_config", "plugin_id", "plugin_params",
)


def _build_dag_def_from_template(
    tpl: Dict[str, Any],
    resolved_inputs: Dict[str, Any],
    task_by_node: Dict[str, str],
) -> Dict[str, Any]:
    """Baut aus einem Workflow-Template ein run_workflow_dag-kompatibles DAG-JSON.
    Task-IDs der Kanban-Spiegelung werden als kanban_task_id injiziert, damit der
    Runner den Task-Status live mitzieht."""
    dag_nodes: List[Dict[str, Any]] = []
    for node in tpl.get("nodes") or []:
        if not isinstance(node, dict) or not node.get("id"):
            continue
        d: Dict[str, Any] = {
            "id": str(node["id"]),
            "type": str(node.get("type") or "agent").lower(),
            "title": _render_vars(node.get("title") or node["id"], resolved_inputs),
            "prompt": _render_vars(node.get("prompt") or "", resolved_inputs),
            "kanban_task_id": task_by_node.get(str(node["id"])),
        }
        for key in _DAG_NODE_PASSTHROUGH_KEYS:
            if node.get(key) is not None:
                val = node[key]
                if key == "expected_output" and isinstance(val, str):
                    val = _render_vars(val, resolved_inputs)
                elif key in ("plugin_params", "media_config") and isinstance(val, dict):
                    val = {
                        pk: (_render_vars(pv, resolved_inputs) if isinstance(pv, str) else pv)
                        for pk, pv in val.items()
                    }
                d[key] = val
        if d["type"] == "fanout":
            if node.get("branches"):
                d["branches"] = node["branches"]
            if node.get("quorum_min") is not None:
                d["quorum_min"] = node["quorum_min"]
        dag_nodes.append(d)
    return {
        "id": str(tpl.get("id") or "workflow"),
        "title": tpl.get("title") or "",
        "nodes": dag_nodes,
        "edges": [e for e in (tpl.get("edges") or []) if isinstance(e, dict)],
    }


def _run_dag_in_background_thread(dag_def: Dict[str, Any], run_id: str) -> None:
    from backend.workflow_dag_runner import run_workflow_dag
    asyncio.run(run_workflow_dag(dag_def=dag_def, run_id=run_id))


def _schedule_dag_execution(dag_def: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """Startet den DAG-Runner aus beliebigem Kontext: im laufenden Event-Loop
    als Task, sonst als eigener Daemon-Thread mit eigenem Loop."""
    from backend.workflow_dag_runner import run_workflow_dag
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(run_workflow_dag(dag_def=dag_def, run_id=run_id))
        return {"execution": "async_task"}
    threading.Thread(
        target=_run_dag_in_background_thread,
        args=(dag_def, run_id),
        name=f"wf-dag-{run_id}",
        daemon=True,
    ).start()
    return {"execution": "thread"}


def launch_workflow_run(
    tpl_id: str,
    inputs: Optional[Dict[str, Any]] = None,
    cron_schedule: Optional[str] = None,
    n8n_webhook_url: Optional[str] = None,
    execute: bool = True,
) -> Dict[str, Any]:
    """Materialisiert ein Template nach Kanban UND startet die echte DAG-Ausfuehrung.
    Rueckgabewert: Resultat der Materialisierung + Ausfuehrungs-Status."""
    res = materialize_workflow_to_kanban(
        tpl_id=tpl_id,
        inputs=inputs,
        cron_schedule=cron_schedule,
        n8n_webhook_url=n8n_webhook_url,
    )
    tpl = get_workflow_template(tpl_id)
    task_by_node = {
        str(t.get("node_id")): str(t.get("task_id") or "")
        for t in (res.get("created_tasks") or [])
        if t.get("node_id")
    }
    dag_def = _build_dag_def_from_template(
        tpl or {},
        dict(res.get("resolved_inputs") or {}),
        task_by_node,
    )
    run_id = str(res.get("run_id") or "")
    exec_info: Dict[str, Any] = {"execution": "skipped"}
    if execute and dag_def.get("nodes"):
        exec_info = _schedule_dag_execution(dag_def, run_id)
    return {**res, **exec_info, "dag_nodes": len(dag_def.get("nodes") or [])}
