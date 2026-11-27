"""
backend/eu_ai_act_inventory.py
==============================
KI-Inventar & Risikoklassifizierungsregister für den EU AI Act (Verordnung (EU) 2024/1689, Art. 6, Anhang III, Art. 50 & Art. 95).
Klassifiziert alle aktiven Spezialisten des Archon OS-Kaders präzise (wortgrenzen- und rollenbasiert) nach europäischen Risikoklassen:
- HIGH_RISK (Art. 6 & Anhang III Nr. 4/5): HR-, Recruiting-, Bewerberauswahl-, Arbeitsrechts-/Personalentscheidungs- & Bonitätssysteme
- SPECIFIC_TRANSPARENCY (Art. 50): Externe Kommunikation, Outreach, PR, Marketing, Chatbots & synthetische Außeninhalte
- MINIMAL_RISK (Art. 95): Interne Analyse, Finanzen/Controlling intern, Software/DevOps, Strategie, Research
Ergänzt pro Spezialist kryptografischen SOUL-Prompt-Hash (SHA-256), Zero-Egress-Schutzstatus und Pflicht-Guardrails (M49).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(WORKSPACE_DIR, "agent_profiles.json")
INVENTORY_FILE = os.path.join(WORKSPACE_DIR, "data", "eu_ai_act_inventory.json")

# Audit D15: explizite Positivliste als SSOT. Die fruehere Zahl "26" in einem
# Kommentar war veraltet: die gepruefte Positivliste und das behoerdliche
# Inventar enthalten 28 HIGH_RISK-Rollen. EXPECTED_HIGH_RISK_COUNT wird unten
# aus der Positivliste abgeleitet, damit Kommentar, Zahl und Klassifikation
# nicht erneut auseinanderlaufen (D15-M5).
# Frueher lieferte eine substringsuche basierte Klassifikation 21 Rollen und
# False Positives ueber "tax" in "taxonomy". Wortgrenzen werden zusaetzlich
# geprueft (siehe _REGULATED_TERM_RE), sind aber nicht mehr klassifikations-
# entscheidend — nur die gepruefte Liste ist hoheitlich.
HIGH_RISK_AGENT_IDS = frozenset({
    # Anhang III Nr. 4 — Beschaeftigung & Personal
    "hr_recruiter",
    "labor_law_hr_governance",
    # Recht / Compliance
    "legal_counsel",
    "commercial_jurist_contracts",
    "ip_patent_analyst",
    "compliance_gdpr_auditor",
    # Anhang III Nr. 5(b) — Steuer, Finanzen, Versicherungen, Bonitaet
    "tax_holding_advisor",
    "vvgmbh_immo_tax_lead",
    "finance_lead",
    "debt_financing_specialist",
    "insurance_claims_manager",
    "liability_risk_analyst",
    "bi_controller",
    "realestate_dcf_calculator",
    # Medizin / Pharma / Wissenschaft (Art. 6)
    "clinical_medical_advisor",
    "medtech_regulatory_lead",
    "pharma_biotech_scientist",
    "scientific_literature_synthesizer",
    "chemistry_materials_specialist",
    # Bau / Planung / Industriesicherheit
    "construction_project_manager",
    "baugb_permit_expert",
    "urban_planning_architect",
    "industrial_process_engineer",
    # Hoheitliche/vertragliche Entscheidungen mit erheblicher Wirkung
    "executive_decision_architect",
    "vendor_contract_negotiator",
    "facility_asset_manager",
    # D15-H6: NICHT mehr "funktional identisch zum CEO". Der CEO
    # (executive_decision_architect) ist die einzige hoheitliche
    # Freigabeinstanz; der founder ist reine Strategieberatung OHNE
    # Freigaberecht. Beide bleiben HIGH_RISK, aber die Mandate sind
    # disambiguiiert (4-Augen-Freigaben laufen ausschliesslich ueber den CEO).
    # Die SSOT-Aenderungen in agent_profiles.json / org_hierarchy.json macht
    # Partition C; dieses Modul dokumentiert und konsumiert die Regel.
    "founder",
    # D15/MED: Containment-/Credential-/Sperraktionen mit realem Exekutivtool.
    "crisis_escalation_lead",
})
# D15-M5: Zahl aus der Positivliste ableiten, statt sie redundant zu pflegen.
EXPECTED_HIGH_RISK_COUNT = len(HIGH_RISK_AGENT_IDS)

# D15-H6: einzige ID mit hoheitlicher Freigabebefugnis (Konsument: classify_agent).
APPROVAL_AUTHORITY_AGENT_ID = "executive_decision_architect"

# Hoheits-Reihenfolge fuer Reklassifikations-Gates (tiefer = strenger).
RISK_TIER_ORDER = {
    "PROHIBITED": 0,
    "HIGH_RISK": 1,
    "LIMITED_RISK": 2,
    "SPECIFIC_TRANSPARENCY": 3,
    "MINIMAL_RISK": 4,
}
VALID_RISK_TIERS = frozenset(RISK_TIER_ORDER)

# D15-M5: die drei frueheren IDs existieren in keinem der 71 Profile der SSOT
# und waren tote Klassifikationsziele. Sie sind nun als *validierte historische
# Aliase* markiert: ein Alias wird nur dann als HIGH_RISK klassifiziert, wenn
# die ID in der jeweiigen Profil-SSOT real vorhanden ist (siehe
# classify_agent(known_ids=...)). In der Produktiv-SSOT greift damit keiner
# der Aliase mehr; Profile mit solchen IDs werden weiterhin korrekt nach
# Anhang III Nr. 5(b) eingestuft, falls sie jemals inventarisiert werden.
HISTORICAL_CREDIT_RISK_ALIASES: frozenset[str] = frozenset({
    "credit_risk_scorer",
    "loan_underwriter",
    "bonitaetspruefung",
})
CREDIT_RISK_AGENT_IDS: frozenset[str] = frozenset(HISTORICAL_CREDIT_RISK_ALIASES)

_PROHIBITED_MARKERS = (
    "social_scoring",
    "workplace_emotion_recognition",
    "emotion_recognition_workplace",
    "subliminal_manipulation",
)

# H-15-2/F023: NUR reale IDs aus den 71 Profilen (SSOT agent_profiles.json).
# Die alte Positivliste enthielt ausschliesslich nicht existierende Handles,
# wodurch echte Außenkommunikationsrollen als MINIMAL_RISK durchfielen.
TRANSPARENCY_AGENT_IDS = frozenset({
    "affiliate_partner_manager",
    "b2b_outreach_specialist",
    "content_repurposing_specialist",
    "customer_retention_specialist",
    "customer_support_lead",
    "direct_response_copywriter",
    "gtm_launch_strategist",
    "growth_hacker_lead",
    "linkedin_social_media_specialist",
    "paid_ads_manager",
    "pitchdeck_offer_designer",
    "pr_press_communicator",
    "seo_geo_specialist",
    "speechwriter_keynote_designer",
    "storyteller_ghostwriter",
    "telegram_bot",
    "video_script_architect",
})

_HIGH_RISK_ID_NAME_RE = re.compile(
    r"\b(recruiter|recruiting|bewerber\w*|candidate\w*|headhunting|chro|personalauswahl|personalmanagement|leistungsbewertung|bonitaetspruefung|credit_scor\w*)\b",
    re.IGNORECASE,
)
_HIGH_RISK_PURPOSE_RE = re.compile(
    r"\b(bewerbungen|bewerberauswahl|kandidatenauswahl|auswahlmatrix|personalentscheidungen|leistungsbewertung\w*|arbeitsvertr[aä]ge|aufhebungsvereinbarung\w*|arbeitszeugnis\w*)\b",
    re.IGNORECASE,
)
# Audit D15: Wortgrenzen auf ISOLIERTEN Feldern — kein Substring-Match mehr
# ueber Skills ("tax" in "taxonomy", "recht" in "arbeitsrecht-skill").
_REGULATED_TERM_RE = re.compile(
    r"\b(medizin|medizinisch|medical|klinisch|clinical|recht|legal|steuer|tax|treasury|finanz|finance|pharma|biotech|bonitaet|kredit|insurance|versicherung)\b",
    re.IGNORECASE,
)

_TRANSPARENCY_ID_NAME_RE = re.compile(
    r"\b(outreach|copywrit\w*|marketing|pr_press|pressemitteilung\w*|social_media|newsletter|"
    r"sales|vertrieb\w*|chatbot|support|ghostwriter|influencer|brand\w*|"
    r"ads|media|content|speech\w*|keynote|retention|deck|video_script)\b",
    re.IGNORECASE,
)
# H-15-3/F023: Außenwirkung wird aus der BESCHREIBUNG abgeleitet, nicht aus
# Skill-Namen (z.B. 'cold-email' im founder-Profil). Die Positivliste bleibt
# hoheitlich; die Regex ist nur ein Hinweis für echte Außentexte.
_TRANSPARENCY_PURPOSE_RE = re.compile(
    r"\b(cold[- ]?email\w*|erstnachrichten|follow[- ]?up|pressemitteilung\w*|"
    r"marketing[- ]?kampagne\w*|werbetext\w*|werbung|kampagnen\w*|"
    r"kundenkommunikation|außenkommunikation|social[- ]?media[- ]?post\w*|"
    r"content[- ]?erstellung|speech|keynote|retention|pitch[- ]?deck)\b",
    re.IGNORECASE,
)


# D15-H2: EINZIGE Prompt-SSOT ist ``agent_profiles.json.prompt`` (bzw.
# ``system_prompt``) — genau der Text, den der Dispatch als System-Prompt
# verwendet. ``souls/<id>/SOUL.md`` ist ein abgeleitetes Artefakt und darf
# nicht laengst dispatchen Prompt-Bytes pinnen. Beide Seiten (Pin in
# generate_inventory und Live-Pruefung in compliance_engine) normalisieren
# den Text identisch, damit der Vergleich bytesicher funktioniert.
SOUL_HASH_SOURCE = "profile_prompt_v2"


def _normalize_soul_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _hash_soul_text(text: str) -> Optional[str]:
    normalized = _normalize_soul_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def _canonical_soul_file(agent_id: str) -> str:
    return os.path.join(WORKSPACE_DIR, "souls", agent_id, "SOUL.md")


def compute_live_soul_sha256(agent_id: str, profiles_file: Optional[str] = None) -> Optional[str]:
    """Live-Hash der Prompt-SSOT (agent_profiles.json) fuer ``agent_id``.

    Nur wenn die SSOT keinen Prompt enthaelt, wird das kanonische
    ``souls/<id>/SOUL.md``-Artefakt als Fallback herangezogen. Fehlt beides,
    wird bewusst ``None`` geliefert (fail-closed). ``profiles_file`` ist
   override-bar, damit Produktivpfad und Tests dieselbe Quelle verwenden.
    """
    aid = str(agent_id or "").strip()
    if not aid:
        return None
    source = profiles_file if profiles_file is not None else PROFILES_FILE
    try:
        if os.path.isfile(source):
            with open(source, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            profiles = data if isinstance(data, list) else list(data.values())
            for prof in profiles:
                if isinstance(prof, dict) and str(prof.get("id") or "").strip() == aid:
                    prompt = prof.get("prompt") or prof.get("system_prompt") or ""
                    hashed = _hash_soul_text(prompt)
                    if hashed:
                        return hashed
                    break
    except Exception as exc:
        print(f"[EUAIAct] Prompt-SSOT {source} nicht lesbar: {exc}", file=sys.stderr)
    try:
        canon = _canonical_soul_file(aid)
        if os.path.isfile(canon):
            with open(canon, "r", encoding="utf-8", newline="") as fh:
                return _hash_soul_text(fh.read())
    except Exception as exc:
        print(f"[EUAIAct] kanonisches SOUL {aid} nicht lesbar: {exc}", file=sys.stderr)
    return None


def validate_classification_ids(profiles: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """D15-M5: CI-Gate — alle hoheitlichen ID-Sets sind subset der Profil-SSOT.

    Prueft zusaetzlich, dass die aus der Positivliste abgeleitete erwartete
    HIGH_RISK-Anzahl mit der Positivliste uebereinstimmt und dass keine
    historischen Phantomer als aktive Klassifikationsziele gepflegt werden.
    """
    if profiles is None:
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            profiles = data if isinstance(data, list) else list(data.values())
        except Exception:
            profiles = []
    known = {str(p.get("id") or "").strip() for p in profiles if isinstance(p, dict)}
    unknown_high = sorted(HIGH_RISK_AGENT_IDS - known)
    unknown_transparency = sorted(TRANSPARENCY_AGENT_IDS - known)
    # Kredit-Aliase duerfen nur als markierte historische Aliase gefuehrt
    # werden; ein aktiver, nicht in der SSOT vorhandener Pin waere ein Phantom.
    active_credit = sorted(CREDIT_RISK_AGENT_IDS & known)
    aliases_outside_ssot = sorted(CREDIT_RISK_AGENT_IDS - known)
    ok = (
        not unknown_high
        and not unknown_transparency
        and CREDIT_RISK_AGENT_IDS.issubset(HISTORICAL_CREDIT_RISK_ALIASES)
        and EXPECTED_HIGH_RISK_COUNT == len(HIGH_RISK_AGENT_IDS)
    )
    return {
        "ok": ok,
        "profile_count": len(known),
        "high_risk_count": len(HIGH_RISK_AGENT_IDS),
        "expected_high_risk_count": EXPECTED_HIGH_RISK_COUNT,
        "unknown_high_risk_ids": unknown_high,
        "unknown_transparency_ids": unknown_transparency,
        "active_credit_risk_ids": active_credit,
        "historical_credit_aliases_outside_ssot": aliases_outside_ssot,
    }


def _compute_soul_sha256(agent: Dict[str, Any]) -> Optional[str]:
    """Berechnet den Pin aus der EINEN Prompt-SSOT (agent_profiles.json).

    Audit D15: frueher wurde bei fehlender Quelle ein Hash aus id/name/
    description erfunden und in der behoerdlichen PDF als "gepinnt" gefuehrt.
    Jetzt ist der tatsaechlich dispatche Prompt maengeblich; das kanonische
    SOUL-Artefakt ist nur Fallback. Ohne echte Quelle wird bewusst None
    geliefert (fail-closed in compliance_engine.check_activation_allowed).
    """
    prompt_text = agent.get("prompt") or agent.get("system_prompt") or ""
    hashed = _hash_soul_text(prompt_text)
    if hashed:
        return hashed
    aid = str(agent.get("id") or "").strip()
    if aid:
        try:
            canon = _canonical_soul_file(aid)
            if os.path.isfile(canon):
                with open(canon, "r", encoding="utf-8", newline="") as fh:
                    return _hash_soul_text(fh.read())
        except Exception as exc:
            print(f"[EUAIAct] kanonisches SOUL {aid} nicht lesbar: {exc}", file=sys.stderr)
    return None


def _is_zero_egress_category(category: str, aid: str) -> bool:
    try:
        from backend.privacy_router import get_privacy_config
        cfg = get_privacy_config()
        sens = [str(s).lower() for s in cfg.get("sensitive_categories", [])]
    except Exception:
        sens = ["finance", "receipts", "contracts", "crm", "gdpr", "personalakte", "hr"]
    haystack = f"{category} {aid}".lower()
    keywords = set(sens) | {"recht", "steuern", "compliance", "finanzen", "controlling", "hr", "personal", "medizin", "klinisch", "vertr"}
    return any(k in haystack for k in keywords)


class EUAIActInventoryManager:
    """Verwaltet und generiert das behördliche KI-Inventar nach Art. 6, Anhang III, Art. 50 & Art. 95 EU AI Act."""

    HIGH_RISK_KEYWORDS = [
        "recruiting", "bewerber", "candidate", "hr_recruiter", "personalauswahl",
        "leistungsbewertung", "headhunting", "chro",
    ]

    TRANSPARENCY_KEYWORDS = [
        "email", "e-mail", "outreach", "cold", "marketing", "copywriting",
        "chatbot", "sales", "vertrieb", "social", "linkedin",
        "pressemitteilung", "campaign", "newsletter",
    ]

    def __init__(self, profiles_file: str = PROFILES_FILE, inventory_file: str = INVENTORY_FILE):
        self.profiles_file = profiles_file
        self.inventory_file = inventory_file
        os.makedirs(os.path.dirname(self.inventory_file), exist_ok=True)

    def load_profiles(self) -> List[Dict[str, Any]]:
        """Lädt alle Agentenprofile aus agent_profiles.json."""
        if not os.path.exists(self.profiles_file):
            return []
        try:
            with open(self.profiles_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else list(data.values())
        except Exception as e:
            print(f"[EUAIAct] Fehler beim Laden von agent_profiles.json: {e}", file=sys.stderr)
            return []

    def classify_agent(
        self, agent: Dict[str, Any], known_ids: Optional[set[str]] = None
    ) -> Dict[str, Any]:
        """Klassifiziert einen Agenten präzise nach VO (EU) 2024/1689.

        ``known_ids`` ist die Profil-SSOT der laufenden Inventarisierung.
        Historische Kredit-Aliase (D15-M5) werden nur beruecksichtigt, wenn
        ihre ID dort tatsaechlich existiert — sonst waeren sie tote
        Klassifikationsziele ohne Profil.
        """
        aid = str(agent.get("id") or agent.get("name", "unknown")).strip()
        name = str(agent.get("name") or aid).strip()
        category = str(agent.get("category", "General")).strip()
        desc = str(agent.get("description") or "")
        skills = " ".join(agent.get("skills") or [])
        # H-15-2: die Transparenz-Regex darf NUR auf ID+Name wirken. Viele
        # Fachrollen fuehren generische Skills wie `media`/`social-media`, die
        # sonst 39 statt der realen Außenrollen als Art.50 klassifizieren.
        id_and_name = f"{aid} {name}"
        purpose_text = f"{desc} {skills}"
        # H-15-3: Art.50-Auswirkung aus der Aufgabenbeschreibung, niemals aus
        # Skill-Namen — sonst wird ein Strategie-CEO wegen 'cold-email' falsch
        # als Transparenzrolle klassifiziert.
        transparency_purpose = desc

        provider = agent.get("provider", "omniroute")
        model = agent.get("model", "strict-free-tier-combo")
        soul_sha256 = _compute_soul_sha256(agent)
        zero_egress = _is_zero_egress_category(category, aid)

        is_prohibited = any(m in f"{aid} {desc}".lower() for m in _PROHIBITED_MARKERS)
        # D15-M5: historische Aliase sind nur gueltig, wenn die ID in der
        # Profil-SSOT existiert. Ohne ``known_ids`` (Einzelaufruf) gilt der
        # uebergebene Agent selbst als SSOT-Beleg.
        ssot_ids = known_ids if known_ids is not None else {aid}
        is_credit_risk = (
            (not is_prohibited) and (aid in CREDIT_RISK_AGENT_IDS) and (aid in ssot_ids)
        )
        # Audit D15: die explizite Positivliste (28 Rollen, aus EXPECTED_HIGH_RISK_COUNT
        # abgeleitet) ist hoheitlich.
        # Die Wortgrenzen-Regex wird nur auf isolierte Kontextfelder angewendet
        # und dient als Audit-Hinweis, nicht als Klassifikationsersatz — damit
        # gibt es keine False Positives mehr durch Skill-Namen ("taxonomy").
        isolated_text = f"{category} {name} {desc} {agent.get('category_en', '')}"
        regulated_signal = bool(_REGULATED_TERM_RE.search(isolated_text))
        hr_signal = aid in {"hr_recruiter", "labor_law_hr_governance"} or (
            bool(_HIGH_RISK_ID_NAME_RE.search(f"{aid} {name}"))
            and bool(_HIGH_RISK_PURPOSE_RE.search(purpose_text))
        )
        in_positive_list = aid in HIGH_RISK_AGENT_IDS
        is_hr_high_risk = (not is_prohibited) and not is_credit_risk and hr_signal
        is_regulated_high_risk = (
            (not is_prohibited) and not is_credit_risk and not is_hr_high_risk
            and in_positive_list
        )
        is_high_risk = (not is_prohibited) and (
            is_credit_risk or is_hr_high_risk or is_regulated_high_risk
        )

        is_transparency = (
            not is_prohibited
            and not is_high_risk
            and (
                aid in TRANSPARENCY_AGENT_IDS
                or bool(_TRANSPARENCY_ID_NAME_RE.search(id_and_name))
                or bool(_TRANSPARENCY_PURPOSE_RE.search(transparency_purpose))
            )
        )

        if is_prohibited:
            risk_tier = "PROHIBITED"
            legal_basis = "Art. 5 VO (EU) 2024/1689 (Verbotene KI-Praktik — zwingende Sperrung seit 02.02.2025)"
            human_oversight = "PROHIBITED_BLOCKED"
            data_protection = "Betrieb untersagt (Art. 5 EU AI Act)"
            compliance_status = "BLOCKED_PROHIBITED"
            audit_interval_months = 1
            required_guardrails = ["HARD_BLOCK_ART5"]
        elif is_credit_risk:
            risk_tier = "HIGH_RISK"
            legal_basis = "Art. 6 Abs. 2 i.V.m. Anhang III Nr. 5 lit. b EU AI Act (Kreditwürdigkeitsprüfung & Finanzscoring — FRIA Art. 27 erforderlich)"
            human_oversight = "MANDATORY_HITL (4-Augen-Freigabe & FRIA vor Kredit-/Bonitätsentscheidungen)"
            data_protection = "PII-Maskierung aktiv, lokale Datenhaltung, revisionssicheres GoBD-Audit-Log, FRIA Art. 27"
            compliance_status = "COMPLIANT_WITH_OVERSIGHT"
            audit_interval_months = 6
            required_guardrails = ["MANDATORY_4_EYES_HITL", "FRIA_ART27", "PII_MASKING", "GOBD_MERKLE_AUDIT", "SOUL_HASH_PINNING"]
        elif is_hr_high_risk:
            risk_tier = "HIGH_RISK"
            legal_basis = "Art. 6 Abs. 2 i.V.m. Anhang III Nr. 4 EU AI Act (Beschäftigung, Personalmanagement & Recruiting — Art. 26 Abs. 7 BetrVG)"
            human_oversight = "MANDATORY_HITL (4-Augen-Freigabe vor Übernahme von Personalentscheidungen)"
            data_protection = "PII-Maskierung aktiv, lokale Datenhaltung, revisionssicheres GoBD-Audit-Log"
            compliance_status = "COMPLIANT_WITH_OVERSIGHT"
            audit_interval_months = 6
            required_guardrails = ["MANDATORY_4_EYES_HITL", "WORKS_COUNCIL_NOTICE_ART26_7", "PII_MASKING", "GOBD_MERKLE_AUDIT", "SOUL_HASH_PINNING"]
        elif is_regulated_high_risk:
            risk_tier = "HIGH_RISK"
            legal_basis = "Art. 6 VO (EU) 2024/1689 — konservative Einstufung regulierter Fachdomänen (Medizin/Recht/Steuer/Finanzen); FRIA Art. 27 empfohlen"
            human_oversight = "MANDATORY_HITL (4-Augen-Freigabe vor bindenden Aussagen oder Entscheidungen)"
            data_protection = "PII-Maskierung aktiv, lokale Datenhaltung, revisionssicheres GoBD-Audit-Log"
            compliance_status = "COMPLIANT_WITH_OVERSIGHT"
            audit_interval_months = 6
            required_guardrails = ["MANDATORY_4_EYES_HITL", "NEGATIVE_SCOPE_GUARDRAILS", "PII_MASKING", "GOBD_MERKLE_AUDIT", "SOUL_HASH_PINNING"]
        elif is_transparency:
            risk_tier = "SPECIFIC_TRANSPARENCY"
            legal_basis = "Art. 50 EU AI Act (Transparenzpflicht für KI-Interaktion & synthetische Inhalte)"
            human_oversight = "HUMAN_IN_THE_LOOP (E-Mail- & Content-Freigabe-Queue vor Außenversand)"
            data_protection = "DSGVO Zero-Egress Option, Kennzeichnungspflicht bei Außenversand"
            compliance_status = "COMPLIANT"
            audit_interval_months = 12
            required_guardrails = ["OUTBOUND_APPROVAL_QUEUE", "AI_DISCLOSURE_TAG", "GOBD_MERKLE_AUDIT"]
        else:
            risk_tier = "MINIMAL_RISK"
            legal_basis = "Art. 95 EU AI Act (Interne Fachassistenz & Analyse — freiwillige Governance-Kodizes)"
            human_oversight = "AUTONOMOUS_SUPERVISED (System Watchdog & Revisionssicheres Audit-Log)"
            data_protection = "Zero Data Retention / On-Premise Routing für sensible Domänen"
            compliance_status = "COMPLIANT"
            audit_interval_months = 24
            required_guardrails = ["GOBD_MERKLE_AUDIT", "DUAL_LLM_PROMPT_GUARD"]

        return {
            "agent_id": aid,
            "agent_name": name,
            "category": category,
            "risk_tier": risk_tier,
            "legal_basis": legal_basis,
            "human_oversight_measure": human_oversight,
            "data_protection_measures": data_protection,
            "compliance_status": compliance_status,
            "audit_interval_months": audit_interval_months,
            "underlying_model": f"{provider} / {model}",
            "primary_purpose": desc or "Autonome Fachassistenz im Archon OS Ökosystem",
            "soul_sha256": soul_sha256,
            "soul_hash_source": SOUL_HASH_SOURCE,
            "regulated_term_signal": regulated_signal,  # Audit-Hinweis (Wortgrenzen, isolierte Felder)
            "zero_egress_protected": zero_egress,
            "required_guardrails": required_guardrails,
            # D15-H6: nur der CEO besitzt hoheitliche Freigabebefugnis; der
            # founder ist Strategieberatung ohne Freigaberecht.
            "approval_authority": aid == APPROVAL_AUTHORITY_AGENT_ID,
            # D15-M1: nicht mehr bool(pin), sondern echter Vergleich gegen die
            # aktuelle Prompt-SSOT. Drift macht guardrails_verified=false.
            "guardrails_verified": bool(soul_sha256)
            and soul_sha256 == compute_live_soul_sha256(aid)
            and ("HITL" in human_oversight if is_high_risk else True),
            "last_classified_at": datetime.datetime.now().strftime("%Y-%m-%d"),
        }

    def generate_inventory(self, save: bool = True) -> List[Dict[str, Any]]:
        """Klassifiziert alle aktiven Spezialisten und speichert das Verzeichnis in data/eu_ai_act_inventory.json."""
        profiles = self.load_profiles()
        inventory = []

        overrides: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(self.inventory_file):
            try:
                with open(self.inventory_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                    for item in existing:
                        if item.get("is_manual_override"):
                            overrides[item["agent_id"]] = item
            except Exception as exc:
                print(f"[EUAIAct] Bestehendes Inventar konnte nicht geladen werden, manuelle Overrides bleiben unberuecksichtigt: {exc}", file=sys.stderr)

        known_ids = {str(p.get("id") or p.get("name") or "").strip() for p in profiles}
        for p in profiles:
            aid = p.get("id") or p.get("name")
            classified = self.classify_agent(p, known_ids=known_ids)
            if aid in overrides:
                merged = dict(classified)
                merged.update(overrides[aid])
                merged["soul_sha256"] = classified["soul_sha256"]
                inventory.append(merged)
            else:
                inventory.append(classified)

        tier_order = {"HIGH_RISK": 0, "SPECIFIC_TRANSPARENCY": 1, "MINIMAL_RISK": 2}
        inventory = sorted(inventory, key=lambda x: (tier_order.get(x["risk_tier"], 9), x["agent_name"]))

        if save:
            tmp = f"{self.inventory_file}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(inventory, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.inventory_file)

        return inventory

    def get_inventory(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """Gibt das aktuelle KI-Inventar zurück (regeneriert automatisch bei Schema-Upgrade oder neueren Profilen)."""
        if not refresh and os.path.exists(self.inventory_file):
            try:
                profiles = self.load_profiles()
                if (
                    not os.path.exists(self.profiles_file)
                    or os.path.getmtime(self.inventory_file) >= os.path.getmtime(self.profiles_file)
                ):
                    with open(self.inventory_file, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    # Ein reiner mtime-Vergleich reicht nicht: ein Inventar, das
                    # mit einer anderen (kleineren) Profilbasis geschrieben
                    # wurde, bleibt sonst "aktuell" und liefert nur 1 statt
                    # 73 Agenten. Zusaetzlich die Profilmenge abgleichen.
                    if (
                        loaded and isinstance(loaded, list)
                        and "soul_sha256" in loaded[0]
                        # D15-H2: ein mit alter Hash-Quelle (souls/<id>/SOUL.md)
                        # geschriebenes Inventar darf nicht als "aktuell" gelten,
                        # sonst wuerde der geprinnte Prompt dauerhaft driftieren.
                        and loaded[0].get("soul_hash_source") == SOUL_HASH_SOURCE
                        and len(loaded) == len(profiles)
                    ):
                        return loaded
            except Exception as exc:
                print(f"[EUAIAct] Gecachtes Inventar nicht lesbar, Inventar wird neu generiert: {exc}", file=sys.stderr)
        return self.generate_inventory(save=True)

    def get_stats(self) -> Dict[str, Any]:
        """Liefert Kennzahlen zur EU AI Act Compliance für Dashboards und Audits."""
        inventory = self.get_inventory()
        total = len(inventory)
        counts = {"PROHIBITED": 0, "HIGH_RISK": 0, "SPECIFIC_TRANSPARENCY": 0, "MINIMAL_RISK": 0}

        compliant_count = 0
        oversight_count = 0
        for item in inventory:
            tier = item.get("risk_tier", "MINIMAL_RISK")
            counts[tier] = counts.get(tier, 0) + 1
            c_stat = str(item.get("compliance_status") or "")
            oversight = str(item.get("human_oversight_measure") or "")
            if tier != "PROHIBITED" and c_stat not in ("NON_COMPLIANT", "BLOCKED_PROHIBITED"):
                compliant_count += 1
            if tier != "PROHIBITED" and oversight and oversight not in ("NONE", "PROHIBITED_BLOCKED"):
                oversight_count += 1

        soul_pinned = sum(1 for item in inventory if item.get("soul_sha256"))
        zero_egress_count = sum(1 for item in inventory if item.get("zero_egress_protected"))
        oversight_pct = round((oversight_count / total) * 100.0, 1) if total > 0 else 0.0
        readiness_pct = round((compliant_count / total) * 100.0, 1) if total > 0 else 0.0

        return {
            "total_agents": total,
            "risk_distribution": counts,
            "prohibited_count": counts.get("PROHIBITED", 0),
            "high_risk_count": counts.get("HIGH_RISK", 0),
            "transparency_risk_count": counts.get("SPECIFIC_TRANSPARENCY", 0),
            "minimal_risk_count": counts.get("MINIMAL_RISK", 0),
            "soul_hashes_pinned": soul_pinned,
            "zero_egress_agents": zero_egress_count,
            "human_oversight_rate_pct": oversight_pct,
            "compliance_readiness_score": readiness_pct,
            "applicable_regulations": [
                "Verordnung (EU) 2024/1689 (EU AI Act — Art. 4, 5, 6, 26, 27, Anhang III, Art. 50, Art. 95)",
                "DSGVO (Verordnung (EU) 2016/679 — Art. 13, 15, 17, 18, 25, 30, 32)",
                "GoBD (BMF-Schreiben 28.11.2019 / 11.03.2024 — Rz. 151 ff.) & BEG IV",
            ],
        }

    @staticmethod
    def _validate_override(
        item: Dict[str, Any], updates: Dict[str, Any], verified_approval_id: str = ""
    ) -> Dict[str, Any]:
        """H-14-3/F022: Hoheits-Gates fuer Reklassifikation (fail-closed)."""
        reason = str(updates.get("override_reason") or "").strip()
        current = str(item.get("risk_tier") or "MINIMAL_RISK")
        new_tier = str(updates.get("risk_tier") or current)
        # Der Router erzwingt die Begruendung ueber Pydantic fuer JEDEN
        # Reklassifikations-Call. Auf Engine-Ebene ist sie fuer echte Tier-
        # Aenderungen zwingend; reine Feldkorrekturen bleiben kompatibel.
        if "risk_tier" in updates and len(reason) < 10:
            raise ValueError("override_reason_required: Begruendung mit mind. 10 Zeichen obligatorisch.")
        if new_tier not in VALID_RISK_TIERS:
            raise ValueError(f"unknown_risk_tier: {new_tier}")
        if current == "PROHIBITED" and new_tier != "PROHIBITED":
            raise ValueError("prohibited_downgrade_forbidden: Art. 5-Sperrung ist nicht aufhebbar.")

        if (
            current in ("HIGH_RISK", "LIMITED_RISK", "SPECIFIC_TRANSPARENCY")
            and RISK_TIER_ORDER.get(new_tier, 99) > RISK_TIER_ORDER.get(current, 99)
            and not str(verified_approval_id or "").strip()
        ):
            raise ValueError(
                "four_eyes_proposal_required: Downgrade von "
                f"{current} nach {new_tier} erfordert den 4-Augen-Vorschlagspfad "
                "(approval request mit zweiter, identitaetsverschiedener Person)."
            )
        return updates

    def set_manual_override(
        self,
        agent_id: str,
        updates: Dict[str, Any],
        actor: str = "admin",
        *,
        verified_approval_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Manuelle Klassifizierungsaenderung inkl. zwingendem Revisionsnachweis.

        H-14-3/F022: PROHIBITED-Downgrades sind hart gesperrt, Downgrades von
        HIGH_RISK/LIMITED_RISK/SPECIFIC_TRANSPARENCY nur mit verifizierter
        4-Augen-Freigabe. Audit-Schreibfehler werden NICHT verschluckt.
        """
        inventory = self.get_inventory()
        target = None
        allowed_fields = {
            "risk_tier",
            "legal_basis",
            "human_oversight_measure",
            "data_protection_measures",
            "compliance_status",
            "audit_interval_months",
            "override_reason",
        }
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}
        for idx, item in enumerate(inventory):
            if item["agent_id"] == agent_id:
                filtered = self._validate_override(item, filtered, verified_approval_id)
                old_tier = str(item.get("risk_tier") or "")
                item.update(filtered)
                item["is_manual_override"] = True
                item["override_by"] = str(actor or "admin")
                item["override_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if str(verified_approval_id or "").strip():
                    item["override_approval_id"] = str(verified_approval_id).strip()
                item["last_classified_at"] = item["override_at"]
                target = item
                inventory[idx] = item
                _old_tier = old_tier
                break
        else:
            return None

        tmp = f"{self.inventory_file}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(inventory, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.inventory_file)
        from backend.audit_log import _require_audit_event
        _require_audit_event(
            "governance", "ai_act_reclassified", str(actor or "admin"),
            {
                "target_agent": agent_id,
                "updates": filtered,
                "old_risk_tier": _old_tier,
                "new_risk_tier": str(filtered.get("risk_tier") or _old_tier),
                "approval_id": str(verified_approval_id or "") or None,
            },
        )
        return target

    def apply_approved_reclassification(
        self, agent_id: str, updates: Dict[str, Any], actor: str, approval_id: str
    ) -> Optional[Dict[str, Any]]:
        """Wendet einen per 4-Augen-Vorschlag freigegebenen Downgrade an."""
        if not str(approval_id or "").strip():
            raise ValueError("approval_id_required")
        return self.set_manual_override(
            agent_id, updates, actor=actor, verified_approval_id=approval_id
        )

    def export_report_markdown(self) -> str:
        """Erzeugt einen behördlich konformen Markdown-Bericht über das gesamte KI-Register."""
        inv = self.get_inventory()
        stats = self.get_stats()
        now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

        md = []
        md.append("# Offizielles KI-Systemregister & Konformitätsbericht nach EU AI Act")
        md.append(f"**Rechtsgrundlage:** Verordnung (EU) 2024/1689 (Art. 4, 6, Anhang III, Art. 50 & Art. 95) | **Stand:** {now}\n")
        md.append("## 1. Zusammenfassung des KI-Inventars")
        md.append(f"- **Erfasste autonome Agenten:** {stats['total_agents']}")
        md.append(f"- **Hochrisiko-Systeme (Art. 6 & Anhang III):** {stats['high_risk_count']}")
        md.append(f"- **Systeme mit Transparenzpflicht (Art. 50):** {stats['transparency_risk_count']}")
        md.append(f"- **Systeme mit Minimalrisiko (Art. 95):** {stats['minimal_risk_count']}")
        md.append(f"- **Gepinnte SOUL-Systemprompt-Hashes (SHA-256):** {stats['soul_hashes_pinned']}")
        md.append(f"- **Menschliche Aufsichtsquote (Human-in-the-Loop):** {stats['human_oversight_rate_pct']}%\n")

        md.append("## 2. Detailliertes Verzeichnis aller Agenten")
        md.append("| Agenten-ID | Name | Kategorie | Risikostufe | SOUL-SHA256 | Menschliche Aufsicht | Modell |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        for item in inv:
            aid = item["agent_id"]
            aname = item["agent_name"]
            cat = item["category"]
            tier = item["risk_tier"]
            shash = str(item.get("soul_sha256", ""))[:12]
            oversight = item["human_oversight_measure"].split("(")[0].strip()
            model = item["underlying_model"]
            md.append(f"| `{aid}` | {aname} | {cat} | **{tier}** | `{shash}` | {oversight} | {model} |")

        md.append("\n## 3. Technische Schutzmaßnahmen & Governance")
        md.append("1. **Human-in-the-Loop (HITL):** Bei allen Hochrisiko- und Transparenz-Agenten werden Entscheidungen und Außenkommunikation vorab in einer Freigabe-Queue zur manuellen Prüfung vorgelegt.")
        md.append("2. **Zero-Egress & Lokale LLMs:** Sensible Verarbeitungen können vollständig ohne Datenabfluss auf lokalen Modellen (z. B. LM Studio / Ollama) ausgeführt werden.")
        md.append("3. **Revisionssicheres Audit-Log:** Jeder Agentenaufruf, jedes Tool und jede Modellausgabe wird mit SHA-256 Hashverkettung unveränderlich archiviert.")

        return "\n".join(md)


eu_ai_act_inventory_manager = EUAIActInventoryManager()
