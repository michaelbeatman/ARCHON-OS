"""
backend/config_validator.py
Pre-Flight Konfigurationsprüfung & Schema-Validator für Archon OS (Pillar 6 & Resilienz).
Prüft beim Systemstart agent_profiles.json, config/teams.json, config/org_hierarchy.json,
settings.json und .env auf syntaktische und semantische Konsistenz.
"""

import json
import os
from typing import Any, Dict, List, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class ConfigValidator:
    def __init__(self, workspace_dir: str = WORKSPACE_DIR):
        self.workspace_dir = workspace_dir

    def validate_settings(self) -> Tuple[List[str], List[str], Dict[str, Any]]:
        errors = []
        warnings = []
        path = os.path.join(self.workspace_dir, "settings.json")
        if not os.path.exists(path):
            return [f"settings.json fehlt unter {path}"], [], {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return [f"settings.json ist kein valides JSON: {e}"], [], {}

        required_sections = ["concurrency", "circuit_breaker", "fleet_and_hygiene"]
        for sec in required_sections:
            if sec not in data:
                warnings.append(f"settings.json: Empfohlener Abschnitt '{sec}' fehlt.")

        # Pruefe Concurrency-Limits
        conc = data.get("concurrency", {})
        max_workers = conc.get("max_concurrent_agents")
        if max_workers is not None and (not isinstance(max_workers, int) or max_workers < 1 or max_workers > 32):
            errors.append(f"settings.json: max_concurrent_agents muss zwischen 1 und 32 liegen (ist: {max_workers}).")

        # Pruefe Zero-Egress & Privacy-Router Konsistenz (LOCAL_ON_PREM + Hard-Block)
        try:
            from backend.privacy_router import get_privacy_config, verify_zero_egress_config
            ze_report = verify_zero_egress_config(get_privacy_config())
            for issue in ze_report.get("issues", []):
                if issue.startswith("Kritisch:"):
                    errors.append(f"privacy_router: {issue}")
                else:
                    warnings.append(f"privacy_router: {issue}")
        except Exception as ze_exc:
            warnings.append(f"privacy_router Validierung übersprungen: {ze_exc}")

        return errors, warnings, {"sections": len(data)}

    def validate_agent_profiles(self) -> Tuple[List[str], List[str], Dict[str, Any], set]:
        errors = []
        warnings = []
        path = os.path.join(self.workspace_dir, "agent_profiles.json")
        if not os.path.exists(path):
            return [f"agent_profiles.json fehlt unter {path}"], [], {}, set()

        try:
            with open(path, "r", encoding="utf-8") as f:
                profiles = json.load(f)
        except Exception as e:
            return [f"agent_profiles.json ist kein valides JSON: {e}"], [], {}, set()

        if not isinstance(profiles, list):
            return ["agent_profiles.json muss eine Liste von Profilen sein."], [], {}, set()

        seen_ids = set()
        for idx, p in enumerate(profiles):
            pid = p.get("id")
            if not pid:
                errors.append(f"Profil #{idx} hat keine 'id'.")
                continue
            if pid in seen_ids:
                errors.append(f"Doppelte Profil-ID gefunden: '{pid}'.")
            seen_ids.add(pid)

            if not p.get("name"):
                warnings.append(f"Profil '{pid}' hat keinen 'name'.")
            if not p.get("prompt") and not p.get("system_prompt"):
                warnings.append(f"Profil '{pid}' hat keinen Prompt definiert.")

        return errors, warnings, {"total_profiles": len(profiles)}, seen_ids

    def validate_teams(self, known_agent_ids: set) -> Tuple[List[str], List[str], Dict[str, Any]]:
        errors = []
        warnings = []
        path = os.path.join(self.workspace_dir, "config", "teams.json")
        if not os.path.exists(path):
            return [], [f"config/teams.json existiert nicht unter {path}"], {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return [f"config/teams.json ist kein valides JSON: {e}"], [], {}

        teams_list = data.get("teams", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for t in teams_list:
            tid = t.get("id")
            lead = t.get("lead_id")
            if lead and known_agent_ids and lead not in known_agent_ids:
                errors.append(f"Team '{tid}': Lead-ID '{lead}' ist nicht in agent_profiles.json registriert.")
            if not lead:
                warnings.append(f"Team '{tid}': kein lead_id definiert.")
            members = t.get("member_agent_ids") or []
            if known_agent_ids:
                orphan_members = [m for m in members if m not in known_agent_ids]
                if orphan_members:
                    errors.append(
                        f"Team '{tid}': unbekannte Member-IDs: {', '.join(orphan_members[:8])}"
                    )
        # H-2: Org-Chart muss Report-Linien (links) besitzen, sonst sind
        # Teams/Supervisor nur Dekoration.
        org_path = os.path.join(self.workspace_dir, "config", "org_hierarchy.json")
        if os.path.exists(org_path):
            try:
                with open(org_path, "r", encoding="utf-8") as fh:
                    org = json.load(fh)
                if not org.get("links"):
                    warnings.append("org_hierarchy.json: keine 'links' — Berichtslinien fehlen.")
            except Exception as exc:
                warnings.append(f"org_hierarchy.json nicht lesbar: {exc}")

        return errors, warnings, {"total_teams": len(teams_list)}

    def validate_org_hierarchy(self, known_agent_ids: set) -> Tuple[List[str], List[str], Dict[str, Any]]:
        errors: List[str] = []
        warnings: List[str] = []
        path = os.path.join(self.workspace_dir, "config", "org_hierarchy.json")
        if not os.path.exists(path):
            return [], [f"config/org_hierarchy.json existiert nicht unter {path}"], {}

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            return [f"config/org_hierarchy.json ist kein valides JSON: {e}"], [], {}

        nodes = data.get("nodes", [])
        links = data.get("links", [])

        node_ids = set()
        for n in nodes:
            nid = n.get("id")
            if nid:
                node_ids.add(nid)
                if known_agent_ids and nid not in known_agent_ids and nid not in ("michael_keller", "hermes_orchestrator"):
                    warnings.append(f"Organigramm: Knoten-ID '{nid}' existiert nicht im Agenten-Kader.")

        return errors, warnings, {"nodes_count": len(nodes), "links_count": len(links)}

    def validate_profile_ssot(self, known_agent_ids: set) -> Tuple[List[str], List[str], Dict[str, Any]]:
        """K-4: Drift zwischen der SSOT (agent_profiles.json) und den
        abgeleiteten Artefakten (.hermes/profiles, roles.json) erkennen.

        Nur echte Abweichungen sind Fehler; fehlt ein komplettes abgeleitetes
        Verzeichnis (z. B. in isolierten Test-Workspaces), genuegt eine
        Warnung, damit der Validator nicht grundlos alle Checks sperrt.
        """
        errors: List[str] = []
        warnings: List[str] = []
        ssot_ids = set(known_agent_ids)

        # 1. Hermes-Profilordner
        profiles_dir = os.path.join(self.workspace_dir, ".hermes", "profiles")
        if not os.path.isdir(profiles_dir):
            warnings.append(".hermes/profiles fehlt — abgeleitete Profile nicht pruefbar.")
        else:
            disk_ids = {
                name for name in os.listdir(profiles_dir)
                if os.path.isdir(os.path.join(profiles_dir, name)) and not name.startswith(".")
            }
            missing_dirs = sorted(ssot_ids - disk_ids)
            orphan_dirs = sorted(disk_ids - ssot_ids)
            if missing_dirs:
                errors.append(
                    f"Profil-SSOT: fehlende Hermes-Profile: {', '.join(missing_dirs[:8])}"
                    + (" ..." if len(missing_dirs) > 8 else "")
                    + " (python scripts/sync_profile_ssot.py)"
                )
            if orphan_dirs:
                errors.append(
                    f"Profil-SSOT: verwaiste Hermes-Profile: {', '.join(orphan_dirs[:8])}"
                    + (" ..." if len(orphan_dirs) > 8 else "")
                )

        # 2. roles.json (abgeleitete Rollen-Projektion)
        roles_path = os.path.join(self.workspace_dir, "roles.json")
        if not os.path.exists(roles_path):
            warnings.append("roles.json fehlt — Rollen-Projektion nicht pruefbar.")
        else:
            try:
                with open(roles_path, "r", encoding="utf-8") as fh:
                    roles = json.load(fh)
                if isinstance(roles, dict):
                    roles = roles.get("roles", [])
                role_ids = {
                    str(r.get("id")) for r in roles
                    if isinstance(r, dict) and r.get("id")
                }
                missing_roles = sorted(ssot_ids - role_ids)
                stale_roles = sorted(role_ids - ssot_ids)
                if missing_roles:
                    errors.append(
                        f"Profil-SSOT: roles.json fehlen {len(missing_roles)} Rollen: "
                        + ", ".join(missing_roles[:8]) + (" ..." if len(missing_roles) > 8 else "")
                    )
                if stale_roles:
                    errors.append(
                        f"Profil-SSOT: roles.json enthält veraltete Rollen: {', '.join(stale_roles[:8])}"
                    )
                # P4/D15: Auch Feld-/Prompt-Drift in roles.json hart als Fehler pruefen.
                ssot_path = os.path.join(self.workspace_dir, "agent_profiles.json")
                if os.path.exists(ssot_path):
                    try:
                        from scripts.sync_profile_ssot import _projection_hashes as _proj_fn
                    except Exception:
                        _proj_fn = None  # type: ignore[assignment]
                    if _proj_fn is not None:
                        ssot_hashes = _proj_fn(ssot_path)
                        role_hashes = _proj_fn(roles_path)
                        field_mismatch = sorted(
                            rid for rid in (set(ssot_hashes) & set(role_hashes))
                            if ssot_hashes[rid] != role_hashes[rid]
                        )
                    else:
                        with open(ssot_path, "r", encoding="utf-8") as sfh:
                            ssot_list = json.load(sfh)
                        ssot_by_id = {
                            str(p.get("id")): p for p in (ssot_list if isinstance(ssot_list, list) else [])
                            if isinstance(p, dict) and p.get("id")
                        }
                        roles_by_id = {
                            str(r.get("id")): r for r in roles
                            if isinstance(r, dict) and r.get("id")
                        }
                        field_mismatch = sorted(
                            rid for rid in (set(ssot_by_id) & set(roles_by_id))
                            if ssot_by_id[rid].get("prompt") != roles_by_id[rid].get("prompt")
                        )
                    if field_mismatch:
                        errors.append(
                            f"Profil-SSOT: roles.json Feld-/Prompt-Drift bei {len(field_mismatch)} Rollen: "
                            + ", ".join(field_mismatch[:8])
                            + (" ..." if len(field_mismatch) > 8 else "")
                        )
            except Exception as exc:
                errors.append(f"Profil-SSOT: roles.json nicht lesbar: {exc}")

        stats = {
            "ssot_profiles": len(ssot_ids),
        }
        return errors, warnings, stats

    def validate_env_file(self) -> Tuple[List[str], List[str], Dict[str, Any]]:
        errors = []
        warnings = []
        path = os.path.join(self.workspace_dir, ".env")
        if not os.path.exists(path):
            return [], [".env-Datei fehlt im Projekt-Root (nutze .env.example als Vorlage)."], {}

        env_vars = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        env_vars[k.strip()] = v.strip()
        except Exception as e:
            return [f"Fehler beim Lesen der .env: {e}"], [], {}

        # Pruefe Ports
        if "PORT" in env_vars:
            try:
                p = int(env_vars["PORT"])
                if p < 1 or p > 65535:
                    errors.append(f".env: PORT {p} ist ungültig.")
            except ValueError:
                errors.append(f".env: PORT '{env_vars['PORT']}' ist keine Zahl.")

        if "HOST" in env_vars and not env_vars["HOST"]:
            warnings.append(".env: HOST ist leer.")

        return errors, warnings, {"configured_env_vars": len(env_vars)}

    def validate_all(self, strict: bool = False) -> Dict[str, Any]:
        """Führt den kompletten Pre-Flight-Check durch."""
        all_errors = []
        all_warnings = []
        stats = {}

        # 1. settings.json
        e, w, s = self.validate_settings()
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["settings"] = s

        # 2. agent_profiles.json
        e, w, s, known_agents = self.validate_agent_profiles()
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["profiles"] = s

        # 3. Profil-SSOT (K-4): agent_profiles.json vs. Hermes-Profile vs. roles.json
        e, w, s = self.validate_profile_ssot(known_agents)
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["profile_ssot"] = s

        # 4. config/teams.json
        e, w, s = self.validate_teams(known_agents)
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["teams"] = s

        # 5. config/org_hierarchy.json
        e, w, s = self.validate_org_hierarchy(known_agents)
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["org_hierarchy"] = s

        # 6. .env
        e, w, s = self.validate_env_file()
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["env"] = s

        is_valid = len(all_errors) == 0
        result = {
            "valid": is_valid,
            "error_count": len(all_errors),
            "warning_count": len(all_warnings),
            "errors": all_errors,
            "warnings": all_warnings,
            "stats": stats
        }

        if strict and not is_valid:
            raise RuntimeError(f"Pre-Flight Konfigurationsprüfung fehlgeschlagen: {all_errors}")

        return result

# Globales Singleton
validator = ConfigValidator()
