from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""Skill-Inventar (Dateiindex, Frontmatter-Parsing, Skills-Endpunkte)."""

import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, BackgroundTasks, Body, File, HTTPException, Query, Request, UploadFile

from archon.routers._rbac import require_admin_or_503
from utils.path_jail import safe_filename, PathJailError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from archon.core.paths import OPT_DATA_DIR
from archon.core.runtime import APP_ROOT, DATA_DIR, MEMORY_DIR, WORKSPACE_DIR, add_ticker, logger

# --------------------------------------------------
# Dependency-Injektion statt Kopie
# --------------------------------------------------
# skills_engine, api_get_hermes_profiles werden aus main.py per configure() injiziert
# shutil ist stdlib — lokal importieren
_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert die aus main.py injizierten Abhängigkeiten (einmalig beim Import)."""
    _DEPS.update(deps)
    _missing = {"skills_engine", "api_get_hermes_profiles"} - set(_DEPS)
    if _missing:
        logger.warning(f"[Router] skills: fehlende Dependencies {sorted(_missing)}")

import shutil

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)])


def get_all_skill_search_roots():
    return [
        os.path.join(APP_ROOT, "antigravity_complete_skills_package"),
        os.path.join(APP_ROOT, "templates", "skills"),
        os.path.join(APP_ROOT, ".agents", "skills"),
        os.path.join(APP_ROOT, "config", "skills"),
        os.path.join(APP_ROOT, "paperclip", "skills"),
        os.path.join(APP_ROOT, "paperclip", ".agents", "skills"),
        os.path.join(APP_ROOT, "paperclip", "packages", "skills-catalog"),
        os.path.join(APP_ROOT, "OpenMontage", ".agents", "skills"),
        os.path.join(APP_ROOT, "OpenMontage", "skills"),
        os.path.join(APP_ROOT, "agent_workspace", "obsidian_vault", "Skripte"),
        os.path.join(OPT_DATA_DIR, "skills"),
        os.path.expanduser("~/.hermes/skills"),
        os.path.join(WORKSPACE_DIR, "data", "hermes_skills"),
        os.path.join(WORKSPACE_DIR, "templates", "skills"),
        os.path.join(WORKSPACE_DIR, ".agents", "skills"),
        os.path.join(MEMORY_DIR, "hermes_skills"),
        "/app/skills"
    ]


_SKILL_INDEX_DISK_PATH = os.path.join(DATA_DIR, "hermes_skills_index.json")


_HERMES_SKILLS_CACHE_TTL = 300.0


_HERMES_SKILLS_CACHE = None


_HERMES_SKILLS_CACHE_TIME = 0

