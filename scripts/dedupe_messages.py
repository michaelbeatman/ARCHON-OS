#!/usr/bin/env python3
"""
Archon CRM - Duplikat-Bereinigung (Nachrichtenverlauf)
=======================================================
Entfernt doppelte Nachrichten im nachrichtenverlauf aller Kontakte in PocketBase.
Nutzt die robuste Tiefendeduplizierung aus crm_dedupe_deep.py.

Usage:
  python scripts/dedupe_messages.py [--dry-run]
"""

import sys
import os

# Delegate directly to crm_dedupe_deep
from crm_dedupe_deep import main

if __name__ == "__main__":
    main()
