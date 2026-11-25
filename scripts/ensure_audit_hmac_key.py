#!/usr/bin/env python3
"""Stellt die drei getrennten Audit-HMAC-Secrets in .env sicher.

Audit 23.11.2026: der Startup-Check bricht seit der Sanierung bei nicht-
lokaler Bindung/Auth-Zwang ohne HMAC-Key hart ab. D05 (H-05-1/MED): die
Execution-Receipt-Kette und der externe Anker brauchen EIGENE Keys — ein
kompromittierter Audit-Key darf nicht beide anderen Ketten mitkompromittieren.
Dieses Skript erzeugt alle fehlenden Keys einmalig und idempotent
(ein vorhandener Key wird niemals überschrieben).

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

# (Env-Name, Zweck) — drei getrennte Secrets, kein Geteilter Key.
KEY_SPECS = (
    ("ARCHON_AUDIT_HMAC_KEY", "zentrale Audit-Kette"),
    ("ARCHON_RECEIPT_HMAC_KEY", "Execution-Receipt-Kette"),
    ("ARCHON_AUDIT_ANCHOR_KEY", "externer Audit-Anker"),
)
# Rückwärtskompatible Konstante für alte Aufrufer.
KEY_NAME = KEY_SPECS[0][0]


def _key_re(name: str) -> re.Pattern:
    return re.compile(rf"^\s*{re.escape(name)}\s*=\s*(.*?)\s*$", re.MULTILINE)


def read_env() -> str:
    return ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.is_file() else ""


def current_key(env_text: str, name: str) -> str:
    m = _key_re(name).search(env_text)
    if not m:
        return ""
    value = m.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.strip()


def _present(env_text: str, name: str) -> str:
    """ENV-Variable der Umgebung hat Vorrang (Docker-Secrets etc.)."""
    return os.environ.get(name, "").strip() or current_key(env_text, name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Nur prüfen, nichts schreiben")
    args = parser.parse_args()

    env_text = read_env()
    missing: list[tuple[str, str]] = []
    for name, _purpose in KEY_SPECS:
        if not _present(env_text, name):
            missing.append((name, _purpose))

    if args.check:
        if missing:
            for name, purpose in missing:
                print(f"[FEHLER] {name} ({purpose}) fehlt in {ENV_FILE}.", file=sys.stderr)
            return 1
        for name, purpose in KEY_SPECS:
            print(f"[OK] {name} ({purpose}) vorhanden.")
        return 0

    if not missing:
        for name, purpose in KEY_SPECS:
            print(f"[OK] {name} ({purpose}) vorhanden ({len(_present(env_text, name))} Zeichen).")
        return 0

    lines: list[str] = []
    if env_text and not env_text.endswith("\n"):
        env_text += "\n"
    for name, purpose in missing:
        generated = secrets.token_hex(32)
        lines.append(f"{name}={generated}")
        print(f"[OK] {name} ({purpose}) erzeugt und in .env gespeichert.")
    ENV_FILE.write_text(env_text + "\n".join(lines) + "\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass  # Windows: ACL-Härtung erfolgt durch utils/secret_files.py
    print("[HINWEIS] Archon OS neu starten, damit die Keys im Prozess sichtbar sind.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
