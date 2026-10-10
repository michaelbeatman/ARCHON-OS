import os
import sys
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

API_KEY = "R9YRVG7-FCFMRNK-NZ3FKSX-QKN5RHF"
BASE_URL = "http://localhost:3001/api/v1"
WORKSPACE = "mein-workspace"
VAULT_PATH = r"C:\Mein Obsidian"
STATE_FILE = r"C:\Mein Obsidian\synced_vault_all.json"

state_lock = threading.Lock()

def get_synced():
    synced = set()
    for sf in [STATE_FILE, r"C:\Mein Obsidian\synced_cannabis.json"]:
        if os.path.exists(sf):
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    synced.update(json.load(f))
            except Exception:
                pass
    return synced

def save_synced(synced_set):
    with state_lock:
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(list(synced_set)), f, indent=2)
        except Exception as e:
            print(f"Error saving state: {e}", flush=True)

def sync_single_document(rel_path, full_path):
    t0 = time.time()
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            text_content = f.read()

        payload = json.dumps({
            "textContent": text_content,
            "metadata": {
                "title": os.path.basename(full_path),
                "docpath": rel_path
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{BASE_URL}/document/raw-text",
            data=payload,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode())
            doc = res.get("documents", [{}])[0]
            location = doc.get("location")
            if not location:
                return rel_path, False, f"Keine Location: {res}", time.time() - t0

        embed_payload = json.dumps({
            "adds": [location],
            "deletes": []
        }).encode("utf-8")

        embed_req = urllib.request.Request(
            f"{BASE_URL}/workspace/{WORKSPACE}/update-embeddings",
            data=embed_payload,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json"
            }
        )
        with urllib.request.urlopen(embed_req, timeout=180) as resp:
            embed_res = json.loads(resp.read().decode())
            if embed_res.get("workspace"):
                return rel_path, True, "OK", time.time() - t0
            return rel_path, False, f"Embed failed: {embed_res}", time.time() - t0
    except Exception as e:
        return rel_path, False, str(e), time.time() - t0

def main():
    synced = get_synced()
    files_to_sync = []
    bib_dir = os.path.join(VAULT_PATH, "02_Wissensbibliothek")
    
    for root, dirs, files in os.walk(bib_dir):
        if "_assets" in root:
            continue
        for f in files:
            if f.endswith(".md"):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, VAULT_PATH).replace("\\", "/")
                if rel not in synced:
                    files_to_sync.append((rel, p))

    total = len(files_to_sync)
    print(f"=== PARALLELER RAG SYNC START: {total} neue Dokumente (4 WORKER) ===", flush=True)

    success_count = 0
    fail_count = 0
    counter = 0

    max_workers = 4
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(sync_single_document, rel, p): rel for rel, p in files_to_sync}
        for future in as_completed(futures):
            counter += 1
            rel_path, ok, msg, duration = future.result()
            if ok:
                success_count += 1
                synced.add(rel_path)
                print(f"[{counter}/{total}] [OK {duration:.1f}s] {rel_path}", flush=True)
            else:
                fail_count += 1
                print(f"[{counter}/{total}] [FEHLER {duration:.1f}s] {rel_path}: {msg}", flush=True)

            if counter % 15 == 0:
                save_synced(synced)

    save_synced(synced)
    print(f"\n=== SYNC BEENDET ===", flush=True)
    print(f"Erfolgreich: {success_count} | Fehler: {fail_count} | Gesamt: {counter}", flush=True)

if __name__ == "__main__":
    main()
