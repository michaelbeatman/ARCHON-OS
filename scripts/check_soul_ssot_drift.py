#!/usr/bin/env python3
"""Audit D15: Drift zwischen kanonischem souls/ und den Runtime-Caches melden.

Die Runtime-Bäume (.hermes/profiles, data/hermes_profiles) sind gitignorierte
Caches. Ein Runtime-SOUL gilt als synchron, wenn sein Inhalt exakt einem der
kanonischen Varianten desselben Agenten entspricht (DE/EN, Compact/Pro/Full).
So bleiben Sprach- und Moduswechsel erlaubt, aber inhaltliche Divergenz wird
erkannt.

Usage:
    python scripts/check_soul_ssot_drift.py --allow-missing   # CI
    python scripts/check_soul_ssot_drift.py                   # lokal streng
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "souls"
RUNTIMES = (ROOT / ".hermes" / "profiles", ROOT / "data" / "hermes_profiles")
SOUL_PREFIXES = ("SOUL.md", "SOUL_COMPACT.md", "SOUL_PRO.md", "SOUL_FULL.md")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-missing", action="store_true")
    args = ap.parse_args()

    if not CANON.is_dir():
        print("[DRIFT] kanonisches souls/ fehlt – bitte build_souls_ssot.py ausführen.")
        return 1

    canon_hashes: dict[str, set[str]] = {}
    for path in CANON.glob("*/SOUL*.md"):
        agent = path.parent.name
        canon_hashes.setdefault(agent, set()).add(_sha(path.read_text(encoding="utf-8").strip()))

    problems: list[str] = []
    checked = 0
    for runtime in RUNTIMES:
        if not runtime.is_dir():
            if args.allow_missing:
                print(f"[DRIFT] {runtime.relative_to(ROOT)} nicht vorhanden (CI: toleriert).")
                continue
            problems.append(f"{runtime.relative_to(ROOT)} fehlt")
            continue
        for agent_dir in sorted(p for p in runtime.iterdir() if p.is_dir() and not p.name.startswith(".")):
            agent = agent_dir.name
            known = canon_hashes.get(agent)
            if not known:
                problems.append(f"{agent_dir.relative_to(ROOT)}: kein kanonisches Profil")
                continue
            for soul in agent_dir.glob("SOUL*.md"):
                if not soul.name.startswith(SOUL_PREFIXES):
                    continue
                checked += 1
                if _sha(soul.read_text(encoding="utf-8", errors="replace").strip()) not in known:
                    problems.append(f"{soul.relative_to(ROOT)}: Inhalt nicht in souls/ kanonisch")

    print(f"[DRIFT] {checked} Runtime-SOULs gegen {len(canon_hashes)} kanonische Profile geprüft; {len(problems)} Abweichungen.")
    for item in problems[:25]:
        print("  -", item)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
