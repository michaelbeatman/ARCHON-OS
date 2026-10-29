"""
backend/research_sources.py — Informationsquellen-Strategie & Vertrauens-Registry für Archon OS.
Säule 2: KOGNITION & WISSEN — Research Lab & Internet-Watchdog.

Verwaltet den kuratierten Pool verifizierter Quellen, Trust-Tiers für die Quellen-Triangulation
und Zitationsregeln für alle Text- und Recherche-Agenten.
"""

from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

# ==============================================================================
# TRUST TIERS (VERTRAUENSSTUFEN)
# ==============================================================================
TRUST_TIERS = {
    "TIER_1_OFFICIAL": {
        "level": 1,
        "name": "Amtlich & Primärquelle",
        "weight": 1.0,
        "badge_color": "emerald",
        "description": "Offizielle Verlautbarungen von Ministerien, Zentralbanken und staatlichen Agenturen. Höchste Faktensicherheit."
    },
    "TIER_2_ESTABLISHED_MEDIA": {
        "level": 2,
        "name": "Etabliertes Leitmedium",
        "weight": 0.9,
        "badge_color": "sky",
        "description": "Verifizierter Fach- und Qualitätsjournalismus mit redaktioneller Sorgfaltspflicht."
    },
    "TIER_3_ACADEMIC": {
        "level": 3,
        "name": "Wissenschaft & Pre-Prints",
        "weight": 0.85,
        "badge_color": "indigo",
        "description": "Fachpublikationen und wissenschaftliche Pre-Print-Server (z. B. ArXiv). Hohe Evidenz, bei Preprints vorläufig."
    },
    "TIER_4_MARKET_DATA": {
        "level": 4,
        "name": "Markt- & Börsendaten",
        "weight": 0.8,
        "badge_color": "amber",
        "description": "Finanzportale und Börsenströme. Valide Indikatoren für Marktreaktionen und Investorenstimmung."
    },
    "TIER_5_AI_REFERENCE": {
        "level": 5,
        "name": "KI-Synthese / Hinweis",
        "weight": 0.5,
        "badge_color": "zinc",
        "description": "KI-generierte Enzyklopädien oder unbestätigte Web-Snippets. Gilt nur als Recherche-Hinweis und zählt nicht als unabhängige Quelle in der Triangulation."
    }
}

