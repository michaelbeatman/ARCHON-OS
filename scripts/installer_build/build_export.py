import os
import shutil
import re
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("archon.installer_build")

SOURCE_DIR = r"."
DEST_DIR = r"/path/to/archon-os"

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "logs", "venv", ".venv", ".venv-tools", 
    "dist", "build", "backups", "agent_workspace", ".next", ".vscode", "tmp"
}
IGNORE_EXTS = {".db", ".sqlite", ".bak", ".log", ".tmp"}
IGNORE_FILES = {".env", "credentials.json"}

# Obsidian Mapping
OBSIDIAN_SOURCE = r"./obsidian_vault"
OBSIDIAN_DEST = os.path.join(DEST_DIR, "Obsidian_Vault")
OBSIDIAN_ALLOWED = {"02_Wissensbibliothek": "00_Wissensbibliothek", "00_HR_Agenten": "00_HR_Agenten"}

print(f"Starte Export Pipeline...")

# F-051: Fehlgeschlagene Scrub-Vorgänge dürfen nicht unsichtbar bleiben.
failed_files = []

if os.path.exists(DEST_DIR):
    shutil.rmtree(DEST_DIR, ignore_errors=True)

os.makedirs(DEST_DIR, exist_ok=True)

def scrub_content(content):
    content = content.replace("C:/Users/User", "/opt/archon")
    content = re.sub(r"\bmicha\b", "admin_orchestrator", content)
    content = re.sub(r"\bmichael\b", "admin", content, flags=re.IGNORECASE)
    content = content.replace("michael-keller-writing-style", "default-writing-style")
    content = content.replace("michael-keller-profile", "admin-profile")
    return content

for root, dirs, files in os.walk(SOURCE_DIR):
    dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
    
    rel_path = os.path.relpath(root, SOURCE_DIR)
    dest_path = os.path.join(DEST_DIR, rel_path) if rel_path != "." else DEST_DIR
    os.makedirs(dest_path, exist_ok=True)
    
    for file in files:
        if file in IGNORE_FILES: continue
        ext = os.path.splitext(file)[1].lower()
        if ext in IGNORE_EXTS: continue
        
        src_file = os.path.join(root, file)
        dst_file = os.path.join(dest_path, file)
        
        if ext in {".png", ".jpg", ".jpeg", ".ico", ".pdf", ".zip", ".exe", ".ttf", ".woff", ".woff2"}:
            shutil.copy2(src_file, dst_file)
        else:
            try:
                with open(src_file, "r", encoding="utf-8") as f:
                    content = f.read()
                clean_content = scrub_content(content)
                with open(dst_file, "w", encoding="utf-8") as f:
                    f.write(clean_content)
            except UnicodeDecodeError:
                shutil.copy2(src_file, dst_file)

if os.path.exists(OBSIDIAN_SOURCE):
    for src_folder, dest_folder in OBSIDIAN_ALLOWED.items():
        src_full = os.path.join(OBSIDIAN_SOURCE, src_folder)
        dst_full = os.path.join(OBSIDIAN_DEST, dest_folder)
        if os.path.exists(src_full):
            shutil.copytree(src_full, dst_full)
            for r, d, files in os.walk(dst_full):
                for file in files:
                    if file.endswith(".md"):
                        p = os.path.join(r, file)
                        try:
                            with open(p, "r", encoding="utf-8") as file_obj:
                                cont = file_obj.read()
                            clean_cont = scrub_content(cont)
                            with open(p, "w", encoding="utf-8") as file_obj:
                                file_obj.write(clean_cont)
                        except (OSError, ValueError) as exc:
                            # F-051: Nie nacktes `except: pass` — ein fehlgeschlagener
                            # Scrub darf nicht als erfolgreicher Export gemeldet werden.
                            failed_files.append(p)
                            logger.error("[Export] Scrub fehlgeschlagen fuer '%s': %s", p, exc)

if failed_files:
    print(f"\n[!] Export mit {len(failed_files)} fehlerhaften Dateien abgeschlossen:")
    for _p in failed_files[:20]:
        print(f"    - {_p}")
    # Obsidian-Markdown ist kritischer Export-Inhalt: kein Erfolgs-Exit bei
    # nicht bereinigten Dateien (fail-closed, kein BaseException-Catch).
    sys.exit(1)

print("\n[+] Export abgeschlossen!")
