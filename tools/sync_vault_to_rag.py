#!/usr/bin/env python3
"""
tools/sync_vault_to_rag.py - Ingestion-Skript für Obsidian Vault zu AnythingLLM

Überträgt Markdown-Kapitel aus dem Obsidian-Vault automatisiert an AnythingLLM.
Verwendet httpx (oder urllib fallback), damit das Skript sowohl auf dem Host
als auch nativ im Docker-Container ohne zusätzliche Pip-Installationen lauffähig ist.

Optimierungen:
1. Idempotenz & Tracking:
   - Status-Datei unter /opt/data/synced_files.json (mit Fallback auf ./data/synced_files.json)
   - Speichert relative Pfade aller erfolgreich verarbeiteten Dateien
   - Überspringt bereits synchronisierte Dateien direkt beim Scan
2. CLI-Parameter:
   - --all: Verarbeitet alle noch nicht synchronisierten Dateien ohne künstliches Limit
   - --limit N: Verarbeitet maximal N noch nicht synchronisierte Dateien
   - Pflichtprüfung: Entweder --limit oder --all muss angegeben werden, sonst erscheint
     eine verständliche Fehlermeldung mit Hilfetext
3. Sicherheitsmechanismen:
   - Lastschutz mit time.sleep(2) zwischen Uploads
   - Striktes Ignorieren von .obsidian, .trash, .git und _Index_-Dateien
"""

import os
import sys
import time
import json
import argparse
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Set, Optional

# Httpx bevorzugen, Fallback auf urllib
try:
    import httpx
except ImportError:
    httpx = None


# Embedding eines Buchkapitels dauert auf schwacher CPU mehrere Minuten.
# Timeout deshalb konfigurierbar; ein zu kurzer Wert bricht den Client ab,
# waehrend der Server fertig einbettet (Dokument landet im Index, wird aber
# nicht als synchronisiert vermerkt und beim naechsten Lauf erneut hochgeladen).
SYNC_TIMEOUT = float(os.environ.get("RAG_SYNC_TIMEOUT", "900"))


def get_default_vault_path() -> Path:
    """Ermittelt den Vault-Pfad — SSOT-Resolver zuerst (G dieses Audits)."""
    # G: vorher hatte dieses Skript eine eigene Kandidatenliste und konnte
    # einen anderen Vault als die /api/vault-Routen indizieren (Split-Brain).
    try:
        from archon.core.runtime import resolve_obsidian_vault_path
        central = resolve_obsidian_vault_path()
        if central and os.path.isdir(central):
            return Path(central)
    except Exception:
        pass

    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path and os.path.exists(env_path):
        return Path(env_path)

    candidates = [
        Path("/opt/data/obsidian"),
        Path(r"./obsidian_vault"),
        Path("./agent_workspace/obsidian_vault"),
        Path("./obsidian_vault")
    ]
    for c in candidates:
        if c.exists():
            return c

    return Path("/opt/data/obsidian")


def get_sync_state_file_path() -> Path:
    """Ermittelt und stellt den Pfad für die Status-Datei synced_files.json bereit."""
    candidates = [
        Path("/opt/data/synced_files.json"),
        Path("./data/synced_files.json"),
        Path("/app/data/synced_files.json")
    ]
    for c in candidates:
        if c.parent.exists():
            return c

    primary = candidates[0]
    try:
        primary.parent.mkdir(parents=True, exist_ok=True)
        return primary
    except Exception:
        fallback = candidates[1]
        fallback.parent.mkdir(parents=True, exist_ok=True)
        return fallback


def load_synced_files(state_path: Path) -> Dict[str, Dict[str, Any]]:
    """C20: Pfad -> {mtime,size}. Alte Listenformate werden einmalig migriert."""
    if not state_path.exists():
        return {}

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "synced_files" in data:
                data = data["synced_files"]
            if isinstance(data, list):
                # Legacy: keine mtime vorhanden -> einmal neu synchronisieren
                return {str(p): {} for p in data}
            if isinstance(data, dict):
                return {str(k): (v if isinstance(v, dict) else {}) for k, v in data.items()}
    except Exception as e:
        print(f"[WARNUNG] Status-Datei '{state_path}' konnte nicht gelesen werden: {e}", file=sys.stderr)

    return {}


