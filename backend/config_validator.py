"""
backend/config_validator.py
Pre-Flight Konfigurationsprüfung & Schema-Validator für Archon OS (Pillar 6 & Resilienz).
Prüft beim Systemstart agent_profiles.json, config/teams.json, config/org_hierarchy.json,
settings.json und .env auf syntaktische und semantische Konsistenz.
"""

import os
import sys
import json
import re
from typing import Dict, Any, List, Tuple

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
            from backend.privacy_router import verify_zero_egress_config, get_privacy_config
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
                warnings.append(f"Team '{tid}': Lead-ID '{lead}' ist nicht in agent_profiles.json registriert.")

        return errors, warnings, {"total_teams": len(teams_list)}

    def validate_org_hierarchy(self, known_agent_ids: set) -> Tuple[List[str], List[str], Dict[str, Any]]:
        errors = []
        warnings = []
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

        # 3. config/teams.json
        e, w, s = self.validate_teams(known_agents)
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["teams"] = s

        # 4. config/org_hierarchy.json
        e, w, s = self.validate_org_hierarchy(known_agents)
        all_errors.extend(e)
        all_warnings.extend(w)
        stats["org_hierarchy"] = s

        # 5. .env
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