# ==============================================================================
# KURATIERTER QUELLEN-POOL FÜR ARCHON OS
# ==============================================================================
CURATED_SOURCES_POOL: List[Dict[str, Any]] = [
    # --------------------------------------------------------------------------
    # 1. INVESTITIONEN, HANDELSABKOMMEN & GEOPOLITIK (HIGH IMPACT)
    # --------------------------------------------------------------------------
    {
        "id": "src-bundesregierung",
        "name": "Bundesregierung (Presse & Gipfel)",
        "category": "Investitionen & Geopolitik",
        "domain": "bundesregierung.de",
        "trust_tier": "TIER_1_OFFICIAL",
        "source_type": "search_feed",
        "query_or_url": "site:bundesregierung.de (\"Invest in Germany\" OR Investitionsgipfel OR Wirtschaftspolitik OR Außenwirtschaft)",
        "homepage": "https://www.bundesregierung.de",
        "description": "Primärquelle für Beschlüsse des Bundeskabinetts, den Invest in Germany Summit und Großinvestitionen.",
        "active": True
    },
    {
        "id": "src-bmwk",
        "name": "BMWK (Wirtschaft & Industrie)",
        "category": "Investitionen & Geopolitik",
        "domain": "bmwk.de",
        "trust_tier": "TIER_1_OFFICIAL",
        "source_type": "search_feed",
        "query_or_url": "BMWK OR \"Wirtschaftsministerium\" (Investition OR Förderung OR Industrie OR Handelsabkommen)",
        "homepage": "https://www.bmwk.de",
        "description": "Industrieförderung, Halbleiter-Subventionen, Wirtschaftsinitiativen und Handelsabkommen.",
        "active": True
    },
    {
        "id": "src-dihk",
        "name": "DIHK (Außenwirtschaft & Handel)",
        "category": "Investitionen & Geopolitik",
        "domain": "dihk.de",
        "trust_tier": "TIER_1_OFFICIAL",
        "source_type": "search_feed",
        "query_or_url": "site:dihk.de (Außenwirtschaft OR Handelsabkommen OR Freihandelsabkommen OR Export)",
        "homepage": "https://www.dihk.de",
        "description": "Dachorganisation der Industrie- und Handelskammern für internationale Abkommen und Exporte.",
        "active": True
    },
    {
        "id": "src-gtai",
        "name": "GTAI (Germany Trade & Invest)",
        "category": "Investitionen & Geopolitik",
        "domain": "gtai.de",
        "trust_tier": "TIER_1_OFFICIAL",
        "source_type": "search_feed",
        "query_or_url": "site:gtai.de OR \"Germany Trade and Invest\"",
        "homepage": "https://www.gtai.de",
        "description": "Offizielle Außenwirtschafts-Agentur der Bundesrepublik Deutschland für Auslandsmärkte und Investitionen.",
        "active": True
    },
    {
        "id": "src-invest-radar",
        "name": "High-Impact Investitions-Radar",
        "category": "Investitionen & Geopolitik",
        "domain": "google.com",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "search_feed",
        "query_or_url": "(\"Invest in Germany\" OR \"Investitionsgipfel\" OR \"Deutschlandfonds\" OR \"Freihandelsabkommen\") Deutschland",
        "homepage": "https://news.google.de",
        "description": "Metascan aller Leitmedien zu staatlichen Investitionsgipfeln und bilateralen Handelsabkommen.",
        "active": True
    },

    # --------------------------------------------------------------------------
    # 2. WIRTSCHAFT & FINANZEN (MAKROÖKONOMIE)
    # --------------------------------------------------------------------------
    {
        "id": "src-handelsblatt-top",
        "name": "Handelsblatt (Top-Themen)",
        "category": "Wirtschaft & Finanzen",
        "domain": "handelsblatt.com",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "rss",
        "query_or_url": "https://www.handelsblatt.com/contentexport/feed/top-themen",
        "homepage": "https://www.handelsblatt.com",
        "description": "Deutsches Leitmedium für Konjunktur, Unternehmen, Finanzmärkte und Wirtschaftspolitik.",
        "active": True
    },
    {
        "id": "src-handelsblatt-politik",
        "name": "Handelsblatt (Politik & Ökonomie)",
        "category": "Wirtschaft & Finanzen",
        "domain": "handelsblatt.com",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "rss",
        "query_or_url": "https://www.handelsblatt.com/contentexport/feed/politik",
        "homepage": "https://www.handelsblatt.com",
        "description": "Wirtschaftspolitische Analysen, Gesetzgebung und internationale Handelsbeziehungen.",
        "active": True
    },
    {
        "id": "src-bundesbank",
        "name": "Deutsche Bundesbank (Presse & Daten)",
        "category": "Wirtschaft & Finanzen",
        "domain": "bundesbank.de",
        "trust_tier": "TIER_1_OFFICIAL",
        "source_type": "search_feed",
        "query_or_url": "site:bundesbank.de (Pressemitteilung OR Monatsbericht OR Konjunktur)",
        "homepage": "https://www.bundesbank.de",
        "description": "Amtliche Finanzstatistiken, Geldpolitik, Bankenaufsicht und Monatsberichte.",
        "active": True
    },
    {
        "id": "src-reuters",
        "name": "Reuters Business (Globale Märkte)",
        "category": "Wirtschaft & Finanzen",
        "domain": "reuters.com",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "search_feed",
        "query_or_url": "Reuters (Wirtschaft OR Börse OR Konjunktur OR Notenbank)",
        "homepage": "https://www.reuters.com",
        "description": "Internationale Nachrichtenagentur für Echtzeit-Wirtschaftsdaten und globale Zinsentscheide.",
        "active": True
    },
    {
        "id": "src-finanzen-boerse",
        "name": "Finanzen & Börse Radar (DAX & Ströme)",
        "category": "Wirtschaft & Finanzen",
        "domain": "finanzen.net",
        "trust_tier": "TIER_4_MARKET_DATA",
        "source_type": "search_feed",
        "query_or_url": "(site:finanzen.net OR site:boerse-online.de) (Investition OR DAX OR Zinsen)",
        "homepage": "https://www.finanzen.net",
        "description": "Marktreaktionen, Analysten-Einschätzungen und institutionelle Investorenströme.",
        "active": True
    },

    # --------------------------------------------------------------------------
    # 3. TECHNOLOGIE, KI & DIGITALISIERUNG
    # --------------------------------------------------------------------------
    {
        "id": "src-heise",
        "name": "Heise Online (IT-Leitmedium DACH)",
        "category": "Technologie & KI",
        "domain": "heise.de",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "rss",
        "query_or_url": "https://www.heise.de/rss/heise-atom.xml",
        "homepage": "https://www.heise.de",
        "description": "Führendes IT-Nachrichtenportal im deutschsprachigen Raum für Cloud, Dev, Security und KI.",
        "active": True
    },
    {
        "id": "src-techcrunch",
        "name": "TechCrunch (Startups & Tech-Infrastruktur)",
        "category": "Technologie & KI",
        "domain": "techcrunch.com",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "rss",
        "query_or_url": "https://techcrunch.com/feed/",
        "homepage": "https://techcrunch.com",
        "description": "Globale Berichterstattung über Wagniskapital, Tech-Unicorns, KI-Modelle und IT-Architektur.",
        "active": True
    },
    {
        "id": "src-arxiv-ai",
        "name": "ArXiv AI (Wissenschaftliche CS-Preprints)",
        "category": "Technologie & KI",
        "domain": "arxiv.org",
        "trust_tier": "TIER_3_ACADEMIC",
        "source_type": "rss",
        "query_or_url": "https://rss.arxiv.org/rss/cs.AI",
        "homepage": "https://arxiv.org",
        "description": "Preprint-Server der Cornell University für modernste Forschung in Machine Learning & LLMs.",
        "active": True
    },

    # --------------------------------------------------------------------------
    # 4. POLITIK, WISSENSCHAFT & FAKTENBASIS
    # --------------------------------------------------------------------------
    {
        "id": "src-tagesschau",
        "name": "Tagesschau (Eilmeldungen & Politik)",
        "category": "Politik & Wissenschaft",
        "domain": "tagesschau.de",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "rss",
        "query_or_url": "https://www.tagesschau.de/xml/rss2/",
        "homepage": "https://www.tagesschau.de",
        "description": "Öffentlich-rechtliche Leitnachrichten der ARD für Faktenchecks und politische Einordnung.",
        "active": True
    },
    {
        "id": "src-spektrum",
        "name": "Spektrum der Wissenschaft (Forschung & Fakten)",
        "category": "Politik & Wissenschaft",
        "domain": "spektrum.de",
        "trust_tier": "TIER_2_ESTABLISHED_MEDIA",
        "source_type": "search_feed",
        "query_or_url": "site:spektrum.de",
        "homepage": "https://www.spektrum.de",
        "description": "Renommierte Wissenschaftsberichterstattung zu Grundlagenforschung, Energie und Naturwissenschaften.",
        "active": True
    }
]

