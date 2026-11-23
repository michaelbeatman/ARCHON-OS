#!/usr/bin/env python3
"""Stellt sicher, dass ARCHON_AUDIT_HMAC_KEY in .env gesetzt ist.

Audit 23.11.2026: der Startup-Check bricht seit der Sanierung bei nicht-
lokaler Bindung/Auth-Zwang ohne HMAC-Key hart ab. Bestehende Installationen
haben den Key oft noch nicht — dieses Skript erzeugt ihn einmalig und
idempotent (ein Key wird niemals überschrieben).

Usage:
    python scripts/ensure_audit_hmac_key.py            # erzeugt falls nötig
    python scripts/ensure_audit_hmac_key.py --check     # nur prüfen (CI)
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
KEY_NAME = "ARCHON_AUDIT_HMAC_KEY"
KEY_RE = re.compile(rf"^\s*{KEY_NAME}\s*=\s*(.*?)\s*$", re.MULTILINE)


def read_env() -> str:
    return ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.is_file() else ""


def current_key(env_text: str) -> str:
    m = KEY_RE.search(env_text)
    if not m:
        return ""
    value = m.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Nur prüfen, nichts schreiben")
    args = parser.parse_args()

    env_text = read_env()
    # ENV-Variable der Umgebung hat Vorrang (Docker-Secrets etc.).
    env_value = os.environ.get(KEY_NAME, "").strip()
    key = env_value or current_key(env_text)

    if key:
        print(f"[OK] {KEY_NAME} vorhanden ({len(key)} Zeichen).")
        return 0

    if args.check:
        print(f"[FEHLER] {KEY_NAME} fehlt in {ENV_FILE}.", file=sys.stderr)
        return 1

    generated = secrets.token_hex(32)
    line = f"{KEY_NAME}={generated}\n"
    if env_text and not env_text.endswith("\n"):
        env_text += "\n"
    ENV_FILE.write_text(env_text + line, encoding="utf-8")
    try:
        ENV_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass  # Windows: ACL-Härtung erfolgt durch utils/secret_files.py
    print(f"[OK] {KEY_NAME} erzeugt und in .env gespeichert (0644->0600).")
    print("[HINWEIS] Archon OS neu starten, damit der Startup-Check den Key sieht.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
