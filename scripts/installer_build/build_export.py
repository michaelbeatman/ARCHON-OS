import os
import shutil
import re

SOURCE_DIR = r"C:\.Antigravity-projekte\AgenticOS-2026"
DEST_DIR = r"C:\.Antigravity-projekte\AgenticOS-Dist"

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "logs", "venv", ".venv", ".venv-tools", 
    "dist", "build", "backups", "agent_workspace", ".next", ".vscode", "tmp"
}
IGNORE_EXTS = {".db", ".sqlite", ".bak", ".log", ".tmp"}
IGNORE_FILES = {".env", "credentials.json"}

# Obsidian Mapping
OBSIDIAN_SOURCE = r"C:\Mein Obsidian"
OBSIDIAN_DEST = os.path.join(DEST_DIR, "Obsidian_Vault")
OBSIDIAN_ALLOWED = {"02_Wissensbibliothek": "00_Wissensbibliothek", "00_HR_Agenten": "00_HR_Agenten"}

print(f"Starte Export Pipeline...")

if os.path.exists(DEST_DIR):
    shutil.rmtree(DEST_DIR, ignore_errors=True)

os.makedirs(DEST_DIR, exist_ok=True)

def scrub_content(content):
    content = content.replace(r"C:\Users\micha", r"C:\Users\User")
    content = content.replace(r"C:/Users/micha", r"C:/Users/User")
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
            for r, d, f in os.walk(dst_full):
                for file in f:
                    if file.endswith(".md"):
                        p = os.path.join(r, file)
                        try:
                            with open(p, "r", encoding="utf-8") as file_obj:
                                cont = file_obj.read()
                            clean_cont = scrub_content(cont)
                            with open(p, "w", encoding="utf-8") as file_obj:
                                file_obj.write(clean_cont)
                        except: pass

print("\n[+] Export abgeschlossen!")
