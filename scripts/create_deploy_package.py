#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to create the clean deployment package:
AgenticOS-2026_Homeserver_Deploy_v0.3.1.zip
in /mnt/raid/_ARCHON Backups/Archon v0.3.1/ (or Y:\\_ARCHON Backups\\Archon v0.3.1\\)
"""
import os
import sys
import zipfile
import time
import shutil

VERSION = "v0.3.1"
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Target backup directory
if os.path.exists("/mnt/raid/_ARCHON Backups"):
    OUT_DIR = f"/mnt/raid/_ARCHON Backups/Archon {VERSION}"
elif os.path.exists(r"Y:\_ARCHON Backups"):
    OUT_DIR = rf"Y:\_ARCHON Backups\Archon {VERSION}"
else:
    OUT_DIR = os.path.join(BASE_DIR, "backups", f"Archon_{VERSION}")

OUT_ZIP = os.path.join(OUT_DIR, f"AgenticOS-2026_Homeserver_Deploy_{VERSION}.zip")

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
    "_ARCHON Backups",
    "LinkedIn-backup",
    "OpenMontage",
    "paperclip",
    "library",
    "archive",
    "static_backup",
    "browser-use",
    "antigravity_complete_skills_package",
    "dist",
    "build",
    "staging",
}

EXCLUDE_EXTS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".bak",
    ".tmp",
    ".zip",
    ".tar.gz",
    ".tar",
    ".gz",
    ".bundle"
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
    name_lower = filename.lower()
    
    # Exclude backup archives & bundles
    if any(name_lower.endswith(ext) for ext in EXCLUDE_EXTS):
        return True
        
    if name_lower.startswith("~$") or ".bak" in name_lower:
        return True
        
    if filename in {"credentials.json", "gmail_token.json", "google_token.json"}:
        return True
        
    return False

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("=" * 65)
    print(f"Creating deploy package: {OUT_ZIP}")
    print(f"Source Directory:        {BASE_DIR}")
    print("=" * 65)
    t0 = time.time()
    
    file_count = 0
    total_bytes = 0

    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(BASE_DIR):
            # Modify dirs in-place to avoid descending into excluded directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, BASE_DIR)
                
                if should_exclude(rel_path):
                    continue
                
                if file.startswith("~$") or file.endswith(".tmp"):
                    continue
                    
                try:
                    zf.write(full_path, arcname=rel_path)
                    file_count += 1
                    total_bytes += os.path.getsize(full_path)
                    if file_count % 300 == 0:
                        print(f"  Added {file_count} files ({(total_bytes / (1024*1024)):.1f} MB uncompressed)...")
                except Exception as e:
                    print(f"  Warning: Skipped {rel_path} ({e})")

    dur = time.time() - t0
    zip_size_mb = os.path.getsize(OUT_ZIP) / (1024 * 1024)
    print("=" * 65)
    print(f"SUCCESS: Package created in {dur:.1f}s")
    print(f"Total files included: {file_count}")
    print(f"Uncompressed size:    {(total_bytes / (1024*1024)):.1f} MB")
    print(f"Compressed zip size:  {zip_size_mb:.1f} MB")
    print(f"Output path:          {OUT_ZIP}")
    print("=" * 65)

if __name__ == "__main__":
    main()
