#!/usr/bin/env python3
"""
scripts/audit_secrets.py
Zentraler Pre-Commit- und CI-Audit-Scanner fuer Archon OS.
Verhindert das versehentliche Committen oder Pushen von sensiblen Zugangsdaten,
API-Keys, Token-Dateien und Passwoertern in das Git-Repository.
"""

import sys
import os
import re
import subprocess
import argparse
from typing import List, Tuple

# Dateinamen und Pfade, die NIEMALS im Git landen duerfen
FORBIDDEN_FILE_PATTERNS = [
    r"^\.env$",
    r"^\.env\.(?!example$)[a-zA-Z0-9_\-]+$",
    r".*token.*\.json$",
    r"credentials\.json$",
    r".*\.pem$",
    r".*\.key$",
    r".*\.pfx$",
    r".*\.p12$",
    r".*id_rsa.*",
    r".*id_ed25519.*",
    r".*\.kdbx$",
    r".*API-Keys\.md$",
]

# Zulaessige Ausnahmen (Dateien, die Mustersuchbegriffe oder Dummy-Werte enthalten)
SAFE_FILE_EXCEPTIONS = {
    ".gitignore",
    ".env.example",
    "backend/secret_masker.py",
    "scripts/audit_secrets.py",
    "local_security_guard.py",
    "tests/test_security_and_validation.py",
    "tests/test_m30_onboarding_wizard.py",
    "docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md",
    "docs/security/SECRETS_MANAGEMENT_UND_ROTATION.md",
}

SAFE_FOLDER_EXCEPTIONS = [
    "templates/fabric/",
]

# Regex-Pruefmuster fuer sensible Inhalte in Dateien
CONTENT_SECRET_PATTERNS = [
    ("OpenAI / OpenRouter API Key", re.compile(r'\bsk-[a-zA-Z0-9_\-]{20,}\b')),
    ("Anthropic API Key", re.compile(r'\bsk-ant-[a-zA-Z0-9_\-]{20,}\b')),
    ("GitHub Personal Access Token (Legacy)", re.compile(r'\bghp_[a-zA-Z0-9]{36}\b')),
    ("GitHub Fine-grained PAT", re.compile(r'\bgithub_pat_[a-zA-Z0-9_]{50,}\b')),
    ("Telegram Bot Token", re.compile(r'\b\d{8,10}:[a-zA-Z0-9_-]{35}\b')),
    ("Private Key Header", re.compile(r'-----BEGIN [A-Z ]+PRIVATE KEY-----')),
    ("JWT Token", re.compile(r'\beyJ[a-zA-Z0-9_\-]{15,}\.eyJ[a-zA-Z0-9_\-]{15,}\.[a-zA-Z0-9_\-]{15,}\b')),
    ("Verbindungsstring mit Passwort", re.compile(r'://[a-zA-Z0-9_\.\-]+:[^@\s]{6,}@[a-zA-Z0-9_\.\-]+')),
]

def is_forbidden_filename(filename: str) -> bool:
    basename = os.path.basename(filename)
    
    # 1. Spezifische Dateinamen pruefen
    for pattern in FORBIDDEN_FILE_PATTERNS:
        if re.search(pattern, basename, re.IGNORECASE):
            return True
    return False

def scan_file_content(filepath: str) -> List[Tuple[int, str, str]]:
    """Scannt den Inhalt einer Datei zeilenweise nach Mustern. Gibt (zeilennummer, mustername, zensierter_fund) zurueck."""
    findings = []
    norm_path = filepath.replace("\\", "/")
    
    # Ausnahmen ueberspringen
    for exc in SAFE_FILE_EXCEPTIONS:
        if norm_path.endswith(exc):
            return []
    for fld in SAFE_FOLDER_EXCEPTIONS:
        if fld in norm_path:
            return []

    # Nur Textdateien pruefen; binaere ueberspringen
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for idx, line in enumerate(f, 1):
                # Dummy/Placeholder Werte ignorieren
                line_lower = line.lower()
                if any(x in line_lower for x in ("your_", "example", "placeholder", "dummy", "test-key", "mock", "[geschützt", "[geschuetzt", "paperclip:paperclip@127.0.0.1")):
                    continue
                for name, regex in CONTENT_SECRET_PATTERNS:
                    match = regex.search(line)
                    if match:
                        found_str = match.group(0)
                        # Leicht maskieren fuer Logging
                        masked = found_str[:4] + "..." + found_str[-4:] if len(found_str) > 8 else "***"
                        findings.append((idx, name, masked))
    except Exception as e:
        # Falls unlesbar oder Verzeichnis
        pass

    return findings

def get_staged_files() -> List[str]:
    """Gibt die Liste aller aktuell gestagten Dateien im Git-Index zurueck."""
    try:
        res = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                             capture_output=True, text=True, check=True)
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return []

def get_tracked_files() -> List[str]:
    """Gibt alle von Git getrackten Dateien zurueck."""
    try:
        res = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return []

def main():
    parser = argparse.ArgumentParser(description="Archon OS Secrets & Credentials Audit Scanner")
    parser.add_argument("--staged", action="store_true", help="Nur aktuell im Git gestagte Dateien pruefen (Pre-Commit)")
    parser.add_argument("--all", action="store_true", help="Alle getrackten Dateien im gesamten Repository pruefen")
    parser.add_argument("--file", type=str, help="Eine einzelne Datei pruefen")
    args = parser.parse_args()

    files_to_check = []
    if args.file:
        files_to_check = [args.file]
    elif args.all:
        files_to_check = get_tracked_files()
    else:
        # Default: staged files (Pre-Commit)
        files_to_check = get_staged_files()

    if not files_to_check:
        print("[Audit-Secrets] Keine relevanten Dateien zur Pruefung ausgewaehlt.")
        sys.exit(0)

    violations = []

    for fpath in files_to_check:
        # 1. Dateinamen-Check
        if is_forbidden_filename(fpath):
            violations.append(f"FORBIDDEN FILE: '{fpath}' darf NIEMALS im Git committed werden!")
            continue

        # 2. Inhalts-Check (nur wenn Datei physisch existiert)
        if os.path.isfile(fpath):
            content_findings = scan_file_content(fpath)
            for line_no, pattern_name, masked_val in content_findings:
                violations.append(f"SECRET IN FILE: '{fpath}' Zeile {line_no}: {pattern_name} gefunden ({masked_val})")

    if violations:
        print("\n" + "=" * 70)
        print("  [SICHERHEITS-STOPP] KRITISCHE ZUGANGSDATEN / SECRETS ERKANNT!")
        print("=" * 70)
        for v in violations:
            print(f"  [X] {v}")
        print("=" * 70)
        print("Commit und Push wurden blockiert.")
        print("Bitte entferne sensible Daten oder fuege die Datei zur .gitignore hinzu.")
        print("=" * 70 + "\n")
        sys.exit(1)

    print(f"[Audit-Secrets] OK: {len(files_to_check)} Datei(en) geprueft - keine Secrets gefunden.")
    sys.exit(0)

if __name__ == "__main__":
    main()
