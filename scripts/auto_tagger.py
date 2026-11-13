"""
auto_tagger.py
--------------
Scannt alle Kontakte in PocketBase und versieht sie mit Tags nach der
ueberarbeiteten Taxonomie:

  - Tier-Klassifizierung (tier-1 / tier-2 / tier-3 / tier-unbekannt)
  - Branche, Hierarchie, Fachbereich, Spezialisierung
  - Numerisches `rating`-Feld (Tier 1 = 5, Tier 2 = 3, Tier 3 = 1, Unbekannt = 0)

Regionen werden NICHT als Tags gesetzt (das Feld 'region' existiert bereits).

STRIKTE ANWEISUNG:
  Rumpfe oder rate NIEMALS Informationen. Wenn das Feld 'unternehmen' oder
  'rolle' keine klaren Branchen-Hinweise enthaelt und der 'nachrichtenverlauf'
  leer ist, vergib AUSSCHLIESSLICH das Tag 'tier-unbekannt' und erstelle
  KEINE fiktiven Branchen-Tags.
"""


import requests
import time
import sys

# ─── Konfiguration ──────────────────────────────────────────────────────────
POCKETBASE_URL = "http://127.0.0.1:8090"
COLLECTION     = "Kontakte"
BATCH_SIZE     = 50
PER_PAGE       = 100        # PocketBase-Limit: max 100 pro Seite
MAX_TAGS       = 20
SLEEP_BATCH    = 0.3        # Sekunden zwischen Batches (schont den DB-Thread)

# ─── Keyword-Tabellen ────────────────────────────────────────────────────────

# --- Branchen ---
INDUSTRY_MAP = {
    "pharma":          ["pharma", "pharmaceutical", "arzneimittel", "generika",
                        "rx", "otc", "cro", "pharmaindustrie"],
    "medizintechnik":  ["medizintechnik", "medtech", "medical device",
                        "medizinprodukt", "diagnostik", "labordiagnostik"],
    "großhandel":      ["großhandel", "großhändler", "wholesale", "distribution",
                        "handelsvertreter", "handelsunternehmen"],
    "chemie":          ["chemie", "chemical", "petrochemie", "spezialchemie"],
    "healthcare":      ["healthcare", "gesundheit", "klinik", "krankenhaus",
                        "hospital", "pflege", "medizin", "arzt", "ärztin"],
    "biotechnologie":  ["biotech", "biotechnologie", "biopharma", "biologics",
                        "cell therapy", "gene therapy"],
    "executive search":["executive search", "headhunting", "personalberatung",
                        "personalvermittlung", "recruitment", "recruiting",
                        "search firm", "search consultant"],
    "unternehmensberatung": ["unternehmensberatung", "consulting", "beratung",
                             "strategy consulting", "management consulting"],
    "it":              ["it", "software", "digital", "tech", "saas", "cloud",
                        "ai", "künstliche intelligenz", "data"],
    "logistik":        ["logistik", "logistics", "supply chain", "transport",
                        "lager", "fulfillment", "3pl"],
    "fmcg":            ["fmcg", "consumer goods", "lebensmittel", "food",
                        "nahrungsmittel", "getränke"],
    "industrie":       ["industrie", "manufacturing", "fertigung", "maschinenbau",
                        "automation", "produktion"],
    "finanzen":        ["finance", "finanz", "bank", "investment", "private equity",
                        "venture capital", "asset management"],
}

