"""
backend/playbooks_engine.py
===========================
M44 — „1-Click Business Playbooks“ (Operations-Vorlagen, n8n-artiger Katalog & Editor).

- 10 aktivierte Starter-Playbooks + 15 nachladbare Katalog-Playbooks (25 gesamt)
- CRUD-Editor für eigene Mehr-Schritt-Vorlagen
- 1-Klick-Runner mit Variablen-Substitution ({{kunde}}, {{thema}}, …)
"""

from __future__ import annotations

import datetime
import json
import os
import threading
import uuid
from typing import Any, Dict, List, Optional

from archon.core.runtime import WORKSPACE_DIR

BUILTIN_PLAYBOOKS: List[Dict[str, Any]] = [
    # --- 10 aktivierte Starter-Playbooks ---
    {
        "id": "pb_customer_onboarding",
        "title": "Kunden-Onboarding (End-to-End)",
        "category": "Sales & CRM",
        "description": "Legt CRM-Akte an, prüft Vertragsdaten, erstellt Kickoff-Tasks und legt ein Obsidian-Projektdossier an.",
        "active": True,
        "builtin": True,
        "variables": ["kunde", "ansprechpartner", "projekt_ziel"],
        "steps": [
            {"order": 1, "title": "CRM- & Marktrecherche", "agent_id": "hermes-researcher", "prompt_template": "Recherchiere Unternehmensprofil und Branche für {{kunde}} (Kontakt: {{ansprechpartner}})."},
            {"order": 2, "title": "Vertrags- & Compliance-Check", "agent_id": "commercial_jurist_contracts", "prompt_template": "Prüfe Standard-NDA/MSA-Anforderungen für {{kunde}}."},
            {"order": 3, "title": "Kickoff-Planung", "agent_id": "executive_decision_architect", "prompt_template": "Erstelle 30-Tage-Onboarding-Plan für {{kunde}} mit Ziel: {{projekt_ziel}}."},
        ],
    },
    {
        "id": "pb_competitor_teardown",
        "title": "Wettbewerbs-Teardown & SWOT",
        "category": "Strategie & Boardroom",
        "description": "Analysiert einen Wettbewerber strukturiert nach Preismodell, Produkt, Schwachstellen und Gegenstrategie.",
        "active": True,
        "builtin": True,
        "variables": ["wettbewerber", "fokus_markt"],
        "steps": [
            {"order": 1, "title": "Fakten- & Pricing-Scan", "agent_id": "hermes-researcher", "prompt_template": "Sammle aktuelle Produkte, Preise und Positionierung von {{wettbewerber}} im Markt {{fokus_markt}}."},
            {"order": 2, "title": "Strategische SWOT-Synthese", "agent_id": "executive_decision_architect", "prompt_template": "Erstelle SWOT-Analyse und konkrete Differenzierungshebel gegen {{wettbewerber}}."},
        ],
    },
    {
        "id": "pb_rfp_to_offer",
        "title": "Lastenheft → Angebot",
        "category": "Sales & CRM",
        "description": "Zerlegt ein Kunden-Lastenheft in Arbeitspakete, kalkuliert Aufwand/Marge und entwirft ein Angebot.",
        "active": True,
        "builtin": True,
        "variables": ["kunde", "leistungsbeschreibung", "budget_rahmen"],
        "steps": [
            {"order": 1, "title": "Anforderungs-Extraktion", "agent_id": "systems_architect", "prompt_template": "Zerlege folgende Anforderungen für {{kunde}} in Arbeitspakete: {{leistungsbeschreibung}}"},
            {"order": 2, "title": "Kalkulation & Marge", "agent_id": "cfo_financial_strategist", "prompt_template": "Kalkuliere Aufwände und Preisstruktur im Rahmen {{budget_rahmen}}."},
            {"order": 3, "title": "Angebots-Entwurf", "agent_id": "sales_director", "prompt_template": "Formuliere ein überzeugendes Angebot für {{kunde}}."},
        ],
    },
    {
        "id": "pb_monthly_close",
        "title": "Monatsabschluss-Check (ERP)",
        "category": "Finanzen & ERP",
        "description": "Prüft offene Posten, stößt Mahnstufen-Vorschläge an und bereitet die Monatsübersicht vor.",
        "active": True,
        "builtin": True,
        "variables": ["monat", "mandant"],
        "steps": [
            {"order": 1, "title": "Offene-Posten-Prüfung", "agent_id": "cfo_financial_strategist", "prompt_template": "Prüfe offene Debitoren/Kreditoren für {{mandant}} im Zeitraum {{monat}}."},
            {"order": 2, "title": "Abweichungs- & Liquiditätsbericht", "agent_id": "controlling_analyst", "prompt_template": "Erstelle kompakten Monatsabschluss-Bericht für {{mandant}} ({{monat}})."},
        ],
    },
    {
        "id": "pb_contract_risk_check",
        "title": "Vertrags-Risiko-Check (HITL)",
        "category": "Recht & Compliance",
        "description": "Prüft Verträge auf Haftungsfallen, Kündigungsfristen und DSGVO-Lücken inkl. Freigabe-Gate.",
        "active": True,
        "builtin": True,
        "variables": ["vertragspartner", "vertragsart"],
        "steps": [
            {"order": 1, "title": "Klausel- & Haftungsanalyse", "agent_id": "commercial_jurist_contracts", "prompt_template": "Analysiere Risiken, Haftungsobergrenzen und Laufzeiten für {{vertragsart}} mit {{vertragspartner}}."},
            {"order": 2, "title": "DSGVO/AVV-Prüfung", "agent_id": "compliance_officer", "prompt_template": "Prüfe Datenschutz- und AVV-Anforderungen für {{vertragspartner}}."},
        ],
    },
    {
        "id": "pb_boardroom_investment",
        "title": "Investitions-Entscheidung (Boardroom)",
        "category": "Strategie & Boardroom",
        "description": "Bewertet eine geplante Investition aus CFO-, Risiko- und Wachstums-Perspektive.",
        "active": True,
        "builtin": True,
        "variables": ["investition", "betrag_eur", "amortisation_monate"],
        "steps": [
            {"order": 1, "title": "ROI- & Cashflow-Modell", "agent_id": "cfo_financial_strategist", "prompt_template": "Bewerte ROI und Liquiditätswirkung für '{{investition}}' ({{betrag_eur}} EUR, Ziel {{amortisation_monate}} Monate)."},
            {"order": 2, "title": "Boardroom-Votum", "agent_id": "executive_decision_architect", "prompt_template": "Fasse Pro/Contra und klare Go/No-Go-Empfehlung für '{{investition}}' zusammen."},
        ],
    },
    {
        "id": "pb_weekly_exec_briefing",
        "title": "Executive Weekly Briefing",
        "category": "Operations & Führung",
        "description": "Verdichtet Kanban-Fortschritt, Watchdog-Signale und offene Entscheidungen für die Wochenplanung.",
        "active": True,
        "builtin": True,
        "variables": ["kalenderwoche"],
        "steps": [
            {"order": 1, "title": "Status-Aggregation", "agent_id": "operations_director", "prompt_template": "Erstelle Executive Weekly Briefing für KW {{kalenderwoche}} inkl. Top-3-Prioritäten und Blockern."},
        ],
    },
    {
        "id": "pb_gdpr_dsar_response",
        "title": "DSGVO-Auskunftsersuchen (Art. 15)",
        "category": "Recht & Compliance",
        "description": "Strukturierter Ablauf zur fristgerechten Beantwortung eines Betroffenen-Auskunftsersuchens.",
        "active": True,
        "builtin": True,
        "variables": ["anfragender", "eingangsdatum"],
        "steps": [
            {"order": 1, "title": "Datenbestand prüfen", "agent_id": "compliance_officer", "prompt_template": "Identifiziere betroffene Systeme für DSGVO-Anfrage von {{anfragender}} (Eingang: {{eingangsdatum}})."},
            {"order": 2, "title": "Antwortschreiben entwerfen", "agent_id": "commercial_jurist_contracts", "prompt_template": "Erstelle rechtssicheren Art.-15-Antwortentwurf für {{anfragender}}."},
        ],
    },
    {
        "id": "pb_incident_postmortem",
        "title": "System-Incident Postmortem",
        "category": "Engineering & Ops",
        "description": "Blameless Root-Cause-Analyse nach Störungen inkl. konkreter Härtungs-Tasks.",
        "active": True,
        "builtin": True,
        "variables": ["incident_titel", "auswirkung"],
        "steps": [
            {"order": 1, "title": "Root-Cause-Analyse", "agent_id": "senior_fullstack_engineer", "prompt_template": "Analysiere Ursache und Timeline für Incident '{{incident_titel}}' (Auswirkung: {{auswirkung}})."},
            {"order": 2, "title": "Präventions-Maßnahmen", "agent_id": "systems_architect", "prompt_template": "Definiere konkrete technische Schutzmaßnahmen für '{{incident_titel}}'."},
        ],
    },
    {
        "id": "pb_content_campaign",
        "title": "B2B-Content- & LinkedIn-Kampagne",
        "category": "Marketing & Content",
        "description": "Erstellt aus einem Kernthema einen LinkedIn-Beitrag, einen Newsletter-Teaser und visuelle Hooks.",
        "active": True,
        "builtin": True,
        "variables": ["thema", "zielgruppe"],
        "steps": [
            {"order": 1, "title": "Hook & Kernbotschaft", "agent_id": "content_strategist", "prompt_template": "Entwickle 3 prägnante B2B-Hooks zum Thema '{{thema}}' für Zielgruppe {{zielgruppe}}."},
            {"order": 2, "title": "Post-Ausarbeitung", "agent_id": "copywriter", "prompt_template": "Formuliere den finalen LinkedIn-Post und Call-to-Action für '{{thema}}'."},
        ],
    },
    # --- 15 nachladbare Katalog-Playbooks (active=False, wie bei n8n nachladbar) ---
    {"id": "pb_ma_due_diligence", "title": "M&A Due-Diligence-Checkliste", "category": "Strategie & Boardroom", "description": "Strukturierte Commercial-, Financial- und Legal-DD für Zielunternehmen.", "active": False, "builtin": True, "variables": ["target_firma"], "steps": [{"order": 1, "title": "DD-Fragenkatalog", "agent_id": "cfo_financial_strategist", "prompt_template": "Erstelle Due-Diligence-Prüfplan für {{target_firma}}."}]},
    {"id": "pb_esg_supply_chain", "title": "ESG & Lieferketten-Check", "category": "Recht & Compliance", "description": "Prüft Lieferanten auf LkSG-/CSRD-Kriterien.", "active": False, "builtin": True, "variables": ["lieferant"], "steps": [{"order": 1, "title": "ESG-Bewertung", "agent_id": "compliance_officer", "prompt_template": "Bewerte ESG-Risiken für Lieferant {{lieferant}}."}]},
    {"id": "pb_patent_ip_search", "title": "Patent- & IP-Vorrecherche", "category": "Recht & Compliance", "description": "Recherchiert Schutzrechte und Freedom-to-Operate-Hinweise.", "active": False, "builtin": True, "variables": ["technologie"], "steps": [{"order": 1, "title": "IP-Recherche", "agent_id": "hermes-researcher", "prompt_template": "Recherchiere Patentlandschaft zu {{technologie}}."}]},
    {"id": "pb_recruiting_scorecard", "title": "Recruiting-Scorecard & Interview-Leitfaden", "category": "Operations & Führung", "description": "Erstellt strukturierte Bewertungskriterien und Interviewfragen.", "active": False, "builtin": True, "variables": ["rolle"], "steps": [{"order": 1, "title": "Scorecard-Design", "agent_id": "hr_director", "prompt_template": "Erstelle Recruiting-Scorecard für Position {{rolle}}."}]},
    {"id": "pb_price_increase_comms", "title": "Preiserhöhungs-Kommunikation", "category": "Sales & CRM", "description": "Formuliert wertorientierte Kundenanschreiben bei Preisanpassungen.", "active": False, "builtin": True, "variables": ["produkt", "prozent"], "steps": [{"order": 1, "title": "Kundenanschreiben", "agent_id": "sales_director", "prompt_template": "Entwirf Preisanpassungs-Schreiben für {{produkt}} (+{{prozent}}%)."}]},
    {"id": "pb_skonto_optimizer", "title": "Kreditoren-Skonto-Optimierung", "category": "Finanzen & ERP", "description": "Berechnet implizite Jahresrendite von Skontofristen vs. Kontokorrent.", "active": False, "builtin": True, "variables": ["zeitraum"], "steps": [{"order": 1, "title": "Skonto-Analyse", "agent_id": "cfo_financial_strategist", "prompt_template": "Prüfe Skonto-Potenziale für {{zeitraum}}."}]},
    {"id": "pb_saas_subscription_audit", "title": "SaaS-Abo- & Lizenz-Audit", "category": "Finanzen & ERP", "description": "Identifiziert ungenutzte Software-Lizenzen und Kündigungsfenster.", "active": False, "builtin": True, "variables": ["abteilung"], "steps": [{"order": 1, "title": "Lizenz-Review", "agent_id": "controlling_analyst", "prompt_template": "Auditiere SaaS-Kosten in Abteilung {{abteilung}}."}]},
    {"id": "pb_crisis_pr_plan", "title": "Krisen-PR-Sofortplan", "category": "Marketing & Content", "description": "Q&A, Stakeholder-Statement und interne Sprachregelung binnen 30 Min.", "active": False, "builtin": True, "variables": ["vorfall"], "steps": [{"order": 1, "title": "Krisen-Statement", "agent_id": "content_strategist", "prompt_template": "Erstelle Krisen-Q&A und Statement zu: {{vorfall}}."}]},
    {"id": "pb_okr_quarterly", "title": "OKR-Quartalsplanung", "category": "Operations & Führung", "description": "Leitet messbare Key Results aus Unternehmenszielen ab.", "active": False, "builtin": True, "variables": ["quartal", "fokus"], "steps": [{"order": 1, "title": "OKR-Entwurf", "agent_id": "executive_decision_architect", "prompt_template": "Entwirf OKRs für {{quartal}} mit Fokus {{fokus}}."}]},
    {"id": "pb_iso27001_prep", "title": "ISO-27001-Audit-Vorbereitung", "category": "Engineering & Ops", "description": "Prüft Annex-A-Nachweise, Richtlinien und offene Maßnahmen.", "active": False, "builtin": True, "variables": ["scope"], "steps": [{"order": 1, "title": "Control-Check", "agent_id": "compliance_officer", "prompt_template": "Prüfe ISO-27001-Readiness für Scope {{scope}}."}]},
    {"id": "pb_supplier_alternative", "title": "Lieferanten-Alternativsuche (Dual Sourcing)", "category": "Operations & Führung", "description": "Bewertet Zweitlieferanten zur Reduktion von Klumpenrisiken.", "active": False, "builtin": True, "variables": ["material_oder_service"], "steps": [{"order": 1, "title": "Markt-Screening", "agent_id": "hermes-researcher", "prompt_template": "Finde 5 alternative Anbieter für {{material_oder_service}} in DACH/EU."}]},
    {"id": "pb_annual_budget", "title": "Jahresbudget-Planung (Top-Down / Bottom-Up)", "category": "Finanzen & ERP", "description": "Strukturiert Kostenstellen, Investitionen und Umsatzannahmen.", "active": False, "builtin": True, "variables": ["jahr"], "steps": [{"order": 1, "title": "Budget-Struktur", "agent_id": "cfo_financial_strategist", "prompt_template": "Erstelle Budget-Vorlage für Geschäftsjahr {{jahr}}."}]},
    {"id": "pb_churn_prevention", "title": "Kunden-Churn-Prävention", "category": "Sales & CRM", "description": "Analysiert Warnsignale bei Bestandskunden und schlägt Bindungsmaßnahmen vor.", "active": False, "builtin": True, "variables": ["kunde"], "steps": [{"order": 1, "title": "Retention-Plan", "agent_id": "sales_director", "prompt_template": "Entwickle Bindungsplan für Bestandskunde {{kunde}}."}]},
    {"id": "pb_product_launch", "title": "Product-Launch-Checkliste", "category": "Marketing & Content", "description": "Koordiniert Release, Doku, Sales-Enablement und Launch-Kommunikation.", "active": False, "builtin": True, "variables": ["produktname", "launch_datum"], "steps": [{"order": 1, "title": "Launch-Plan", "agent_id": "operations_director", "prompt_template": "Erstelle Launch-Checkliste für {{produktname}} zum {{launch_datum}}."}]},
    {"id": "pb_ai_act_risk_check", "title": "EU AI Act Anwendungs-Prüfung", "category": "Recht & Compliance", "description": "Klassifiziert einen neuen KI-Use-Case nach Anhang III / Art. 50.", "active": False, "builtin": True, "variables": ["use_case"], "steps": [{"order": 1, "title": "Risiko-Einstufung", "agent_id": "compliance_officer", "prompt_template": "Klassifiziere KI-Use-Case '{{use_case}}' nach EU AI Act."}]},
]