# Bekannte Domain-Mappings zur schnellen Reputationsbewertung
DOMAIN_REPUTATION_MAP: Dict[str, str] = {
    "bundesregierung.de": "TIER_1_OFFICIAL",
    "bmwk.de": "TIER_1_OFFICIAL",
    "bundesbank.de": "TIER_1_OFFICIAL",
    "dihk.de": "TIER_1_OFFICIAL",
    "gtai.de": "TIER_1_OFFICIAL",
    "destatis.de": "TIER_1_OFFICIAL",
    "ec.europa.eu": "TIER_1_OFFICIAL",
    "handelsblatt.com": "TIER_2_ESTABLISHED_MEDIA",
    "tagesschau.de": "TIER_2_ESTABLISHED_MEDIA",
    "heise.de": "TIER_2_ESTABLISHED_MEDIA",
    "reuters.com": "TIER_2_ESTABLISHED_MEDIA",
    "techcrunch.com": "TIER_2_ESTABLISHED_MEDIA",
    "spektrum.de": "TIER_2_ESTABLISHED_MEDIA",
    "technologyreview.com": "TIER_2_ESTABLISHED_MEDIA",
    "arxiv.org": "TIER_3_ACADEMIC",
    "nature.com": "TIER_3_ACADEMIC",
    "science.org": "TIER_3_ACADEMIC",
    "finanzen.net": "TIER_4_MARKET_DATA",
    "boerse-online.de": "TIER_4_MARKET_DATA",
    "bloomberg.com": "TIER_2_ESTABLISHED_MEDIA",
    "grokipedia.com": "TIER_5_AI_REFERENCE",
    "wikipedia.org": "TIER_5_AI_REFERENCE",
}