# --- Rollen-Kategorie (verdeckter Markt) ---
ROLE_CATEGORY_MAP = {
    "executive-search": [
        "executive search", "search consultant", "search & advisory", "headhunter",
        "head hunting", "headhunting", "personalberater", "personalberatung",
        "executive recruiting", "leadership advisory", "executive advisor",
        "michael page", "korn ferry", "heidrick", "egon zehnder", "stanton chase",
        "spencer stuart", "boyden", "kienbaum", "amrop", "valtus",
        "rochus mummert", "division one", "norecu", "senator", "hapeko",
    ],
    "recruiter": [
        "recruiter", "recruiting", "recruitment", "talent acquisition",
        "talent scout", "active sourcing", "talent partner", "personalvermittlung",
        "talentgewinnung", "sourcing", "recruiting-consultant", "talent manager",
        "personalvermittler", "besetzung von", "recruiting manager",
    ],
    "interim": [
        "interim", "interim management", "interim executive", "interim manager",
        "interim-", "freelance", "freiberuflich", "on demand talent",
        "flexible workforce", "temporär",
    ],
    "hr": [
        "human resources", "hr ", "personalleiter", "personalchef", "head of hr",
        "chief people", "people & culture", "personalkompetenz", "hr-interim",
        "personal management", "personalentwickler", "hr business partner",
        "gesamtpersonalleiter", "hr direktorin",
    ],
    "c-level": [
        "ceo", "coo", "cto", "cfo", "cmo", "chief executive", "chief operating",
        "chief financial", "chief technology", "president", "chairman",
    ],
    "finance-pe": [
        "cfo", "chief financial", "finance", "finanzen", "private equity", "investor",
        "investment", "venture capital", "capital", "bank", "controlling", "pe ",
        "treasury", "alteth", "holding",
    ],
    "consulting": [
        "consultant", "consulting", "berater", "beratung", "advisor", "advisory",
        "strategy", "management consulting", "business development", "tuomo",
        "unternehmensberatung",
    ],
    "quality-gmp": [
        "qualified person", "quality", "gmp", "gdp", "quality assurance", "qm ",
        "regulatory", "zulassung", "compliance", "armeniz", "good manufacturing",
        "steril", "charge", "quality director", "quality manager",
    ],
        "geschaeftsfuehrung": [
        "geschäftsführer", "geschäftsführerin", "managing director",
        "managing partner", "general manager", "vorstand", "inhaber",
        "inhaberin", "eigentümer", "gesellschafter", "gründer", "gruender",
        "founder", "co-founder", "ko-founder",
    ],
}

# --- Branchen-Fokus (Life Sci / MedTech / Cannabis) ---
BUSINESS_SCOPE_MAP = {
    "medical-cannabis": [
        "cannabis", "cbd", "thc", "cannabinoid", "hanf", "medcan", "cannamedical",
        "cannavigia", "bloomwell", "demecan", "phytoflow",
    ],
    "life-sciences": [
        "life sciences", "lifescience", "pharma", "biotech", "biologics", "medtech",
        "medical device", "medizintechnik", "cdmo", "diagnostics", "clinical",
        "pharmaindustrie", "generika",
    ],
    "healthcare": [
        "healthcare", "gesundheit", "gesundheitswesen", "apotheke", "apotheken",
        "klinik", "health", "pharmacy",
    ],
}

# --- Hierarchie ---
HIERARCHY_MAP = {
    "c-level":         ["ceo", "cfo", "coo", "cto", "cmo", "cdo", "cso",
                        "chief executive", "chief financial", "chief operating",
                        "chief technology", "chief marketing", "chief digital",
                        "chief sales", "chief commercial", "chief strategy"],
    "geschäftsführung":["geschäftsführer", "geschäftsführerin", "managing director",
                        "managing partner", "general manager", "gf ", "md ",
                        "inhaber", "inhaberin", "owner", "eigentümer",
                        "gesellschafter", "vorstand", "vorständin", "vorstands",
                        "board member", "aufsichtsrat"],
    "vice president":  ["vice president", "vp ", "svp", "evp", "group vp"],
    "director":        ["director", "direktor", "direktorin", "head of",
                        "abteilungsleiter", "bereichsleiter", "division head",
                        "senior director", "global director"],
    "headhunter":      ["headhunter", "executive search", "search consultant",
                        "talent acquisition", "talent scout", "recruiter",
                        "personalberater", "personalberaterin"],
    "hr-leiter":       ["hr director", "hr leiter", "head of hr",
                        "personalleiter", "personalchef", "vp hr",
                        "chief people officer", "cpo", "chief hr"],
    "manager":         ["manager", "managerin", "projektleiter", "teamleiter",
                        "senior manager", "account manager", "key account"],
    "consultant":      ["consultant", "berater", "beraterin", "advisor",
                        "specialist", "spezialist", "senior consultant",
                        "associate consultant"],
    "partner":         ["partner", "geschäftspartner", "principal"],
}