class PlaybooksEngine:
    """Verwaltet Starter-Playbooks, nachladbaren Katalog, Editor-CRUD und 1-Klick-Runs."""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        base_data = data_dir or os.path.join(WORKSPACE_DIR, "data")
        self.data_dir = os.path.realpath(base_data)
        os.makedirs(self.data_dir, exist_ok=True)
        self.store_file = os.path.join(self.data_dir, "playbooks_store.json")
        self.runs_file = os.path.join(self.data_dir, "playbooks_runs.json")
        self._lock = threading.RLock()
        self._ensure_store()

    def _ensure_store(self) -> None:
        with self._lock:
            if not os.path.exists(self.store_file):
                self._write_json(self.store_file, BUILTIN_PLAYBOOKS)
            if not os.path.exists(self.runs_file):
                self._write_json(self.runs_file, [])

    def _read_json(self, path: str, default: Any) -> Any:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default

    def _write_json(self, path: str, data: Any) -> None:
        tmp = f"{path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def list_playbooks(
        self,
        active_only: Optional[bool] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            items: List[Dict[str, Any]] = self._read_json(self.store_file, [])
        cat_l = (category or "").strip().lower()
        q_l = (search or "").strip().lower()
        out: List[Dict[str, Any]] = []
        for pb in items:
            if active_only is True and not pb.get("active", False):
                continue
            if active_only is False and pb.get("active", False):
                continue
            if cat_l and cat_l not in str(pb.get("category", "")).lower():
                continue
            if q_l:
                hay = f"{pb.get('title', '')} {pb.get('description', '')} {pb.get('category', '')}".lower()
                if q_l not in hay:
                    continue
            out.append(pb)
        return out

    def get_playbook(self, playbook_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            items = self._read_json(self.store_file, [])
        for pb in items:
            if pb.get("id") == playbook_id:
                return pb
        return None

    def create_playbook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("Titel darf nicht leer sein.")
        steps = payload.get("steps") or []
        if not isinstance(steps, list) or not steps:
            raise ValueError("Mindestens ein Schritt (steps) ist erforderlich.")

        pb_id = str(payload.get("id") or f"pb_custom_{uuid.uuid4().hex[:8]}")
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        new_pb = {
            "id": pb_id,
            "title": title,
            "category": str(payload.get("category") or "Operations & Führung"),
            "description": str(payload.get("description") or ""),
            "active": bool(payload.get("active", True)),
            "builtin": False,
            "variables": list(payload.get("variables") or []),
            "steps": [
                {
                    "order": idx + 1,
                    "title": str(s.get("title") or f"Schritt {idx + 1}"),
                    "agent_id": str(s.get("agent_id") or "executive_decision_architect"),
                    "prompt_template": str(s.get("prompt_template") or ""),
                }
                for idx, s in enumerate(steps)
            ],
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        with self._lock:
            items = self._read_json(self.store_file, [])
            if any(x.get("id") == pb_id for x in items):
                raise ValueError(f"Playbook-ID '{pb_id}' existiert bereits.")
            items.append(new_pb)
            self._write_json(self.store_file, items)
        return new_pb

    def update_playbook(self, playbook_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            items = self._read_json(self.store_file, [])
            for idx, pb in enumerate(items):
                if pb.get("id") == playbook_id:
                    for field in ("title", "category", "description", "variables", "steps", "active"):
                        if field in payload and payload[field] is not None:
                            pb[field] = payload[field]
                    pb["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    items[idx] = pb
                    self._write_json(self.store_file, items)
                    return pb
        raise KeyError(f"Playbook '{playbook_id}' nicht gefunden.")

    def toggle_playbook(self, playbook_id: str, active: bool) -> Dict[str, Any]:
        return self.update_playbook(playbook_id, {"active": bool(active)})

    def delete_playbook(self, playbook_id: str) -> bool:
        with self._lock:
            items = self._read_json(self.store_file, [])
            for idx, pb in enumerate(items):
                if pb.get("id") == playbook_id:
                    if pb.get("builtin"):
                        raise ValueError("Built-in Playbooks können nur deaktiviert, nicht gelöscht werden.")
                    items.pop(idx)
                    self._write_json(self.store_file, items)
                    return True
        return False

    def run_playbook(self, playbook_id: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pb = self.get_playbook(playbook_id)
        if not pb:
            raise KeyError(f"Playbook '{playbook_id}' nicht gefunden.")

        vars_map = variables or {}
        rendered_steps: List[Dict[str, Any]] = []
        for step in pb.get("steps", []):
            prompt = str(step.get("prompt_template") or "")
            for k, v in vars_map.items():
                prompt = prompt.replace(f"{{{{{k}}}}}", str(v))
            rendered_steps.append({
                "order": step.get("order"),
                "title": step.get("title"),
                "agent_id": step.get("agent_id"),
                "rendered_prompt": prompt,
                "status": "queued",
            })

        run_record = {
            "run_id": f"pbrun_{uuid.uuid4().hex[:8]}",
            "playbook_id": playbook_id,
            "playbook_title": pb.get("title"),
            "variables": vars_map,
            "steps": rendered_steps,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "queued",
        }
        with self._lock:
            runs = self._read_json(self.runs_file, [])
            runs.insert(0, run_record)
            self._write_json(self.runs_file, runs[:200])
        return run_record


playbooks_engine = PlaybooksEngine()