GLOBAL_HERMES_SKILLS = [
    # 1. Immobilien & Bau
    {"id": "skill-baugb-checker", "name": "BauGB & B-Plan Prüfer", "category": "Immobilien & Bau", "description": "Prüft Zulässigkeit nach § 30, § 34, § 35 BauGB, GRZ/GFZ und Nachverdichtung.", "tags": ["BauGB", "B-Plan", "§34"]},
    {"id": "skill-lbo-standards", "name": "LBO Abstandsflächen-Rechner", "category": "Immobilien & Bau", "description": "Berechnet Abstandsflächen, Stellplatzschlüssel und Brandschutz nach LBO.", "tags": ["LBO", "Abstandsflächen", "Stellplätze"]},
    {"id": "skill-realestate-dcf", "name": "Immobilien-DCF & Rendite-Modell", "category": "Immobilien & Bau", "description": "Erstellt Cashflow-Projektionen, Vervielfältiger, IRR, ROI und Zins-Stresstests.", "tags": ["DCF", "Rendite", "IRR", "Cashflow"]},
    {"id": "skill-bki-cost-estimator", "name": "Baukosten-Kalkulator (DIN 276)", "category": "Immobilien & Bau", "description": "Schätzt Baukosten nach Kostengruppen 100-700 und BKI-Kennwerten.", "tags": ["DIN276", "BKI", "Baukosten"]},
    {"id": "skill-hoai-workflow", "name": "HOAI & VOB Bauleiter-Toolkit", "category": "Immobilien & Bau", "description": "Prüft HOAI Leistungsphasen 1-9 und VOB/B-konforme Nachträge.", "tags": ["HOAI", "VOB", "Bauleitung"]},
    {"id": "skill-esg-realestate", "name": "ESG & KfW-Effizienz-Check", "category": "Immobilien & Bau", "description": "Prüft ESG-Kriterien, GEG und KfW-Förderstufen für Gebäude.", "tags": ["ESG", "KfW", "GEG", "Nachhaltigkeit"]},

    # 2. Recht & Steuern
    {"id": "skill-contract-redline", "name": "Vertrags-Redlining & Klausel-Prüfer", "category": "Recht & Steuern", "description": "Analysiert BGB-Kaufverträge, NDAs, Dienstbarkeiten und AGB auf Fallstricke.", "tags": ["BGB", "Verträge", "Redline"]},
    {"id": "skill-tax-structure-optimizer", "name": "Holding- & Steuer-Strukturierer", "category": "Recht & Steuern", "description": "Modelliert § 8b KStG, vermögensverwaltende GmbH und Grunderwerbsteuer.", "tags": ["Steuern", "Holding", "GmbH", "KStG"]},
    {"id": "skill-gdpr-audit", "name": "DSGVO / GDPR Compliance Auditor", "category": "Recht & Steuern", "description": "Artikel-genaue DSGVO-Prüfung, AVV-Erstellung und PII-Schutz.", "tags": ["DSGVO", "GDPR", "Datenschutz", "AVV"]},
    {"id": "skill-liability-scanner", "name": "Haftungs- & Risiko-Scanner", "category": "Recht & Steuern", "description": "Erkennt Freistellungs- und Haftungsrisiken in Geschäftsverträgen.", "tags": ["Haftung", "Compliance", "Risiko"]},

    # 3. Finanzen & M&A
    {"id": "skill-dcf-valuation", "name": "Unternehmensbewertung (DCF/WACC)", "category": "Finanzen & M&A", "description": "Berechnet Multiples, Discounted Cash Flow und Enterprise Value.", "tags": ["DCF", "WACC", "Valuation"]},
    {"id": "skill-ma-playbook", "name": "M&A Due Diligence Playbook", "category": "Finanzen & M&A", "description": "Strukturierte Due-Diligence-Listen für Finance, Legal, Tech & HR.", "tags": ["M&A", "Due Diligence", "Transaktionen"]},
    {"id": "skill-saas-metrics", "name": "SaaS Health & Unit Economics", "category": "Finanzen & M&A", "description": "Kalkuliert ARR, MRR, CAC, LTV, Magic Number und Rule of 40.", "tags": ["SaaS", "ARR", "CAC", "LTV"]},
    {"id": "skill-grant-matcher", "name": "Fördermittel- & Grant-Scout", "category": "Finanzen & M&A", "description": "Sucht nach ZIM-, BAFA-, KfW- und Horizon-Europe-Förderungen.", "tags": ["Grants", "Förderung", "KfW", "BAFA"]},

    # 4. Vertrieb & Marketing
    {"id": "skill-cold-outreach", "name": "B2B Cold Outreach & LinkedIn Sequencer", "category": "Vertrieb & Marketing", "description": "Erstellt konversionsstarke Anspracheskripte und E-Mail-Sequenzen.", "tags": ["B2B", "Outreach", "LinkedIn", "Sales"]},
    {"id": "skill-pricing-calculator", "name": "Pricing & Packaging Strategist", "category": "Vertrieb & Marketing", "description": "Führt Van-Westendorp-Preissensitivitäts- & Feature-Tier-Analysen durch.", "tags": ["Pricing", "Packaging", "Funnels"]},
    {"id": "skill-competitive-matrix", "name": "Competitor Intelligence & Feature Matrix", "category": "Vertrieb & Marketing", "description": "Erstellt radar-basierte Wettbewerbsmatrizen und Gap-Analysen.", "tags": ["Competitor", "Matrix", "Research"]},
    {"id": "skill-seo-audit", "name": "High-Intent SEO & Content Pipeline", "category": "Vertrieb & Marketing", "description": "Analysiert SERP-Intents, Keyword-Cluster und Content-Architektur.", "tags": ["SEO", "Content", "SERP"]},

    # 5. Software, KI & Tech
    {"id": "skill-karpathy-coder", "name": "Karpathy Clean Coder (Minimal Complexity)", "category": "Software & Tech", "description": "Schreibt sauberen, modularen Code ohne Over-Engineering.", "tags": ["CleanCode", "Python", "TypeScript"]},
    {"id": "skill-docker-generator", "name": "Docker & Container Hardening", "category": "Software & Tech", "description": "Generiert gehärtete Multi-Stage Dockerfiles und Compose-Setups.", "tags": ["Docker", "Containers", "DevOps"]},
    {"id": "skill-database-designer", "name": "Database Schema & Migration Architect", "category": "Software & Tech", "description": "Designt SQL/NoSQL Schemas, Indizes und optimierte Queries.", "tags": ["SQL", "Postgres", "Database"]},
    {"id": "skill-cloud-security", "name": "Cloud Security & IAM Privilege Auditor", "category": "Software & Tech", "description": "Scannt AWS/GCP/Azure-Setups auf Schwachstellen und Least-Privilege.", "tags": ["Cloud", "Security", "AWS", "GCP"]},

    # 6. Quality & Healthcare
    {"id": "skill-iso13485-prep", "name": "ISO 13485 & MDR Audit-Kit", "category": "Quality & Healthcare", "description": "Prüft Design Controls, CAPA und technische Dokumentation.", "tags": ["ISO13485", "MDR", "QMS"]},
    {"id": "skill-pubmed-fetch", "name": "PubMed & Clinical Evidence Fetcher", "category": "Quality & Healthcare", "description": "Extrahiert Evidenz, Studiendaten und Fachliteratur aus NCBI/PubMed.", "tags": ["PubMed", "Medical", "Evidence"]}
]


