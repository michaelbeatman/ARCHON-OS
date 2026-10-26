# -*- coding: utf-8 -*-
"""
Script to create the clean deployment package:
AgenticOS-2026_Homeserver_Deploy_v0.3.zip
in Y:\_ARCHON Backups\Archon v0.3\
"""
import os
import sys
import zipfile
import time

SRC_DIR = r"C:\.Antigravity-projekte\AgenticOS-2026"
OUT_DIR = r"Y:\_ARCHON Backups\Archon v0.3"
OUT_ZIP = os.path.join(OUT_DIR, "AgenticOS-2026_Homeserver_Deploy_v0.3.zip")

EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".venv-tools",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".hermes",
    "_archive_legacy",
    "backups",
    "LinkedIn-backup",
    "OpenMontage",
    "paperclip",
    "library",
    "archive",
    "static_backup",
    "browser-use",
    "antigravity_complete_skills_package",
    "dist",
    "build"
}

EXCLUDE_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".bak",
    ".tmp"
}

def should_exclude(rel_path):
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in EXCLUDE_DIRS:
            return True
        if p.startswith("~$"):
            return True
        if p == "backups" and "data" in parts:
            return True

    filename = parts[-1]
    _, ext = os.path.splitext(filename)
    if ext.lower() in EXCLUDE_EXTS:
        return True
    if filename.startswith("~$"):
        return True
    if filename in {"credentials.json", "gmail_token.json", "google_token.json"}:
        return True
    return False

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Creating deploy package: {OUT_ZIP}")
    t0 = time.time()
    
    file_count = 0
    total_bytes = 0

    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(SRC_DIR):
            # Modify dirs in-place to avoid descending into excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, SRC_DIR)
                
                if should_exclude(rel_path):
                    continue
                
                # Check for lock files or temporary files
                if file.startswith("~$") or file.endswith(".tmp"):
                    continue
                    
                try:
                    zf.write(full_path, arcname=rel_path)
                    file_count += 1
                    total_bytes += os.path.getsize(full_path)
                    if file_count % 250 == 0:
                        print(f"  Added {file_count} files ({(total_bytes / (1024*1024)):.1f} MB uncompressed)...")
                except Exception as e:
                    print(f"  Warning: Skipped {rel_path} ({e})")

    dur = time.time() - t0
    zip_size_mb = os.path.getsize(OUT_ZIP) / (1024 * 1024)
    print("=" * 60)
    print(f"SUCCESS: Package created in {dur:.1f}s")
    print(f"Total files included: {file_count}")
    print(f"Uncompressed size:    {(total_bytes / (1024*1024)):.1f} MB")
    print(f"Compressed zip size:  {zip_size_mb:.1f} MB")
    print("=" * 60)

if __name__ == "__main__":
    main()
