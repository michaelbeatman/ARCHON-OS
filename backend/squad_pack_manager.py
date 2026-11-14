"""
backend/squad_pack_manager.py
=============================
M51 — Portabler „Squad-Blueprint“-Paketmanager (.archonpack Import/Export).

Bündelt komplette Fachabteilungen als signiertes/geprüftes ZIP-Archiv (.archonpack):
- manifest.json (Version, Metadaten, SHA-256 Checksummen)
- agents/roles.json & agent_profiles.json (Secret-bereinigt) + 3-Stufen-SOUL.md
- skills/ (zugehörige Skill-Dateien)
- boardroom/frameworks.json
- prompts/templates.json (aus prompt_studio_catalog.json)
- n8n/ (zugehörige Workflow-JSONs)
"""

from __future__ import annotations

import datetime
import hashlib
import io
import json
import os
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from archon.core.runtime import WORKSPACE_DIR

PACK_FORMAT_VERSION = "1.0"
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB Schutz vor Zip-Bomben
SECRET_KEYS = ("api_key", "bot_token", "token", "password", "secret", "private_key")


def _scrub_secrets(obj: Any) -> Any:
    """Entfernt potenzielle Secret-Felder rekursiv vor dem Export."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if any(sk == kl or kl.endswith(f"_{sk}") for sk in SECRET_KEYS) and not kl.endswith("_env"):
                cleaned[k] = ""
            else:
                cleaned[k] = _scrub_secrets(v)
        return cleaned
    if isinstance(obj, list):
        return [_scrub_secrets(x) for x in obj]
    return obj


def _is_safe_zip_member(name: str) -> bool:
    if not name or name.startswith("/") or name.startswith("\\"):
        return False
    norm = os.path.normpath(name)
    if norm.startswith("..") or os.path.isabs(norm):
        return False
    parts = name.replace("\\", "/").split("/")
    if ".." in parts:
        return False
    return True


class SquadPackManager:
    """Export, Inspektion & Import portabler .archonpack Squad-Blueprints."""

    def __init__(self, workspace_dir: str = WORKSPACE_DIR) -> None:
        self.workspace_dir = os.path.realpath(workspace_dir)

    def _load_json_safe(self, rel_path: str, default: Any) -> Any:
        fpath = os.path.join(self.workspace_dir, rel_path)
        if not os.path.exists(fpath):
            return default
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default

    def _save_json_atomic(self, rel_path: str, data: Any) -> None:
        fpath = os.path.join(self.workspace_dir, rel_path)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        tmp = f"{fpath}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, fpath)

    def list_available_domains(self) -> List[Dict[str, Any]]:
        """Listet exportierbare Domänen inkl. Agenten-Anzahl auf."""
        roles_raw = self._load_json_safe("roles.json", [])
        items = roles_raw if isinstance(roles_raw, list) else roles_raw.get("roles", list(roles_raw.values())) if isinstance(roles_raw, dict) else []
        counts: Dict[str, int] = {}
        for r in items:
            if not isinstance(r, dict):
                continue
            dom = str(r.get("domain") or r.get("category") or "general").strip()
            counts[dom] = counts.get(dom, 0) + 1
        return [{"domain": k, "agent_count": v} for k, v in sorted(counts.items())]

    def export_pack(
        self,
        name: str,
        domain: Optional[str] = None,
        agent_ids: Optional[List[str]] = None,
        include_prompts: bool = True,
        include_n8n: bool = True,
        author: str = "Archon OS",
        description: str = "",
    ) -> Tuple[bytes, Dict[str, Any]]:
        """Erstellt ein .archonpack ZIP-Archiv im Speicher und liefert (zip_bytes, manifest)."""
        domain_l = (domain or "").strip().lower()
        target_ids = set(agent_ids or [])

        # 1. Rollen filtern
        roles_raw = self._load_json_safe("roles.json", [])
        all_roles = roles_raw if isinstance(roles_raw, list) else roles_raw.get("roles", list(roles_raw.values())) if isinstance(roles_raw, dict) else []
        selected_roles: List[Dict[str, Any]] = []
        selected_ids: set = set()
        for r in all_roles:
            if not isinstance(r, dict):
                continue
            rid = str(r.get("id") or r.get("role_id") or "")
            rdom = str(r.get("domain") or r.get("category") or "").lower()
            if target_ids:
                if rid in target_ids:
                    selected_roles.append(_scrub_secrets(r))
                    selected_ids.add(rid)
            elif domain_l:
                if domain_l in rdom:
                    selected_roles.append(_scrub_secrets(r))
                    selected_ids.add(rid)
            else:
                selected_roles.append(_scrub_secrets(r))
                selected_ids.add(rid)

        # 2. Agent-Profile filtern
        profiles_raw = self._load_json_safe("agent_profiles.json", {})
        selected_profiles: Dict[str, Any] = {}
        if isinstance(profiles_raw, dict):
            for pid, pval in profiles_raw.items():
                if not selected_ids or pid in selected_ids:
                    selected_profiles[pid] = _scrub_secrets(pval)

        # 3. 3-Stufen-SOUL.md Dateien einsammeln (falls vorhanden)
        soul_files: Dict[str, str] = {}
        for soul_root_rel in ("hermes_profiles", "agent_workspace/souls", "souls"):
            soul_root = os.path.join(self.workspace_dir, soul_root_rel)
            if not os.path.isdir(soul_root):
                continue
            for root, _, files in os.walk(soul_root):
                for fname in files:
                    if not fname.endswith(".md"):
                        continue
                    fpath = os.path.join(root, fname)
                    rel_sub = os.path.relpath(fpath, soul_root).replace("\\", "/")
                    if selected_ids and not any(aid in rel_sub for aid in selected_ids):
                        continue
                    try:
                        with open(fpath, "r", encoding="utf-8") as fh:
                            soul_files[f"agents/souls/{rel_sub}"] = fh.read()
                    except Exception:
                        pass

        # 4. Skills einsammeln
        skill_files: Dict[str, str] = {}
        skills_dir = os.path.join(self.workspace_dir, "skills")
        if os.path.isdir(skills_dir):
            for root, _, files in os.walk(skills_dir):
                for fname in files:
                    if not (fname.endswith(".md") or fname.endswith(".json") or fname.endswith(".py")):
                        continue
                    fpath = os.path.join(root, fname)
                    rel_sub = os.path.relpath(fpath, skills_dir).replace("\\", "/")
                    if domain_l and domain_l not in rel_sub.lower() and selected_ids and not any(aid in rel_sub for aid in selected_ids):
                        continue
                    try:
                        with open(fpath, "r", encoding="utf-8") as fh:
                            skill_files[f"skills/{rel_sub}"] = fh.read()
                    except Exception:
                        pass

        # 5. Boardroom Frameworks
        fw_raw = self._load_json_safe("config/boardroom_frameworks.json", {"frameworks": []})
        frameworks = fw_raw.get("frameworks", []) if isinstance(fw_raw, dict) else fw_raw

        # 6. Prompt Studio Templates (B)
        selected_prompts: List[Any] = []
        if include_prompts:
            cat_raw = self._load_json_safe("prompt_studio_catalog.json", [])
            cat_items = cat_raw if isinstance(cat_raw, list) else cat_raw.get("templates", []) if isinstance(cat_raw, dict) else []
            for tpl in cat_items:
                if not isinstance(tpl, dict):
                    continue
                tdom = str(tpl.get("domain") or tpl.get("category") or "").lower()
                if not domain_l or domain_l in tdom:
                    selected_prompts.append(tpl)
                if len(selected_prompts) >= 100:
                    break

        # 7. n8n Workflows (B)
        n8n_files: Dict[str, str] = {}
        if include_n8n:
            for n8n_rel in ("n8n_workflows", "deploy/n8n", "config/n8n"):
                ndir = os.path.join(self.workspace_dir, n8n_rel)
                if not os.path.isdir(ndir):
                    continue
                for fname in sorted(os.listdir(ndir)):
                    if fname.endswith(".json"):
                        fpath = os.path.join(ndir, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as fh:
                                n8n_files[f"n8n/{fname}"] = fh.read()
                        except Exception:
                            pass

        # Dateien zusammenstellen + SHA-256 berechnen
        entries: Dict[str, bytes] = {
            "agents/roles.json": json.dumps(selected_roles, ensure_ascii=False, indent=2).encode("utf-8"),
            "agents/agent_profiles.json": json.dumps(selected_profiles, ensure_ascii=False, indent=2).encode("utf-8"),
            "boardroom/frameworks.json": json.dumps(frameworks, ensure_ascii=False, indent=2).encode("utf-8"),
        }
        if include_prompts:
            entries["prompts/templates.json"] = json.dumps(selected_prompts, ensure_ascii=False, indent=2).encode("utf-8")
        for k, v in soul_files.items():
            entries[k] = v.encode("utf-8")
        for k, v in skill_files.items():
            entries[k] = v.encode("utf-8")
        for k, v in n8n_files.items():
            entries[k] = v.encode("utf-8")

        checksums = {path: hashlib.sha256(raw).hexdigest() for path, raw in sorted(entries.items())}
        manifest: Dict[str, Any] = {
            "format_version": PACK_FORMAT_VERSION,
            "name": name,
            "domain": domain or "all",
            "description": description,
            "author": author,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "stats": {
                "agents": len(selected_roles),
                "profiles": len(selected_profiles),
                "souls": len(soul_files),
                "skills": len(skill_files),
                "frameworks": len(frameworks) if isinstance(frameworks, list) else 0,
                "prompts": len(selected_prompts),
                "n8n_workflows": len(n8n_files),
            },
            "checksums": checksums,
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for path, raw in sorted(entries.items()):
                zf.writestr(path, raw)

        return buf.getvalue(), manifest

    def inspect_pack(self, pack_bytes: bytes) -> Tuple[bool, Dict[str, Any]]:
        """Prüft ein .archonpack Archiv (Zip-Slip, Größe, Checksummen) ohne Schreibzugriff."""
        try:
            zf = zipfile.ZipFile(io.BytesIO(pack_bytes), "r")
        except zipfile.BadZipFile:
            return False, {"error": "Ungültiges .archonpack Archiv (kein gültiges ZIP)."}

        with zf:
            infos = zf.infolist()
            total_size = sum(i.file_size for i in infos)
            if total_size > MAX_UNCOMPRESSED_BYTES:
                return False, {"error": f"Archiv überschreitet Maximalgröße ({total_size} > {MAX_UNCOMPRESSED_BYTES})."}

            for info in infos:
                if not _is_safe_zip_member(info.filename):
                    return False, {"error": f"Unsicherer Pfad im Archiv abgelehnt: {info.filename}"}

            names = set(zf.namelist())
            if "manifest.json" not in names:
                return False, {"error": "manifest.json fehlt im .archonpack Archiv."}

            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            checksums = manifest.get("checksums") or {}
            mismatches: List[str] = []
            for path, expected_sha in checksums.items():
                if path not in names:
                    mismatches.append(f"fehlt: {path}")
                    continue
                actual_sha = hashlib.sha256(zf.read(path)).hexdigest()
                if actual_sha != expected_sha:
                    mismatches.append(f"sha256 mismatch: {path}")

            if mismatches:
                return False, {"error": "Integritätsprüfung fehlgeschlagen", "details": mismatches}

            return True, {
                "valid": True,
                "manifest": manifest,
                "file_count": len(infos),
                "total_uncompressed_bytes": total_size,
            }

    def import_pack(self, pack_bytes: bytes, conflict_mode: str = "skip") -> Tuple[bool, Dict[str, Any]]:
        """Importiert ein geprüftes .archonpack Archiv in den Workspace."""
        ok, inspect_res = self.inspect_pack(pack_bytes)
        if not ok:
            return False, inspect_res

        overwrite = conflict_mode == "overwrite"
        imported_counts = {"roles": 0, "profiles": 0, "souls": 0, "skills": 0, "prompts": 0, "n8n": 0}

        with zipfile.ZipFile(io.BytesIO(pack_bytes), "r") as zf:
            names = set(zf.namelist())

            # 1. Roles mergen
            if "agents/roles.json" in names:
                incoming_roles = json.loads(zf.read("agents/roles.json").decode("utf-8"))
                existing = self._load_json_safe("roles.json", [])
                is_wrapped = isinstance(existing, dict) and "roles" in existing
                role_list = list(existing["roles"]) if is_wrapped else (list(existing) if isinstance(existing, list) else [])
                by_id = {str(r.get("id") or r.get("role_id")): idx for idx, r in enumerate(role_list) if isinstance(r, dict)}
                for r in incoming_roles:
                    if not isinstance(r, dict):
                        continue
                    rid = str(r.get("id") or r.get("role_id") or "")
                    if not rid:
                        continue
                    if rid in by_id:
                        if overwrite:
                            role_list[by_id[rid]] = r
                            imported_counts["roles"] += 1
                    else:
                        role_list.append(r)
                        by_id[rid] = len(role_list) - 1
                        imported_counts["roles"] += 1
                self._save_json_atomic("roles.json", {"roles": role_list} if is_wrapped else role_list)

            # 2. Agent Profiles mergen
            if "agents/agent_profiles.json" in names:
                incoming_prof = json.loads(zf.read("agents/agent_profiles.json").decode("utf-8"))
                existing_prof = self._load_json_safe("agent_profiles.json", {})
                if isinstance(existing_prof, dict) and isinstance(incoming_prof, dict):
                    for pid, pval in incoming_prof.items():
                        if pid not in existing_prof or overwrite:
                            existing_prof[pid] = pval
                            imported_counts["profiles"] += 1
                    self._save_json_atomic("agent_profiles.json", existing_prof)

            # 3. Souls, Skills & n8n Dateien schreiben (strikt im Workspace-Jail)
            for fname in sorted(names):
                if fname.endswith("/"):
                    continue
                target_rel: Optional[str] = None
                bucket: Optional[str] = None
                if fname.startswith("agents/souls/"):
                    target_rel = os.path.join("agent_workspace", "souls", fname[len("agents/souls/"):])
                    bucket = "souls"
                elif fname.startswith("skills/"):
                    target_rel = os.path.join("skills", fname[len("skills/"):])
                    bucket = "skills"
                elif fname.startswith("n8n/"):
                    target_rel = os.path.join("n8n_workflows", fname[len("n8n/"):])
                    bucket = "n8n"

                if target_rel and bucket:
                    dest = os.path.realpath(os.path.join(self.workspace_dir, target_rel))
                    if not (dest == self.workspace_dir or dest.startswith(self.workspace_dir + os.sep)):
                        continue
                    if os.path.exists(dest) and not overwrite:
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as out_fh:
                        out_fh.write(zf.read(fname))
                    imported_counts[bucket] += 1

            # 4. Prompt Studio Templates mergen
            if "prompts/templates.json" in names:
                incoming_tpls = json.loads(zf.read("prompts/templates.json").decode("utf-8"))
                cat = self._load_json_safe("prompt_studio_catalog.json", [])
                if isinstance(cat, list) and isinstance(incoming_tpls, list):
                    existing_ids = {t.get("id") for t in cat if isinstance(t, dict)}
                    for tpl in incoming_tpls:
                        if isinstance(tpl, dict) and tpl.get("id") not in existing_ids:
                            cat.append(tpl)
                            imported_counts["prompts"] += 1
                    self._save_json_atomic("prompt_studio_catalog.json", cat)

        return True, {
            "status": "imported",
            "pack_name": inspect_res["manifest"].get("name"),
            "conflict_mode": conflict_mode,
            "imported": imported_counts,
        }


squad_pack_manager = SquadPackManager()
