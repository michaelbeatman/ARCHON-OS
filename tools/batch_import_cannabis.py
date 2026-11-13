import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
from utils.batch_library_importer import process_document, slugify

SOURCE_DIR = r"Y:\_CANNABIS"
VAULT_DIR = r"./obsidian_vault"
TARGET_CATEGORY = "06_Cannabis_Wirtschaft_Medizin"

def main():
    target_category_dir = os.path.join(VAULT_DIR, "02_Wissensbibliothek", TARGET_CATEGORY)
    os.makedirs(target_category_dir, exist_ok=True)
    
    existing_items = set(os.listdir(target_category_dir))
    all_files = sorted([f for f in os.listdir(SOURCE_DIR) if f.lower().endswith(".pdf")])
    
    pending_files = []
    for f in all_files:
        base = os.path.splitext(f)[0]
        slug = slugify(base)
        is_done = False
        if slug in existing_items or f"_Index_{slug}.md" in existing_items or f"{slug}.md" in existing_items:
            is_done = True
        else:
            for v in existing_items:
                if slug in v or v in slug:
                    is_done = True
                    break
        if not is_done:
            pending_files.append(f)

    total_pending = len(pending_files)
    print(f"=== BATCH-INGEST START: {total_pending} Dokumente zu verarbeiten ===", flush=True)
    
    success_count = 0
    fail_count = 0
    
    for idx, filename in enumerate(pending_files, 1):
        fpath = os.path.join(SOURCE_DIR, filename)
        fsize_mb = os.path.getsize(fpath) / (1024 * 1024)
        print(f"[{idx}/{total_pending}] Verarbeite: '{filename}' ({fsize_mb:.1f} MB)...", flush=True)
        
        t0 = time.time()
        try:
            res = process_document(fpath, VAULT_DIR, TARGET_CATEGORY)
            dt = time.time() - t0
            pages = res.get("total_pages", 0)
            status = res.get("status", "ok")
            print(f"    -> Fertig in {dt:.1f}s | Seiten: {pages} | Status: {status}", flush=True)
            success_count += 1
        except Exception as e:
            dt = time.time() - t0
            print(f"    -> FEHLER nach {dt:.1f}s: {e}", flush=True)
            fail_count += 1
            
    print(f"\n=== BATCH-INGEST BEENDET ===", flush=True)
    print(f"Erfolgreich: {success_count} | Fehler: {fail_count} | Gesamt: {total_pending}", flush=True)

if __name__ == "__main__":
    main()
