#!/usr/bin/env python3
"""
scripts/validate_config.py
CLI Pre-Flight Konfigurationsprüfung für Archon OS.
Ermöglicht den schnellen Konsistenz-Check vor Releases, Reboots oder im CI/CD.
"""

import sys
import os

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_DIR)

from backend.config_validator import validator

def main():
    print("=" * 70)
    print("  Archon OS – Pre-Flight Konfigurations- & Konsistenz-Prüfung")
    print("=" * 70)

    res = validator.validate_all(strict=False)

    print(f"Status:       {'[OK] GÜLTIG' if res['valid'] else '[FEHLER] UNGÜLTIG'}")
    print(f"Fehler:       {res['error_count']}")
    print(f"Warnungen:    {res['warning_count']}")
    print("-" * 70)
    print(f"Stats:")
    for k, v in res.get("stats", {}).items():
        print(f"  - {k:<15}: {v}")

    if res["warnings"]:
        print("\nWarnungen:")
        for w in res["warnings"]:
            print(f"  [!] {w}")

    if res["errors"]:
        print("\nKritische Fehler:")
        for e in res["errors"]:
            print(f"  [X] {e}")
        print("=" * 70)
        sys.exit(1)

    print("=" * 70)
    print("Pre-Flight Check erfolgreich abgeschlossen. System ist startbereit.")
    sys.exit(0)

if __name__ == "__main__":
    main()
