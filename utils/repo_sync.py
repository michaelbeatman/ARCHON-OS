import os
import json
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in locals() else os.getcwd()
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

_CACHE = {}

GERMAN_SEARCH_SYNONYMS = {
    "buchhalter": ["accountant", "accounting", "bookkeeper", "ledger", "finance", "audit", "tax", "bilanz"],
    "buchhaltung": ["accountant", "accounting", "bookkeeper", "tax", "finance", "bilanz"],
    "steuer": ["tax", "taxes", "vat", "holding", "finance", "accounting", "fiscal"],
    "steuerberater": ["tax", "tax advisor", "accountant", "fiscal", "taxation"],
    "anwalt": ["lawyer", "attorney", "legal", "jurist", "counsel", "law", "court"],
    "rechtsanwalt": ["lawyer", "attorney", "legal", "jurist", "counsel", "law"],
    "jurist": ["lawyer", "attorney", "legal", "jurist", "contract", "law"],
    "recht": ["law", "legal", "attorney", "lawyer", "compliance", "jurist"],
    "vertrag": ["contract", "agreement", "nda", "sla", "legal", "terms"],
    "vertragsprüfung": ["contract", "legal", "clause", "agreement", "review"],
    "entwickler": ["developer", "engineer", "coder", "programmer", "software", "frontend", "backend", "fullstack", "dev"],
    "programmierer": ["programmer", "coder", "developer", "software", "code", "python", "javascript"],
    "software": ["software", "developer", "engineer", "dev", "app", "code"],
    "architekt": ["architect", "architecture", "system", "solutions", "cloud"],
    "immobilien": ["real estate", "property", "realtor", "housing", "building", "construction", "mortgage", "immo"],
    "makler": ["real estate", "broker", "realtor", "agent", "sales", "immo"],
    "bau": ["construction", "building", "permit", "civil engineer", "architecture", "baugb"],
    "baurecht": ["construction", "building", "permit", "zoning", "baugb"],
    "vertrieb": ["sales", "outreach", "b2b", "lead", "closing", "revenue", "pitch", "cold call"],
    "verkauf": ["sales", "selling", "retail", "shop", "ecommerce", "merchant"],
    "marketing": ["marketing", "growth", "seo", "content", "campaign", "ad", "copywriter", "branding"],
    "texter": ["copywriter", "writer", "author", "content", "story", "blog", "ghostwriter"],
    "autor": ["writer", "author", "novelist", "screenplay", "book", "essay"],
    "schreiben": ["write", "writing", "copy", "author", "content"],
    "arzt": ["doctor", "physician", "medical", "medicine", "clinic", "surgeon", "health"],
    "medizin": ["medical", "medicine", "doctor", "health", "pharma", "clinical"],
    "lehrer": ["teacher", "educator", "tutor", "instructor", "professor", "school"],
    "trainer": ["coach", "trainer", "fitness", "instructor"],
    "berater": ["consultant", "advisor", "coach", "strategist", "mentor"],
    "finanzen": ["finance", "financial", "cfo", "investment", "budget", "money", "banking"],
    "personal": ["hr", "human resources", "recruiter", "recruitment", "talent", "hiring"],
    "bewerbung": ["resume", "cv", "interview", "hiring", "career", "job"],
    "sicherheit": ["security", "cyber", "hacker", "pentest", "auth", "firewall", "safety"],
    "datenschutz": ["gdpr", "dsgvo", "privacy", "compliance", "data protection"],
    "daten": ["data", "database", "analytics", "sql", "bi", "scientist"],
    "datenbank": ["database", "sql", "nosql", "postgres", "mysql", "mongodb", "db"],
    "designer": ["designer", "ui", "ux", "graphic", "visual", "art", "creative"],
    "übersetzer": ["translator", "translation", "interpreter", "language", "multilingual"],
    "kundenservice": ["customer service", "support", "customer success", "helpdesk"],
    "chef": ["ceo", "executive", "leader", "manager", "director", "founder"],
    "geschäftsführer": ["ceo", "managing director", "executive", "founder"],
    "psychologe": ["psychologist", "therapist", "mental health", "counselor"],
    "koch": ["chef", "cook", "recipe", "culinary", "restaurant", "food"],
    "ernährung": ["nutrition", "dietitian", "food", "diet", "meal"],
    "ki": ["ai", "artificial intelligence", "ml", "machine learning", "prompt", "llm"],
    "recherche": ["research", "investigation", "search", "analyst", "scout"]
}

def get_marketplace_sources():
    return [
        {"id": "fabric", "name": "Daniel Miessler Fabric (255 Patterns)"},
        {"id": "crewai", "name": "CrewAI Business Roles (51 Rollen)"},
        {"id": "personas", "name": "Professional Persona Hub (2.090+ Experten)"}
    ]

