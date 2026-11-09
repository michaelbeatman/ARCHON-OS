"""Fachlogik der Hermes-Profil-Verwaltung: Profil speichern und loeschen.

Extrahiziert aus ``archon/routers/hermes_profiles.py`` (P2, Gate-Approve-Defekt).
Dieser Service kennt **keine** HTTP-Schicht: kein ``Request``, kein ``Body``,
kein ``require_admin_or_503``.

Autorisierung passiert ausserhalb:

* HTTP-Pfad  -> ``require_admin_or_503(request)`` als erste Zeile im Router.
* Gate-Pfad  -> die Gate-Entscheidung in ``main.py``, die hier zusaetzlich
  durch ``_verify_gate()`` fail-closed nachgeprueft wird.

Fehler werden als Domaenenexceptions gemeldet. Der Router uebersetzt sie in
dieselben HTTP-Antworten (Statuscode + ``detail``-Text) wie vor der Extraktion.

Zyklusfrei: importiert nur ``archon.core.*``, niemals ``main``.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
from typing import Any, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel

from archon.core.config import config
from archon.core.paths import OPT_DATA_DIR
from archon.core.runtime import APP_ROOT, MEMORY_DIR, add_ticker, logger
from archon.core.permissions import (
    create_permission_gate as _create_permission_gate,
    load_permission_gates as _load_permission_gates,
)
from archon.core.profiles import (
    DEFAULT_HERMES_TOOLS, api_get_hermes_profiles, create_rolling_backup,
    get_hermes_profiles_base_dirs, invalidate_hermes_profiles_cache,
    materialize_data_uri_avatar, resolve_avatar_file,
)

__all__ = [
    "GateNotApproved", "ProfileProtectedError", "ProfileValidationError",
    "ProfilesServiceError", "agent_profiles_json_path", "configure",
    "delete_profile", "save_profile",
]

GATE_KIND_TOOLS = "tools_erweiterung"
GATE_KIND_DELETE = "profil_loeschen"

PROTECTED_PROFILES = ("default", "hermes_default", "micha")


# ---------------------------------------------------------------------------
# Domaenenfehler — der Router uebersetzt sie in HTTP-Antworten
# ---------------------------------------------------------------------------

class ProfilesServiceError(Exception):
    """Basisklasse aller fachlichen Fehler dieses Service."""


class ProfileValidationError(ProfilesServiceError):
    """Profil-Payload verletzt das Schema (Router: 422)."""


class ProfileProtectedError(ProfilesServiceError):
    """System-Profil darf nicht geloescht werden (Router: 400)."""

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        super().__init__(f"System-Profil '{profile_id}' kann nicht gelöscht werden.")


class GateNotApproved(ProfilesServiceError):
    """Kein gueltiges, offenes Gate fuer diese Aktion (Router: 403).

    Wird geworfen, sobald ein ``approved_gate_id`` mitgegeben wird, das sich
    nicht verifizieren laesst. Fail-closed: lieber sperren als durchlassen.
    """


# ---------------------------------------------------------------------------
# Abhaengigkeiten (eine echte Injektion statt ``_DEPS`` aus main.py)
# ---------------------------------------------------------------------------

_org_sync_node: Optional[Callable[..., None]] = None
_org_sync_warned = False


def configure(*, org_sync_node: Optional[Callable[..., None]] = None) -> None:
    """Registriert den Organigramm-Sync aus main.py (einmalig beim Start)."""
    global _org_sync_node
    _org_sync_node = org_sync_node


def _run_org_sync(sync: Optional[Callable[..., None]], p_id: str, **kwargs: Any) -> None:
    """Ruft den Organigramm-Sync auf — oder sagt einmal laut, dass er fehlt."""
    global _org_sync_warned
    if sync is None:
        if not _org_sync_warned:
            _org_sync_warned = True
            logger.warning(
                "[Profiles] Organigramm-Sync ist nicht verdrahtet — Profil wird "
                "gespeichert, der Org-Chart bleibt unveraendert. "
                "profiles_service.configure(org_sync_node=...) fehlt."
            )
        return
    sync(p_id, **kwargs)


def agent_profiles_json_path() -> str:
    """Pfad der agent_profiles.json (Operations-Kanban & Org-Chart).

    Frueher leitete sich der Pfad aus ``__file__`` des Routers ab und zeigte
    damit auf ``archon/routers/`` — dort liegt die Datei nie, der Sync-Block war
    toter Code. Jetzt dieselbe Wurzel wie alle anderen Profil-Pfade.
    """
    return os.path.join(APP_ROOT, "agent_profiles.json")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class AgentProfileValidationSchema(BaseModel):
    id: str
    name: str
    person_name: str
    category: str
    model: str
    prompt: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: List[str]

    def get_prompt_text(self) -> str:
        val = (self.prompt or self.system_prompt or "").strip()
        if not val:
            val = f"Du bist {self.person_name} ({self.name})."
        return val


# ---------------------------------------------------------------------------
# Gate-Verifikation (fail-closed)
# ---------------------------------------------------------------------------

def _verify_gate(gate_id: str, kind: str, expected_payload: Dict[str, Any]) -> dict:
    """Prueft, dass ``gate_id`` ein offenes Gate dieses Typs fuer diese Aktion ist.

    Regel: ausfuehren nur bei verifiziertem Gate. Fehlt es, gehoert es zu einer
    anderen Aktion oder ist es bereits entschieden, wird gesperrt. Der Aufruf
    liegt zwischen Entscheidung und Ausfuehrung, das Gate ist dort noch
    ``pending``; ``main.py`` schreibt ``approved`` erst nach dem Erfolg.
    """
    gates = (_load_permission_gates() or {}).get("gates", []) or []
    gate = next((g for g in gates if g.get("id") == gate_id), None)
    if gate is None:
        raise GateNotApproved(f"Gate '{gate_id}' existiert nicht.")
    if gate.get("kind") != kind:
        raise GateNotApproved(
            f"Gate '{gate_id}' ist vom Kind '{gate.get('kind')}', erwartet '{kind}'.")
    status = gate.get("status")
    if status != "pending":
        raise GateNotApproved(
            f"Gate '{gate_id}' ist nicht offen (Status '{status}').")
    gate_payload = gate.get("payload") or {}
    for key, want in expected_payload.items():
        have = gate_payload.get(key)
        if have != want:
            raise GateNotApproved(
                f"Gate '{gate_id}' gehoert nicht zu {key}='{want}' (Gate traegt '{have}').")
    return gate


# ---------------------------------------------------------------------------
# Speichern
# ---------------------------------------------------------------------------

def save_profile(profile_data: Dict[str, Any], *,
                 org_sync_node: Optional[Callable[..., None]] = None) -> dict:
    """Legt ein Profil an bzw. schreibt es fort. Liefert das Ergebnis-Dict."""
    _sync = org_sync_node if org_sync_node is not None else _org_sync_node
    p_id = profile_data.get("id")
    if not p_id:
        p_id = re.sub(r'[^a-zA-Z0-9_]', '_', profile_data.get("name", "custom_agent").lower())
        profile_data["id"] = p_id

    person_name = profile_data.get("person_name") or profile_data.get("name", p_id)
    profile_data["person_name"] = person_name
    avatar_val = profile_data.get("avatar") or profile_data.get("avatar_url") or f"https://api.dicebear.com/7.x/notionists/svg?seed={p_id}&backgroundColor=3b82f6"
    profile_data["avatar"] = avatar_val
    # --- PERMISSION-GATE: NEUE TOOLS = Rechte-Erweiterung -> Owner per Telegram ---
    incoming_tools = profile_data.get("tools")
    _approved_gate_id = str(profile_data.get("_approved_gate_id") or "").strip()
    if _approved_gate_id:
        _verify_gate(_approved_gate_id, GATE_KIND_TOOLS, {"id": p_id})
    if isinstance(incoming_tools, list) and not _approved_gate_id:
        _alt_tools = []
        for p_base in get_hermes_profiles_base_dirs():
            yml = os.path.join(p_base, p_id, "profile.yaml")
            if os.path.exists(yml):
                try:
                    import yaml as _yaml
                    with open(yml, "r", encoding="utf-8") as _fy:
                        _alt_tools = (_yaml.safe_load(_fy) or {}).get("tools") or []
                    break
                except Exception:
                    pass
        _neue = [t for t in incoming_tools if t not in _alt_tools]
        if _neue:
            detail = (f"Profil '{p_id}' bekommt neue Tools: {', '.join(_neue[:8])}"
                      + (f" (+{len(_neue)-8} weitere)" if len(_neue) > 8 else ""))
            gate = _create_permission_gate(
                "tools_erweiterung", detail,
                f"agent:{profile_data.get('requested_by') or 'ui-owner'}",
                {k: v for k, v in profile_data.items() if k != "_approved_gate_id"})
            return {"status": "pending_owner_approval", "gate_id": gate["id"],
                    "message": "Rechte-Erweiterung erkannt: Warte auf deine Telegram-Bestätigung. "
                               f"Antworte dort: 'Erlauben {gate['id']}' oder 'Verbieten {gate['id']}'."}
    assigned_tools = profile_data.get("tools", DEFAULT_HERMES_TOOLS)
    profile_data["tools"] = assigned_tools
    assigned_skills = profile_data.get("skills", [])
    provider_val = profile_data.get("provider", "openrouter")
    model_val = profile_data.get("model", "deepseek/deepseek-v4-flash-0731")
    reasoning_val = str(profile_data.get("reasoning_level") or "high").strip().lower()
    if reasoning_val not in ("off", "minimal", "low", "medium", "high", "max"):
        reasoning_val = "high"
    profile_data["reasoning_level"] = reasoning_val
    status_val = profile_data.get("status", "active")
    is_fav = bool(profile_data.get("is_favorite", (p_id in ["default", "micha"])))

    # Prompt robust auflösen: Payload -> SOUL.md auf Disk -> Fallback
    prompt_val = (profile_data.get("prompt") or profile_data.get("system_prompt") or "").strip()
    if not prompt_val:
        for p_base in get_hermes_profiles_base_dirs():
            sf = os.path.join(p_base, p_id, "SOUL.md")
            if os.path.exists(sf):
                try:
                    with open(sf, "r", encoding="utf-8") as f_soul:
                        content = f_soul.read().strip()
                        if content:
                            prompt_val = content
                            break
                except Exception:
                    pass
        if not prompt_val:
            prompt_val = f"Du bist {person_name} ({profile_data.get('name', p_id)}). {profile_data.get('description', '')}".strip()

    profile_data["prompt"] = prompt_val
    profile_data["system_prompt"] = prompt_val
    profile_data["model"] = model_val

    # Pydantic-Schema-Validierung
    try:
        validated_profile = AgentProfileValidationSchema(
            id=str(p_id).strip(),
            name=str(profile_data.get("name", p_id)).strip(),
            person_name=str(person_name).strip(),
            category=str(profile_data.get("category", "1. Strategie, Führung & Lebensplanung")).strip(),
            model=str(model_val).strip(),
            prompt=profile_data.get("prompt"),
            system_prompt=profile_data.get("system_prompt"),
            tools=list(assigned_tools) if isinstance(assigned_tools, list) else []
        )
        prompt_text = validated_profile.get_prompt_text()
        if not validated_profile.name or not validated_profile.person_name or not validated_profile.category or not validated_profile.model:
            raise ValueError("All fields (id, name, person_name, category, model) are required and must be non-empty.")
    except Exception as val_err:
        logger.warning(f"[Profile Validation Failed] Rejecting profile save for '{p_id}': {val_err}")
        raise ProfileValidationError(str(val_err))

    # In allen aktiven Profil-Ordnern anlegen/schreiben
    av_blob = None
    av_mime = "image/jpeg"
    clean_avatar = avatar_val

    if avatar_val and avatar_val.startswith("data:image"):
        # Ein Schreibpfad fuer alle: der atomare Helfer (tmp + os.replace) legt die
        # Datei im Laufzeitverzeichnis ab (avatars_dir, nicht mehr im versionierten
        # APP_ROOT/static/avatars) und liefert genau die /static-URL zurueck, die
        # profile.yaml speichert. Frueher stand hier eine Kopie ohne tmp+replace.
        clean_avatar = materialize_data_uri_avatar(p_id, avatar_val)
        if clean_avatar:
            avatar_val = clean_avatar
            profile_data["avatar"] = clean_avatar
            profile_data["avatar_url"] = clean_avatar
            logger.info(f"[Profiles] Saved custom avatar for '{p_id}' as {clean_avatar}")
        else:
            logger.error(f"[Profiles] Error decoding/saving base64 avatar for {p_id}")
            clean_avatar = "/static/avatars/avatar_001.jpg"
    elif avatar_val and len(avatar_val) < 500:
        clean_avatar = avatar_val
    else:
        found_custom = False
        for test_ext in [".png", ".jpg", ".jpeg", ".webp"]:
            # Laufzeitverzeichnis zuerst, dann der versionierte Altbestand.
            if resolve_avatar_file(f"custom_{p_id}{test_ext}"):
                clean_avatar = f"/static/avatars/custom_{p_id}{test_ext}"
                found_custom = True
                break
        if not found_custom:
            clean_avatar = "/static/avatars/avatar_001.jpg"

    # Wenn Skills oder Tools über den Reiter 'Fähigkeiten' geändert wurden,
    # synchronisiere diese sofort in SOUL_COMPACT.md, SOUL_PRO.md, SOUL_FULL.md und SOUL.md
    try:
        if any(os.path.exists(os.path.join(b, p_id, "SOUL_COMPACT.md")) for b in get_hermes_profiles_base_dirs()):
            from scripts.sync_soul_modes import sync_single_agent_capabilities_to_soul
            synced_soul = sync_single_agent_capabilities_to_soul(
                p_id,
                profile_data,
                base_dirs=get_hermes_profiles_base_dirs(),
            )
            if synced_soul:
                prompt_text = synced_soul
                profile_data["prompt"] = synced_soul
                profile_data["system_prompt"] = synced_soul
    except Exception as soul_sync_err:
        logger.warning(f"[Profiles] Could not auto-sync SOUL capabilities for {p_id}: {soul_sync_err}")

    for p_base in get_hermes_profiles_base_dirs():
        try:
            target_pdir = os.path.join(p_base, p_id)
            os.makedirs(target_pdir, exist_ok=True)
            os.makedirs(os.path.join(target_pdir, "skills"), exist_ok=True)
            os.makedirs(os.path.join(target_pdir, "memories"), exist_ok=True)
            os.makedirs(os.path.join(target_pdir, "sessions"), exist_ok=True)

            soul_path = os.path.join(target_pdir, "SOUL.md")
            create_rolling_backup(soul_path, max_backups=3)
            with open(soul_path, "w", encoding="utf-8") as f:
                f.write(prompt_text + "\n")

            yaml_path = os.path.join(target_pdir, "profile.yaml")
            create_rolling_backup(yaml_path, max_backups=3)
            
            y_payload = {
                "name": profile_data.get("name", p_id),
                "person_name": person_name,
                "callsign": str(profile_data.get("callsign", "")).strip().lower(),
                "category": profile_data.get("category", "1. Strategie, Führung & Lebensplanung"),
                "description": profile_data.get("description", ""),
                "role_id": p_id,
                "avatar": clean_avatar,
                "avatar_url": clean_avatar,
                "tools": assigned_tools,
                "skills": assigned_skills,
                "status": status_val,
                "is_favorite": is_fav,
                "provider": provider_val,
                "model": model_val,
                "reasoning_level": reasoning_val,
                "llm": {
                    "provider": provider_val,
                    "model": model_val,
                    "reasoning_level": reasoning_val
                }
            }
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(y_payload, f, allow_unicode=True, sort_keys=False)

            # Hermes config.yaml anlegen ODER Modell/Provider aktualisieren
            config_path = os.path.join(target_pdir, "config.yaml")
            if not os.path.exists(config_path):
                default_cfg = {
                    "platforms": {"api_server": {"enabled": False}},
                    "model": {
                        "default": model_val,
                        "provider": provider_val,
                        "base_url": "http://omniroute:20128/v1",
                        "api_key": config.omniroute_api_key
                    },
                    "providers": {
                        "omniroute": {
                            "name": "OmniRoute",
                            "base_url": "http://omniroute:20128/v1",
                            "api_key": config.omniroute_api_key,
                            "key_env": "OMNIROUTE_API_KEY"
                        }
                    }
                }
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(default_cfg, f, allow_unicode=True, sort_keys=False)
            else:
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        existing_cfg = yaml.safe_load(f) or {}
                    if not isinstance(existing_cfg.get("model"), dict):
                        existing_cfg["model"] = {}
                    existing_cfg["model"]["default"] = model_val
                    existing_cfg["model"]["provider"] = provider_val
                    with open(config_path, "w", encoding="utf-8") as f:
                        yaml.dump(existing_cfg, f, allow_unicode=True, sort_keys=False)
                except Exception as cfg_err:
                    logger.warning(f"[Profiles] Could not sync config.yaml for {p_id}: {cfg_err}")

            # Skills synchronisieren (inkl. Entfernen abgewählter Skills aus dem Profil-Ordner)
            skills_sub = os.path.join(target_pdir, "skills")
            if os.path.exists(skills_sub):
                assigned_set = set(assigned_skills) | {s.replace("skill-", "") for s in assigned_skills} | {f"skill-{s}" for s in assigned_skills}
                for existing_entry in os.listdir(skills_sub):
                    if existing_entry.startswith("."):
                        continue
                    entry_base = os.path.splitext(existing_entry)[0]
                    if existing_entry not in assigned_set and entry_base not in assigned_set:
                        full_entry = os.path.join(skills_sub, existing_entry)
                        try:
                            if os.path.isdir(full_entry):
                                shutil.rmtree(full_entry, ignore_errors=True)
                            else:
                                os.unlink(full_entry)
                        except Exception:
                            pass
            global_skills_dir = os.path.join(MEMORY_DIR, "hermes_skills")
            if not os.path.exists(global_skills_dir):
                global_skills_dir = os.path.expanduser("~/.hermes/skills")
            if os.path.exists(global_skills_dir):
                for sk_id in assigned_skills:
                    sk_src = os.path.join(global_skills_dir, sk_id)
                    sk_dst = os.path.join(skills_sub, sk_id)
                    if os.path.exists(sk_src) and not os.path.exists(sk_dst):
                        try:
                            if os.path.isdir(sk_src):
                                shutil.copytree(sk_src, sk_dst)
                            else:
                                shutil.copy2(sk_src, sk_dst)
                        except Exception as e:
                            logger.warning(f"Error copying skill {sk_id}: {e}")
        except Exception as e:
            logger.error(f"[Profiles] Error writing profile to {p_base}: {e}")

    # Synchronisiere agent_profiles.json für Operations-Kanban & Org-Chart
    try:
        ap_file = agent_profiles_json_path()
        if os.path.exists(ap_file):
            with open(ap_file, "r", encoding="utf-8") as f:
                ap_list = json.load(f)
            if isinstance(ap_list, list):
                updated_ap = False
                for item in ap_list:
                    if isinstance(item, dict) and item.get("id") == p_id:
                        item["name"] = profile_data.get("name", p_id)
                        item["person_name"] = person_name
                        item["category"] = profile_data.get("category", item.get("category", ""))
                        item["description"] = profile_data.get("description", item.get("description", ""))
                        item["avatar"] = clean_avatar
                        item["model"] = model_val
                        item["provider"] = provider_val
                        item["reasoning_level"] = reasoning_val
                        item["status"] = status_val
                        item["skills"] = assigned_skills
                        item["tools"] = assigned_tools
                        item["prompt"] = prompt_text
                        item["system_prompt"] = prompt_text
                        updated_ap = True
                        break
                if not updated_ap:
                    ap_list.append({
                        "id": p_id,
                        "name": profile_data.get("name", p_id),
                        "person_name": person_name,
                        "category": profile_data.get("category", ""),
                        "description": profile_data.get("description", ""),
                        "avatar": clean_avatar,
                        "model": model_val,
                        "provider": provider_val,
                        "status": status_val,
                        "skills": assigned_skills,
                        "tools": assigned_tools,
                        "prompt": prompt_text,
                        "system_prompt": prompt_text,
                    })
                with open(ap_file, "w", encoding="utf-8") as f:
                    json.dump(ap_list, f, indent=2, ensure_ascii=False)
    except Exception as ap_err:
        logger.warning(f"[Profiles] Could not sync agent_profiles.json for {p_id}: {ap_err}")

    # Synchronisiere Avatar in avatars.db für Hermes WebUI
    try:
        import sqlite3, hashlib, time
        avatars_db_path = os.path.expanduser("~/.hermes/webui/avatars.db")
        if not os.path.exists(avatars_db_path):
            avatars_db_path = os.path.join(OPT_DATA_DIR, "webui", "avatars.db")
        if os.path.exists(os.path.dirname(avatars_db_path)):
            with sqlite3.connect(avatars_db_path) as av_conn:
                if not av_blob and clean_avatar and clean_avatar.startswith("/static/avatars/"):
                    fname = os.path.basename(clean_avatar.split("?")[0])
                    loc_img = resolve_avatar_file(fname)
                    if loc_img:
                        with open(loc_img, "rb") as img_f:
                            av_blob = img_f.read()
                        av_mime = "image/png" if fname.endswith(".png") else "image/jpeg"
                if av_blob:
                    av_etag = '"' + hashlib.sha256(av_blob).hexdigest()[:32] + '"'
                    av_conn.execute(
                        "INSERT OR REPLACE INTO avatars (profile, mime, bytes, etag, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (p_id, av_mime, av_blob, av_etag, time.time())
                    )
                    av_conn.commit()
    except Exception as e:
        logger.warning(f"[Profiles] Error syncing avatar to avatars.db: {e}")

    _run_org_sync(
        _sync, p_id,
        name=profile_data.get("name", p_id),
        person_name=person_name,
        avatar=clean_avatar,
        provider=provider_val,
        model=model_val,
        reasoning_level=reasoning_val
    )
    # Cache invalidieren und neu aufbauen
    invalidate_hermes_profiles_cache()
    api_get_hermes_profiles()
    add_ticker("Hermes Profiles", f"Profil '{person_name}' ({profile_data.get('name', p_id)}) gespeichert.")
    return {"status": "success", "profile": profile_data}

# ---------------------------------------------------------------------------
# Loeschen (Archiv)
# ---------------------------------------------------------------------------

def delete_profile(profile_id: str, *, approved_gate_id: str = "") -> dict:
    """Archiviert ein Profil und entfernt es aus der Profilliste."""
    if profile_id in PROTECTED_PROFILES:
        raise ProfileProtectedError(profile_id)
    # --- PERMISSION-GATE: Loeschen = Rechte-Entzug -> Owner per Telegram ---
    if approved_gate_id:
        _verify_gate(approved_gate_id, GATE_KIND_DELETE, {"profile_id": profile_id})
    else:
        _gates = _load_permission_gates().get("gates", [])
        _pend = [g for g in _gates if g.get("status") == "pending"
                 and g.get("kind") == "profil_loeschen"
                 and (g.get("payload") or {}).get("profile_id") == profile_id]
        if not _pend:
            gate = _create_permission_gate(
                "profil_loeschen", f"Profil '{profile_id}' soll Dauerhaft geloescht werden (Archiv)",
                "agent:ui-owner", {"profile_id": profile_id})
            return {"status": "pending_owner_approval", "gate_id": gate["id"],
                    "message": "Loeschen braucht deine Telegram-Bestätigung. "
                               f"Antworte: 'Erlauben {gate['id']}' oder 'Verbieten {gate['id']}'."}
        else:
            gate = _pend[0]
            return {
                "status": "pending_owner_approval",
                "gate_id": gate.get("id", ""),
                "message": "Loeschen wartet bereits auf deine Telegram-Bestätigung. "
                           f"Antworte: 'Erlauben {gate.get('id', '')}' oder 'Verbieten {gate.get('id', '')}'."
            }

    archived_locations = []
    for p_base in get_hermes_profiles_base_dirs():
        src_dir = os.path.join(p_base, profile_id)
        if os.path.exists(src_dir):
            archive_dir = os.path.join(p_base, ".archive")
            os.makedirs(archive_dir, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dst_dir = os.path.join(archive_dir, f"{profile_id}_deleted_{ts}")
            try:
                shutil.move(src_dir, dst_dir)
                archived_locations.append(dst_dir)
            except Exception as e:
                logger.error(f"[Profiles] Error archiving {src_dir} to {dst_dir}: {e}")

    # Sofort aus agent_profiles.json entfernen
    for cand in [agent_profiles_json_path()]:
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    j_data = json.load(f)
                if isinstance(j_data, list):
                    filtered = [p for p in j_data if p.get("id") != profile_id]
                    create_rolling_backup(cand, max_backups=3)
                    with open(cand, "w", encoding="utf-8") as f:
                        json.dump(filtered, f, indent=2, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"[Profiles] Error removing deleted profile from {cand}: {e}")

    invalidate_hermes_profiles_cache()
    # Aktualisierte Profil-Liste neu laden & spiegeln
    api_get_hermes_profiles()
    add_ticker("Hermes Profiles", f"Profil '{profile_id}' archiviert und entfernt.")
    return {"status": "success", "profile_id": profile_id, "archived_to": archived_locations}
