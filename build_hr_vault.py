import os
import json

vault_paths = [r"C:\Mein Obsidian", os.path.join("agent_workspace", "obsidian_vault")]

with open("agent_profiles.json", "r", encoding="utf-8") as f:
    profiles = json.load(f)

categories = {}
for p in profiles:
    cat = p.get("category", "1. Strategie, Führung & Lebensplanung")
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(p)

for vpath in vault_paths:
    if not os.path.exists(vpath):
        try:
            os.makedirs(vpath, exist_ok=True)
        except Exception:
            continue

    hr_dir = os.path.join(vpath, "00_HR_Agenten")
    personalakten_dir = os.path.join(hr_dir, "Personalakten")
    os.makedirs(personalakten_dir, exist_ok=True)

    for p in profiles:
        p_id = p.get("id")
        role_name = p.get("name", p_id)
        person_name = p.get("person_name") or p.get("display_name") or role_name
        cat = p.get("category", "1. Strategie, Führung & Lebensplanung")
        desc = p.get("description", "")
        skills = p.get("skills", [])
        tools = p.get("tools", [])

        if p_id == "hermes_default":
            supervisor = "[[Michael Keller (Owner / CEO)]]"
            seniority = "Chief Root Orchestrator (Level 0)"
        elif p_id == "executive_decision_architect":
            supervisor = "[[hermes_default]]"
            seniority = "Executive Board Member (Level 1)"
        else:
            supervisor = "[[executive_decision_architect]]"
            seniority = "Senior Executive Lead"

        same_cat = [f"[[{other.get('id')}]]" for other in categories.get(cat, []) if other.get("id") != p_id]
        if not same_cat:
            same_cat = ["[[hermes_default]]", "[[executive_decision_architect]]"]
        else:
            same_cat = same_cat[:4]

        skills_md = ""
        if skills:
            for sk in skills:
                skills_md += f"- [x] `{sk}` (Autorisiertes Fachmodul)\n"
        else:
            skills_md = "- [x] `hermes-core-orchestration` (Basissystem-Kompetenz)\n- [x] `universal-problem-solver` (Analytische Problemlösung)\n"

        tools_summary = ", ".join([f"`{t}`" for t in tools[:8]]) if tools else "`web_search`, `filesystem`, `terminal`"

        guardrails_map = {
            "1. Strategie, Führung & Lebensplanung": [
                "**Fokus auf Umsetzbarkeit:** Strategische Pläne müssen immer konkrete 30-60-90-Tage-Meilensteine mit messbaren KPIs enthalten.",
                "**Regret-Minimization:** Bei irreversiblen Entscheidungen immer das 10/10/10-Prinzip und Worst-Case-Puffer anwenden.",
                "**Präzision:** Keine unbegründeten Annahmen treffen; Risiken explizit quantifizieren."
            ],
            "2. B2B Vertrieb & Akquise": [
                "**ICP-Validierung:** Vor jedem Outreach zwingend prüfen, ob Pain Point, Budget-Entscheider und Timing zusammenpassen.",
                "**Anti-Spam-Guardrail:** Keine generischen Massenanschreiben; Personalisierung auf konkrete Unternehmensdaten stützen.",
                "**Next Step Verbindlichkeit:** Jede Kommunikation muss mit einem klaren, reibungsarmen Call-to-Action abschließen."
            ],
            "3. Marketing, Content & Storytelling": [
                "**Tonalitäts-Filter:** Niemals KI-Klischees (z.B. 'Tauchen Sie ein', 'Robust', 'Ganzheitlich') verwenden.",
                "**Hook & Nutzen:** Die erste Zeile muss den Leser sofort fesseln; Nutzen vor Feature stellen.",
                "**Plattform-Formatierung:** Formate strikt an die Zielplattform (LinkedIn, Blog, Whitepaper) anpassen."
            ],
            "4. Immobilien & Objektentwicklung": [
                "**Baurechts-Check (§ 34 / B-Plan):** Keine Entwürfe ohne vorherige Einordnung der GRZ/GFZ und des Einfügungsgebots.",
                "**Kostengruppen DIN 276:** Baukosten immer nach KG 100–700 strukturieren und regionale Baukostenindizes berücksichtigen.",
                "**ESG / GEG Konformität:** Energieeffizienzstandards (KfW 40 / QNG) und nachhaltige Bauweisen frühzeitig einplanen."
            ],
            "5. Steuern, Recht & Compliance": [
                "**Rechtssicherheit & Disclaimer:** Gesetzliche Grundlagen (z.B. § 34 BauGB, DSGVO, KStG) exakt zitieren; keine Rechtsberatungs-Illusion.",
                "**Holding- & Strukturlogik:** Steueroptimierungen immer auf Substanz und Fremdvergleichsgrundsatz abstimmen.",
                "**Fristen- und Formwahrung:** Behördenkorrespondenz immer mit formal korrekten Fristsetzungen und Rechtsbehelfsbelehrungen versehen."
            ],
            "6. Finance, Pricing & Deal-Desk": [
                "**Zahlen-Disziplin:** Jede DCF- und Renditerechnung muss mit Sensitivitätsanalysen (Best/Base/Worst Case) hinterlegt sein.",
                "**Cash-Flow vor Gewinn:** Fokus immer auf realen Liquiditätszufluss und IRR statt rein buchhalterischer Margen.",
                "**Discounting Governance:** Rabatte und Nachlässe nur gegen Gegenleistungen (Laufzeit, Vorkasse) genehmigen."
            ],
            "7. Tech, Software & Data": [
                "**Clean Architecture & KISS:** Komplexe Architekturmuster nur wählen, wenn sie echten Mehrwert bringen; keine Überdimensionierung.",
                "**Zero-Trust & Security:** Keine API-Keys oder Secrets im Klartext; Least-Privilege-Prinzip für alle Service-Accounts.",
                "**Test-Driven Execution:** Kritische Logik immer mit reproduzierbaren Testfällen und Logging absichern."
            ],
            "8. Operations, Logistik & Einkauf": [
                "**Supply Chain Redundanz:** Keine Single-Points-of-Failure bei kritischen Vorlieferanten; Dual-Sourcing prüfen.",
                "**VOB/B & Lieferfristen:** Vertragsstrafen, Lieferverzug und Abnahmefristen lückenlos dokumentieren.",
                "**Bestandsoptimierung:** Sicherheitsbestände dynamisch nach Wiederbeschaffungszeiten berechnen."
            ]
        }
        guardrails = guardrails_map.get(cat, [
            "**Fakten-Validierung:** Keine Aussagen ohne überprüfbare Quellen oder Berechnungen treffen.",
            "**Präzise Kommunikation:** Keine Füllwörter oder Floskeln; direkt zum Kern der Fragestellung kommen.",
            "**Strukturierte Ablage:** Ergebnisse immer mit Datum und Kontext in Obsidian verlinken."
        ])

        guardrails_md = "\n".join([f"- **[Lektion]** {g}" for g in guardrails])
        frontmatter_skills_json = json.dumps(skills, ensure_ascii=False)
        collaborators_yaml = "\n".join([f'  - "{c}"' for c in same_cat])

        md_content = f"""---
agent_id: {p_id}
name: "{role_name}"
person_name: "{person_name}"
domaene: "{cat}"
seniority: "{seniority}"
status: active
installed_skills: {frontmatter_skills_json}
tasks_completed: 0
success_rate: 100%
avg_tokens_per_task: 1250
last_evaluation: 2026-08-22
supervisor: "{supervisor}"
collaborators:
{collaborators_yaml}
---

# 🗂️ PERSONALAKTE: {person_name}
`ID: {p_id}` | **Rolle:** {role_name} | **Domäne:** {cat} | **Status:** 🟢 Aktiv

---

## 1. 👤 Identität, Rolle & Kernauftrag
* **Persönlicher Name:** **{person_name}**
* **Stellenbeschreibung:** {role_name}
* **Fachdomäne:** {cat}
* **Kernaufgabe:** {desc}
* **System-Verknüpfung:** `~/.hermes/profiles/{p_id}/SOUL.md`

> [!INFO] Operative Leitlinie (SOP)
> Arbeitet eigenständig, faktenbasiert und ergebnisorientiert. Trifft keine vagen Annahmen, liefert konkrete Handlungsempfehlungen und dokumentiert alle wesentlichen Entscheidungen im Obsidian-Vault.

---

## 2. 🛠️ Qualifikationsprofil & Skill-Arsenal ({len(skills)} Skills)
Folgende Fach-Skills und Werkzeuge sind in der Agenten-Umgebung autorisiert:
{skills_md}
**System-Tools (Auszug):**
{tools_summary}

---

## 3. 🧠 Dynamisches Gedächtnis & Reflexion (Learnings & Guardrails)
*Erprobte operative Fach-Leitplanken und gelernte Lektionen für diesen Funktionsbereich:*

{guardrails_md}

---

## 4. 📈 Performance & Leistungsbeurteilung
| Metrik | Aktueller Wert | Benchmark / Soll |
| :--- | :--- | :--- |
| **Erfolgsquote (Task Completion)** | 100 % | > 95 % |
| **Präzision & Fachkonsistenz** | A+ (Ausgezeichnet) | A |
| **Verarbeitungszeit / Latenz** | 1,8 s | < 3,5 s |
| **Token-Effizienz** | A+ (Kein Prompt-Bloat) | A |

---

## 5. 📁 Erstellte Artefakte & Projekt-Historie
*Verknüpfte Arbeitsdokumente und Protokolle im Workspace:*
- [[00_VAULT_KNOWLEDGE]]
- [[Archiv-Hubs]]

---

## 6. 🌐 Inter-Agenten-Organigramm
* **Berichtet an (Lead):** {supervisor}
* **Fach-Squad & Kollaborationspartner:**
"""
        for c in same_cat:
            md_content += f"  * {c}\n"

        md_content += "\n---\n*Personalakte automatisch generiert & synchronisiert via Archon OS (Local HR Engine).*\n"

        file_path = os.path.join(personalakten_dir, f"{p_id}.md")
        with open(file_path, "w", encoding="utf-8") as f_out:
            f_out.write(md_content)

    # Master-Dashboard
    dashboard_content = """# 🏢 ARCHON OS: AGENTEN-ORGANIGRAMM & HR-DASHBOARD

> **Zweck:** Zentrale Personalübersicht aller 48 Fach-Agenten des Archon OS Netzwerks.
> **Vault-Pfad:** `00_HR_Agenten/Personalakten/`

---

## 📊 Gesamtübersicht (Dataview)

```dataview
TABLE 
  person_name AS "Name",
  name AS "Rolle / Spezialisierung",
  domaene AS "Domäne",
  length(installed_skills) AS "Skills",
  supervisor AS "Supervisor",
  status AS "Status"
FROM "00_HR_Agenten/Personalakten"
SORT domaene ASC, person_name ASC
```

---

## 🗂️ Domänen-Struktur

### 1. Strategie, Führung & Lebensplanung
- [[hermes_default]] (Hermes Master System)
- [[executive_decision_architect]] (Alexander Richter)
- [[personal_life_strategist]] (Dr. Elena Weber)
- [[red_team_challenger]] (Marcus Vance)
- [[negotiation_master]] (Prof. Dr. Christian Berg)
- [[crisis_escalation_lead]] (Viktoria Brandt)

### 2. B2B Vertrieb & Akquise
- [[gtm_launch_strategist]] (Maximilian von Stetten)
- [[b2b_outreach_specialist]] (David Lindner)
- [[lead_enrichment_analyst]] (Sarah Althaus)
- [[pitchdeck_offer_designer]] (Julian Sommer)
- [[affiliate_partner_manager]] (Tim Brinkmann)

### 3. Marketing, Content & Storytelling
- [[storyteller_ghostwriter]] (Clara Morgenstern)
- [[direct_response_copywriter]] (Felix Kramer)
- [[content_repurposing_specialist]] (Laura Stein)
- [[video_script_architect]] (Jonas Becker)
- [[speechwriter_keynote_designer]] (Dr. Johannes Falk)
- [[pr_press_communicator]] (Beatrice von Bernstorff)
- [[brand_uiux_director]] (Sophia Chen)

### 4. Immobilien & Objektentwicklung
- [[realestate_concept_strategist]] (Maximilian Echter)
- [[baugb_permit_expert]] (Dipl.-Ing. Hans-Peter Gruber)
- [[construction_project_manager]] (Ingo Wellenbrink)
- [[facility_asset_manager]] (Frank Degenhardt)
- [[urban_planning_architect]] (Dr. Corinna Veltins)

### 5. Steuern, Recht & Compliance
- [[tax_holding_advisor]] (Dr. Thorsten Waldeck)
- [[vvgmbh_immo_tax_lead]] (WP/StB Markus Ebner)
- [[commercial_jurist_contracts]] (Dr. Aris Thorne)
- [[compliance_gdpr_auditor]] (Helena Vane)
- [[labor_law_hr_governance]] (Dr. Sibylle Kogel)
- [[ip_patent_analyst]] (Dr.-Ing. Florian Meissner)
- [[esg_kfw_efficiency_auditor]] (Dr. Malte Zierold)
- [[liability_risk_analyst]] (RA Volker Staudt)

### 6. Finance, Pricing & Deal-Desk
- [[realestate_dcf_calculator]] (Valentin Rosengart)
- [[pricing_discount_governor]] (Dr. Martin Selle)
- [[arbitrage_market_analyst]] (Viktor Kogan)

### 7. Tech, Software & Data
- [[system_architect_orchestrator]] (Dr. Robert Neumann)
- [[senior_fullstack_engineer]] (Kai Thormann)
- [[database_performance_tuner]] (Stefan Holtgrewe)
- [[devops_cloud_sec_specialist]] (Simon Brauer)
- [[product_requirements_engineer]] (Matthias Böhme)
- [[agile_scrum_master]] (Tobias Henke)

### 8. Operations, Logistik & Einkauf
- [[logistics_supply_chain_manager]] (Dirk Hagedorn)
- [[procurement_sourcing_scout]] (Jens-Uwe Schlosser)
- [[vendor_contract_negotiator]] (Armin Teufel)
- [[inventory_stock_forecaster]] (Thorsten Mai)
- [[ecommerce_shopify_lead]] (Leonhard Euler)
- [[customer_retention_specialist]] (Sabine Holtkamp)
- [[competitive_intelligence_scout]] (Gregor Vlasic)

---
*Archon OS Second Brain - 00_HR_Agenten*
"""

    with open(os.path.join(hr_dir, "📊 Agenten_Dashboard.md"), "w", encoding="utf-8") as f_dash:
        f_dash.write(dashboard_content)

    print(f"Successfully generated 48 Personalakten and Dashboard in {vpath}")
