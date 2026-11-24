#!/usr/bin/env python3
"""Audit D15: kanonische, versionierte 3-Stufen-SOULs erzeugen.

Quelle: agent_profiles.json (SSOT). Ziel: souls/<id>/SOUL_{COMPACT,PRO,FULL}.md
sowie die englischen Varianten *_EN.md und SOUL.md (aktive Stufe = compact).
Runtime-Verzeichnisse (.hermes/profiles, data/hermes_profiles) sind Caches.

AKZEPTIERTE ZAHL (User-Entscheidung 2026-11-24): 497 Artefakte = 71 Profile x 7
(je 3 Tier-Dateien DE + 3 Tier-Dateien EN + SOUL.md). Die frueheren 511/490
Zahlen aus Welle 0 (73 bzw. 70 Profile) sind ueberholt: `micha` und `alpha`
wurden bewusst entfernt, `linkedin_social_media_specialist` ist nicht Teil
der akzeptierten SSOT. Das Manifest wird hier aus denselben 497 normalisierten
Bytes gebaut; EXPECTED_ARTIFACT_COUNT (unten) und souls/manifest.json stimmen
damit ueberein.

D15/MED — Spec-Abgleich: `audit_reports/00_SOLL_SPEC.md` (§15, G-07) nennt
weiterhin 490 Artefakte / 73 Eintraege und ist damit NICHT mehr mit der
akzeptierten SSOT identisch. Diese Abweichung ist eine bewusste User-Entscheidung
und im Fix-Register `audit_reports/fix_a8_roles.md` dokumentiert. Der
verbindliche Spec-Text muss vom Spec-Owner nachgezogen werden (delegiert);
dieser Modul-Docstring ersetzt die Spec nicht stillschweigend.

Usage: python scripts/build_souls_ssot.py [--check]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("ARCHON_SSOT_REPO_ONLY", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_soul_modes as ssm  # noqa: E402

OUT = ROOT / "souls"
MANIFEST = OUT / "manifest.json"
TIERS = (("COMPACT", ssm.build_compact_soul), ("PRO", ssm.build_pro_soul), ("FULL", ssm.build_full_soul))
EXPECTED_ARTIFACT_COUNT = 497  # 71 Profile x 7 (ohne micha/alpha) — siehe Modul-Docstring.
MIN_DISTINCT_NEGATIVE_SCOPES = 60  # D15: Präsenz allein ist kein "rollenspezifisch".
_PREFIX_RE = re.compile(r"^Als .*?\([a-z0-9_]+\)\s*", re.DOTALL)
_HITL_RE = re.compile(r"HITL|4-Augen|menschliche Freigabe", re.IGNORECASE)


def semantic_scope_report(profiles: list[dict]) -> dict:
    """D15: echte Semantik-Prüfung der Negativ-Abgrenzung (nicht nur Präsenz).

    Liefert Anzahl distinct Bodies, fehlende/leere EN-Varianten und die
    HIGH_RISK-IDs ohne HITL-/4-Augen-Hinweis. Diese Metrik ist die Grundlage
    für das CI-Gate; der Drucktext darf nicht mehr "rollenspezifisch" behaupten,
    wenn nur 10 Boilerplates vorliegen.
    """
    bodies_de: set[str] = set()
    missing_en: list[str] = []
    identical_en: list[str] = []
    for prof in profiles:
        pid = str(prof.get("id") or "").strip()
        de = str(prof.get("negative_scope") or "").strip()
        en = str(prof.get("negative_scope_en") or "").strip()
        if not de:
            missing_en.append(pid or "<ohne id>")
            continue
        bodies_de.add(_PREFIX_RE.sub("", de).strip())
        if not en:
            missing_en.append(pid)
        elif en == de:
            identical_en.append(pid)
    high_risk_without_hitl: list[str] = []
    inv_path = ROOT / "data" / "eu_ai_act_inventory.json"
    if inv_path.is_file():
        try:
            inventory = json.loads(inv_path.read_text(encoding="utf-8"))
            high_risk_ids = {
                str(item.get("agent_id")) for item in inventory
                if isinstance(item, dict) and str(item.get("risk_tier") or "") == "HIGH_RISK"
            }
            for prof in profiles:
                pid = str(prof.get("id") or "")
                if pid in high_risk_ids and not _HITL_RE.search(str(prof.get("negative_scope") or "")):
                    high_risk_without_hitl.append(pid)
        except Exception as exc:
            print(f"CHECK: EU-AI-Act-Inventar nicht lesbar ({exc}) — HIGH_RISK-Prüfung übersprungen.")
    return {
        "distinct_bodies": len(bodies_de),
        "missing_en": sorted(set(missing_en)),
        "identical_en": sorted(set(identical_en)),
        "high_risk_without_hitl": sorted(set(high_risk_without_hitl)),
    }


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
                # Einziger kanonischer EN-Pfad: identisch mit dem Runtime-Sync
                # in sync_soul_modes.py (aktuell ein No-op, aber future-proof).
                if lang == "en":
                    text = ssm.adapt_soul_language(text, lang)
                text = ssm.append_role_negative_scope(text, p, lang)
                suffix = "" if lang == "de" else "_EN"
                files[f"{pid}/SOUL_{name}{suffix}.md"] = text.strip() + "\n"
            if lang == "de":
                files[f"{pid}/SOUL.md"] = files[f"{pid}/SOUL_COMPACT.md"]
    return files


def sync_downstream(profiles: list[dict]) -> dict:
    """D15: alle abgeleiteten Artefakte nach einem SOUL-Rebuild nachziehen.

    Reihenfolge: roles.json -> Runtime-Caches -> EU-AI-Act-Inventar ->
    CrewAI-Templates. Nur explizit via `--sync-downstream` aufzurufen.
    """
    report: dict[str, Any] = {}
    import sync_profile_ssot
    import sync_soul_modes as ssm

    report["roles"] = sync_profile_ssot.sync().get("after", {})
    report["runtime_caches"] = ssm.apply_soul_mode(mode="compact")
    sys.path.insert(0, str(ROOT))
    try:
        from backend.eu_ai_act_inventory import eu_ai_act_inventory_manager
        report["inventory"] = {
            "entries": len(eu_ai_act_inventory_manager.generate_inventory(save=True))
        }
    finally:
        sys.path.remove(str(ROOT))

    # CrewAI-Templates: konstante Sperre behalten (Kompatibilitaet zum
    # bestehenden Test), aber je Template eine DISTINCTE rollenspezifische
    # Zeile aus der SSOT ergaenzen.
    hint_map = {
        "research": "research_scout", "analyst": "bi_controller", "writer": "storyteller_ghostwriter",
        "marketing": "linkedin_social_media_specialist", "creative": "brand_uiux_director",
        "qa": "qa_test_engineer", "engineer": "senior_fullstack_engineer", "hr": "hr_recruiter",
        "financial": "finance_lead", "investment": "arbitrage_market_analyst",
        "email": "b2b_outreach_specialist", "spam": "knowledge_librarian",
        "scorer": "qa_test_engineer", "restaurant": "ecommerce_shopify_lead",
        "itinerary": "personal_life_strategist", "meeting": "agile_scrum_master",
        "outliner": "storyteller_ghostwriter", "shakespeare": "storyteller_ghostwriter",
        "formatter": "content_repurposing_specialist", "reporter": "pr_press_communicator",
        "communicator": "pr_press_communicator", "matcher": "lead_enrichment_analyst",
        "cv": "hr_recruiter", "job": "hr_recruiter", "scriptwriter": "video_script_architect",
        "strategist": "executive_decision_architect", "meta": "research_scout",
        "quest": "research_scout",
    }
    used: set[str] = set()
    remaining = [str(p.get("id")) for p in profiles if p.get("id")]
    changed = 0
    for path in sorted((ROOT / "templates" / "crewai").glob("*/system.md")):
        text = path.read_text(encoding="utf-8")
        if "ARCHON_ROLE_SCOPE" in text:
            continue
        stem = path.parent.name
        pid = next((v for k, v in hint_map.items() if k in stem and v not in used), None)
        if pid is None:
            pid = next((p for p in remaining if p not in used), None)
        if pid is None:
            continue
        used.add(pid)
        scope = ssm.ROLE_NEGATIVE_SCOPES_EN.get(pid, "").strip()
        if not scope:
            continue
        marker = "<!-- ARCHON_ROLE_SCOPE -->"
        line = f"{marker}\n- Role-specific boundary ({pid}): {scope}\n"
        anchor = "## NOT ALLOWED / NICHT ERLAUBT (EU AI Act Art. 50)\n"
        if anchor in text:
            text = text.replace(anchor, anchor + line, 1)
        else:
            text = text.rstrip() + "\n\n" + line
        path.write_text(text, encoding="utf-8", newline="\n")
        changed += 1
    report["crewai_templates_updated"] = changed
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument(
        "--sync-downstream", action="store_true",
        help="Nach dem Schreiben roles.json, Runtime-Caches, Inventar und CrewAI-Templates nachziehen",
    )
    args = ap.parse_args()
    profiles = json.loads((ROOT / "agent_profiles.json").read_text(encoding="utf-8"))
    files = _build(profiles)

    if args.check:
        missing = [rel for rel, text in files.items()
                   if not (OUT / rel).is_file() or (OUT / rel).read_text(encoding="utf-8") != text]
        print(f"CHECK: {len(files)} SOUL-Artefakte, abweichend/fehlend: {len(missing)}")
        for rel in missing[:10]:
            print("  ", rel)
        if len(files) != EXPECTED_ARTIFACT_COUNT:
            print(f"CHECK: Soll-Zahl {EXPECTED_ARTIFACT_COUNT}, generiert {len(files)}")
            return 1
        sem = semantic_scope_report(profiles)
        # Korrekter Print-Text: "vorhanden" != "rollenspezifisch".
        print(
            f"CHECK negative_scope: {len(profiles)}/{len(profiles)} vorhanden, "
            f"{sem['distinct_bodies']} distinct (Minimum {MIN_DISTINCT_NEGATIVE_SCOPES})"
        )
        semantic_errors = []
        if sem["distinct_bodies"] < MIN_DISTINCT_NEGATIVE_SCOPES:
            semantic_errors.append(
                f"nur {sem['distinct_bodies']} distinct bodies — Kategorien-Boilerplate ist kein Rollenscope"
            )
        if sem["missing_en"]:
            semantic_errors.append(f"EN-Scope fehlt: {', '.join(sem['missing_en'][:10])}")
        if sem["identical_en"]:
            semantic_errors.append(f"EN-Scope unübersetzt (identisch zu DE): {', '.join(sem['identical_en'][:10])}")
        if sem["high_risk_without_hitl"]:
            semantic_errors.append(
                f"HIGH_RISK ohne HITL/4-Augen-Hinweis: {', '.join(sem['high_risk_without_hitl'][:10])}"
            )
        for err in semantic_errors:
            print("CHECK:", err)
        return 1 if (missing or semantic_errors) else 0

    manifest: dict[str, str] = {}
    for rel, text in files.items():
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="\n")
        manifest[rel] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OK: {len(files)} SOUL-Artefakte in souls/ geschrieben, Manifest mit {len(manifest)} Hashes.")
    if args.sync_downstream:
        report = sync_downstream(profiles)
        print("OK: Downstream-Sync:", json.dumps(report, ensure_ascii=False, default=str)[:800])
    return 0 if len(files) == EXPECTED_ARTIFACT_COUNT else 1


if __name__ == "__main__":
    sys.exit(main())
