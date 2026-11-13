import os
import sys
import json
import time
import urllib.request
import threading

API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "")
BASE_URL = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001/api/v1")
WORKSPACE = os.environ.get("ANYTHINGLLM_WORKSPACE", "mein-workspace")
VAULT_PATH = r"./obsidian_vault"
STATE_FILE = r"./obsidian_vault\synced_vault_all.json"

def get_synced():
    synced = set()
    for sf in [STATE_FILE, r"./obsidian_vault\synced_cannabis.json"]:
        if os.path.exists(sf):
            try:
                with open(sf, "r", encoding="utf-8") as f:
                    synced.update(json.load(f))
            except Exception:
                pass
    return synced

def save_synced(synced_set):
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
        # Timeout für Raw-Text Upload: 180s
        with urllib.request.urlopen(req, timeout=180) as resp:
            res = json.loads(resp.read().decode())
            doc = res.get("documents", [{}])[0]
            location = doc.get("location")
            if not location:
                return False, f"Keine Location: {res}", time.time() - t0

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
        # Erweitertes Timeout: 600 Sekunden (10 Minuten)
        with urllib.request.urlopen(embed_req, timeout=600) as resp:
            embed_res = json.loads(resp.read().decode())
            if embed_res.get("workspace"):
                return True, "OK", time.time() - t0
            return False, f"Embed failed: {embed_res}", time.time() - t0
    except Exception as e:
        return False, str(e), time.time() - t0

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
    print(f"=== SYNC RESTPOSTEN MIT 600s TIMEOUT: {total} Dokumente ===", flush=True)

    success_count = 0
    fail_count = 0

    # Sequenziell (1 Dokument nach dem anderen), damit der Vektorizer die volle CPU/GPU hat
    for idx, (rel, p) in enumerate(files_to_sync, 1):
        fsize_kb = os.path.getsize(p) / 1024
        print(f"[{idx}/{total}] ({fsize_kb:.1f} KB) {rel} -> Sync...", end="", flush=True)
        ok, msg, dt = sync_single_document(rel, p)
        if ok:
            success_count += 1
            synced.add(rel)
            save_synced(synced)
            print(f" -> OK ({dt:.1f}s)", flush=True)
        else:
            fail_count += 1
            print(f" -> FEHLER ({dt:.1f}s): {msg}", flush=True)

    print(f"\n=== RESTPOSTEN SYNC BEENDET ===", flush=True)
    print(f"Erfolgreich: {success_count} | Fehler: {fail_count} | Gesamt: {total}", flush=True)

if __name__ == "__main__":
    main()
