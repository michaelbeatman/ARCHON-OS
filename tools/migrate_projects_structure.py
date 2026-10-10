#!/usr/bin/env python3
"""
tools/migrate_projects_structure.py
Migriert bestehende Einzelfiles in C:\\Mein Obsidian\\Projects in die neue
Standard-3-Ordner-Projektstruktur:
- 01_Zwischenberichte/
- 02_Medien/
- 03_Endprodukte/
- PROJEKT.md
"""

import os
import shutil
import re
from pathlib import Path

VAULT_PROJECTS = Path(os.environ.get("OBSIDIAN_VAULT_PATH", r"C:\Mein Obsidian")) / "Projects"

def sanitize_folder_name(stem: str) -> str:
    # Sauberen Ordnernamen generieren (max 65 Zeichen)
    name = stem
    if len(name) > 65:
        # Schneide an einem Bindestrich ab
        parts = name[:65].split("-")
        if len(parts) > 1:
            name = "-".join(parts[:-1])
        else:
            name = name[:65]
    return name.strip("-_")

def migrate():
    if not VAULT_PROJECTS.exists():
        print(f"Vault Projects path not found: {VAULT_PROJECTS}")
        return

    files = [f for f in VAULT_PROJECTS.iterdir() if f.is_file() and f.suffix == ".md"]
    print(f"Found {len(files)} files to migrate in {VAULT_PROJECTS}")

    for f in sorted(files):
        # Ignoriere Index-Dateien oder Systemdateien
        if f.name.startswith(("_", ".")) or f.name.lower() in ("readme.md", "index.md", "projekt.md"):
            continue

        folder_name = sanitize_folder_name(f.stem)
        target_dir = VAULT_PROJECTS / folder_name
        z_dir = target_dir / "01_Zwischenberichte"
        m_dir = target_dir / "02_Medien"
        e_dir = target_dir / "03_Endprodukte"

        target_dir.mkdir(parents=True, exist_ok=True)
        z_dir.mkdir(exist_ok=True)
        m_dir.mkdir(exist_ok=True)
        e_dir.mkdir(exist_ok=True)

        target_file = e_dir / f.name
        
        # Verschiebe Originaldatei nach 03_Endprodukte
        shutil.move(str(f), str(target_file))
        print(f"Migrated: {f.name} -> {target_dir.name}/03_Endprodukte/{f.name}")

        # Erstelle PROJEKT.md
        title = f.stem.replace("-", " ").replace("_", " ").title()
        projekt_md = target_dir / "PROJEKT.md"
        if not projekt_md.exists():
            content = f"""---
project_folder: "{folder_name}"
primary_document: "[[{f.stem}]]"
created_at: "{Path(target_file).stat().st_mtime}"
---

# 📂 Projekt: {title}

**Hauptdokument:** [[{f.stem}]]

### 📁 Projekt-Struktur:
- `01_Zwischenberichte/`: Entwürfe, Zwischenstände und Arbeitsprotokolle
- `02_Medien/`: Bildmaterial, Videos, Tabellen und Quellenlisten
- `03_Endprodukte/`: [[{f.stem}]]

---
[[00_VAULT_KNOWLEDGE]] | [[Archiv-Hubs]]
"""
            projekt_md.write_text(content, encoding="utf-8")

if __name__ == "__main__":
    migrate()