_SKILL_FILE_INDEX = {}


_SKILL_FILE_INDEX_TIME = 0


def build_skills_file_index(force: bool = False):
    global _SKILL_FILE_INDEX, _SKILL_FILE_INDEX_TIME
    now = time.time()
    if not force and _SKILL_FILE_INDEX and (now - _SKILL_FILE_INDEX_TIME) < 300.0:
        return _SKILL_FILE_INDEX
    
    if not force and not _SKILL_FILE_INDEX and os.path.exists(_SKILL_INDEX_DISK_PATH):
        try:
            with open(_SKILL_INDEX_DISK_PATH, "r", encoding="utf-8") as f:
                _SKILL_FILE_INDEX = json.load(f)
                _SKILL_FILE_INDEX_TIME = now
                return _SKILL_FILE_INDEX
        except Exception:
            pass
    
    index = {}
    search_dirs = get_all_skill_search_roots()
    for s_dir in search_dirs:
        if not os.path.exists(s_dir):
            continue
        try:
            for root, dirs, files in os.walk(s_dir):
                # PRUNING (10.10.2026): Ausschluesse VOR dem Betreten abschneiden
                # (top-down-Walk). Vorher wurde z.B. der komplette .git-Baum
                # traversiert und erst pro Knoten per continue verworfen -
                # gemessen: 10.2s Walk ueber 1671 Verzeichnisse / 4 .git-Baeume.
                dirs[:] = [d for d in dirs if d not in
                           ("node_modules", ".git", "backups", "__pycache__", ".venv", "venv")
                           and not d.endswith(".bak") and not d.startswith(".")]
                if "node_modules" in root or ".git" in root or "backups" in root or root.endswith(".bak"):
                    continue
                if "SKILL.md" in files:
                    folder_name = os.path.basename(root)
                    skill_path = os.path.join(root, "SKILL.md")
                    if folder_name not in index:
                        index[folder_name] = skill_path
                    if folder_name.startswith("skill-"):
                        stripped = folder_name[6:]
                        if stripped not in index:
                            index[stripped] = skill_path
                    else:
                        prefixed = f"skill-{folder_name}"
                        if prefixed not in index:
                            index[prefixed] = skill_path
        except Exception as e:
            print(f"[Skills Indexer] Error walking {s_dir}: {e}")
            
    _SKILL_FILE_INDEX = index
    _SKILL_FILE_INDEX_TIME = now
    try:
        with open(_SKILL_INDEX_DISK_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f)
    except Exception:
        pass
    return index


