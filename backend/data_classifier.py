"""
backend/data_classifier.py
Automatische Datenklassifizierung & Schutzstufen für Archon OS (t-53315b, Pillar 6 & ISO 27001 A.8.2).
Klassifiziert Dokumente, Aufgaben, E-Mails und Notizen in 4 standardisierte Schutzstufen:
- PUBLIC (Stufe 0): Öffentlich freigegebene Inhalte (Marketing, Showroom, Doku)
- INTERNAL (Stufe 1): Interne Arbeitsdokumente, Sprint-Tasks, Code-Architektur
- CONFIDENTIAL (Stufe 2): Verträge, Rechnungen, Angebote, CRM-Kontakte (PII-Scrubbing / EU-Routing)
- STRICTLY_CONFIDENTIAL (Stufe 3): Passwörter, API-Keys, Personalakten, Gehälter, NDAs (Zwingend Zero-Egress / Lokales LLM)
"""

import os
import re
import sys
import json
import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLASSIFICATION_DB = os.path.join(WORKSPACE_DIR, "data", "data_classifications.json")


class ClassificationLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    STRICTLY_CONFIDENTIAL = "STRICTLY_CONFIDENTIAL"


CLASSIFICATION_METADATA = {
    ClassificationLevel.PUBLIC: {
        "level": 0,
        "name_de": "Öffentlich",
        "color": "emerald",
        "description": "Informationen für jedermann ohne Vertraulichkeitsbedarf.",
        "routing_policy": "ALLOW_ANY",
        "cloud_llm_allowed": True,
        "pii_scrubbing_required": False
    },
    ClassificationLevel.INTERNAL: {
        "level": 1,
        "name_de": "Intern",
        "color": "sky",
        "description": "Standardmäßige interne Betriebsinformationen für Mitarbeiter und Agenten.",
        "routing_policy": "STANDARD",
        "cloud_llm_allowed": True,
        "pii_scrubbing_required": False
    },
    ClassificationLevel.CONFIDENTIAL: {
        "level": 2,
        "name_de": "Vertraulich",
        "color": "amber",
        "description": "Geschäfts- und Kundendaten (Verträge, Angebote, Rechnungen, CRM).",
        "routing_policy": "SCRUB_OR_EU_HOSTED",
        "cloud_llm_allowed": True,
        "pii_scrubbing_required": True
    },
    ClassificationLevel.STRICTLY_CONFIDENTIAL: {
        "level": 3,
        "name_de": "Streng geheim",
        "color": "rose",
        "description": "Höchster Schutzbedarf (Secrets, Zugangsdaten, Gehälter, Abmahnungen, NDAs).",
        "routing_policy": "ZERO_EGRESS_LOCAL_ONLY",
        "cloud_llm_allowed": False,
        "pii_scrubbing_required": True
    }
}


