#!/usr/bin/env python3
"""Audit D15 / Re-Audit R-B5: Runtime-SOUL-Caches aus souls/ regenerieren.

`check_soul_ssot_drift.py` vergleicht alle SOUL*.md der Runtime-Baeume gegen
die kanonischen Dateien in `souls/<id>/`. Bestehende, abweichende Cache-Dateien
wurden bisher nie ueberschrieben (`sync_profile_ssot.py` schreibt SOUL.md nur,
wenn sie fehlt, und kennt die Tier-Varianten gar nicht). Dieses Skript ist die
einzige kanonische Quelle fuer die Caches.

Usage:
    python scripts/sync_soul_runtime_cache.py           # regenerieren
    python scripts/sync_soul_runtime_cache.py --check   # nur Drift melden
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "souls"
RUNTIMES = (ROOT / ".hermes" / "profiles", ROOT / "data" / "hermes_profiles")
SOUL_FILES = ("SOUL.md", "SOUL_COMPACT.md", "SOUL_PRO.md", "SOUL_FULL.md",
              "SOUL_COMPACT_EN.md", "SOUL_PRO_EN.md", "SOUL_FULL_EN.md")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not CANON.is_dir():
        print("[SOUL-CACHE] kanonisches souls/ fehlt — zuerst build_souls_ssot.py ausfuehren.")
        return 1

    written = 0
    problems: list[str] = []
    for canon_dir in sorted(p for p in CANON.iterdir() if p.is_dir() and not p.name.startswith(".")):
        agent = canon_dir.name
        sources = {name: canon_dir / name for name in SOUL_FILES if (canon_dir / name).is_file()}
        if not sources:
            continue
        for runtime in RUNTIMES:
            target_dir = runtime / agent
            # data/hermes_profiles enthaelt bewusst fremde Caches; nur echte
            # SSOT-Profile werden angefasst, fremde Verzeichnisse bleiben.
            if not target_dir.is_dir():
                if runtime == ROOT / ".hermes" / "profiles":
                    target_dir.mkdir(parents=True, exist_ok=True)
                else:
                    continue
            for name, src in sources.items():
                content = src.read_text(encoding="utf-8")
                dest = target_dir / name
                if args.check:
                    if dest.is_file() and dest.read_text(encoding="utf-8") != content:
                        problems.append(str(dest.relative_to(ROOT)))
                    continue
                if not dest.is_file() or dest.read_text(encoding="utf-8") != content:
                    dest.write_text(content, encoding="utf-8", newline="\n")
                    written += 1

    if args.check:
        print(f"[SOUL-CACHE] {len(problems)} abweichende/fehlende Runtime-SOULs.")
        for item in problems[:25]:
            print("  -", item)
        return 1 if problems else 0

    print(f"[SOUL-CACHE] {written} Runtime-SOUL-Dateien aus souls/ regeneriert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
