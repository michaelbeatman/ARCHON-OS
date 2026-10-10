import os
import sys
import json
import csv
import io
import re
import shutil
import urllib.request
import zipfile
try:
    import yaml
except ImportError:
    yaml = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in locals() else os.getcwd()
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

def clean_id(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r'[^a-z0-9_]+', '_', s)
    return s.strip('_')

def categorize_role(name: str, desc: str = "") -> str:
    combined = (name + " " + desc).lower()
    if any(k in combined for k in ["strateg", "decision", "plan", "goal", "wisdom", "agil", "lead", "coach", "vision", "interview"]):
        return "1. Strategie, Führung & Lebensplanung"
    elif any(k in combined for k in ["market", "price", "product", "procure", "logistic", "vendor", "shop", "e-com", "amazon", "stock", "supply"]):
        return "2. Handel, Beschaffung & E-Commerce"
    elif any(k in combined for k in ["law", "legal", "tax", "steuer", "recht", "claim", "gdpr", "dsgvo", "audit", "security", "threat", "complian"]):
        return "3. Recht, Steuern & Compliance"
    elif any(k in combined for k in ["realestate", "immo", "bau", "construction", "permit", "property", "house", "building", "architec"]):
        return "4. Immobilien & Objektentwicklung"
    elif any(k in combined for k in ["write", "writing", "copy", "essay", "story", "tweet", "video", "post", "content", "pr", "press", "brand", "design", "speech", "screenplay", "author", "advertiser"]):
        return "5. Kreation, Medien & Content"
    elif any(k in combined for k in ["sales", "lead", "outreach", "pitch", "growth", "customer", "email", "crm", "recruit", "talent", "funnel"]):
        return "6. Vertrieb, CRM & Growth"
    elif any(k in combined for k in ["code", "dev", "software", "data", "docker", "api", "git", "test", "qa", "engineer", "db", "sql", "tech", "linux", "cloud", "javascript", "ethereum"]):
        return "7. Tech, Software & Data"
    return "1. Strategie, Führung & Lebensplanung"