class DataClassifier:
    """Heuristische und regelbasierte Klassifizierungs-Engine für Texte und Dokumente."""

    # 1. Streng geheim (Stufe 3)
    STRICTLY_CONFIDENTIAL_PATTERNS = [
        (re.compile(r'-----BEGIN [A-Z ]+PRIVATE KEY-----'), "Privater kryptografischer Schlüssel"),
        (re.compile(r'\bsk-[a-zA-Z0-9_\-]{20,}\b'), "API Secret Key"),
        (re.compile(r'\bghp_[a-zA-Z0-9]{36}\b'), "GitHub Access Token"),
        (re.compile(r'\b[A-Za-z0-9_-]{8,}:[A-Za-z0-9_-]{35}\b'), "Telegram Bot Token"),
        (re.compile(r'(?:passwort|password|geheimnis|masterkey)\s*[:=]\s*[^\s]{6,}', re.IGNORECASE), "Klartext-Passwort"),
        (re.compile(r'(?:gehalt|monatsgehalt|jahresgehalt|bonus|abfindung)\s*[:=]?\s*\d+', re.IGNORECASE), "Personal-Gehaltsdaten"),
        (re.compile(r'\b(abmahnung|kündigungsschreiben|aufhebungsvertrag|strafanzeige)\b', re.IGNORECASE), "Disziplinar- / Kündigungsdokument"),
        (re.compile(r'\b(non-disclosure agreement|nda|geheimhaltungsvereinbarung|vertraulichkeitsvereinbarung)\b', re.IGNORECASE), "Geheimhaltungsabkommen (NDA)"),
    ]

    # 2. Vertraulich (Stufe 2)
    CONFIDENTIAL_PATTERNS = [
        (re.compile(r'\b(rechnung|rechnungsnummer|umsatzsteuer|ust-id|steuernummer)\b', re.IGNORECASE), "Finanz- & Steuerbeleg"),
        (re.compile(r'\b(angebot|kostenvoranschlag|preiskalkulation|marge)\b', re.IGNORECASE), "Kaufmännisches Angebot / Kalkulation"),
        (re.compile(r'\b(vertrag|vertragspartner|dienstleistungsvertrag|lizenzvertrag)\b', re.IGNORECASE), "Vertragsdokument"),
        (re.compile(r'\bDE\d{2}\s*(?:\d{4}\s*){4}\d{2}\b'), "Deutsche Bankverbindung (IBAN)"),
        (re.compile(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b'), "Personenbezogene E-Mail-Adresse"),
        (re.compile(r'\b(?:\+49|0049|0)[1-9][0-9\s\-\/]{7,}\b'), "Telefonnummer"),
        (re.compile(r'\b(kundennummer|lead|crm-kontakt|interessent)\b', re.IGNORECASE), "CRM-Kundendaten"),
    ]

    # 3. Öffentlich (Stufe 0)
    PUBLIC_PATTERNS = [
        (re.compile(r'\b(pressemitteilung|presseinformation|press release)\b', re.IGNORECASE), "Pressemitteilung"),
        (re.compile(r'\b(produktbroschüre|marketingflyer|landingpage|showroom)\b', re.IGNORECASE), "Öffentliches Marketing"),
        (re.compile(r'\b(release notes|changelog|open source|mit license|apache 2\.0)\b', re.IGNORECASE), "Open Source / Release-Dokumentation"),
    ]

    @classmethod
    def classify(cls, text: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """Analysiert einen Textinhalt und stuft ihn in eine Schutzklasse ein."""
        if not text and not filename:
            level = ClassificationLevel.INTERNAL
            meta = CLASSIFICATION_METADATA[level]
            return {
                "level": level.value,
                "numeric_level": meta["level"],
                "name_de": meta["name_de"],
                "color": meta["color"],
                "routing_policy": meta["routing_policy"],
                "cloud_llm_allowed": meta["cloud_llm_allowed"],
                "pii_scrubbing_required": meta["pii_scrubbing_required"],
                "triggers": ["Standard-Fallback (Leerer Inhalt)"],
                "classified_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        full_content = f"{filename or ''}\n{text or ''}"
        triggers: List[str] = []

        # 1. Streng geheim prüfen
        for regex, desc in cls.STRICTLY_CONFIDENTIAL_PATTERNS:
            if regex.search(full_content):
                triggers.append(desc)

        if triggers:
            level = ClassificationLevel.STRICTLY_CONFIDENTIAL
            meta = CLASSIFICATION_METADATA[level]
            return cls._build_result(level, meta, triggers)

        # 2. Vertraulich prüfen
        for regex, desc in cls.CONFIDENTIAL_PATTERNS:
            if regex.search(full_content):
                triggers.append(desc)

        if triggers:
            level = ClassificationLevel.CONFIDENTIAL
            meta = CLASSIFICATION_METADATA[level]
            return cls._build_result(level, meta, triggers)

        # 3. Öffentlich prüfen
        for regex, desc in cls.PUBLIC_PATTERNS:
            if regex.search(full_content):
                triggers.append(desc)

        if triggers:
            level = ClassificationLevel.PUBLIC
            meta = CLASSIFICATION_METADATA[level]
            return cls._build_result(level, meta, triggers)

        # 4. Standard: Intern
        level = ClassificationLevel.INTERNAL
        meta = CLASSIFICATION_METADATA[level]
        return cls._build_result(level, meta, ["Reguläre interne Systemnotiz / Aufgabe"])

    @classmethod
    def _build_result(cls, level: ClassificationLevel, meta: Dict[str, Any], triggers: List[str]) -> Dict[str, Any]:
        return {
            "level": level.value,
            "numeric_level": meta["level"],
            "name_de": meta["name_de"],
            "color": meta["color"],
            "description": meta["description"],
            "routing_policy": meta["routing_policy"],
            "cloud_llm_allowed": meta["cloud_llm_allowed"],
            "pii_scrubbing_required": meta["pii_scrubbing_required"],
            "triggers": triggers,
            "classified_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    @classmethod
    def tag_item(cls, item_id: str, item_type: str, text: str, filename: Optional[str] = None) -> Dict[str, Any]:
        """Klassifiziert ein Element (Task, Dokument, Mail) und speichert den Tag in data_classifications.json."""
        classification = cls.classify(text, filename=filename)
        entry = {
            "item_id": item_id,
            "item_type": item_type,
            "filename": filename or "",
            "classification": classification,
            "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        os.makedirs(os.path.dirname(CLASSIFICATION_DB), exist_ok=True)
        store = {}
        if os.path.exists(CLASSIFICATION_DB):
            try:
                with open(CLASSIFICATION_DB, "r", encoding="utf-8") as f:
                    store = json.load(f)
            except Exception:
                store = {}

        store[item_id] = entry
        with open(CLASSIFICATION_DB, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)

        return entry

    @classmethod
    def get_classifications(cls, item_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Gibt alle gespeicherten Klassifizierungen zurück."""
        if not os.path.exists(CLASSIFICATION_DB):
            return []
        try:
            with open(CLASSIFICATION_DB, "r", encoding="utf-8") as f:
                store = json.load(f)
                items = list(store.values())
                if item_type:
                    items = [it for it in items if it.get("item_type") == item_type]
                return items
        except Exception:
            return []


# Globaler Singleton
data_classifier = DataClassifier()