# --- Fachbereich ---
FUNCTION_MAP = {
    "einkauf":         ["einkauf", "purchasing", "procurement", "buyer",
                        "category management", "sourcing"],
    "supply chain":    ["supply chain", "scm", "demand planning", "logistics",
                        "operations", "s&op"],
    "vertrieb":        ["vertrieb", "sales", "verkauf", "key account", "bd",
                        "business development", "account executive"],
    "marketing":       ["marketing", "brand", "kommunikation", "pr",
                        "product management", "produktmanagement"],
    "recruiting":      ["recruiting", "recruitment", "talent acquisition",
                        "personalvermittlung", "headhunting", "hr"],
    "interim":         ["interim", "interimsmanager", "interim manager",
                        "interim management", "übergangs"],
    "finance":         ["finance", "controlling", "buchhaltung", "treasury",
                        "rechnungswesen", "accounting", "cfo", "finanzleiter"],
    "regulatory":      ["regulatory", "regulatory affairs", "zulassung",
                        "compliance", "qualitätssicherung", "qm", "quality"],
    "research":        ["research", "forschung", "r&d", "entwicklung",
                        "innovation", "wissenschaft"],
    "digital":         ["digital", "transformation", "digitalisierung",
                        "it management", "cio", "data", "analytics"],
}

# --- Spezialisierung ---
SPEC_MAP = {
    "b2b":             ["b2b", "business to business", "institutional"],
    "transformation":  ["transformation", "change management", "restrukturierung",
                        "turnaround", "restructuring"],
    "international":   ["international", "global", "europe", "dach",
                        "emea", "apac", "americas"],
    "startup":         ["startup", "start-up", "gründer", "founder",
                        "entrepreneur", "scale-up"],
    "generika":        ["generika", "generic", "biosimilar", "branded generics"],
    "regulatory":      ["regulatory", "gmp", "gdp", "fda", "ema", "bfarm",
                        "clinical trials", "mdr", "ivdr"],
    "digitalisierung": ["digitalisierung", "digital transformation", "e-commerce",
                        "platform", "saas"],
}

# ─── KI-Tier-Klassifizierung  (S / A / B / C) ───────────────────────────────
# S-Tier: Top-Entscheider — direkte Interim-/Projekt-Auftraggeber
# A-Tier: Executive Search, HR-Leads, Senior Directors
# B-Tier: Spezialisten, Manager, operative Netzwerkkontakte
# C-Tier: Zu wenig Kontext für sichere Einordnung
#
# Das Feld 'rating' (Sterne) bleibt komplett dem Nutzer überlassen
# und wird von diesem Skript NICHT angefasst.

STIER_KEYWORDS = [
    # C-Level
    "ceo", "cfo", "coo", "cto", "cmo", "cdo", "cso", "chief executive",
    "chief financial", "chief operating", "chief technology", "chief marketing",
    "chief digital", "chief sales", "chief commercial", "chief strategy",
    # Geschäftsführung / Vorstand / Inhaber
    "geschäftsführer", "geschäftsführerin", "managing director", "managing partner",
    "general manager", "inhaber", "inhaberin", "owner", "eigentümer",
    "gesellschafter", "vorstand", "aufsichtsrat", "board member",
    "president", "präsident",
    # Industrie-spezifische Top-Entscheider
    "pharmacist owner", "apothekeneigentümer",
]

ATIER_KEYWORDS = [
    # Headhunter / Executive Search
    "headhunter", "executive search", "search consultant", "talent acquisition",
    "personalberater", "personalberaterin", "personalvermittlung", "recruiter",
    # HR-Leitung
    "hr director", "hr leiter", "head of hr", "personalleiter", "personalchef",
    "vp hr", "chief people officer", "chief hr",
    # Senior Leadership
    "senior director", "global director", "vice president", "vp ", "svp ", "evp ",
    "director", "direktor", "direktorin", "abteilungsleiter", "bereichsleiter",
    "head of ", "division head",
    # Partner
    "partner", "principal",
]

