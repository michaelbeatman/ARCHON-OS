# -*- coding: utf-8 -*-
"""
scripts/consolidate_immo_project.py
Führt die 6 Einzelordner des KI-Immobilien-Projekts vom 11.10.2026 in EINEN
gemeinsamen Projektordner '20261011-projekt-ki-immobilienplattform' zusammen.
Aktualisiert kanban_meta.json thread-safe über backend.kanban_sidecar.
Verschiebt die 6 alten Ordner nach _Archiv_20261010.
"""

import os
import sys
import shutil
from pathlib import Path

# Basis-Pfade
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.kanban_sidecar import update_kanban_meta

# Obsidian Vault Pfad ermitteln
VAULT_DIR = None
for cand in [Path("/opt/data/obsidian"), Path(r"C:\Mein Obsidian"), Path("C:/.Mein Obsidian")]:
    if cand.exists():
        VAULT_DIR = cand
        break

if not VAULT_DIR:
    print("FEHLER: Obsidian Vault nicht gefunden!")
    sys.exit(1)

PROJEKTE_DIR = VAULT_DIR / "01_PROJEKTE"
ARCHIV_DIR = PROJEKTE_DIR / "_Archiv_20261010"
ARCHIV_DIR.mkdir(parents=True, exist_ok=True)

TARGET_NAME = "20261011-projekt-ki-immobilienplattform"
TARGET_DIR = PROJEKTE_DIR / TARGET_NAME
TARGET_Z = TARGET_DIR / "01_Zwischenberichte"
TARGET_M = TARGET_DIR / "02_Medien"
TARGET_E = TARGET_DIR / "03_Endprodukte"

for d in (TARGET_Z, TARGET_M, TARGET_E):
    d.mkdir(parents=True, exist_ok=True)

TASK_FOLDERS = [
    "20261011-t-05b2c1-definiere-die-technischen-produktanforderungen-f-r",
    "20261011-t-26ed2c-entwerfe-die-technische-systemarchitektur-f-r-eine",
    "20261011-t-5c2b1a-entwickle-eine-go-to-market-strategie-f-r-einen-ki",
    "20261011-t-8d3746-message-from-executive-decision-architect-executiv",
    "20261011-t-998c68-pr-fe-die-optimale-rechtsform-und-steuerstruktur-f",
    "20261011-t-b3f578-entwickle-ein-umfassendes-gesch-ftsmodell-f-r-eine",
]

TASK_IDS = ["t-05b2c1", "t-26ed2c", "t-5c2b1a", "t-8d3746", "t-998c68", "t-b3f578"]

print(f"Zielordner: {TARGET_DIR}")

# 1. Dateien einsammeln & kopieren
for folder_name in TASK_FOLDERS:
    src_f = PROJEKTE_DIR / folder_name
    if not src_f.exists():
        print(f"Warnung: Ordner {folder_name} existiert nicht, überspringe.")
        continue

    # Medien kopieren
    m_src = src_f / "02_Medien"
    if m_src.exists():
        for item in m_src.iterdir():
            if item.is_file():
                dest = TARGET_M / item.name
                shutil.copy2(item, dest)
                print(f"Kopiert Medien: {item.name}")

    # Endprodukte kopieren
    e_src = src_f / "03_Endprodukte"
    if e_src.exists():
        for item in e_src.iterdir():
            if item.is_file():
                dest = TARGET_E / item.name
                shutil.copy2(item, dest)
                print(f"Kopiert Endprodukt: {item.name}")

# 2. Gemeinsame PROJEKT.md schreiben
projekt_md_content = """---
project_folder: "20261011-projekt-ki-immobilienplattform"
created_at: "1791740085.0"
title: "KI-gestützte Immobilienmakler-Plattform (MVP)"
status: "done"
source: "delegation_engine_v2"
delegator: "executive_decision_architect"
---

# Projekt: KI-gestützte Immobilienmakler-Plattform (MVP)

- **Herkunft:** Multi-Agenten-Delegation über Archon OS (Chefstrategie: Robert)
- **Status:** COMPLETED (Alle 6 Teilaufträge abgeschlossen)
- **Verbundene Fachmodule:**
  - [[t-b3f578-entwickle-ein-umfassendes-gesch-ftsmodell-f-r-eine]] (`@realestate_concept_strategist` - Geschäftsmodell)
  - [[t-05b2c1-definiere-die-technischen-produktanforderungen-f-r]] (`@product_requirements_engineer` - Lastenheft/MVP)
  - [[t-26ed2c-entwerfe-die-technische-systemarchitektur-f-r-eine]] (`@system_architect_orchestrator` - Cloud-Architektur)
  - [[t-5c2b1a-entwickle-eine-go-to-market-strategie-f-r-einen-ki]] (`@gtm_launch_strategist` - Go-to-Market & Launch)
  - [[t-998c68-pr-fe-die-optimale-rechtsform-und-steuerstruktur-f]] (`@vvgmbh_immo_tax_lead` - Rechtsform & Steuer)
  - [[t-8d3746-message-from-executive-decision-architect-executiv]] (`@realestate_concept_strategist` - Zwischenstand CEO)

### 📁 Projekt-Struktur:
- `01_Zwischenberichte/`: Entwürfe und Arbeitsprotokolle
- `02_Medien/`: Lastenhefte, Architekturskizzen und Steuervergleiche
- `03_Endprodukte/`: Ausgearbeitete Fachberichte aller 6 Module

---
[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]
"""

(TARGET_DIR / "PROJEKT.md").write_text(projekt_md_content, encoding="utf-8")
print("PROJEKT.md angelegt.")

# 3. kanban_meta.json aktualisieren
def _mutate_sidecar(meta):
    tasks_meta = meta.setdefault("tasks", {})
    for tid in TASK_IDS:
        tmeta = tasks_meta.setdefault(tid, {})
        tmeta["obsidian"] = f"01_PROJEKTE/{TARGET_NAME}"
        print(f"Sidecar aktualisiert für {tid} -> 01_PROJEKTE/{TARGET_NAME}")

update_kanban_meta(_mutate_sidecar)
print("kanban_meta.json erfolgreich aktualisiert.")

# 4. Alte 6 Ordner nach _Archiv_20261010 verschieben
for folder_name in TASK_FOLDERS:
    src_f = PROJEKTE_DIR / folder_name
    if src_f.exists():
        dest_f = ARCHIV_DIR / folder_name
        if dest_f.exists():
            shutil.rmtree(dest_f)
        shutil.move(str(src_f), str(dest_f))
        print(f"Verschoben ins Archiv: {folder_name}")

print("Konsolidierung erfolgreich abgeschlossen!")
