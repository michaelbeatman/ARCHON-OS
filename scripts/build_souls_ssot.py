#!/usr/bin/env python3
"""Audit D15: kanonische, versionierte 3-Stufen-SOULs erzeugen.

Quelle: agent_profiles.json (SSOT). Ziel: souls/<id>/SOUL_{COMPACT,PRO,FULL}.md
sowie die englischen Varianten *_EN.md und SOUL.md (aktive Stufe = compact).
Runtime-Verzeichnisse (.hermes/profiles, data/hermes_profiles) sind Caches.

Usage: python scripts/build_souls_ssot.py [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_soul_modes as ssm  # noqa: E402

OUT = ROOT / "souls"
MANIFEST = OUT / "manifest.json"
TIERS = (("COMPACT", ssm.build_compact_soul), ("PRO", ssm.build_pro_soul), ("FULL", ssm.build_full_soul))


def _build(profiles: list[dict]) -> dict[str, str]:
    files: dict[str, str] = {}
    for lang in ("de", "en"):
        old_map = ssm.load_persona_sources(lang=lang)
        for prof in profiles:
            pid = str(prof.get("id") or "").strip()
            if not pid:
                continue
            p = ssm.enrich_profile_english_fields(dict(prof))
            for name, fn in TIERS:
                if name == "FULL":
                    text = fn(p, old_map, profiles, lang=lang)
                else:
                    text = fn(p, "", lang=lang)
                suffix = "" if lang == "de" else "_EN"
                files[f"{pid}/SOUL_{name}{suffix}.md"] = text.strip() + "\n"
            if lang == "de":
                files[f"{pid}/SOUL.md"] = files[f"{pid}/SOUL_COMPACT.md"]
    return files


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    profiles = json.loads((ROOT / "agent_profiles.json").read_text(encoding="utf-8"))
    files = _build(profiles)

    if args.check:
        missing = [rel for rel, text in files.items()
                   if not (OUT / rel).is_file() or (OUT / rel).read_text(encoding="utf-8") != text]
        print(f"CHECK: {len(files)} SOUL-Artefakte, abweichend/fehlend: {len(missing)}")
        for rel in missing[:10]:
            print("  ", rel)
        return 1 if missing else 0

    manifest: dict[str, str] = {}
    for rel, text in files.items():
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        manifest[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OK: {len(files)} SOUL-Artefakte in souls/ geschrieben, Manifest mit {len(manifest)} Hashes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
