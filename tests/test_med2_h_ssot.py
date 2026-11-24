"""Re-Audit D02/D09/D15: statische SSOT-, Doku- und Template-Konsistenz.

Die Tests lesen nur Dateien; keine Migration, kein Replay, keine DB-Zugriffe.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE_COUNT = 71
SOUL_ARTIFACT_COUNT = 497
CREWAI_GUARDRAIL = "Keine rechtsverbindliche, medizinische, steuerliche oder investitionsrechtliche Empfehlung ohne HITL-Freigabe"


def _json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _profiles() -> dict[str, dict]:
    return {p["id"]: p for p in _json("agent_profiles.json")}


def test_profile_ssot_counts_and_ids():
    profiles = _profiles()
    roles = {r["id"]: r for r in _json("roles.json")}
    assert len(profiles) == PROFILE_COUNT, f"agent_profiles.json: {len(profiles)} Profile"
    assert len(roles) == PROFILE_COUNT, f"roles.json: {len(roles)} Rollen"
    assert set(profiles) == set(roles), "SSOT-ID-Mengen divergieren"
    assert "micha" not in profiles and "alpha" not in profiles
    assert "micha" not in roles and "alpha" not in roles


def test_all_profiles_have_role_specific_negative_scope():
    profiles = _profiles()
    missing = [pid for pid, p in profiles.items() if not str(p.get("negative_scope") or "").strip()]
    assert not missing, f"negative_scope fehlt: {missing}"


def test_roles_prompts_match_ssot_byte_for_byte():
    profiles = _profiles()
    roles = {r["id"]: r for r in _json("roles.json")}
    drifted = [
        pid
        for pid in profiles
        if profiles[pid].get("prompt") != roles[pid].get("prompt")
        or profiles[pid].get("person_name") != roles[pid].get("person_name")
    ]
    assert not drifted, f"Prompt-/Persona-Drift in roles.json: {drifted}"


def test_souls_manifest_complete_and_hashes_valid():
    manifest = _json("souls/manifest.json")
    assert len(manifest) == SOUL_ARTIFACT_COUNT, f"nur {len(manifest)} SOUL-Artefakte"
    for rel, expected in manifest.items():
        path = ROOT / "souls" / rel
        assert path.is_file(), f"fehlt: {rel}"
        # Der Generator hasht normalisierten Text; read_text() macht
        # Universal-Newline-Konvertierung (CRLF im Git-Checkout).
        content = path.read_text(encoding="utf-8")
        assert hashlib.sha256(content.encode("utf-8")).hexdigest() == expected, f"Hash abweichend: {rel}"


def test_no_orphaned_runtime_profile_caches():
    ssot_ids = set(_profiles())
    for rel in ("data/hermes_profiles", ".hermes/profiles"):
        base = ROOT / rel
        if not base.is_dir():
            continue  # Runtime-Cache nicht materialisiert — kein Drift moeglich
        dirs = {p.name for p in base.iterdir() if p.is_dir()}
        assert dirs == ssot_ids, f"{rel}: verwaiste={sorted(dirs - ssot_ids)}, fehlend={sorted(ssot_ids - dirs)}"


def test_crewai_system_prompts_have_negative_scope_and_hitl():
    files = sorted((ROOT / "templates" / "crewai").rglob("system.md"))
    assert len(files) >= 45, f"nur {len(files)} CrewAI-System-Prompts gefunden"
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert CREWAI_GUARDRAIL in text, f"keine Negativ-Abgrenzung: {path.relative_to(ROOT)}"
        assert "HITL" in text, f"kein HITL-Hinweis: {path.relative_to(ROOT)}"


def test_active_docs_have_current_profile_counts():
    doc_files = [ROOT / "README.md", ROOT / "README.de.md"]
    doc_files += sorted((ROOT / "docs" / "readme").glob("README.*.md"))
    doc_files += [
        ROOT / "docs" / "SYSTEM_HANDBUCH.md",
        ROOT / "docs" / "system" / "SYSTEM_ARCHITEKTUR_UND_AUDIT_2026.md",
        ROOT / "docs" / "system" / "MANUAL_TRANSLATION_GUIDE.md",
        ROOT / "docs" / "system" / "system_architecture_spec.json",
    ]
    stale = re.compile(r"\b(70|73)\b")
    for path in doc_files:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if stale.search(line) and "Meilenstein 70" not in line:
                raise AssertionError(f"veraltete Profilzahl {path.relative_to(ROOT)}:{number}: {line.strip()[:120]}")


def test_readmes_use_current_release_version():
    current = _json("config/version.json")["version"]
    pattern = re.compile(r"v0\.5\.7\.\d+")
    for rel in ("README.md", "README.de.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        versions = set(pattern.findall(text))
        assert versions <= {current}, f"{rel}: veraltete Release-Version {sorted(versions)}"