def find_skill_file(skill_id: str) -> Optional[str]:
    index = build_skills_file_index()
    if skill_id in index and os.path.exists(index[skill_id]):
        return index[skill_id]
    
    variations = [skill_id]
    if skill_id.startswith("skill-"):
        variations.append(skill_id[6:])
    else:
        variations.append(f"skill-{skill_id}")
        
    for var in variations:
        if var in index and os.path.exists(index[var]):
            return index[var]
            
    for root in get_all_skill_search_roots():
        if not os.path.exists(root):
            continue
        for var in variations:
            direct = os.path.join(root, var, "SKILL.md")
            if os.path.exists(direct):
                index[skill_id] = direct
                return direct
            try:
                for sub in os.listdir(root):
                    sub_path = os.path.join(root, sub)
                    if os.path.isdir(sub_path):
                        target = os.path.join(sub_path, var, "SKILL.md")
                        if os.path.exists(target):
                            index[skill_id] = target
                            return target
            except Exception:
                pass
    return None


def parse_skill_frontmatter_and_content(raw_content: str, default_id: str):
    name = default_id.replace("-", " ").title()
    category = "Allgemein"
    description = ""
    tags = []
    
    parts = raw_content.split("---", 2) if raw_content.startswith("---") else []
    if len(parts) >= 3:
        try:
            fm_data = yaml.safe_load(parts[1])
            if isinstance(fm_data, dict):
                if fm_data.get("name"):
                    name = str(fm_data["name"]).strip()
                if fm_data.get("category"):
                    category = str(fm_data["category"]).strip()
                if fm_data.get("description"):
                    raw_desc = str(fm_data["description"]).strip()
                    if not any(k in raw_desc.lower() for k in ["hermes agent skill", "placeholder", "one paragraph describing"]):
                        description = raw_desc
                if fm_data.get("tags"):
                    t = fm_data["tags"]
                    if isinstance(t, list):
                        tags = [str(x).strip() for x in t if x]
                    elif isinstance(t, str):
                        tags = [x.strip() for x in t.split(",") if x.strip()]
                elif isinstance(fm_data.get("metadata"), dict) and "hermes" in fm_data["metadata"]:
                    h_tags = fm_data["metadata"]["hermes"].get("tags", [])
                    if isinstance(h_tags, list):
                        tags = [str(x).strip() for x in h_tags if x]
        except Exception:
            pass
            
    # Fallback für description falls nicht vorhanden oder leer
    if not description:
        body = parts[2] if len(parts) >= 3 else raw_content
        for line in body.splitlines():
            line_s = line.strip()
            if line_s and not line_s.startswith("#") and not line_s.startswith("```") and not line_s.startswith("-") and not line_s.startswith(">"):
                if len(line_s) > 15:
                    description = line_s[:160]
                    break

    if not description:
        clean_name = name or default_id.replace("-", " ").title()
        description = f"Fach-Skill für {clean_name} im operativen Agenten-Workflow."
                
    return {
        "name": name,
        "category": category,
        "description": description,
        "tags": tags,
        "content": raw_content
    }


def compose_skill_frontmatter(name: str, category: str, tags: List[str], description: str, body_or_full_content: str) -> str:
    content = body_or_full_content.strip()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
        else:
            body = content
    else:
        body = content

    tags_json = json.dumps(tags, ensure_ascii=False) if tags else "[]"
    frontmatter = (
        f"---\n"
        f"name: \"{name}\"\n"
        f"category: \"{category}\"\n"
        f"description: \"{description}\"\n"
        f"tags: {tags_json}\n"
        f"---\n\n"
    )
    return frontmatter + body + "\n"


_SKILLS_CACHE_DISK_PATH = os.path.join(DATA_DIR, "hermes_skills_cache.json")


