import os
import re
import json
import pandas as pd

# Sucht die Datei egal in welchem Unterordner sie liegt
target_file = None
for root, dirs, files in os.walk("."):
    if "sureprompts_catalog_de.xlsx" in files:
        target_file = os.path.join(root, "sureprompts_catalog_de.xlsx")
        break

if not target_file:
    raise FileNotFoundError("sureprompts_catalog_de.xlsx wurde nicht gefunden!")

print(f"Lese Datei: {target_file}")
df = pd.read_excel(target_file)

def clean_field_name(name):
    return re.sub(r'[^\w\s\-\/\(\)]', '', str(name)).strip()

def process_row(row):
    raw_content = str(row['Promptbuilder-Inhalt der Webseite'])
    template_name = str(row['Template_Name'])
    category = str(row['Kategorie'])
    empfohlene_var = str(row['Empfohlene_Variablen']) if pd.notna(row['Empfohlene_Variablen']) else ""
    desc_en = str(row['Beschreibung_EN']) if pd.notna(row['Beschreibung_EN']) else ""
    
    if "Live Preview" in raw_content:
        parts = raw_content.split("Live Preview")
        fields_text, prompt_text = parts[0], parts[1]
    else:
        fields_text, prompt_text = raw_content, raw_content

    field_lines = [line.strip() for line in fields_text.split("\n") if line.strip()]
    extracted_fields = []
    unwanted = ["change", "reset form", "quick start presets", "choose a preset to get started quickly",
                "presets provide preconfigured settings to get you started quickly", "advanced options", "+",
                "select an option", "required", "fields", "live preview", "words", "concise", "detailed", "expert", "copy prompt"]
    
    for i, line in enumerate(field_lines):
        clean_l = clean_field_name(line)
        if not clean_l or clean_l.lower() in unwanted or clean_l.startswith("eg") or len(clean_l) > 45:
            continue
        is_req = "*" in line or (i + 1 < len(field_lines) and "Required" in field_lines[i+1])
        if any(w in clean_l.lower() for w in ["tone", "format", "length", "include", "avoid", "keywords", "action", "audience", "topic", "structure", "goal", "customer", "product", "features", "industry", "platform", "language", "perspective"]):
            if not any(clean_l.lower() == f[0].lower() for f in extracted_fields):
                extracted_fields.append((clean_l, is_req))
        elif is_req:
            if not any(clean_l.lower() == f[0].lower() for f in extracted_fields):
                extracted_fields.append((clean_l, True))

    if not extracted_fields and empfohlene_var:
        for item in empfohlene_var.split(";"):
            clean_item = clean_field_name(item.split("(")[0])
            if clean_item and not any(clean_item.lower() == f[0].lower() for f in extracted_fields):
                extracted_fields.append((clean_item, "Pflicht" in item))

    prompt_lines = [l for l in prompt_text.split("\n")]
    cleaned_prompt_lines = []
    skip_header = True
    for l in prompt_lines:
        ls = l.strip()
        if skip_header:
            if re.search(r'\d+\s+words', ls, re.I) or ls in ["Concise", "Detailed", "Expert", "Change", "Advanced Options", "+"]:
                continue
            if ls == "":
                continue
            skip_header = False
        if ls == "Copy Prompt":
            continue
        cleaned_prompt_lines.append(l)

    cleaned_prompt_body = "\n".join(cleaned_prompt_lines).strip()
    if len(cleaned_prompt_body) < 30:
        cleaned_prompt_body = f"AUFTRAG:\nFühre die Aufgabenstellung für '{template_name}' ({desc_en}) methodisch und strukturiert durch."

    cleaned_prompt_body = re.sub(r'\(\s*\)', '({{post_length}})', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'\babout\s+for\b', 'about {{topic}} for {{target_audience}}', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'\bfor\s+in\s+the\b', 'for {{target_audience}} in the {{industry}}', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'\bfor\s+targeting\b', 'for {{topic}} targeting {{target_audience}}', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'TASK:\s*Write a compelling product description for\s+that converts features into benefits for\s*\.', 
                                'TASK: Write a compelling product description for {{product_name}} that converts features into benefits for {{target_customer}}.', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'TARGET CUSTOMER:\s*\n', 'TARGET CUSTOMER: {{target_customer}}\n', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'FEATURES TO HIGHLIGHT:\s*\n', 'FEATURES TO HIGHLIGHT:\n{{key_features}}\n', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'FEEDBACK DATA:\s*\n', 'FEEDBACK DATA:\n{{feedback_data}}\n', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'CORE VALUES:\s*\n', 'CORE VALUES: {{core_values}}\n', cleaned_prompt_body)
    cleaned_prompt_body = re.sub(r'NUMBER OF SECTIONS:\s*\n', 'NUMBER OF SECTIONS: {{number_of_sections}}\n', cleaned_prompt_body)

    form_fields = []
    var_list_str = ""
    for name, req in extracted_fields:
        var_slug = re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(" ", "_").replace("/", "_"))
        if not var_slug:
            continue
        ftype = "text"
        if any(w in var_slug for w in ["outline", "features", "feedback", "data", "structure", "avoid", "notes", "description"]):
            ftype = "multiline"
        elif any(w in var_slug for w in ["tone", "format", "length", "platform", "sections"]):
            ftype = "select"
            
        form_fields.append({"id": var_slug, "label": name, "type": ftype, "required": req})
        var_list_str += f"- {name}{' (Pflicht)' if req else ''}: {{{{ {var_slug} }}}}\n"

    if not var_list_str:
        var_list_str = "- Hauptthema / Fokus (Pflicht): {{ thema }}\n- Zielgruppe / Kontext: {{ zielgruppe }}\n"
        form_fields = [
            {"id": "thema", "label": "Hauptthema / Fokus", "type": "text", "required": True},
            {"id": "zielgruppe", "label": "Zielgruppe / Kontext", "type": "text", "required": False}
        ]

    enhanced_prompt = f"""AUFTRAG: {template_name.upper()}

1. ROLLE & SYSTEM-KONTEXT
Agieren Sie als hochgradig spezialisierter Experte für {category} innerhalb des Archon OS Mesh.

2. EINGABE-PARAMETER & FORMULAR-VARIABLEN
{var_list_str.strip()}

3. METHODISCHE AUSARBEITUNG
{cleaned_prompt_body}

4. ARCHON OS GOVERNANCE & PHRASEN-VERBOT
- Phrasen-Verbot: Verwenden Sie keinerlei einleitende Begrüßungen ("Hier ist...", "Gerne...") oder abschließende Höflichkeitsfloskeln.
- Keine Gegenfragen: Beenden Sie das Dokument unmittelbar nach dem letzten sachlichen Punkt ohne Rückfragen oder Angebote zur Weiterarbeit.
- Markdown-Struktur: Klare H2- und H3-Gliederung, Bulletpoints für Kernaspekte, Tabellen für Vergleiche.
- Direkte Scannbarkeit: Präzise, faktenorientierte und unmittelbar einsatzfähige Ausarbeitung."""

    return enhanced_prompt.strip(), form_fields

