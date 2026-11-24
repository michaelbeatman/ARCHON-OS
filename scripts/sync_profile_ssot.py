#!/usr/bin/env python3
"""
scripts/sync_profile_ssot.py
============================
K-4: Profil-SSOT bereinigen.

Kanonische Quelle (SSOT) ist ``agent_profiles.json``. Abgeleitete Artefakte:
  * ``.hermes/profiles/<id>/profile.yaml`` + ``SOUL.md`` (Hermes-Laufzeit)
  * ``roles.json`` (Rollen-Projektion fuer Boardroom / MCP-Gateway)

Usage:
    python scripts/sync_profile_ssot.py --check   # nur Drift melden (CI)
    python scripts/sync_profile_ssot.py --check --allow-missing-hermes --json
                                                 # CI: fehlendes .hermes/profiles tolerieren
    python scripts/sync_profile_ssot.py           # abgeleitete Dateien regenerieren
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from typing import Any, Dict, List, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

PROFILES_JSON = os.path.join(WORKSPACE_DIR, "agent_profiles.json")
ROLES_JSON = os.path.join(WORKSPACE_DIR, "roles.json")
HERMES_PROFILES = os.path.join(WORKSPACE_DIR, ".hermes", "profiles")

# Felder, die roles.json als Projektion aus agent_profiles.json fuehrt.
# D15: Negativ-Abgrenzung und EN-Felder gehoeren zwingend dazu — sonst verliert
# jeder Konsument, der auf roles.json zurueckfaellt, die Rollensperren.
ROLE_FIELDS = (
    "id", "name", "name_en", "person_name", "callsign", "category", "category_en",
    "description", "description_en", "prompt", "prompt_en", "system_prompt",
    "system_prompt_en", "negative_scope", "negative_scope_en", "soul_mode",
    "skills", "status", "tools", "avatar", "avatar_url", "model", "provider",
    "reasoning_level", "is_favorite",
)


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _profile_ids() -> List[str]:
    data = _load_json(PROFILES_JSON)
    if not isinstance(data, list):
        raise RuntimeError("agent_profiles.json muss eine Liste sein.")
    return [str(p.get("id") or "").strip() for p in data if isinstance(p, dict) and p.get("id")]


def _disk_ids() -> List[str]:
    if not os.path.isdir(HERMES_PROFILES):
        return []
    return sorted(
        name for name in os.listdir(HERMES_PROFILES)
        if os.path.isdir(os.path.join(HERMES_PROFILES, name)) and not name.startswith(".")
    )


def _role_ids() -> List[str]:
    data = _load_json(ROLES_JSON)
    if isinstance(data, dict):
        data = data.get("roles", [])
    if not isinstance(data, list):
        return []
    return [str(r.get("id") or "").strip() for r in data if isinstance(r, dict) and r.get("id")]


def _projection_hashes(path: str, fields: tuple[str, ...] = ROLE_FIELDS) -> Dict[str, str]:
    """D15: Feld-Hash je ID — ID-Mengen allein erkennen keine Divergenz.

    Der Hash deckt die komplette Rollen-Projektion ab (inkl. negative_scope,
    system_prompt und EN-Felder), nicht nur den Prompt.
    """
    data = _load_json(path)
    if isinstance(data, dict):
        data = data.get("roles", [])
    if not isinstance(data, list):
        return {}
    return {
        str(r.get("id")): hashlib.sha256(
            json.dumps(
                {field: r.get(field) for field in fields},
                ensure_ascii=False, sort_keys=True, default=str,
            ).encode("utf-8")
        ).hexdigest()
        for r in data if isinstance(r, dict) and r.get("id")
    }


def _prompt_hashes(path: str) -> Dict[str, str]:
    """Rueckwaertskompatible Prompt-Hashes (prompt_mismatch im Report)."""
    return _projection_hashes(path, ("prompt",))


def detect_drift(allow_missing_hermes: bool = False) -> Dict[str, Any]:
    """Liefert einen maschinenlesbaren Drift-Report (SSOT = agent_profiles.json).

    ``allow_missing_hermes`` greift nur, wenn ``.hermes/profiles`` gar nicht
    existiert (gitignored in einem sauberen CI-Checkout): fehlende Profilordner
    zaehlen dann nicht als Drift. Rollen-Drift und verwaiste Ordner bleiben
    weiterhin hart. Existiert das Verzeichnis, ist das Verhalten unveraendert.
    """
    src = set(_profile_ids())
    hermes_present = os.path.isdir(HERMES_PROFILES)
    disk = set(_disk_ids())
    roles = set(_role_ids())
    missing_dirs = sorted(src - disk)
    orphan_dirs = sorted(disk - src)
    missing_roles = sorted(src - roles)
    stale_roles = sorted(roles - src)
    src_prompts = _prompt_hashes(PROFILES_JSON)
    role_prompts = _prompt_hashes(ROLES_JSON)
    prompt_mismatch = sorted(
        k for k in src_prompts
        if k in role_prompts and src_prompts[k] != role_prompts[k]
    )
    src_fields = _projection_hashes(PROFILES_JSON)
    role_fields = _projection_hashes(ROLES_JSON)
    field_mismatch = sorted(
        k for k in src_fields
        if k in role_fields and src_fields[k] != role_fields[k]
    )
    disk_skipped = (not hermes_present) and allow_missing_hermes
    effective_missing_dirs: List[str] = [] if disk_skipped else missing_dirs
    drift = bool(
        effective_missing_dirs or orphan_dirs or missing_roles or stale_roles
        or prompt_mismatch or field_mismatch
    )
    return {
        "ssot": "agent_profiles.json",
        "counts": {"ssot": len(src), "disk": len(disk), "roles": len(roles)},
        "missing_dirs": missing_dirs,
        "orphan_dirs": orphan_dirs,
        "missing_roles": missing_roles,
        "stale_roles": stale_roles,
        "prompt_mismatch": prompt_mismatch,
        "field_mismatch": field_mismatch,
        "disk_skipped": disk_skipped,
        "drift": drift,
    }


def _write_profile_yaml(pdir: str, prof: Dict[str, Any]) -> None:
    """Nutze den etablierten Schreiber aus sync_soul_modes, falls importierbar."""
    try:
        from scripts.sync_soul_modes import write_hermes_profile_yaml
        write_hermes_profile_yaml(pdir, prof, lang="de")
        return
    except Exception:
        pass
    # Fallback: minimaler, aber gueltiger profile.yaml-Inhalt.
    import yaml
    payload = {
        "name": prof.get("name") or prof.get("id"),
        "name_en": prof.get("name_en") or prof.get("name") or prof.get("id"),
        "person_name": prof.get("person_name") or prof.get("name") or prof.get("id"),
        "category": prof.get("category") or "1. Strategie, Führung & Lebensplanung",
        "description": prof.get("description") or "",
        "description_en": prof.get("description_en") or prof.get("description") or "",
        "role_id": prof.get("id"),
        "avatar": prof.get("avatar") or "/static/avatars/hermes_default_avatar.png",
        "avatar_url": prof.get("avatar_url") or prof.get("avatar") or "",
        "tools": list(prof.get("tools") or ["web_search"]),
        "skills": list(prof.get("skills") or []),
        "status": prof.get("status") or "active",
        "provider": prof.get("provider") or "omniroute",
        "model": prof.get("model") or "deepseek/deepseek-chat",
    }
    with open(os.path.join(pdir, "profile.yaml"), "w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)


def sync() -> Dict[str, Any]:
    """Regeneriert alle abgeleiteten Artefakte aus agent_profiles.json."""
    before = detect_drift()
    profiles = _load_json(PROFILES_JSON)
    if not isinstance(profiles, list):
        raise RuntimeError("agent_profiles.json muss eine Liste sein.")

    created_dirs: List[str] = []
    for prof in profiles:
        pid = str(prof.get("id") or "").strip()
        if not pid:
            continue
        pdir = os.path.join(HERMES_PROFILES, pid)
        os.makedirs(pdir, exist_ok=True)
        if not os.path.exists(os.path.join(pdir, "profile.yaml")):
            created_dirs.append(pid)
        _write_profile_yaml(pdir, prof)
        soul = os.path.join(pdir, "SOUL.md")
        if not os.path.exists(soul):
            with open(soul, "w", encoding="utf-8") as fh:
                fh.write(
                    f"# {prof.get('person_name') or prof.get('name') or pid}\n\n"
                    f"{prof.get('system_prompt') or prof.get('prompt') or ''}\n"
                )

    # roles.json als reine Projektion neu schreiben (mit Backup).
    role_rows: List[Dict[str, Any]] = []
    for prof in profiles:
        row = {field: prof.get(field) for field in ROLE_FIELDS if field in prof}
        # Sicherstellen, dass konsistent alle Felder vorhanden sind.
        for field in ROLE_FIELDS:
            row.setdefault(field, [] if field in ("skills", "tools") else "")
        role_rows.append(row)
    if os.path.exists(ROLES_JSON):
        shutil.copy2(ROLES_JSON, ROLES_JSON + ".ssot_backup")
    with open(ROLES_JSON + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(role_rows, fh, indent=2, ensure_ascii=False)
    os.replace(ROLES_JSON + ".tmp", ROLES_JSON)

    after = detect_drift()
    return {"before": before, "after": after, "created_dirs": created_dirs}


def main() -> int:
    parser = argparse.ArgumentParser(description="Archon OS Profile-SSOT Sync/Check")
    parser.add_argument("--check", action="store_true", help="Nur Drift melden, nichts schreiben")
    parser.add_argument("--json", action="store_true", help="Report als JSON ausgeben")
    parser.add_argument(
        "--allow-missing-hermes", action="store_true",
        help="Fehlendes .hermes/profiles in der Drift-Entscheidung ignorieren (CI)",
    )
    args = parser.parse_args()

    report = detect_drift(allow_missing_hermes=args.allow_missing_hermes) if args.check else sync()
    display = report if args.check else report.get("after", report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        c = display.get("counts", {})
        print(f"SSOT (agent_profiles.json): {c.get('ssot')}")
        print(f"  Hermes-Profile:          {c.get('disk')}")
        print(f"  roles.json:              {c.get('roles')}")
        if report.get("drift"):
            for key in ("missing_dirs", "orphan_dirs", "missing_roles", "stale_roles", "prompt_mismatch", "field_mismatch"):
                vals = report.get(key) or []
                if vals:
                    print(f"  [!] {key}: {', '.join(vals[:10])}" + (" ..." if len(vals) > 10 else ""))
        else:
            print("  [OK] Keine Drift — alle drei Quellen konsistent.")

    if args.check and report.get("drift"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