_DOMAIN_COMPETENCIES: Dict[str, tuple] = {
    "devops": ("DevOps & CI/CD", "Technik & Infrastruktur", "Orchestriert Container, Builds, Bereitstellungen und Infrastruktur-Automatisierungen."),
    "productivity": ("Produktivität & Workflows", "Organisation & Führung", "Strukturiert Arbeitsabläufe, Task-Priorisierungen und Zeiterfassung."),
    "note-taking": ("Notizen & Wissensmanagement", "Wissen & Dokumentation", "Dokumentiert Erkenntnisse, strukturierte Memos und Obsidian-Notizen."),
    "smart-home": ("Smart Home & IoT", "Automation", "Steuert Sensoren, Aktoren und Hausautomatisierungen via Home Assistant."),
    "creative": ("Kreation & Design", "Design & Medien", "Erstellt Medien-Konzepte, visuelle Layouts und Prompt-Architekturen."),
    "web": ("Web & Recherche", "Web & Recherche", "Entwickelt Webanwendungen und führt strukturierte Online-Recherchen durch."),
    "mlops": ("MLOps & KI-Betrieb", "KI & Data", "Trainiert, evaluiert und betreibt Modelle und Inferenz-Pipelines."),
    "media": ("Medien-Produktion", "Design & Medien", "Verarbeitet, transformiert und konvertiert Audio-, Video- und Bildinhalte."),
    "social-media": ("Social Media Management", "Marketing & Growth", "Konzipiert und plant Beiträge für Twitter/X, LinkedIn und Communitys."),
    "apple": ("Apple Ecosystem", "Betriebssysteme", "Nutzt macOS- und iOS-Schnittstellen für systemnahe Aufgaben."),
    "software-development": ("Software-Entwicklung", "Software", "Konzipiert, implementiert und testet modulare Softwarekomponenten."),
    "email": ("E-Mail & Kommunikation", "Kommunikation", "Verwaltet Postfächer, filtert relevante E-Mails und verfasst Entwürfe.")
}


