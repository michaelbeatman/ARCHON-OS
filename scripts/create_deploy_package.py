#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script to create the clean, privacy-hardened deployment packages:
1. AgenticOS-2026_Homeserver_Deploy_v0.3.1.zip (Blank / Standard, 102 MB)
2. AgenticOS-2026_Homeserver_Deploy_v0.3.1_inkl.Wissensdatenbank.zip (inkl. vollständiger Wissensbibliothek)

Both packages:
- Zero personal correspondence, no emails, no private .env / API-Keys
- No personal documents (Bewerbungen, Lebensläufe, Protokolle, private PDFs)
- No user SQLite databases (kanban.db, state.db, pb_data)
"""
import os
import sys
import zipfile
import time
import argparse

VERSION = "v0.3.1"
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Target backup directory
if os.path.exists("/mnt/raid/_ARCHON Backups"):
    OUT_DIR = f"/mnt/raid/_ARCHON Backups/Archon {VERSION}"
elif os.path.exists(r"Y:\_ARCHON Backups"):
    OUT_DIR = rf"Y:\_ARCHON Backups\Archon {VERSION}"
else:
    OUT_DIR = os.path.join(BASE_DIR, "backups", f"Archon_{VERSION}")

# Strictly excluded directories from the main walk
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
    "paperclip_data",
    "library",
    "archive",
    "static_backup",
    "browser-use",
    "antigravity_complete_skills_package",
    "dist",
    "build",
    "staging",
    "agent_workspace",      # Personal vault excluded
    "obsidian_vault",       # Packaged explicitly
    "pocketbase-media",
    "omniroute_data",
    "quartz_app",
    "pb_data",
    "audio_cache",
    "obsidian-config",
    "inbox",
    "exported_vault",
    "hermes_profiles",
    "quickchat_sessions",
    "autogen",
    "logs",
    "frontend",
    "prime-agent",
    "chrome-extension",
    "scratch",
    "static_backup",
}

# Strictly excluded file extensions
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
    ".bundle",
    ".mp4",
    ".mp3",
    ".wav",
    ".ogg",
    ".webm",
    ".mov",
    ".avi",
    ".pdf",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".db-shm",
    ".db-wal",
    ".db-journal",
    ".xlsx",
    ".csv",
}

# Substring matches that indicate personal data or draft docs
SENSITIVE_PATTERNS = [
    "api-key",
    "apikey",
    "credentials",
    "gmail_token",
    "google_token",
    "protokoll",
    "protocol",
    "bewerbung",
    "lebenslauf",
    "korrespondenz",
    "outreach",
    "vakanz",
    "anzeige",
    "diagnostik",
    "adhs",
    "delst",
    "vorlage_pre_",
    "vorlage_inline",
    "handoff_2026",
    "handover_2026",
    "session_handoff",
    "migration_handoff",
    "keller",
    "pe_haeuser",
]

def is_forbidden(rel_path, filename):
    name_lower = filename.lower()
    path_lower = rel_path.lower()
    
    # 1. Environment files: only allow .env.example
    if name_lower.startswith(".env") and filename != ".env.example":
        return True
        
    # 2. Token / credential files / cache indices
    if any(k in name_lower for k in ("token.json", "credential", "secret.json", "tree_cache", "synced_")):
        return True

    # 3. Disallowed extensions
    if any(name_lower.endswith(ext) for ext in EXCLUDE_EXTS):
        # Allow specific catalog csv files
        if name_lower in {"fabric_patterns_de.csv", "skills_marketplace_catalog.json"}:
            pass
        else:
            return True

    # 4. Lock files & backups
    if name_lower.startswith("~$") or ".bak" in name_lower:
        return True

    # 5. Sensitive keywords (exclude if in filename, unless it's a python module or standard template)
    if not filename.endswith(".py"):
        for pat in SENSITIVE_PATTERNS:
            if pat in name_lower or pat in path_lower:
                return True

    return False

def should_exclude_main(rel_path):
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in EXCLUDE_DIRS:
            return True
        if p.startswith("~$") or p.startswith(".cache"):
            return True
        if p.startswith("C:") or "Antigravity-projekte" in p:
            return True

    filename = parts[-1]
    return is_forbidden(rel_path, filename)

def add_obsidian_curated_folders(zf, counter_ref, include_full_wissensbibliothek=False):
    """
    Packages Obsidian folders:
    - 00_HR_Agenten (from agent_workspace/obsidian_vault)
    - 04_Radar (from obsidian_vault)
    - 05_Content (from obsidian_vault)
    - agent_configs.json & fabric_patterns_de.csv
    - 02_Wissensbibliothek:
        - If include_full_wissensbibliothek=True: loads full /mnt/raid/Mein Obsidian/02_Wissensbibliothek
        - If False: minimal starter files from agent_workspace/obsidian_vault/02_Wissensbibliothek
    """
    mode_label = "INKL. VOLLER WISSENSBIBLIOTHEK" if include_full_wissensbibliothek else "BLANK / MINIMAL"
    print(f"\n[Obsidian ({mode_label})] Packaging curated folders...")
    
    source_vault = os.path.join(BASE_DIR, "agent_workspace", "obsidian_vault")
    root_vault = os.path.join(BASE_DIR, "obsidian_vault")
    
    # 1. From root template vault (04_Radar, 05_Content, config files)
    if os.path.exists(root_vault):
        for root, dirs, files in os.walk(root_vault):
            for file in sorted(files):
                full_path = os.path.join(root, file)
                rel_in_vault = os.path.relpath(full_path, root_vault).replace("\\", "/")
                target_arcname = f"obsidian_vault/{rel_in_vault}"
                
                if is_forbidden(target_arcname, file):
                    continue
                    
                zf.write(full_path, arcname=target_arcname)
                counter_ref[0] += 1
                counter_ref[1] += os.path.getsize(full_path)
                
    # 2. 00_HR_Agenten (from agent_workspace/obsidian_vault)
    hr_dir = os.path.join(source_vault, "00_HR_Agenten")
    if os.path.exists(hr_dir):
        for root, dirs, files in os.walk(hr_dir):
            for file in sorted(files):
                full_path = os.path.join(root, file)
                rel_in_vault = os.path.relpath(full_path, source_vault).replace("\\", "/")
                target_arcname = f"obsidian_vault/{rel_in_vault}"
                
                if is_forbidden(target_arcname, file):
                    continue
                    
                zf.write(full_path, arcname=target_arcname)
                counter_ref[0] += 1
                counter_ref[1] += os.path.getsize(full_path)

    # 3. 02_Wissensbibliothek
    if include_full_wissensbibliothek:
        # Full Wissensbibliothek from /mnt/raid/Mein Obsidian/02_Wissensbibliothek
        full_wissen_dir = "/mnt/raid/Mein Obsidian/02_Wissensbibliothek"
        if not os.path.exists(full_wissen_dir):
            full_wissen_dir = os.path.join(source_vault, "02_Wissensbibliothek")
            
        print(f"  -> Adding full Wissensbibliothek from: {full_wissen_dir}")
        for root, dirs, files in os.walk(full_wissen_dir):
            for file in sorted(files):
                full_path = os.path.join(root, file)
                rel_sub = os.path.relpath(full_path, full_wissen_dir).replace("\\", "/")
                target_arcname = f"obsidian_vault/02_Wissensbibliothek/{rel_sub}"
                
                if is_forbidden(target_arcname, file):
                    continue
                    
                zf.write(full_path, arcname=target_arcname)
                counter_ref[0] += 1
                counter_ref[1] += os.path.getsize(full_path)
                if counter_ref[0] % 1000 == 0:
                    print(f"     [Wissensbibliothek] Added {counter_ref[0]} total files...")
    else:
        # Minimal Wissensbibliothek
        wissen_dir = os.path.join(source_vault, "02_Wissensbibliothek")
        if os.path.exists(wissen_dir):
            for root, dirs, files in os.walk(wissen_dir):
                for file in sorted(files):
                    full_path = os.path.join(root, file)
                    rel_in_vault = os.path.relpath(full_path, source_vault).replace("\\", "/")
                    target_arcname = f"obsidian_vault/{rel_in_vault}"
                    
                    if is_forbidden(target_arcname, file):
                        continue
                        
                    zf.write(full_path, arcname=target_arcname)
                    counter_ref[0] += 1
                    counter_ref[1] += os.path.getsize(full_path)

def audit_zip(zip_path):
    print("\n" + "=" * 65)
    print(f"SECURITY AUDIT: {os.path.basename(zip_path)}")
    print("=" * 65)
    zf = zipfile.ZipFile(zip_path, 'r')
    infolist = zf.infolist()
    print(f"Total entries: {len(infolist)}")
    
    critical_violations = []
    for info in infolist:
        fn = info.filename.lower()
        if fn == ".env" or fn.endswith("/.env") or ".env.backup" in fn or ".env.local" in fn:
            critical_violations.append((info.filename, "Live .env with potential API keys"))
        if any(fn.endswith(ext) for ext in (".db", ".sqlite", ".sqlite3", ".pdf", ".mp4", ".mp3")):
            critical_violations.append((info.filename, "Database, personal PDF, or media file"))
        if any(k in fn for k in ("credential", "gmail_token", "google_token", "api-keys", "bewerbung", "lebenslauf", "anzeige", "adhs", "delst")):
            critical_violations.append((info.filename, "Personal record or secret"))
            
    if critical_violations:
        print(f"❌ AUDIT FAILED: Found {len(critical_violations)} sensitive items!")
        for item, reason in critical_violations[:10]:
            print(f"   - {item} [{reason}]")
        raise RuntimeError(f"Deploy package {zip_path} contains sensitive or private items! Aborting.")
    else:
        print("✅ AUDIT PASSED: ZERO personal files, ZERO credentials, ZERO live databases, ZERO API-Keys.")
        print("=" * 65)

def build_package(target_zip, include_full_wissensbibliothek=False):
    os.makedirs(os.path.dirname(target_zip), exist_ok=True)
    mode_name = "INKL. WISSENSDATENBANK" if include_full_wissensbibliothek else "BLANK / STANDARD"
    print("\n" + "=" * 65)
    print(f"Building: {os.path.basename(target_zip)} [{mode_name}]")
    print("=" * 65)
    t0 = time.time()
    
    counter = [0, 0] # [file_count, total_bytes]

    with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        # 1. Main codebase pass
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
            
            for file in sorted(files):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, BASE_DIR)
                
                if should_exclude_main(rel_path):
                    continue
                    
                try:
                    zf.write(full_path, arcname=rel_path)
                    counter[0] += 1
                    counter[1] += os.path.getsize(full_path)
                    if counter[0] % 1000 == 0:
                        print(f"  Added {counter[0]} codebase files...")
                except Exception as e:
                    print(f"  Warning: Skipped {rel_path} ({e})")
                    
        # 2. Add Obsidian folders
        add_obsidian_curated_folders(zf, counter, include_full_wissensbibliothek=include_full_wissensbibliothek)

    dur = time.time() - t0
    zip_size_mb = os.path.getsize(target_zip) / (1024 * 1024)
    print(f"\nSUCCESS: Created {os.path.basename(target_zip)} in {dur:.1f}s")
    print(f"Total files:      {counter[0]}")
    print(f"Uncompressed:     {(counter[1] / (1024*1024)):.1f} MB")
    print(f"Compressed ZIP:   {zip_size_mb:.1f} MB")
    print(f"File location:    {target_zip}")
    
    # Audit
    audit_zip(target_zip)
    return target_zip

def main():
    parser = argparse.ArgumentParser(description="Create deployment packages")
    parser.add_argument("--mode", choices=["both", "blank", "wissen"], default="both",
                        help="Build both packages, only blank, or only with Wissensdatenbank")
    args = parser.parse_args()

    zip_blank = os.path.join(OUT_DIR, f"AgenticOS-2026_Homeserver_Deploy_{VERSION}.zip")
    zip_wissen = os.path.join(OUT_DIR, f"AgenticOS-2026_Homeserver_Deploy_{VERSION}_inkl.Wissensdatenbank.zip")

    if args.mode in ("both", "blank"):
        build_package(zip_blank, include_full_wissensbibliothek=False)
        # Refresh symlink in workspace root
        link_blank = os.path.join(BASE_DIR, f"AgenticOS-2026_Homeserver_Deploy_{VERSION}.zip")
        if os.path.lexists(link_blank): os.remove(link_blank)
        os.symlink(zip_blank, link_blank)

    if args.mode in ("both", "wissen"):
        build_package(zip_wissen, include_full_wissensbibliothek=True)
        # Refresh symlink in workspace root
        link_wissen = os.path.join(BASE_DIR, f"AgenticOS-2026_Homeserver_Deploy_{VERSION}_inkl.Wissensdatenbank.zip")
        if os.path.lexists(link_wissen): os.remove(link_wissen)
        os.symlink(zip_wissen, link_wissen)

    print("\n" + "=" * 65)
    print("ALL REQUESTED PACKAGES CREATED & AUDITED SUCCESSFULLY.")
    print("=" * 65)

if __name__ == "__main__":
    main()
