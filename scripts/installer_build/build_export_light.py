import os
import shutil
import re

SOURCE_DIR = r"C:\.Antigravity-projekte\AgenticOS-2026"
DEST_DIR = r"C:\.Antigravity-projekte\ARCHON OS-Dist 0.1"

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "logs", "venv", ".venv", ".venv-tools", 
    "dist", "build", "backups", "agent_workspace", ".next", ".vscode", "tmp"
}
IGNORE_EXTS = {".db", ".sqlite", ".bak", ".log", ".tmp"}
IGNORE_FILES = {".env", "credentials.json"}

print(f"Starte Lightweight Export Pipeline (Ohne Obsidian)...")

if not os.path.exists(DEST_DIR):
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

print("\n[+] Lightweight-Export abgeschlossen!")
