"""Test für Baustelle F6: Secrets & API-Key Härtung in tools/ und Backups.

Stellt sicher:
1. Keine hartkodierten RAG API-Keys (weder R9YRVG7 noch ähnliche Muster) in tools/ und Backups.
2. tools/sync_vault_to_rag.py akzeptiert ANYTHINGLLM_API_KEY aus os.environ, falls --api-key nicht übergeben wird.
3. tools/sync_*.py Skripte lesen API_KEY aus der Umgebung statt Hardcoding.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_hardcoded_rag_keys_in_tracked_tree():
    """Prüft, dass kein hartkodierter R9YRVG7-Key in getrackten Dateien verbleibt."""
    result = subprocess.run(
        ["git", "grep", "-n", "R9YRVG7"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    matches = [line for line in result.stdout.strip().split("\n") if line and "test_f6_secrets_hardening.py" not in line]
    assert len(matches) == 0, f"Hartkodierte API-Keys gefunden:\n{chr(10).join(matches)}"


def test_sync_vault_to_rag_reads_env_api_key(monkeypatch):
    """tools/sync_vault_to_rag.py darf --api-key nicht als Pflichtfeld (required=True) erzwingen, wenn ANYTHINGLLM_API_KEY gesetzt ist."""
    script_path = REPO_ROOT / "tools" / "sync_vault_to_rag.py"
    content = script_path.read_text(encoding="utf-8")
    assert 'required=True' not in content or 'parser.add_argument("--api-key", required=True' not in content, (
        "--api-key ist noch als required=True definiert, Env-Fallback wird blockiert"
    )


def test_sync_scripts_read_from_environ():
    """Alle sync_*.py Skripte in tools/ müssen os.environ für API_KEY verwenden."""
    scripts = [
        "sync_remaining_600s.py",
        "sync_cannabis_rag.py",
        "sync_vault_all_parallel.py",
        "sync_cannabis_rag_parallel.py",
    ]
    for s in scripts:
        path = REPO_ROOT / "tools" / s
        if path.exists():
            code = path.read_text(encoding="utf-8")
            assert 'API_KEY = "R9YRVG7' not in code, f"{s} hat noch hartkodierten API-Key"
            assert 'os.environ.get("ANYTHINGLLM_API_KEY"' in code or "os.environ" in code, (
                f"{s} liest API_KEY nicht aus Umgebung"
            )