BTIER_KEYWORDS = [
    "consultant", "berater", "beraterin", "advisor", "specialist", "spezialist",
    "manager", "projektleiter", "teamleiter", "account manager",
    "associate", "analyst", "engineer", "developer", "researcher",
]


# Minimum character threshold for a field to count as meaningful.
# e.g. "IT" (2 chars) or "GmbH" (4 chars) alone should not trigger a tag.
MIN_FIELD_LENGTH = 5


def _verlauf_text(record: dict) -> str:
    """Extracts plain text from nachrichtenverlauf list of message dicts."""
    verlauf = record.get("nachrichtenverlauf") or []
    if isinstance(verlauf, list):
        return " ".join(
            m.get("text", "") or m.get("inhalt", "")
            for m in verlauf
            if isinstance(m, dict)
        ).strip()
    return str(verlauf).strip()


def has_meaningful_context(record: dict) -> bool:
    """
    Returns True when the record has enough context to safely assign tags.
    If no meaningful field is present we fall back to 'tier-unbekannt' instead
    of fabricating tags from thin air.
    """
    rolle       = (record.get("rolle")       or "").strip()
    unternehmen = (record.get("unternehmen") or "").strip()
    kommentar   = (record.get("kommentar")   or "").strip()
    verlauf_str = _verlauf_text(record)

    # At least one field must carry >= MIN_FIELD_LENGTH non-trivial characters
    return any(len(f) >= MIN_FIELD_LENGTH for f in (rolle, unternehmen, kommentar, verlauf_str))


def text_for_matching(record: dict) -> str:
    """Combines all relevant text fields for keyword matching."""
    parts = [
        record.get("name", ""),
        record.get("rolle", ""),
        record.get("unternehmen", ""),
        record.get("kommentar", ""),
        _verlauf_text(record),
    ]
    return " ".join(p for p in parts if p).lower()



def assign_tier(text: str) -> str:
    """Gibt den KI-Tier-Tag (s-tier / a-tier / b-tier) zurueck."""
    for kw in STIER_KEYWORDS:
        if kw in text:
            return "s-tier"
    for kw in ATIER_KEYWORDS:
        if kw in text:
            return "a-tier"
    for kw in BTIER_KEYWORDS:
        if kw in text:
            return "b-tier"
    # Kein spezifisches Keyword gefunden, aber Kontext vorhanden
    return "b-tier"


def match_map(text: str, mapping: dict) -> list[str]:
    """Gibt alle Keys aus `mapping` zurück, deren Keywords in `text` vorkommen."""
    hits = []
    for tag, keywords in mapping.items():
        for kw in keywords:
            if kw in text:
                hits.append(tag)
                break
    return hits


# Alle KI-Tier-Tags — werden beim Update gefiltert
TIER_TAGS = {"s-tier", "a-tier", "b-tier", "c-tier",
             "tier-1", "tier-2", "tier-3", "tier-unbekannt"}  # Legacy cleanup


