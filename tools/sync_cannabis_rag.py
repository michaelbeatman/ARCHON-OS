import os
import sys
import json
import time
import urllib.request
import urllib.parse

API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "")
BASE_URL = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001/api/v1")
WORKSPACE = os.environ.get("ANYTHINGLLM_WORKSPACE", "mein-workspace")
VAULT_PATH = r"C:\Mein Obsidian"
TARGET_DIR = os.path.join(VAULT_PATH, "02_Wissensbibliothek", "06_Cannabis_Wirtschaft_Medizin")
STATE_FILE = r"C:\Mein Obsidian\synced_cannabis.json"

def get_synced():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_synced(synced_set):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(sorted(list(synced_set)), f, indent=2)
    except Exception as e:
        print(f"Error saving state: {e}", flush=True)

def upload_and_embed(rel_path, full_path):
    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
        text_content = f.read()

    # Upload raw text via raw-text endpoint or multipart
    # AnythingLLM raw-text endpoint: POST /api/v1/document/raw-text
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
            return False, f"Keine Location: {res}"

    # Embed in workspace: POST /api/v1/workspace/{WORKSPACE}/update-embeddings
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
            return True, "OK"
        return False, f"Embed failed: {embed_res}"

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
    print(f"=== CANNABIS RAG SYNC START ===", flush=True)
    print(f"Bereits erfasst: {len(synced)} | Neu zu synchronisieren: {total}", flush=True)

    success = 0
    fail = 0

    for idx, (rel, p) in enumerate(files_to_sync, 1):
        print(f"[{idx}/{total}] {rel} -> Sync...", end="", flush=True)
        t0 = time.time()
        try:
            ok, msg = upload_and_embed(rel, p)
            dt = time.time() - t0
            if ok:
                print(f" -> OK ({dt:.1f}s)", flush=True)
                synced.add(rel)
                success += 1
                if success % 20 == 0:
                    save_synced(synced)
            else:
                print(f" -> FEHLER: {msg} ({dt:.1f}s)", flush=True)
                fail += 1
        except Exception as e:
            dt = time.time() - t0
            print(f" -> EXCEPTION: {e} ({dt:.1f}s)", flush=True)
            fail += 1

    save_synced(synced)
    print(f"\n=== CANNABIS RAG SYNC BEENDET ===", flush=True)
    print(f"Erfolgreich: {success} | Fehler: {fail} | Gesamt: {total}", flush=True)

if __name__ == "__main__":
    main()
