#!/usr/bin/env python3
"""Importiert die Archon-n8n-Routinen mit Service-Token, standardmäßig INAKTIV.

Das Token wird zur Laufzeit aus data/.archon_service_token gelesen und in die
HTTP-Nodes eingesetzt — es steht damit nicht im Repository.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "scripts", "n8n_routine_workflows.json")
TOKEN_FILE = os.path.join(ROOT, "data", ".archon_service_token")
CONTAINER = "n8n"


def main() -> int:
    token = ""
    if os.path.exists(TOKEN_FILE):
        token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    if not token:
        token = os.environ.get("ARCHON_SERVICE_TOKEN", "").strip()
    if not token:
        print("FEHLER: Kein Service-Token gefunden (.archon_service_token).")
        return 1

    with open(TEMPLATE, encoding="utf-8") as fh:
        workflows = json.load(fh)
    tmpdir = tempfile.mkdtemp(prefix="archon_n8n_")
    try:
        files = []
        for wf in workflows:
            raw = json.dumps(wf, ensure_ascii=False, indent=2).replace("__ARCHON_SERVICE_TOKEN__", token)
            name = "".join(c if c.isalnum() or c in "-_" else "_" for c in wf.get("name", "workflow"))[:60]
            path = os.path.join(tmpdir, f"{name}.json")
            # C: 0600 beim Anlegen UND vor dem Schreiben erzwingen — das
            # Token darf nie in einer 0644-Datei auf der Platte landen.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.close(fd)
            os.chmod(path, 0o600)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(raw)
            files.append(path)

        print(f"{len(files)} Workflow-Dateien vorbereitet.")
        subprocess.run(["docker", "exec", CONTAINER, "mkdir", "-p", "/tmp/archon_import"], check=True)
        for path in files:
            subprocess.run(["docker", "cp", path, f"{CONTAINER}:/tmp/archon_import/{os.path.basename(path)}"], check=True)

        # Standard: importiert INAKTIV (--activeState false ist Default)
        res = subprocess.run(
            ["docker", "exec", CONTAINER, "n8n", "import:workflow", "--separate", "--input=/tmp/archon_import"],
            capture_output=True, text=True,
        )
        print(res.stdout.strip() or res.stderr.strip())
        return 0 if res.returncode == 0 else res.returncode
    finally:
        # C: tokenhaltige Temp-Dateien hinterlassen keine Spuren — weder auf
        # dem Host noch im Container. Laeuft auch bei Fehlern/Exceptions.
        shutil.rmtree(tmpdir, ignore_errors=True)
        subprocess.run(
            ["docker", "exec", CONTAINER, "rm", "-rf", "/tmp/archon_import"],
            capture_output=True, text=True,
        )


if __name__ == "__main__":
    sys.exit(main())