def build_tags(record: dict) -> list[str]:
    """
    Erstellt das Tag-Array fuer einen Kontakt.

    KI-Tier (s/a/b/c) wird immer als erster Tag gesetzt.
    Das Feld 'rating' (Sterne) wird NICHT beruehrt — das bleibt
    die persoenliche Bewertung des Nutzers.

    STRIKTE ANWEISUNG: Wenn kein aussagekraeftiger Kontext vorhanden
    (leere rolle, unternehmen, kommentar, verlauf), wird NUR 'c-tier'
    vergeben — keine fiktiven Branchen-Tags.
    """
    existing = record.get("tags") or []

    # --- Thin record: kein Kontext → c-tier ---
    if not has_meaningful_context(record):
        preserved = [t for t in existing if t not in TIER_TAGS]
        return list(dict.fromkeys(["c-tier"] + preserved))[:MAX_TAGS]

    # --- Normale Klassifizierung ---
    text = text_for_matching(record)
    tier_tag = assign_tier(text)

    tags: list[str] = [tier_tag]
    tags += match_map(text, INDUSTRY_MAP)
    tags += match_map(text, HIERARCHY_MAP)
    tags += match_map(text, FUNCTION_MAP)
    tags += match_map(text, SPEC_MAP)
    tags += match_map(text, ROLE_CATEGORY_MAP)
    tags += match_map(text, BUSINESS_SCOPE_MAP)

    # Bestehende nicht-Tier-Tags behalten (z.B. "LinkedIn Import")
    preserved = [t for t in existing if t not in TIER_TAGS and t not in tags]
    tags += preserved

    # Deduplizieren, Reihenfolge bewahren
    seen: set[str] = set()
    unique_tags: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique_tags.append(t)

    return unique_tags[:MAX_TAGS]



# ─── PocketBase Helpers ───────────────────────────────────────────────────────

def fetch_all_contacts() -> list[dict]:
    """Lädt alle Kontakte seitenweise."""
    records = []
    page = 1
    while True:
        url = (f"{POCKETBASE_URL}/api/collections/{COLLECTION}/records"
               f"?perPage={PER_PAGE}&page={page}")
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])
        records.extend(items)
        if len(records) >= data.get("totalItems", 0):
            break
        page += 1
    return records


def patch_contact(record_id: str, tags: list[str]) -> bool:
    """Schickt einen PATCH-Request NUR fuer das tags-Feld.
    Das rating-Feld (Sterne) wird bewusst NICHT angefasst."""
    url = f"{POCKETBASE_URL}/api/collections/{COLLECTION}/records/{record_id}"
    payload = {"tags": tags}
    resp = requests.patch(url, json=payload, timeout=10)
    return resp.ok


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("🚀 Archon CRM Auto-Tagger gestartet")
    print(f"   PocketBase: {POCKETBASE_URL}")
    print(f"   Collection: {COLLECTION}")
    print()

    print("📥 Lade alle Kontakte …")
    try:
        contacts = fetch_all_contacts()
    except Exception as exc:
        print(f"❌ Fehler beim Laden: {exc}", file=sys.stderr)
        sys.exit(1)

    total = len(contacts)
    print(f"✅ {total} Kontakte geladen\n")

    success = 0
    failed  = 0
    tier_counts = {"s-tier": 0, "a-tier": 0, "b-tier": 0, "c-tier": 0}

    for batch_start in range(0, total, BATCH_SIZE):
        batch = contacts[batch_start : batch_start + BATCH_SIZE]
        batch_end = min(batch_start + BATCH_SIZE, total)

        print(f"--- Batch {batch_start + 1}-{batch_end} / {total} ---")

        for record in batch:
            rid  = record["id"]
            name = record.get("name", "(unbekannt)")

            try:
                tags = build_tags(record)
                tier = tags[0] if tags else "c-tier"
                tier_counts[tier] = tier_counts.get(tier, 0) + 1

                ok = patch_contact(rid, tags)
                if ok:
                    print(f"  v [{tier}] {name[:60]}")
                    success += 1
                else:
                    print(f"  x PATCH fehlgeschlagen: {name[:60]}")
                    failed += 1
            except Exception as exc:
                print(f"  x Ausnahme: {name[:60]}: {exc}")
                failed += 1

        time.sleep(SLEEP_BATCH)

    print()
    print("════════════════════════════════════════")
    print(f"✅ Erfolgreich:  {success}")
    print(f"❌ Fehlgeschlagen: {failed}")
    print()
    print("📊 Tier-Verteilung:")
    for tier, count in tier_counts.items():
        bar = "█" * (count // max(1, total // 40))
        pct = round(count / max(1, total) * 100)
        print(f"  {tier}: {count:>4} ({pct:>3}%)  {bar}")
    print("════════════════════════════════════════")


if __name__ == "__main__":
    main()