def ingest_fabric():
    print("\n--- 1. Ingesting Daniel Miessler Fabric Patterns ---")
    fabric_dir = os.path.join(TEMPLATES_DIR, "fabric")
    os.makedirs(fabric_dir, exist_ok=True)
    
    existing = [d for d in os.listdir(fabric_dir) if os.path.isdir(os.path.join(fabric_dir, d)) and os.path.exists(os.path.join(fabric_dir, d, "system.md"))]
    if len(existing) >= 200:
        print(f"Fabric patterns already cached: {len(existing)} patterns present.")
        return len(existing)

    zip_url = "https://github.com/danielmiessler/fabric/archive/refs/heads/main.zip"
    print(f"Downloading Fabric from {zip_url}...")
    req = urllib.request.Request(zip_url, headers={"User-Agent": "ArchonOS-Ingest"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            content = resp.read()
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                pattern_files = [f for f in z.namelist() if "/patterns/" in f and f.endswith("system.md")]
                for f in pattern_files:
                    parts = f.split("/patterns/")
                    if len(parts) == 2:
                        rel_path = parts[1]
                        target_file = os.path.join(fabric_dir, rel_path)
                        os.makedirs(os.path.dirname(target_file), exist_ok=True)
                        with open(target_file, "wb") as out:
                            out.write(z.read(f))
        patterns_count = len([d for d in os.listdir(fabric_dir) if os.path.isdir(os.path.join(fabric_dir, d))])
        print(f"Successfully ingested {patterns_count} Fabric patterns.")
        return patterns_count
    except Exception as e:
        print(f"Fabric ingest failed: {e}")
        return len(existing)

def ingest_crewai():
    print("\n--- 2. Ingesting CrewAI Examples Business Roles ---")
    crewai_dir = os.path.join(TEMPLATES_DIR, "crewai")
    if os.path.exists(crewai_dir):
        shutil.rmtree(crewai_dir, ignore_errors=True)
    os.makedirs(crewai_dir, exist_ok=True)

    zip_url = "https://github.com/crewAIInc/crewAI-examples/archive/refs/heads/main.zip"
    print(f"Downloading CrewAI examples from {zip_url}...")
    req = urllib.request.Request(zip_url, headers={"User-Agent": "ArchonOS-Ingest"})
    
    count = 0
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            content = resp.read()
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                yaml_files = [f for f in z.namelist() if f.endswith("agents.yaml") or f.endswith("agents.yml")]
                
                for yf in yaml_files:
                    try:
                        raw_yaml = z.read(yf).decode("utf-8", errors="ignore")
                        crew_name = yf.split("/")[1] if len(yf.split("/")) > 2 else "crew"
                        
                        agents_dict = {}
                        if yaml:
                            try:
                                loaded = yaml.safe_load(raw_yaml)
                                if isinstance(loaded, dict):
                                    agents_dict = loaded
                            except Exception:
                                pass
                        
                        if not agents_dict:
                            current_key = None
                            for line in raw_yaml.splitlines():
                                line_str = line.strip()
                                if line and not line.startswith(" ") and ":" in line and not line.startswith("#"):
                                    current_key = line.split(":", 1)[0].strip()
                                    agents_dict[current_key] = {}
                                elif current_key and ":" in line_str and not line_str.startswith("#"):
                                    k, v = line_str.split(":", 1)
                                    agents_dict[current_key][k.strip()] = v.strip().strip('"\'')

                        for agent_key, agent_data in agents_dict.items():
                            if not isinstance(agent_data, dict):
                                continue
                            
                            role = str(agent_data.get("role") or agent_key.replace("_", " ").title()).strip().replace("\n", " ").replace("\r", "")
                            goal = str(agent_data.get("goal") or "").strip().replace("\r", "")
                            backstory = str(agent_data.get("backstory") or "").strip().replace("\r", "")
                            
                            if not goal and not backstory and len(role) < 3:
                                continue

                            role_id = clean_id(f"crew_{crew_name}_{agent_key}")
                            role_folder = os.path.join(crewai_dir, role_id)
                            os.makedirs(role_folder, exist_ok=True)
                            
                            category = categorize_role(role, f"{goal} {backstory}")
                            desc = (goal[:140] + "...") if len(goal) > 140 else (goal or f"CrewAI Rolle für {role}")
                            
                            system_prompt = f"""# ROLE: {role} (CrewAI {crew_name.replace('-', ' ').title()})

## GOAL / ZIEL:
{goal}

## BACKSTORY / HINTERGRUND:
{backstory}

## METHODIK & AUSFÜHRUNG:
- Handle stets im Einklang mit deiner definierten Rolle und arbeite strukturiert, ergebnisorientiert und präzise.
- Liefere konkrete, direkt anwendbare Ergebnisse ohne unnötige Füllphrasen."""

                            with open(os.path.join(role_folder, "system.md"), "w", encoding="utf-8") as f:
                                f.write(system_prompt + "\n")
                                
                            meta_data = {
                                "id": role_id,
                                "name": f"{role} ({crew_name.replace('-', ' ').title()})",
                                "category": category,
                                "description": desc,
                                "skills": ["Research", "Strategic Planning", "Tool Execution"]
                            }
                            with open(os.path.join(role_folder, "meta.json"), "w", encoding="utf-8") as f:
                                json.dump(meta_data, f, indent=2, ensure_ascii=False)
                                
                            count += 1
                    except Exception as e:
                        print(f"Error parsing {yf}: {e}")
                        
        print(f"Successfully ingested {count} CrewAI agent roles into {crewai_dir}.")
        return count
    except Exception as e:
        print(f"CrewAI ingest failed: {e}")
        return 0

def ingest_personas():
    print("\n--- 3. Ingesting Professional Personas & Expert Roles ---")
    personas_dir = os.path.join(TEMPLATES_DIR, "personas")
    if os.path.exists(personas_dir):
        shutil.rmtree(personas_dir, ignore_errors=True)
    os.makedirs(personas_dir, exist_ok=True)

    prompts_url = "https://raw.githubusercontent.com/f/awesome-chatgpt-prompts/main/prompts.csv"
    print(f"Downloading Awesome ChatGPT Prompts from {prompts_url}...")
    req = urllib.request.Request(prompts_url, headers={"User-Agent": "ArchonOS-Ingest"})
    
    count = 0
    try:
        csv.field_size_limit(2147483647)
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
            reader = csv.DictReader(io.StringIO(text))
            
            for row in reader:
                act = row.get("act", "").strip()
                prompt = row.get("prompt", "").strip()
                if not act or not prompt or len(prompt) < 25:
                    continue

                if any(ord(c) > 127 for c in act):
                    continue
                if '?' in act or len(act) > 70:
                    continue

                clean_name = act.replace("\n", " ").replace("\r", "").strip()
                act_id = clean_id(f"persona_{clean_name}")
                folder = os.path.join(personas_dir, act_id)
                os.makedirs(folder, exist_ok=True)

                category = categorize_role(clean_name, prompt[:100])
                desc = f"Fach-Experte: '{clean_name}'. {prompt[:120]}..."

                system_prompt = f"""# ROLE: Professional Persona - {clean_name}

{prompt}

## ARBEITSPRINZIPIEN:
- Beantworte Anfragen mit höchster Fachkompetenz, Präzision und Tiefe.
- Strukturiere komplexe Sachverhalte in übersichtliche Abschnitte, Bulletpoints und konkrete Handlungsschritte."""

                with open(os.path.join(folder, "system.md"), "w", encoding="utf-8") as f:
                    f.write(system_prompt + "\n")

                meta_data = {
                    "id": act_id,
                    "name": clean_name,
                    "category": category,
                    "description": desc,
                    "skills": ["Research", "Tool Execution"]
                }
                with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, indent=2, ensure_ascii=False)

                count += 1
                
        print(f"Successfully ingested {count} clean Professional Personas into {personas_dir}.")
        return count
    except Exception as e:
        print(f"Personas ingest failed: {e}")
        return 0

def main():
    print("==================================================")
    print("ARCHON OS UNIVERSAL TALENT-MARKTPLATZ INGEST")
    print("==================================================")
    f_count = ingest_fabric()
    c_count = ingest_crewai()
    p_count = ingest_personas()
    print("==================================================")
    print(f"INGEST COMPLETE! Total Templates Cached: {f_count + c_count + p_count}")
    print(f"  - Fabric Patterns: {f_count}")
    print(f"  - CrewAI Roles: {c_count}")
    print(f"  - Professional Personas: {p_count}")
    print("==================================================")

if __name__ == "__main__":
    main()
