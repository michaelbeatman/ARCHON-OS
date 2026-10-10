import os
import sys
import json
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

API_KEY = "R9YRVG7-FCFMRNK-NZ3FKSX-QKN5RHF"
BASE_URL = "http://localhost:3001/api/v1"
WORKSPACE = "mein-workspace"
VAULT_PATH = r"C:\Mein Obsidian"
TARGET_DIR = os.path.join(VAULT_PATH, "02_Wissensbibliothek", "06_Cannabis_Wirtschaft_Medizin")
STATE_FILE = r"C:\Mein Obsidian\synced_cannabis.json"

state_lock = threading.Lock()

def get_synced():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

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
    for root, dirs, files in os.walk(TARGET_DIR):
        for f in files:
            if f.endswith(".md"):
                p = os.path.join(root, f)
                rel = os.path.relpath(p, VAULT_PATH).replace("\\", "/")
                if rel not in synced:
                    files_to_sync.append((rel, p))

    total = len(files_to_sync)
    print(f"=== PARALLELER CANNABIS RAG SYNC START (4 WORKER) ===", flush=True)
    print(f"Bereits erfasst: {len(synced)} | Verbleibend: {total}", flush=True)

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
    print(f"\n=== PARALLELER SYNC BEENDET ===", flush=True)
    print(f"Erfolgreich: {success_count} | Fehler: {fail_count} | Gesamt verarbeitet: {counter}", flush=True)

if __name__ == "__main__":
    main()
