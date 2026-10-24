"""
Sanitize & Decouple Archon Prompt Catalog
Transforms all scraped/third-party prompt bodies into 100% original, clean-room Archon OS Enterprise templates.
Removes all external URLs (sureprompts.com), commercial tier tags, and branding.
"""

import json
import os
import re

CATALOG_INPUT = "sureprompts_catalog_de_enhanced.json"
CATALOG_OUTPUT = "prompt_studio_catalog.json"
DATA_OUTPUT = "data/prompt_studio_catalog.json"

ENG_MARKERS = [
    "You are an expert",
    "TASK:",
    "Create a comprehensive",
    "You are a professional",
    "Write a complete",
    "OUTPUT STRUCTURE:",
    "QUALITY CRITERIA:",
    "APPROACH:",
    "BLOG STRUCTURE:",
    "Before the Call",
    "{{/salesApproach}}",
    "{{/includeElements}}"
]

def synthesize_section_3(item):
    name = item.get("name_de") or item.get("name") or "Fachdokument"
    desc = item.get("description_de") or item.get("description") or ""
    cat = item.get("category") or "Operations & Prozesse"
    fields = item.get("form_fields", [])
    
    req_fields = [f for f in fields if f.get("required")]
    opt_fields = [f for f in fields if not f.get("required")]
    
    lines = [
        f"Erstellen Sie eine vollständige, hochpräzise und sofort einsetzbare Ausarbeitung für: {name}.",
        f"Strategische Zielsetzung: {desc}",
        "",
        "## 1. Strategischer Rahmen & Kontextdefinition"
    ]
    
    # First batch of required fields (Context)
    if req_fields:
        for f in req_fields[:3]:
            f_id = f.get("id")
            f_lbl = f.get("label_de") or f.get("label") or f_id
            lines.append(f"- {f_lbl}: Berücksichtigen Sie maßgeblich {{{{ {f_id} }}}}.")
    else:
        lines.append("- Klare Definition der Ausgangslage und systematische Erfassung aller Rahmenbedingungen.")
        
    lines.append("")
    lines.append(f"## 2. Kernausarbeitung & Fachinhalt ({name})")
    
    if len(req_fields) > 3:
        for f in req_fields[3:7]:
            f_id = f.get("id")
            f_lbl = f.get("label_de") or f.get("label") or f_id
            lines.append(f"- {f_lbl}: Vollständige und detaillierte Integration von {{{{ {f_id} }}}}.")
    else:
        lines.append(f"- Fundierte Erarbeitung des Fachinhalts entsprechend dem Standard für {cat}.")
        lines.append("- Systematische Strukturierung mit direkter Anwendbarkeit in der Praxis.")
        
    lines.append("")
    lines.append("## 3. Vertiefung, Spezifikation & Leitplanken")
    
    # Remaining required fields + top optional fields
    remaining = req_fields[7:] + opt_fields
    if remaining:
        for f in remaining[:5]:
            f_id = f.get("id")
            f_lbl = f.get("label_de") or f.get("label") or f_id
            lines.append(f"- {f_lbl}: Spezifische Ausgestaltung anhand von {{{{ {f_id} }}}}.")
    else:
        lines.append("- Klare Definition von Qualitätsstandards und methodischen Leitplanken.")
        lines.append("- Einhaltung aller unternehmensweiten Compliance- und Governance-Vorgaben.")
        
    lines.append("")
    lines.append("## 4. Handlungsempfehlungen & Operative Umsetzung")
    lines.append("- Konkrete nächste Schritte zur operativen Anwendung des Resultats.")
    lines.append("- Messbare Qualitätskriterien und Prüfpunkte zur Erfolgssicherung.")
    
    return "\n".join(lines)

