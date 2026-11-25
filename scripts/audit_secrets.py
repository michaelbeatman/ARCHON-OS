#!/usr/bin/env python3
"""
scripts/audit_secrets.py
Zentraler Pre-Commit- und CI-Audit-Scanner fuer Archon OS.
Verhindert das versehentliche Committen oder Pushen von sensiblen Zugangsdaten,
API-Keys, Token-Dateien und Passwoertern in das Git-Repository.

Rotation (D04/MED):GitHub 90 d, Telegram 180 d, Provider 90 d. Das Register
enthält NUR Env-Key-Namen und ISO-Datumsangaben — niemals echte Secret-Werte;
Ausgaben zeigen ausschliesslich Key-Name, Klasse, Alter und Frist.
"""

import sys
import os
import re
import subprocess
import argparse
import datetime
import json
from typing import List, Tuple, Optional

_WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROTATION_REGISTER_FILE = os.environ.get(
    "ARCHON_SECRETS_ROTATION_REGISTER",
    os.path.join(_WORKSPACE_DIR, "config", "secrets_rotation.json"),
)
ROTATION_LIMITS_DAYS = {"github": 90, "telegram": 180, "provider": 90}

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
    # G2: Admin-Erstartpasswort und Passkey-HITL-Stores niemals committen.
    r"^\.archon_initial_admin_password(?:\..*)?$",
    r"^passkey_hitl\.json(?:\..*)?$",
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
    "tests/test_zero_egress_and_dispatch_audit.py",
    "docs/system/SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md",
    "docs/security/SECRETS_MANAGEMENT_UND_ROTATION.md",
    # D04/H-04-2: Auditberichte zitieren den kompromittierten Konstanten-
    # Wert als Beleg. Das ist Dokumentation, kein Code-Einsatz.
    "audit_reports/domain_04.md",
    "audit_reports/_archiv_2026-11-24_pre_audit/_archiv_2026-11-24_run5/2026-11-24_d04_security.md",
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
    # Eigene Tokenformate (Audit 23.11.2026) — vorher nicht erkannt.
    ("Archon Live Token", re.compile(r'\barchon_live_[a-zA-Z0-9_\-]{16,}\b')),
    ("Archon HITL Proof", re.compile(r'\btok_[a-zA-Z0-9_\-]{20,}\b')),
    # D04/H-04-2: hartcodierte API-Key-Pepper/Salts sind kompromittiert.
    ("Hardcodierter API-Key-Pepper/Salt", re.compile(
        r'\bARCHON_OS_API_KEY_SALT_[0-9A-Z_]+'
        r'|\b(?:KEY_SALT|LEGACY_KEY_SALT)\s*=\s*["\'][^"\']{8,}["\']'
    )),
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
        res = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                             capture_output=True, text=True, check=True)
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception as exc:
        # Fail-closed: ein Git-Fehler darf den Zero-Leak-Gate nicht grün machen.
        raise RuntimeError(f"[Audit-Secrets] Git-Index nicht lesbar: {exc}") from exc

def get_tracked_files() -> List[str]:
    """Gibt alle von Git getrackten Dateien zurueck."""
    try:
        res = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True)
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception as exc:
        raise RuntimeError(f"[Audit-Secrets] Git-Tracking nicht lesbar: {exc}") from exc

def check_rotation(register_path: str = ROTATION_REGISTER_FILE, now: Optional[datetime.datetime] = None) -> List[str]:
    """Prueft Alter/Rotationsfristen. Gibt nur Key-Namen und Alter zurueck."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not os.path.isfile(register_path):
        return [
            f"ROTATION REGISTER FEHLT: {register_path} — "
            "GitHub 90 / Telegram 180 / Provider 90 Tage nicht nachweisbar."
        ]
    try:
        with open(register_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        return [f"ROTATION REGISTER UNLESBAR: {type(exc).__name__} — Fristen nicht nachweisbar."]
    entries = data.get("credentials") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return ["ROTATION REGISTER UNGUELTIG: 'credentials' fehlt."]
    findings: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            findings.append("ROTATION REGISTER UNGUELTIG: Eintrag kein Objekt.")
            continue
        key_name = str(entry.get("env_key") or entry.get("key") or "UNKNOWN")
        cls = str(entry.get("class") or "").strip().lower()
        if cls not in ROTATION_LIMITS_DAYS:
            findings.append(f"ROTATION KLASSE UNBEKANNT: {key_name} ({cls})")
            continue
        raw_date = str(entry.get("last_rotated_at") or "").strip()
        try:
            rotated = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            if rotated.tzinfo is None:
                rotated = rotated.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            findings.append(f"ROTATION DATUM UNGUELTIG: {key_name} ({cls})")
            continue
        age_days = (now - rotated).days
        limit = ROTATION_LIMITS_DAYS[cls]
        if age_days > limit:
            findings.append(
                f"ROTATION UEBERFAELLIG: {key_name} ({cls}) — {age_days} Tage, "
                f"Frist {limit} Tage."
            )
    return findings


def main():
    parser = argparse.ArgumentParser(description="Archon OS Secrets & Credentials Audit Scanner")
    parser.add_argument("--staged", action="store_true", help="Nur aktuell im Git gestagte Dateien pruefen (Pre-Commit)")
    parser.add_argument("--all", action="store_true", help="Alle getrackten Dateien im gesamten Repository pruefen")
    parser.add_argument("--file", type=str, help="Eine einzelne Datei pruefen")
    parser.add_argument("--rotation", action="store_true", help="Rotationsregister/Alter pruefen (GitHub 90/Telegram 180/Provider 90 Tage)")
    args = parser.parse_args()

    files_to_check = []
    if args.file:
        files_to_check = [args.file]
    elif args.all:
        files_to_check = get_tracked_files()
    else:
        # Default: staged files (Pre-Commit)
        files_to_check = get_staged_files()

    # Rotation wird bei --rotation und --all (Full-Audit) geprueft.
    rotation_findings = (
        check_rotation() if (args.rotation or args.all) else []
    )

    if not files_to_check and not (args.rotation or rotation_findings):
        print("[Audit-Secrets] Keine relevanten Dateien zur Pruefung ausgewaehlt.")
        sys.exit(0)

    violations = list(rotation_findings)

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