def normalize_text(t: str) -> str:
    return re.sub(r'[\W_]+', ' ', t.lower()).strip()

def list_templates_for_source(source_id: str, search: str = None, category: str = None):
    source_dir = os.path.join(TEMPLATES_DIR, source_id)
    if not os.path.exists(source_dir):
        source_dir = os.path.join("/app/templates", source_id)
        if not os.path.exists(source_dir):
            return []

    cache_key = f"{source_id}"
    if cache_key not in _CACHE:
        indexed = []
        for item in sorted(os.listdir(source_dir)):
            item_path = os.path.join(source_dir, item)
            if not os.path.isdir(item_path) or item.startswith("."):
                continue

            system_file = os.path.join(item_path, "system.md")
            if not os.path.exists(system_file):
                continue

            meta_file = os.path.join(item_path, "meta.json")
            name = item.replace("_", " ").title()
            cat = "1. Strategie, Führung & Lebensplanung"
            description = f"Template: {item}"
            skills = ["Research", "Tool Execution"]

            if os.path.exists(meta_file):
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        name = meta.get("name", name)
                        cat = meta.get("category", cat)
                        description = meta.get("description", description)
                        skills = meta.get("skills", skills)
                except Exception:
                    pass
            else:
                if any(k in item for k in ["strategy", "strategic", "decision", "plan", "goal", "wisdom", "analyze", "agility"]):
                    cat = "1. Strategie, Führung & Lebensplanung"
                elif any(k in item for k in ["market", "price", "product", "procure", "logistic", "vendor"]):
                    cat = "2. Handel, Beschaffung & E-Commerce"
                elif any(k in item for k in ["law", "legal", "tax", "claim", "gdpr", "audit", "security", "threat"]):
                    cat = "3. Recht, Steuern & Compliance"
                elif any(k in item for k in ["realestate", "construction", "permit", "property", "house", "building"]):
                    cat = "4. Immobilien & Objektentwicklung"
                elif any(k in item for k in ["write", "writing", "copy", "essay", "story", "tweet", "video", "post", "improve", "create_"]):
                    cat = "5. Kreation, Medien & Content"
                elif any(k in item for k in ["sales", "lead", "outreach", "pitch", "growth", "customer", "email", "crm"]):
                    cat = "6. Vertrieb, CRM & Growth"
                elif any(k in item for k in ["code", "dev", "architecture", "software", "data", "docker", "api", "git", "test"]):
                    cat = "7. Tech, Software & Data"

            indexed.append({
                "id": item,
                "source": source_id,
                "name": name,
                "category": cat,
                "description": description,
                "skills": skills,
                "_search_norm": normalize_text(f"{name} {item} {description} {cat}")
            })
        _CACHE[cache_key] = indexed

    results = _CACHE[cache_key]
    
    if search:
        s_clean = normalize_text(search)
        search_terms = [s_clean]
        
        # Expand search with German synonyms
        for de_term, en_synonyms in GERMAN_SEARCH_SYNONYMS.items():
            if de_term in s_clean or s_clean in de_term:
                search_terms.extend([normalize_text(s) for s in en_synonyms])
            elif any(normalize_text(en) in s_clean for en in en_synonyms):
                search_terms.append(de_term)
                search_terms.extend([normalize_text(s) for s in en_synonyms])
                
        search_terms = list(dict.fromkeys([st for st in search_terms if len(st) >= 2]))
        
        def matches_item(item):
            norm_corpus = item.get("_search_norm") or normalize_text(f"{item['name']} {item['id']} {item.get('description', '')} {item.get('category', '')}")
            return any(term in norm_corpus for term in search_terms)
            
        results = [t for t in results if matches_item(t)]

    if category and category != "all":
        results = [t for t in results if t.get("category") == category]

    return results

def get_template_detail(source_id: str, template_id: str):
    source_dir = os.path.join(TEMPLATES_DIR, source_id, template_id)
    if not os.path.exists(source_dir):
        source_dir = os.path.join("/app/templates", source_id, template_id)
        if not os.path.exists(source_dir):
            return None

    system_file = os.path.join(source_dir, "system.md")
    if not os.path.exists(system_file):
        return None

    with open(system_file, "r", encoding="utf-8", errors="ignore") as f:
        system_content = f.read()

    meta_file = os.path.join(source_dir, "meta.json")
    name = template_id.replace("_", " ").title()
    category = "1. Strategie, Führung & Lebensplanung"
    description = f"Template: {template_id}"
    skills = ["Research", "Tool Execution"]

    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
                name = meta.get("name", name)
                category = meta.get("category", category)
                description = meta.get("description", description)
                skills = meta.get("skills", skills)
        except Exception:
            pass

    return {
        "id": template_id,
        "source": source_id,
        "name": name,
        "category": category,
        "description": description,
        "skills": skills,
        "system_prompt": system_content
    }