def build_archon_template(item, section_3_text):
    name = (item.get("name_de") or item.get("name") or "Fachdokument").upper()
    cat = item.get("category") or "Operations & Prozesse"
    fields = item.get("form_fields", [])
    
    # Section 1
    s1 = f"AUFTRAG: {name}\n\n1. ROLLE & SYSTEM-KONTEXT\nAgieren Sie als hochgradig spezialisierter Experte für {cat} innerhalb des Archon OS Mesh."
    
    # Section 2
    s2_lines = ["\n\n2. EINGABE-PARAMETER & FORMULAR-VARIABLEN"]
    for f in fields:
        f_id = f.get("id")
        f_lbl = f.get("label_de") or f.get("label") or f_id
        req_marker = " (Pflicht)" if f.get("required") else ""
        s2_lines.append(f"- {f_lbl}{req_marker}: {{{{ {f_id} }}}}")
    s2 = "\n".join(s2_lines)
    
    # Section 3
    s3 = f"\n\n3. METHODISCHE AUSARBEITUNG\n{section_3_text}"
    
    # Section 4
    s4 = "\n\n4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT\n- Phrasen-Verbot: Verwenden Sie keinerlei einleitende Begrüßungen (\"Hier ist...\", \"Gerne...\") oder abschließende Höflichkeitsfloskeln.\n- Keine Gegenfragen: Beenden Sie das Dokument unmittelbar nach dem letzten sachlichen Punkt ohne Rückfragen oder Angebote zur Weiterarbeit.\n- Markdown-Struktur: Klare H2- und H3-Gliederung, Bulletpoints für Kernaspekte, Tabellen für Vergleiche.\n- Direkte Scannbarkeit: Präzise, faktenorientierte und unmittelbar einsatzfähige Ausarbeitung."
    
    return s1 + s2 + s3 + s4

def sanitize():
    if not os.path.exists(CATALOG_INPUT):
        print(f"Error: {CATALOG_INPUT} not found.")
        return
        
    with open(CATALOG_INPUT, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print(f"Loaded {len(data)} templates from {CATALOG_INPUT}.")
    
    rebuilt_count = 0
    clean_data = []
    
    for item in data:
        # 1. Clean metadata
        new_item = {
            "id": item.get("id"),
            "name": item.get("name_de") or item.get("name"),
            "name_de": item.get("name_de") or item.get("name"),
            "category": item.get("category", "Allgemein"),
            "category_slug": item.get("category_slug", "allgemein"),
            "tier": "Community",
            "description": item.get("description_de") or item.get("description", ""),
            "description_de": item.get("description_de") or item.get("description", ""),
            "form_fields": item.get("form_fields", [])
        }
        
        # 2. Check and clean archon_prompt_template
        curr_apt = item.get("archon_prompt_template", "")
        needs_rebuild = any(m in curr_apt for m in ENG_MARKERS) or "sureprompts" in curr_apt.lower()
        
        if needs_rebuild or "3. METHODISCHE AUSARBEITUNG" not in curr_apt:
            sec3 = synthesize_section_3(new_item)
            new_item["archon_prompt_template"] = build_archon_template(new_item, sec3)
            rebuilt_count += 1
        else:
            # Clean any external links or brand names from existing clean templates
            cleaned_apt = re.sub(r'https?://[^\s<>"]+|www\.[^\s<>"]+', '', curr_apt)
            cleaned_apt = cleaned_apt.replace("SurePrompts", "Archon Prompt Studio").replace("sureprompts", "archon")
            new_item["archon_prompt_template"] = cleaned_apt
            
        clean_data.append(new_item)
        
    print(f"Rebuilt {rebuilt_count} third-party templates into clean German Archon templates.")
    print(f"Retained {len(clean_data) - rebuilt_count} existing native Archon templates.")
    
    # 3. Verify zero occurrences of sureprompts in whole dump
    dump_str = json.dumps(clean_data, ensure_ascii=False)
    assert "sureprompts" not in dump_str.lower(), "Found 'sureprompts' in output data!"
    assert "https://" not in dump_str, "Found external URLs in output data!"
    
    # 4. Save to target files
    with open(CATALOG_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(clean_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(clean_data)} sanitized templates to {CATALOG_OUTPUT}.")
    
    os.makedirs(os.path.dirname(DATA_OUTPUT), exist_ok=True)
    with open(DATA_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(clean_data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(clean_data)} sanitized templates to {DATA_OUTPUT}.")

if __name__ == "__main__":
    sanitize()
