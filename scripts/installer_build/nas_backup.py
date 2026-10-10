import os
import zipfile
from datetime import datetime
import shutil
import sys

SOURCE_DIR = r"C:\.Antigravity-projekte\AgenticOS-2026"
NAS_DIR = r"Y:\_ARCHON Backups"

try:
    os.makedirs(NAS_DIR, exist_ok=True)
except Exception as e:
    print(f"Fehler: Konnte NAS-Ordner nicht erstellen/erreichen. {e}")
    sys.exit(1)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
zip_filename = f"ArchonOS_Backup_{timestamp}.zip"
zip_filepath = os.path.join(NAS_DIR, zip_filename)

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv", ".venv-tools", 
    "dist", "build", "backups", ".next", "tmp", "AgenticOS-Dist"
}

print(f"Erstelle NAS-Backup: {zip_filepath}")
print("Komprimiere Dateien (ohne Mllordner)...")

total_files = 0
try:
    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(SOURCE_DIR):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, SOURCE_DIR)
                zipf.write(file_path, arcname)
                total_files += 1

    size_mb = os.path.getsize(zip_filepath) / (1024*1024)
    print(f"Backup erfolgreich abgeschlossen!")
    print(f"Gesichert: {total_files} Dateien")
    print(f"Archivgre: {size_mb:.2f} MB")
except Exception as e:
    print(f"Kritischer Fehler beim Zippen: {e}")
    sys.exit(1)