@router.get("/api/hermes/skills")
def api_get_hermes_skills(force: bool = False):
    global _HERMES_SKILLS_CACHE, _HERMES_SKILLS_CACHE_TIME
    now = time.time()
    if not force and _HERMES_SKILLS_CACHE is not None and (now - _HERMES_SKILLS_CACHE_TIME) < _HERMES_SKILLS_CACHE_TTL:
        return _HERMES_SKILLS_CACHE

    if not force and not _HERMES_SKILLS_CACHE and os.path.exists(_SKILLS_CACHE_DISK_PATH):
        try:
            with open(_SKILLS_CACHE_DISK_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and isinstance(data, list) and len(data) > 0:
                    _HERMES_SKILLS_CACHE = data
                    _HERMES_SKILLS_CACHE_TIME = now
                    return data
        except Exception:
            pass

    index = build_skills_file_index(force=force)
    discovered_skills = []
    seen_paths = set()
    seen_ids = set()

    for skill_id, file_path in index.items():
        if not file_path or file_path in seen_paths or skill_id in seen_ids:
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            parsed = parse_skill_frontmatter_and_content(raw, skill_id)
            seen_paths.add(file_path)
            seen_ids.add(skill_id)
            discovered_skills.append({
                "id": skill_id,
                "name": parsed["name"],
                "category": parsed["category"],
                "description": parsed["description"],
                "tags": parsed["tags"] or [parsed["category"].split(" ")[0]],
                "file_path": file_path
            })
        except Exception:
            pass

    if not discovered_skills:
        discovered_skills = GLOBAL_HERMES_SKILLS

    _HERMES_SKILLS_CACHE = discovered_skills
    _HERMES_SKILLS_CACHE_TIME = now
    try:
        with open(_SKILLS_CACHE_DISK_PATH, "w", encoding="utf-8") as f:
            json.dump(discovered_skills, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return discovered_skills


@router.get("/api/hermes/skills/{skill_id}")
def api_get_single_hermes_skill(skill_id: str):
    file_path = find_skill_file(skill_id)
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            parsed = parse_skill_frontmatter_and_content(content, skill_id)
            orig_path = os.path.join(os.path.dirname(file_path), ".SKILL.md.orig")
            has_backup = os.path.exists(orig_path)
            return {
                "id": skill_id,
                "name": parsed["name"],
                "category": parsed["category"],
                "description": parsed["description"],
                "tags": parsed["tags"],
                "content": content,
                "file_path": file_path,
                "has_original_backup": has_backup
            }
        except Exception as e:
            print(f"[Skills API] Error reading {file_path}: {e}")

    # Fallback to Global Hermes skills
    for item in GLOBAL_HERMES_SKILLS:
        if item.get("id") == skill_id or item.get("id") == f"skill-{skill_id}":
            return {
                **item,
                "content": f"---\nname: \"{item.get('name')}\"\ncategory: \"{item.get('category')}\"\ndescription: \"{item.get('description')}\"\ntags: {json.dumps(item.get('tags', []))}\n---\n\n# {item.get('name')}\n{item.get('description')}\n\n## Parameter & Ausführung\nFühre diesen Skill im Kontext des übergeordneten Agenten aus.",
                "file_path": "",
                "has_original_backup": False
            }

    # Bekannte Domänen-Kompetenzen
    if skill_id.lower() in _DOMAIN_COMPETENCIES:
        d_name, d_cat, d_desc = _DOMAIN_COMPETENCIES[skill_id.lower()]
        return {
            "id": skill_id,
            "name": d_name,
            "category": d_cat,
            "description": d_desc,
            "tags": [d_cat, "Kompetenz"],
            "content": f"# {d_name}\n\n{d_desc}\n\n## Status\nAktive Kernkompetenz im Profil dieses Agenten.",
            "file_path": "",
            "has_original_backup": False
        }
            
    clean_title = skill_id.replace("-", " ").replace("_", " ").title()
    return {
        "id": skill_id,
        "name": clean_title,
        "category": "Fachkompetenz",
        "description": f"Spezialisierte Fachkompetenz '{clean_title}' für diesen Agenten.",
        "tags": ["Fachkompetenz"],
        "content": f"# Fachkompetenz: {clean_title}\n\nSpezialisierte Handlungsanweisung und Fachkompetenz für diesen Agenten.",
        "file_path": "",
        "has_original_backup": False
    }


@router.post("/api/hermes/skills/{skill_id}")
async def api_save_single_hermes_skill(skill_id: str, request: Request):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if ".." in skill_id or "/" in skill_id or "\\" in skill_id:
        raise HTTPException(status_code=400, detail="Ungueltige skill_id (Pfad-Traversal unzulaessig).")
    try:
        skill_id = safe_filename(skill_id)
    except (PathJailError, ValueError) as e:
        raise HTTPException(status_code=400, detail={"code": "skills_invalid_skill_id", "params": {"error": str(e)}})
    global _HERMES_SKILLS_CACHE
    data = await request.json()
    file_path = find_skill_file(skill_id)
    
    if not file_path:
        skills_dir = os.path.join(MEMORY_DIR, "hermes_skills", skill_id)
        os.makedirs(skills_dir, exist_ok=True)
        file_path = os.path.join(skills_dir, "SKILL.md")
    else:
        skills_dir = os.path.dirname(file_path)
        
    orig_path = os.path.join(skills_dir, ".SKILL.md.orig")
    
    # Create original snapshot backup if this is the first edit
    if os.path.exists(file_path) and not os.path.exists(orig_path):
        try:
            shutil.copy2(file_path, orig_path)
            print(f"[Skills API] Created original backup snapshot at {orig_path}")
        except Exception as e:
            print(f"[Skills API] Failed to create backup: {e}")
            
    name = data.get("name", skill_id)
    category = data.get("category", "Allgemein")
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    description = data.get("description", "")
    content = data.get("content", "")
    
    composed_content = compose_skill_frontmatter(name, category, tags, description, content)
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(composed_content)
        print(f"[Skills API] Saved skill {skill_id} to {file_path}")
    except Exception as e:
        print(f"[Skills API] Error writing skill {skill_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
        
    # Invalidate caches
    _HERMES_SKILLS_CACHE = None
    build_skills_file_index(force=True)
    
    return {
        "status": "ok", 
        "id": skill_id, 
        "file_path": file_path, 
        "has_original_backup": os.path.exists(orig_path)
    }


@router.post("/api/hermes/skills/{skill_id}/reset")
def api_reset_single_hermes_skill(request: Request, skill_id: str):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    global _HERMES_SKILLS_CACHE
    file_path = find_skill_file(skill_id)
    if not file_path or not os.path.exists(file_path):
        return JSONResponse(status_code=404, content={"error": f"Skill {skill_id} nicht gefunden."})
        
    skills_dir = os.path.dirname(file_path)
    orig_path = os.path.join(skills_dir, ".SKILL.md.orig")
    
    if not os.path.exists(orig_path):
        return JSONResponse(status_code=400, content={"error": "Keine Original-Sicherung (.SKILL.md.orig) für diesen Skill vorhanden."})
        
    try:
        shutil.copy2(orig_path, file_path)
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            restored_content = f.read()
        parsed = parse_skill_frontmatter_and_content(restored_content, skill_id)
        
        # Invalidate cache
        _HERMES_SKILLS_CACHE = None
        build_skills_file_index(force=True)
        
        return {
            "status": "ok",
            "id": skill_id,
            "message": "Skill erfolgreich auf Originalzustand zurückgesetzt.",
            "content": restored_content,
            "name": parsed["name"],
            "category": parsed["category"],
            "description": parsed["description"],
            "tags": parsed["tags"],
            "has_original_backup": True
        }
    except Exception as e:
        print(f"[Skills API] Error resetting skill {skill_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/api/v1/skills/docker/inspect")
def api_skills_docker_inspect():
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].docker.inspect_system()


@router.get("/api/v1/skills/docker/logs")
def api_skills_docker_logs(container_name: str, tail: int = 100):
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].docker.read_container_logs(container_name, tail)


@router.post("/api/v1/skills/docker/restart")
def api_skills_docker_restart(request: Request, container_name: str = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].docker.restart_service(container_name)


@router.post("/api/v1/skills/obsidian/write")
def api_skills_obsidian_write(request: Request, title: str = Body(...), content: str = Body(...), tags: List[str] = Body(None)):
    # RBAC: schreibt Dateien in den Vault (Z-01) — wie alle Nachbarrouten.
    require_admin_or_503(request)
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].obsidian.write_obsidian_note(title, content, tags)