def _file_fingerprint(file_path: Path) -> Dict[str, Any]:
    try:
        st = file_path.stat()
        return {"mtime": st.st_mtime, "size": st.st_size}
    except OSError:
        return {}


def record_synced_file(state_path: Path, rel_path_str: str, file_path: Optional[Path] = None) -> None:
    """Speichert Pfad + Fingerprint atomar (C20: Aenderungen erkennbar)."""
    synced = load_synced_files(state_path)
    synced[rel_path_str] = _file_fingerprint(file_path) if file_path else {}
    temp_path = None
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        # H (dieses Audits): fester Name `.tmp` kollidierte bei parallelen
        # Sync-Läufen. mkstemp liefert einen eindeutigen Namen im Zielordner.
        fd, temp_path = tempfile.mkstemp(
            dir=str(state_path.parent), prefix=".synced_", suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(synced, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, state_path)
        # Directory-fsync: der Rename muss nach Stromausfall sichtbar bleiben.
        try:
            dir_fd = os.open(str(state_path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
        temp_path = None
    except Exception as e:
        print(f"[WARNUNG] Status-Datei '{state_path}' konnte nicht aktualisiert werden: {e}", file=sys.stderr)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def get_anythingllm_base_url() -> str:
    """Ermittelt die erreichbare AnythingLLM Base-URL."""
    env_url = os.environ.get("ANYTHINGLLM_URL")
    if env_url:
        return env_url.rstrip("/") + "/api/v1"

    candidates = [
        "http://anything-llm:3001/api/v1",
        "http://127.0.0.1:3001/api/v1",
        "http://localhost:3001/api/v1"
    ]
    if httpx:
        for url in candidates:
            try:
                ping_target = url.replace("/api/v1", "/api/ping")
                with httpx.Client(timeout=1.5) as client:
                    res = client.get(ping_target)
                    if res.status_code in [200, 403, 401]:
                        return url
            except Exception:
                continue

    return "http://anything-llm:3001/api/v1"


def should_include_file(file_path: Path, vault_base: Path, synced_files: Dict[str, Dict[str, Any]]) -> bool:
    """
    Prüft, ob eine .md-Datei für den RAG-Index qualifiziert ist:
    - Endung muss .md sein.
    - Ignoriert Verzeichnisse wie .obsidian, .trash, .git sowie _Index_-Dateien strikt.
    - Erfasst Markdown-Dateien (*.md), die in Unterordnern wie 02_Recht_Steuern, 06_Cannabis oder 08_Projektmanagement_Organisation liegen.
    - Idempotenz: Überspringt Dateien, die bereits in synced_files.json enthalten sind.
    """
    rel_str = str(file_path.relative_to(vault_base)).replace("\\", "/")
    filename = file_path.name

    if not filename.lower().endswith(".md"):
        return False

    # 1. Idempotenz-Check: nur ueberspringen, wenn der Fingerprint unveraendert
    # ist. Vorher wurde eine Datei nach der Erstindizierung NIE wieder sync'd.
    previous = synced_files.get(rel_str)
    if previous is not None:
        current = _file_fingerprint(file_path)
        if previous and current and (
            abs(float(previous.get("mtime", 0)) - float(current.get("mtime", 0))) < 0.001
            and previous.get("size") == current.get("size")
        ):
            return False

    # 2. Ausschluss von Systemordnern & Index-Dateien
    lower_rel = rel_str.lower()
    if any(blocked in lower_rel for blocked in [".obsidian", ".trash", ".git", "_index_"]):
        return False

    # 3. Zieldestinationen: 02_Recht_Steuern, 06_Cannabis, 08_Projektmanagement_Organisation
    # oder allgemein Kapitel-Dateien in 02_Wissensbibliothek
    target_prefixes = [
        "02_recht_steuern",
        "06_cannabis",
        "08_projektmanagement_organisation"
    ]
    is_target_dir = any(t in lower_rel for t in target_prefixes)
    is_chapter = filename.startswith("Kapitel_") or filename.lower().startswith("kapitel_")

    if is_target_dir and (is_chapter or "02_wissensbibliothek" in lower_rel):
        return True

    # Ergänzend: Buchkapitel mit Kapitel_ in Inhaltsordnern (z. B. 01_, 03_, 07_)
    parts = file_path.relative_to(vault_base).parts
    for part in parts[:-1]:
        if len(part) >= 3 and part[:2].isdigit() and part[2] == "_" and is_chapter:
            return True

    return False


def collect_pending_vault_files(vault_path: Path, synced_files: Dict[str, Dict[str, Any]]) -> List[Path]:
    """Sammelt rekursiv alle qualifizierten, noch nicht synchronisierten Markdown-Dateien."""
    if not vault_path.exists():
        return []

    collected: List[Path] = []
    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in [".obsidian", ".trash", ".git"]]
        for f in files:
            full_p = Path(root) / f
            if should_include_file(full_p, vault_path, synced_files):
                collected.append(full_p)

    collected.sort()
    return collected


def upload_document(base_url: str, api_key: str, file_path: Path) -> Optional[str]:
    """
    1. Datei per Multipart-Upload an POST /api/v1/document/upload senden.
    Gibt den 'location' Pfad des Dokuments im Storage zurück.
    """
    upload_url = f"{base_url}/document/upload"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        if httpx:
            files = {"file": (file_path.name, file_bytes, "text/markdown")}
            with httpx.Client(timeout=SYNC_TIMEOUT) as client:
                res = client.post(upload_url, headers=headers, files=files)
                if res.status_code != 200:
                    print(f"    [FEHLER Upload] HTTP {res.status_code}: {res.text[:120]}", file=sys.stderr)
                    return None
                data = res.json()
        else:
            import urllib.request
            import uuid
            boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
            body_parts = []
            body_parts.append(f"--{boundary}\r\n".encode())
            body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode())
            body_parts.append(b"Content-Type: text/markdown\r\n\r\n")
            body_parts.append(file_bytes)
            body_parts.append(f"\r\n--{boundary}--\r\n".encode())
            body = b"".join(body_parts)

            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            req = urllib.request.Request(upload_url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=SYNC_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())

        if isinstance(data, dict):
            documents = data.get("documents")
            if documents and isinstance(documents, list) and len(documents) > 0:
                return documents[0].get("location")
            if "location" in data:
                return data["location"]

        print(f"    [FEHLER Upload] Unerwartete Response-Struktur: {data}", file=sys.stderr)
        return None

    except Exception as e:
        print(f"    [EXCEPTION Upload]: {e}", file=sys.stderr)
        return None


def add_document_to_workspace(base_url: str, api_key: str, workspace_slug: str, doc_location: str) -> bool:
    """
    2. Dokument dem Workspace zuweisen via POST /api/v1/workspace/{workspace}/update-embeddings
    mit Payload {"adds": [location]}.
    """
    update_url = f"{base_url}/workspace/{workspace_slug}/update-embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "adds": [doc_location]
    }

    try:
        if httpx:
            with httpx.Client(timeout=SYNC_TIMEOUT) as client:
                res = client.post(update_url, headers=headers, json=payload)
                if res.status_code == 200:
                    return True
                print(f"    [FEHLER Update-Embeddings] HTTP {res.status_code}: {res.text[:120]}", file=sys.stderr)
                return False
        else:
            import urllib.request
            req_data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(update_url, data=req_data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=SYNC_TIMEOUT) as resp:
                if resp.status == 200:
                    return True
            return False

    except Exception as e:
        print(f"    [EXCEPTION Update-Embeddings]: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Synchronisiert Obsidian-Vault Markdown-Dateien mit AnythingLLM (mit Idempotenz-Tracking).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Beispiele:
  # Verarbeite die nächsten 10 noch nicht synchronisierten Dateien:
  python tools/sync_vault_to_rag.py --api-key <KEY> --limit 10

  # Verarbeite ALLE noch ausstehenden Dateien:
  python tools/sync_vault_to_rag.py --api-key <KEY> --all
        """
    )
    parser.add_argument("--api-key", default=os.environ.get("ANYTHINGLLM_API_KEY"), help="AnythingLLM API-Key (Standard: aus ANYTHINGLLM_API_KEY)")
    parser.add_argument("--limit", type=int, default=None, help="Maximale Anzahl an zu verarbeitenden Dateien")
    parser.add_argument("--all", action="store_true", help="Synchronisiert alle noch nicht verarbeiteten Dateien ohne Limit")
    parser.add_argument("--vault-path", type=str, default=None, help="Optionaler Pfad zum Obsidian Vault")
    parser.add_argument("--workspace", type=str, default="mein-workspace", help="Ziel-Workspace Slug (Standard: mein-workspace)")
    parser.add_argument("--base-url", type=str, default=None, help="AnythingLLM Base-URL (z. B. http://anything-llm:3001/api/v1)")
    parser.add_argument("--state-file", type=str, default=None, help="Pfad zur Status-Datei (Standard: /opt/data/synced_files.json)")

    args = parser.parse_args()

    api_key = (args.api_key or "").strip()
    if not api_key:
        print("\n[FEHLER] Kein API-Key angegeben!", file=sys.stderr)
        print("Bitte gib entweder einen API-Key mit '--api-key <KEY>' an oder setze ANYTHINGLLM_API_KEY als Umgebungsvariable.\n", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(2)

    # Validierung: Weder --limit noch --all angegeben
    if not args.all and args.limit is None:
        print("\n[FEHLER] Fehlender Batch-Umfang!", file=sys.stderr)
        print("Bitte gib entweder ein Dateilimit mit '--limit <ANZAHL>' an oder nutze '--all', um alle ausstehenden Dateien zu verarbeiten.\n", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(2)

    vault_dir = Path(args.vault_path) if args.vault_path else get_default_vault_path()
    state_file = Path(args.state_file) if args.state_file else get_sync_state_file_path()
    base_url = args.base_url.rstrip("/") if args.base_url else get_anythingllm_base_url()
    workspace = args.workspace
    api_key = args.api_key.strip()

    limit_desc = "UNBEGRENZT (--all)" if args.all else f"{args.limit} Dateien"

    print("=" * 65)
    print("ARCHON OS: Obsidian Vault -> AnythingLLM Ingest Pipeline")
    print("=" * 65)
    print(f"Vault Pfad:       {vault_dir}")
    print(f"Status-Datei:     {state_file}")
    print(f"AnythingLLM API:  {base_url}")
    print(f"Ziel-Workspace:   {workspace}")
    print(f"Batch-Modus:      {limit_desc}")
    print("-" * 65)

    if not vault_dir.exists():
        print(f"[FEHLER] Quellverzeichnis '{vault_dir}' existiert nicht!", file=sys.stderr)
        sys.exit(1)

    # 1. Bisherigen Status laden
    synced_files = load_synced_files(state_file)
    print(f"[STATUS] Bereits synchronisiert: {len(synced_files)} Dateien in {state_file.name}")

    # 2. Ausstehende Dateien sammeln (Bereits synchronisierte werden sofort gefiltert)
    pending_files = collect_pending_vault_files(vault_dir, synced_files)
    if not pending_files:
        print("[HINWEIS] Keine neuen, ungesyncten Markdown-Dateien gefunden. Vault ist auf dem neuesten Stand.")
        sys.exit(0)

    # 3. Auswahl nach Parametern
    if args.all:
        selected_files = pending_files
    else:
        selected_files = pending_files[:max(1, args.limit)]

    total = len(selected_files)
    print(f"[SCAN] Ausstehend: {len(pending_files)} Dateien. Verarbeite diesen Durchlauf: {total} Dateien...")
    print("-" * 65)

    success_count = 0
    for idx, fpath in enumerate(selected_files, start=1):
        rel_str = str(fpath.relative_to(vault_dir)).replace("\\", "/")
        print(f"[{idx}/{total}] {rel_str} -> Uploading...", end="", flush=True)

        location = upload_document(base_url, api_key, fpath)
        if not location:
            print(" -> FEHLER (Upload)")
            continue

        ok = add_document_to_workspace(base_url, api_key, workspace, location)
        if ok:
            print(" -> OK")
            success_count += 1
            # Idempotenz-Tracking: Sofort atomar erfassen
            record_synced_file(state_file, rel_str, fpath)
        else:
            print(" -> FEHLER (Embeddings)")

        # Lastschutz: 2 Sekunden Pause zwischen zwei Dateien
        if idx < total:
            time.sleep(2)

    print("-" * 65)
    print(f"[FERTIG] {success_count}/{total} Dokumente erfolgreich im RAG-Index verarbeitet.")
    print(f"[STATUS] Neuer Gesamtstand synchronisierter Dateien: {len(load_synced_files(state_file))}")
    print("=" * 65)


if __name__ == "__main__":
    main()
