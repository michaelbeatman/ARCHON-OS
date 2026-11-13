import os
import json
import re
import time
import urllib.request
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(BASE_DIR, "sureprompts_catalog_de_enhanced.json")
XLSX_PATH = os.path.join(BASE_DIR, "sureprompts_catalog_de_enhanced.xlsx")
CACHE_PATH = os.path.join(BASE_DIR, "sureprompts_translations_cache.json")

FIELD_DICT = {
    "topic": "Thema / Gegenstand",
    "blog_topic": "Blog-Thema",
    "target_audience": "Zielgruppe",
    "audience": "Zielgruppe / Empfänger",
    "tone": "Tonfall & Stil",
    "post_length": "Textlänge / Umfang",
    "length": "Umfang / Länge",
    "blog_outline_structure": "Blog-Gliederung & Struktur",
    "outline": "Gliederung / Aufbau",
    "seo_keywords": "SEO-Keywords & Suchbegriffe",
    "keywords": "Schlüsselbegriffe / Keywords",
    "call_to_action": "Handlungsaufforderung (CTA)",
    "cta": "Call to Action",
    "include_elements": "Zu integrierende Elemente",
    "actionable_tips": "Praktische Tipps & Ratschläge",
    "avoid": "Zu vermeiden",
    "words_phrases_or_topics_to_avoid": "Zu vermeidende Wörter, Floskeln oder Themen",
    "product_name": "Produktname",
    "product_description": "Produktbeschreibung",
    "target_customer": "Zielkunde / Käufer-Persona",
    "key_features": "Wichtigste Funktionen & Merkmale",
    "features": "Funktionen & Features",
    "core_benefits": "Kernnutzen & Mehrwerte",
    "benefits": "Vorteile & Nutzen",
    "industry": "Branche / Marktsegment",
    "platform": "Plattform / Kanal",
    "format": "Ausgabeformat",
    "language": "Sprache",
    "goal": "Primäres Ziel",
    "objectives": "Ziele & Erfolgsfaktoren",
    "context": "Kontext / Hintergrundinformationen",
    "details": "Details & Spezifikationen",
    "perspective": "Perspektive / Blickwinkel",
    "notes": "Zusätzliche Hinweise & Notizen",
    "data": "Daten / Rohdaten",
    "feedback_data": "Kundenfeedback / Analyse-Daten",
    "core_values": "Grundwerte & Leitlinien",
    "number_of_sections": "Anzahl der Abschnitte",
    "email_subject": "E-Mail-Betreff",
    "recipient": "Empfänger / Ansprechpartner",
    "sender_name": "Absender / Rolle",
    "problem_statement": "Problemstellung / Schmerzpunkt",
    "solution": "Lösungsansatz / Angebot",
    "metrics": "Kennzahlen & Messgrößen (KPIs)",
    "competitors": "Wettbewerber / Alternativen",
    "budget": "Budgetrahmen",
    "timeline": "Zeitplan & Meilensteine",
    "tech_stack": "Technologie-Stack",
    "programming_language": "Programmiersprache",
    "code_snippet": "Code-Ausschnitt / Skript",
    "framework": "Framework / Bibliothek",
    "error_message": "Fehlermeldung / Stacktrace",
    "use_case": "Anwendungsfall / Use Case",
    "role": "Rolle / Persona",
    "scope": "Umfang / Geltungsbereich"
}

def translate_field_label(label: str, fid: str) -> str:
    clean_id = fid.lower().strip()
    if clean_id in FIELD_DICT:
        return FIELD_DICT[clean_id]
    for k, v in FIELD_DICT.items():
        if k in clean_id:
            return v
    lbl = label
    replacements = [
        ("Target Audience", "Zielgruppe"),
        ("Audience", "Zielgruppe"),
        ("Topic", "Thema"),
        ("Tone", "Tonfall"),
        ("Length", "Länge / Umfang"),
        ("Keywords", "Schlüsselbegriffe"),
        ("Structure", "Struktur"),
        ("Outline", "Gliederung"),
        ("Features", "Funktionen"),
        ("Benefits", "Vorteile"),
        ("Product", "Produkt"),
        ("Customer", "Kunde"),
        ("Industry", "Branche"),
        ("Company", "Unternehmen"),
        ("Objectives", "Ziele"),
        ("Requirements", "Anforderungen"),
        ("Description", "Beschreibung"),
        ("Platform", "Plattform"),
        ("Overview", "Überblick"),
        ("Analysis", "Analyse"),
        ("Strategy", "Strategie"),
        ("Process", "Prozess"),
        ("Guidelines", "Richtlinien"),
        ("Actionable", "Praxisnahe"),
        ("Avoid", "Vermeiden"),
        ("Notes", "Hinweise"),
        ("Language", "Sprache"),
        ("Format", "Format"),
        ("Background", "Hintergrund"),
        ("Example", "Beispiel"),
        ("Summary", "Zusammenfassung"),
        ("Challenge", "Herausforderung"),
        ("Context", "Kontext")
    ]
    for en, de in replacements:
        lbl = re.sub(r'\b' + en + r'\b', de, lbl, flags=re.IGNORECASE)
    return lbl.strip()