@router.get("/api/v1/skills/obsidian/search")
def api_skills_obsidian_search(query: str):
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].obsidian.search_obsidian_notes(query)


@router.post("/api/v1/skills/obsidian/changelog")
def api_skills_obsidian_changelog(version: str = Body(...), changes: List[str] = Body(...)):
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].obsidian.update_changelog(version, changes)


@router.get("/api/v1/skills/rag/query")
def api_skills_rag_query(prompt: str):
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].rag.query_knowledge_base(prompt)


@router.post("/api/v1/skills/rag/store")
def api_skills_rag_store(event_data: Dict = Body(...)):
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].rag.store_system_metric(event_data)


@router.post("/api/v1/skills/git/pytest")
def api_skills_git_pytest(request: Request, test_path: str = Body("tests/")):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].testing.run_pytest(test_path)


@router.post("/api/v1/skills/git/commit")
def api_skills_git_commit(request: Request, message: str = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return _DEPS["skills_engine"].testing.git_safe_commit(message)


@router.post("/api/v1/skills/mcp/connect")
async def api_skills_mcp_connect(request: Request, server_script_or_url: str = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    return await _DEPS["skills_engine"].mcp.connect_mcp_server(server_script_or_url)


@router.post("/api/v1/skills/mcp/execute")
async def api_skills_mcp_execute(request: Request, tool_name: str = Body(...), arguments: Dict = Body(...), agent_id: str = Body(None)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    if not _DEPS.get("skills_engine"):
         raise HTTPException(status_code=500, detail="Skills engine not initialized")
    if not agent_id:
         raise HTTPException(status_code=400, detail="agent_id is required to verify permissions")
        
    # Check permissions (User-defined capability mapping)
    profiles = _DEPS["api_get_hermes_profiles"]()
    prof = next((p for p in profiles if p["id"] == agent_id), None)
    if not prof:
         raise HTTPException(status_code=403, detail="Agent profile not found")
         
    allowed_tools = prof.get("tools", []) + prof.get("skills", [])
    
    # Simple check: tool_name like mcp__omniroute__check_quota -> server is omniroute
    parts = tool_name.split("__")
    if len(parts) >= 2 and parts[0] == "mcp":
        server_name = parts[1]
        allowed_servers = [t.replace("mcp__", "") for t in allowed_tools if t.startswith("mcp__")]
        if server_name not in allowed_servers and tool_name not in allowed_tools:
            raise HTTPException(status_code=403, detail={"code": "skills_agent_not_authorized", "params": {"agent_id": agent_id, "server_name": server_name}})
    
    from backend.plugin_manager import get_plugin_manager
    pm = get_plugin_manager()
    try:
        arguments = await pm.apply_before_tool_execute(tool_name, arguments, {"agent_id": agent_id})
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    
    engine = _DEPS.get("skills_engine")
    if not engine:
        raise HTTPException(status_code=503, detail="skills_engine dependency not configured")
    raw_res = await engine.mcp.execute_mcp_tool(tool_name, arguments)
    return await pm.apply_after_tool_execute(tool_name, raw_res, {"agent_id": agent_id})