enhanced_prompts = []
form_schemas_json = []
json_catalog = []

for idx, row in df.iterrows():
    p, ff = process_row(row)
    enhanced_prompts.append(p)
    form_schemas_json.append(json.dumps(ff, ensure_ascii=False))
    json_catalog.append({
        "id": str(row['Template_Slug']),
        "name": str(row['Template_Name']),
        "category": str(row['Kategorie']),
        "category_slug": str(row['Kategorie_Slug']),
        "tier": str(row['Tier']),
        "description": str(row['Beschreibung_EN']) if pd.notna(row['Beschreibung_EN']) else "",
        "url": str(row['URL']) if pd.notna(row['URL']) else "",
        "form_fields": ff,
        "archon_prompt_template": p
    })

df['Form_Fields_Schema_JSON'] = form_schemas_json
df['Archon_Prompt_Template'] = enhanced_prompts

out_dir = os.path.dirname(target_file)
out_xlsx = os.path.join(out_dir, "sureprompts_catalog_de_enhanced.xlsx")
out_json = os.path.join(out_dir, "sureprompts_catalog_de_enhanced.json")

df.to_excel(out_xlsx, index=False)
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(json_catalog, f, ensure_ascii=False, indent=2)

print(f"ERFOLG! Gespeichert unter:\n- {out_xlsx}\n- {out_json}")
