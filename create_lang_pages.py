#!/usr/bin/env python3
"""DEPRECATED - bitte ``python scripts/build_site_i18n.py`` verwenden.

Dieses Skript war die alte, kaputte Quelle der Sprachseiten:

* Es erzeugte für 9 Sprachen englische Redirect-Stubs statt Übersetzungen.
* Die ``replacements``-Map passte nicht mehr zum heutigen ``site/index.html``,
  sodass beim Ausführen fast alle Texte wieder auf Englisch zurückfielen.
* Die hreflang-Tags wurden nie in die tatsächlichen Seiten geschrieben.

Der Aufruf wird jetzt sicher an den neuen Generator delegiert, damit ein alter
Befehl oder ein altes Build-Skript die Übersetzungen nicht mehr zerstört.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GENERATOR = ROOT / "scripts" / "build_site_i18n.py"


def main() -> int:
    print("create_lang_pages.py ist veraltet - delegiere an scripts/build_site_i18n.py")
    return subprocess.call([sys.executable, str(GENERATOR), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