def get_curated_sources_pool() -> List[Dict[str, Any]]:
    """Gibt den vollständigen Quellen-Pool mit angereicherten Tier-Details zurück."""
    enriched = []
    for s in CURATED_SOURCES_POOL:
        item = dict(s)
        tier_info = TRUST_TIERS.get(s["trust_tier"], TRUST_TIERS["TIER_2_ESTABLISHED_MEDIA"])
        item["tier_level"] = tier_info["level"]
        item["tier_name"] = tier_info["name"]
        item["tier_weight"] = tier_info["weight"]
        item["tier_color"] = tier_info["badge_color"]
        enriched.append(item)
    return enriched

def get_domain_reputation(domain_or_url: str) -> Dict[str, Any]:
    """
    Ermittelt Vertrauensstufe und Gewichtung für eine Domain oder URL.
    """
    clean_domain = domain_or_url.lower().strip()
    if "://" in clean_domain:
        try:
            clean_domain = urlparse(clean_domain).netloc.lower()
        except Exception:
            pass
    # Subdomains abfangen (z. B. www.handelsblatt.com -> handelsblatt.com)
    parts = clean_domain.split(".")
    base_domain = clean_domain
    if len(parts) > 2:
        base_domain = ".".join(parts[-2:])

    tier_key = DOMAIN_REPUTATION_MAP.get(clean_domain) or DOMAIN_REPUTATION_MAP.get(base_domain) or "TIER_5_AI_REFERENCE"
    tier_info = TRUST_TIERS.get(tier_key, TRUST_TIERS["TIER_5_AI_REFERENCE"])
    return {
        "domain": clean_domain,
        "tier_key": tier_key,
        "level": tier_info["level"],
        "name": tier_info["name"],
        "weight": tier_info["weight"],
        "badge_color": tier_info["badge_color"],
        "is_primary": tier_info["level"] == 1,
        "is_established": tier_info["level"] <= 2
    }

def format_citation(name: str, url: str, date_str: Optional[str] = None) -> str:
    """Erzeugt ein normiertes Markdown-Zitat mit anklickbarem Hyperlink."""
    if not url or url == "#":
        return f"*{name}*"
    citation = f"[{name}]({url})"
    if date_str:
        citation += f" (Stand: {date_str})"
    return citation

def evaluate_triangulation_quality(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Bewertet die Evidenz-Stärke anhand der Domain-Reputation und Diversität.
    Kriterien:
    - HOCH: Mindestens 1 TIER 1 (Amtlich) ODER mindestens 3 unabhängige TIER 2 Domains.
    - MODERAT: 2 unabhängige TIER 2 Domains oder TIER 3/4 Evidenz.
    - GERING: Nur 1 Domain oder rein KI-generierte Inhalte (Grokipedia).
    """
    unique_domains = set()
    has_tier_1 = False
    tier_2_count = 0
    total_weight = 0.0

    for s in sources:
        dom = s.get("domain", "")
        if not dom and s.get("url"):
            dom = urlparse(s.get("url", "")).netloc
        if not dom or s.get("ai_generated"):
            continue

        rep = get_domain_reputation(dom)
        unique_domains.add(dom)
        total_weight += rep["weight"]
        if rep["level"] == 1:
            has_tier_1 = True
        elif rep["level"] == 2:
            tier_2_count += 1

    unique_count = len(unique_domains)
    if has_tier_1 or (unique_count >= 3 and tier_2_count >= 2):
        verdict = "HOCH (Amtlich validiert oder ≥ 3 Leitmedien)"
        score = 10 if has_tier_1 else 9
    elif unique_count >= 2:
        verdict = f"MODERAT ({unique_count} unabhängige Quellen)"
        score = 7
    elif unique_count == 1:
        verdict = "GERING (Einzelquelle ohne Bestätigung)"
        score = 4
    else:
        verdict = "UNBESTÄTIGT (Keine unabhängigen Quellen)"
        score = 2

    return {
        "verdict": verdict,
        "score": score,
        "unique_domains": unique_count,
        "has_tier_1_official": has_tier_1,
        "tier_2_count": tier_2_count
    }