def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def call_llm_batch(items):
    prompt = f"""Du bist ein deutscher Übersetzungsexperte für Software- und Prompt-Engineering.
Übersetze die englischen Titel ('name') und Kurzbeschreibungen ('description') der folgenden Prompt-Vorlagen präzise und professionell ins Deutsche.
Antworte AUSSCHLIESSLICH mit einem validen JSON-Array ohne Begrüßung oder Markdown-Codeblöcke:
[
  {{
    "id": "...",
    "name_de": "Deutscher Titel",
    "description_de": "Flüssige, präzise deutsche Beschreibung"
  }}
]

Eingabe:
{json.dumps(items, ensure_ascii=False, indent=2)}"""

    req = urllib.request.Request(
        "http://omniroute:20128/v1/chat/completions",
        data=json.dumps({
            "model": "auto/best-fast",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2500
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    res = urllib.request.urlopen(req, timeout=45)
    content = json.loads(res.read().decode())["choices"][0]["message"]["content"].strip()
    
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
    content = content.strip()
    return json.loads(content)

def main():
    print("=== STARTE VEREDELUNG & DEUTSCHE ÜBERSETZUNG DES SUREPROMPTS-KATALOGS ===")
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    cache = load_cache()
    to_translate = []
    for t in catalog:
        tid = t["id"]
        if tid not in cache:
            to_translate.append({
                "id": tid,
                "name": t.get("name", tid),
                "description": t.get("description", "")
            })
            
    print(f"Gesamt: {len(catalog)} Vorlagen. Zu übersetzen via LLM: {len(to_translate)} Vorlagen.")
    
    batch_size = 20
    for i in range(0, len(to_translate), batch_size):
        batch = to_translate[i:i+batch_size]
        print(f"Übersetze Batch {i//batch_size + 1}/{(len(to_translate)-1)//batch_size + 1} ({len(batch)} Vorlagen)...")
        try:
            results = call_llm_batch(batch)
            for r in results:
                if "id" in r and "description_de" in r:
                    cache[r["id"]] = {
                        "name_de": r.get("name_de", r["id"]),
                        "description_de": r.get("description_de", "")
                    }
            save_cache(cache)
            time.sleep(0.3)
        except Exception as e:
            print(f"Fehler bei Batch via LLM: {e}. Verwende Fallback-Heuristik...")
            for item in batch:
                cache[item["id"]] = {
                    "name_de": item["name"],
                    "description_de": item["description"]
                }
            save_cache(cache)

    print("Aktualisiere Katalog-Daten mit deutschen Texten...")
    for t in catalog:
        tid = t["id"]
        trans = cache.get(tid, {})
        name_de = trans.get("name_de") or t.get("name", tid)
        desc_de = trans.get("description_de") or t.get("description", "")
        
        t["name_de"] = name_de
        t["name"] = name_de
        t["description_de"] = desc_de
        t["description"] = desc_de
        
        fields = t.get("form_fields", [])
        var_lines_de = []
        for f in fields:
            fid = f.get("id", "")
            orig_lbl = f.get("label", fid)
            lbl_de = translate_field_label(orig_lbl, fid)
            f["label_de"] = lbl_de
            f["label"] = lbl_de
            f["placeholder_de"] = f"z. B. {lbl_de} hier eingeben..."
            req = f.get("required", False)
            var_lines_de.append(f"- {lbl_de}{' (Pflicht)' if req else ''}: {{{{ {fid} }}}}")
            
        raw_tmpl = t.get("archon_prompt_template", "")
        if "2. EINGABE-PARAMETER & FORMULAR-VARIABLEN" in raw_tmpl and "3. METHODISCHE AUSARBEITUNG" in raw_tmpl:
            parts = raw_tmpl.split("2. EINGABE-PARAMETER & FORMULAR-VARIABLEN")
            head = parts[0]
            rest = parts[1].split("3. METHODISCHE AUSARBEITUNG")
            tail = rest[1]
            new_var_block = "\n".join(var_lines_de)
            t["archon_prompt_template"] = f"{head}2. EINGABE-PARAMETER & FORMULAR-VARIABLEN\n{new_var_block}\n\n3. METHODISCHE AUSARBEITUNG{tail}"

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
        
    df = pd.DataFrame(catalog)
    df['Form_Fields_Schema_JSON'] = df['form_fields'].apply(lambda x: json.dumps(x, ensure_ascii=False))
    df['Archon_Prompt_Template'] = df['archon_prompt_template']
    df.to_excel(XLSX_PATH, index=False)
    
    print(f"FERTIG! {len(catalog)} Vorlagen erfolgreich veredelt und übersetzt!")
    print(f"- {JSON_PATH}")
    print(f"- {XLSX_PATH}")

if __name__ == "__main__":
    main()
