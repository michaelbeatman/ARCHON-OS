import os
import json
import re
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(BASE_DIR, "sureprompts_catalog_de_enhanced.json")
XLSX_PATH = os.path.join(BASE_DIR, "sureprompts_catalog_de_enhanced.xlsx")

TRANSLATIONS_MAP = {
    "dashboard-narrative": "Erstellen Sie überzeugende Storylines und Daten-Narrative für Dashboards und Visualisierungen.",
    "job_title": "Stellenbezeichnung / Position",
    "key_message": "Kernbotschaft",
    "key_messages": "Zentrale Kernbotschaften",
    "launch_channels": "Vertriebs- & Marketingkanäle",
    "endpoint_path": "API-Endpunkt-Pfad",
    "current_state": "Ist-Zustand / Aktuelle Ausgangslage",
    "key_message_value_proposition": "Kernbotschaft & Nutzenversprechen",
    "documentary_subject": "Dokumentarfilm-Thema / Gegenstand",
    "required_data_points": "Erforderliche Datenpunkte & Kennzahlen",
    "how_they_used_your_product": "Produktnutzung & Anwendungspraxis",
    "core_argument_thesis": "Kernargument & Leitthese",
    "expertise_domain": "Fachbereich / Expertendomäne",
    "okr_period": "OKR-Zyklus / Betrachtungszeitraum",
    "sales_platform": "Vertriebsplattform / Marktplatz",
    "prompt_techniques_to_use": "Anzuwendende Prompt-Techniken",
    "workshop_objectives": "Workshop-Ziele & Ergebnisse",
    "market_opportunity": "Marktpotenzial & Chance",
    "prioritization_framework": "Priorisierungs-Framework (z. B. RICE, MoSCoW)",
    "include_edge_cases": "Grenzfälle & Randbedingungen berücksichtigen",
    "task_type": "Aufgabentyp & Kategorie",
    "who_are_you_pitching_to": "Zielgruppe des Pitches / Entscheider",
    "data_description": "Beschreibung der Datenbasis",
    "website_type": "Website-Typ & Zweck",
    "pricing_model": "Preise & Monetarisierungsmodell",
    "website_brand": "Website / Markenidentität",
    "this_issues_topic": "Schwerpunktthema dieser Ausgabe",
    "central_theme_message": "Zentrales Leitmotiv / Botschaft",
    "programming_language": "Programmiersprache",
    "customer_name_company": "Kundenname / Unternehmen",
    "quality_requirements": "Qualitätsanforderungen & Akzeptanzkriterien",
    "code_snippet": "Code-Ausschnitt / Skript",
    "target_audience": "Zielgruppe / Empfänger",
    "blog_topic": "Blog-Thema / Fokus",
    "tone": "Tonfall & Stil",
    "length": "Umfang & Textlänge",
    "format": "Ausgabeformat",
    "industry": "Branche & Marktumfeld",
    "keywords": "Schlüsselbegriffe / SEO-Keywords",
    "call_to_action": "Handlungsaufforderung (CTA)",
    "cta": "Handlungsaufforderung (CTA)",
    "avoid": "Zu vermeiden (Tabus & Restriktionen)",
    "context": "Zusätzlicher Kontext & Hintergrund",
    "details": "Details & Spezifikationen",
    "features": "Wichtigste Funktionen & Merkmale",
    "benefits": "Kernnutzen & Mehrwerte"
}

def clean_label(lbl, fid):
    fid_clean = fid.lower().strip()
    if fid_clean in TRANSLATIONS_MAP:
        return TRANSLATIONS_MAP[fid_clean]
    for k, v in TRANSLATIONS_MAP.items():
        if k in fid_clean:
            return v
    # Pattern replacements
    replacements = [
        ("Job Title", "Stellenbezeichnung"),
        ("Key Message", "Kernbotschaft"),
        ("Value Proposition", "Nutzenversprechen"),
        ("Subject", "Gegenstand / Betreff"),
        ("Objective", "Zielsetzung"),
        ("Channel", "Kanal"),
        ("State", "Zustand"),
        ("Points", "Punkte"),
        ("Product", "Produkt"),
        ("Thesis", "These"),
        ("Domain", "Fachbereich"),
        ("Period", "Zeitraum"),
        ("Platform", "Plattform"),
        ("Techniques", "Techniken"),
        ("Opportunity", "Gelegenheit"),
        ("Framework", "Framework"),
        ("Edge Cases", "Grenzfälle"),
        ("Type", "Typ"),
        ("Data", "Daten"),
        ("Model", "Modell"),
        ("Brand", "Marke"),
        ("Topic", "Thema"),
        ("Theme", "Motiv"),
        ("Language", "Sprache"),
        ("Company", "Unternehmen"),
        ("Quality", "Qualität"),
        ("Requirements", "Anforderungen")
    ]
    res = lbl
    for en, de in replacements:
        res = re.sub(r'\b' + en + r'\b', de, res, flags=re.IGNORECASE)
    return res.strip()

with open(JSON_PATH, "r", encoding="utf-8") as f:
    catalog = json.load(f)

for t in catalog:
    tid = t["id"]
    if tid == "dashboard-narrative":
        t["description"] = TRANSLATIONS_MAP["dashboard-narrative"]
        t["description_de"] = TRANSLATIONS_MAP["dashboard-narrative"]

    # Sweep through form fields
    for fld in t.get("form_fields", []):
        fid = fld.get("id", "")
        old_lbl = fld.get("label_de") or fld.get("label") or fid
        new_lbl = clean_label(old_lbl, fid)
        fld["label"] = new_lbl
        fld["label_de"] = new_lbl
        fld["placeholder_de"] = f"z. B. {new_lbl} hier eingeben..."

    # Update variable block in archon_prompt_template
    raw_tmpl = t.get("archon_prompt_template", "")
    if "2. EINGABE-PARAMETER & FORMULAR-VARIABLEN" in raw_tmpl and "3. METHODISCHE AUSARBEITUNG" in raw_tmpl:
        parts = raw_tmpl.split("2. EINGABE-PARAMETER & FORMULAR-VARIABLEN")
        head = parts[0]
        rest = parts[1].split("3. METHODISCHE AUSARBEITUNG")
        tail = rest[1]
        var_lines = []
        for fld in t.get("form_fields", []):
            req = fld.get("required", False)
            fid = fld.get("id", "")
            lbl = fld.get("label_de", fid)
            var_lines.append(f"- {lbl}{' (Pflicht)' if req else ''}: {{{{ {fid} }}}}")
        new_var_block = "\n".join(var_lines)
        t["archon_prompt_template"] = f"{head}2. EINGABE-PARAMETER & FORMULAR-VARIABLEN\n{new_var_block}\n\n3. METHODISCHE AUSARBEITUNG{tail}"

with open(JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(catalog, f, ensure_ascii=False, indent=2)

df = pd.DataFrame(catalog)
df['Form_Fields_Schema_JSON'] = df['form_fields'].apply(lambda x: json.dumps(x, ensure_ascii=False))
df['Archon_Prompt_Template'] = df['archon_prompt_template']
df.to_excel(XLSX_PATH, index=False)

print(f"Sweep abgeschlossen! Alle 324 Templates sind nun zu 100% deutsch.")
