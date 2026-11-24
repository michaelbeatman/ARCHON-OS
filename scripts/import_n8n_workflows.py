#!/usr/bin/env python3
"""Importiert ALLE Archon-n8n-Workflows AKTIV (D06/HIGH).

Quellen (beide versioniert, keine echten Secrets im Repo):
  - scripts/n8n_routine_workflows.json    (3 Schedule-/Routine-Workflows)
  - scripts/n8n_workflows_bundle.json     (5 On-Demand-Workflows + HMAC-Receiver)

Das Service-Token wird zur Laufzeit aus data/.archon_service_token (oder ENV)
gelesen und NUR in Archon-API-HTTP-Nodes eingesetzt — es steht nie im Repo.
Nach dem Import setzt activate_n8n_workflows.js `active=1` und registriert alle
Webhooks. Ohne Token bricht der Import ab (keine aktiven, tokenlosen Workflows).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTINE_TEMPLATE = os.path.join(ROOT, "scripts", "n8n_routine_workflows.json")
BUNDLE = os.path.join(ROOT, "scripts", "n8n_workflows_bundle.json")
TOKEN_FILE = os.path.join(ROOT, "data", ".archon_service_token")
ACTIVATE_JS = os.path.join(ROOT, "scripts", "activate_n8n_workflows.js")
CONTAINER = "n8n"
ARCHON_HOST = "http://archon-os:8501"
TOKEN_PLACEHOLDER = "__ARCHON_SERVICE_TOKEN__"


def load_token() -> str:
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            tok = fh.read().strip()
        if tok:
            return tok
    return os.environ.get("ARCHON_SERVICE_TOKEN", "").strip()


def load_workflows() -> list:
    workflows = []
    seen = set()
    for path in (ROUTINE_TEMPLATE, BUNDLE):
        with open(path, encoding="utf-8") as fh:
            for wf in json.load(fh):
                if wf.get("id") in seen:
                    continue
                seen.add(wf.get("id"))
                workflows.append(wf)
    return workflows


def inject_token(workflows: list, token: str) -> list:
    """Token ausschliesslich an lokale Archon-API-HTTP-Nodes (kein Exfil-Risiko)."""
    for wf in workflows:
        for node in wf.get("nodes", []):
            params = node.get("parameters", {})
            url = params.get("url")
            if isinstance(url, str):
                for legacy in ("http://ARCHON-OS:8501", "http://archon-os:8501"):
                    if url.startswith(legacy):
                        params["url"] = ARCHON_HOST + url[len(legacy):]
                        break
            if node.get("type") != "n8n-nodes-base.httpRequest":
                continue
            if not str(params.get("url", "")).startswith(ARCHON_HOST):
                continue
            params["sendHeaders"] = True
            headers = params.setdefault("headerParameters", {}).setdefault("parameters", [])
            hdr = next(
                (h for h in headers if str(h.get("name", "")).lower() == "x-archon-service-token"),
                None,
            )
            if hdr is None:
                headers.append({"name": "X-Archon-Service-Token", "value": token})
            elif str(hdr.get("value", "")).strip() in ("", TOKEN_PLACEHOLDER):
                hdr["value"] = token
    return workflows


def main() -> int:
    token = load_token()
    if not token:
        print("FEHLER: Kein Service-Token gefunden (.archon_service_token / ARCHON_SERVICE_TOKEN).")
        return 1

    workflows = inject_token(load_workflows(), token)
    tmpdir = tempfile.mkdtemp(prefix="archon_n8n_")
    try:
        files = []
        for wf in workflows:
            raw = json.dumps(wf, ensure_ascii=False, indent=2).replace(TOKEN_PLACEHOLDER, token)
            name = "".join(c if c.isalnum() or c in "-_" else "_" for c in wf.get("name", "workflow"))[:60]
            path = os.path.join(tmpdir, f"{name}.json")
            # 0600 beim Anlegen UND vor dem Schreiben — kein Token in 0644-Dateien.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.close(fd)
            os.chmod(path, 0o600)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(raw)
            files.append(path)

        print(f"{len(files)} Workflow-Dateien vorbereitet (alle aktiv).")
        subprocess.run(["docker", "exec", CONTAINER, "mkdir", "-p", "/tmp/archon_import"], check=True)
        for path in files:
            subprocess.run(
                ["docker", "cp", path, f"{CONTAINER}:/tmp/archon_import/{os.path.basename(path)}"],
                check=True,
            )

        # Import als inaktiv (n8n-CLI), danach atomare Aktivierung inkl.
        # Webhook-Registrierung ueber activate_n8n_workflows.js.
        res = subprocess.run(
            ["docker", "exec", CONTAINER, "n8n", "import:workflow", "--separate", "--input=/tmp/archon_import"],
            capture_output=True, text=True,
        )
        print(res.stdout.strip() or res.stderr.strip())
        if res.returncode != 0:
            return res.returncode

        subprocess.run(
            ["docker", "cp", ACTIVATE_JS, f"{CONTAINER}:/tmp/activate_workflows.js"], check=True
        )
        act = subprocess.run(
            ["docker", "exec", CONTAINER, "node", "/tmp/activate_workflows.js"],
            capture_output=True, text=True,
        )
        print("[Activation Output]")
        print(act.stdout.strip() or act.stderr.strip())
        if act.returncode != 0:
            return act.returncode

        lst = subprocess.run(
            ["docker", "exec", CONTAINER, "n8n", "list:workflow"], capture_output=True, text=True
        )
        print("[Verifikation]")
        print(lst.stdout.strip() or lst.stderr.strip())
        return 0
    finally:
        # Tokenhaltige Temp-Dateien hinterlassen keine Spuren (auch bei Fehlern).
        shutil.rmtree(tmpdir, ignore_errors=True)
        subprocess.run(
            ["docker", "exec", CONTAINER, "rm", "-rf", "/tmp/archon_import /tmp/activate_workflows.js"],
            capture_output=True, text=True,
        )


if __name__ == "__main__":
    sys.exit(main())
