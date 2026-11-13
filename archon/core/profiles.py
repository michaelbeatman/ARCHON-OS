"""Hermes-Profil-Registry (Cache, Pfade, Auflösung).

Aus main.py ausgelagert, damit Router und Services Profile lesen können, ohne
main.py zu importieren. Haelt den 300-Sekunden-Cache und den Pre-Warm beim
Import (spart beim ersten Request ~20s Kaltaufbau).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional

import yaml

from archon.core.config import config
from archon.core.paths import HERMES_PROFILES_BASE, OPT_DATA_DIR
from archon.core.runtime import APP_ROOT, MEMORY_DIR, logger

DEFAULT_HERMES_TOOLS = [
    "web_search", "browser", "terminal", "filesystem", "execute_code", "vision_analyze",
    "image_generate", "bfl_flux3", "text_to_speech", "speech_to_text", "skills", "task_planning",
    "memory", "session_search", "clarify", "delegate_task", "cronjob", "computer_use"
]

# --------------------------------------------------
# Avatare: data:-URI -> Datei unter /static/avatars
# --------------------------------------------------
# Der Profil-Editor speichert hochgeladene Bilder als Base64 im profile.yaml.
# Im Listen-Endpunkt kostete das gemessen 1,25 MB pro Antwort (5 Profile, jedes
# Bild zweimal als `avatar` und `avatar_url` gesendet) — 96 % der 2,6 MB. Die
# Datei ist eine reine Ableitung des YAML-Werts: identische Bytes, nur ueber
# /static ausgeliefert. Das YAML bleibt unveraendert die Quelle der Wahrheit.
_AVATAR_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_AVATAR_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# Env-Override fuer das Laufzeit-Ablageverzeichnis der Avatare.
AVATARS_DIR_ENV = "ARCHON_AVATARS_DIR"

# Im Container ist OPT_DATA_DIR der beschreibbare Laufzeitspeicher (= Host ~/.hermes).
# Auf dem Host gibt es /opt/data nicht, dort ist ~/.hermes das Pendant.
_CONTAINER_DATA_DIR = "/opt/data"
_CONTAINER_AVATARS_DIR = "/opt/data/webui/static_avatars"
_HOST_AVATARS_DIR = "~/.hermes/webui/static_avatars"


def _container_data_available() -> bool:
    """True, wenn dieser Prozess im Container-Kontext mit /opt/data laeuft.

    Eigene Funktion als Test-Seam: die Pfad-Aufloesung soll ohne echtes
    /opt/data-Verzeichnis pruefbar sein (die Testsuite laeuft auf dem Host).
    """
    return os.path.isdir(_CONTAINER_DATA_DIR)


def avatars_dir() -> str:
    """Beschreibbares Laufzeit-Verzeichnis der Avatare (NICHT der versionierte Baum).

    Aufloesung, erster Treffer gewinnt:

    1. ``ARCHON_AVATARS_DIR`` (Env) — gewinnt immer, auch gegen /opt/data.
    2. ``/opt/data/webui/static_avatars``, wenn ``/opt/data`` existiert (Container).
    3. ``~/.hermes/webui/static_avatars`` (Host-Pendant).

    Angelegt wird das Verzeichnis vom Schreibpfad
    (:func:`materialize_data_uri_avatar`), nicht hier — diese Funktion bleibt
    billig und lesbar, damit Lesepfade sie ohne Nebenwirkung rufen koennen.
    """
    env = config.avatars_dir
    if env:
        return os.path.expanduser(env)
    if _container_data_available():
        return _CONTAINER_AVATARS_DIR
    return os.path.expanduser(_HOST_AVATARS_DIR)


def avatars_legacy_dir() -> str:
    """Versionierter Katalog samt Alt-Avataren — nur noch lesend.

    Hier liegen die kuratierten ``avatar_NNN.jpg`` und die historischen
    ``custom_*``-PNGs. Geschrieben wird dorthin nicht mehr (siehe
    :func:`avatars_dir`), gelesen schon: Auslieferung und Datenbank-Sync
    fallen auf dieses Verzeichnis zurueck.
    """
    return os.path.join(APP_ROOT, "static", "avatars")


def resolve_avatar_file(filename: str) -> Optional[str]:
    """Liefert den ersten existierenden Dateipfad zu einem Avatarnamen.

    Kette: Laufzeitverzeichnis (:func:`avatars_dir`) -> versionierter Bestand
    (:func:`avatars_legacy_dir`). ``None``, wenn der Name unbrauchbar ist oder
    nirgends eine Datei liegt. Der Name wird auf einen Basisnamen reduziert,
    damit kein Aufrufer einen Pfad-Ausbruch durchreichen kann.
    """
    name = os.path.basename(filename or "").strip()
    if not name or name.startswith(".") or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        return None
    for directory in (avatars_dir(), avatars_legacy_dir()):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def materialize_data_uri_avatar(profile_id: str, data_url: str) -> Optional[str]:
    """Schreibt einen data:-URI-Avatar als Datei und liefert den /static-Pfad.

    Gibt None zurueck, wenn der Wert kein verwertbarer data:-URI ist — der
    Aufrufer behaelt dann den Originalwert (nie stillschweigend ein anderes Bild).
    """
    if not isinstance(data_url, str) or not data_url.startswith("data:image"):
        return None
    if not _AVATAR_ID_RE.match(profile_id or ""):
        return None
    try:
        header, b64 = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "").strip().lower()
        ext = _AVATAR_MIME_EXT.get(mime)
        if not ext:
            return None
        raw = base64.b64decode(b64, validate=False)
        if not raw:
            return None
        target_dir = avatars_dir()
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, f"custom_{profile_id}{ext}")
        unchanged = False
        if os.path.exists(target):
            try:
                with open(target, "rb") as fh:
                    unchanged = fh.read() == raw
            except OSError:
                unchanged = False
        if not unchanged:
            tmp = f"{target}.tmp"
            with open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, target)
            logger.info(f"[Profiles] Avatar von '{profile_id}' aus data:-URI materialisiert ({len(raw)} B)")
        return f"/static/avatars/custom_{profile_id}{ext}"
    except Exception as e:  # Base64 kaputt, Rechte, Platte voll
        logger.warning(f"[Profiles] Avatar-Materialisierung fuer '{profile_id}' fehlgeschlagen: {e}")
        return None


_ROLE_AVATAR_FIELDS = ("avatar", "avatar_url")


def materialize_role_avatars(roles: Any) -> Any:
    """Ersetzt data:-URI-Avatare einer Rollen-Liste durch die /static-Pfade.

    `roles.json` bleibt die Quelle der Wahrheit: die data-URI wird nur fuer die
    Antwort materialisiert (Datei anlegen, Pfad ausliefern). Die Eingabe wird
    nicht verandert — `load_roles()` liefert ein gecachtes Objekt, das auch
    interne Leser (Prompt-Aufbau, Boardroom) benutzen und das seinen data-URI
    behalten muss.

    Je Ziel-Feld wird der vorhandene, idempotente `materialize_data_uri_avatar`
    benutzt; liefert er None (ungueltiger Wert), bleibt der Originalwert stehen
    — es wird nie ein Feld geleert.
    """
    if not isinstance(roles, list):
        return roles
    # Ein Bild steckt in der Datei zweimal (avatar + avatar_url): einmal
    # materialisieren genuegt, sonst wird dieselbe halbe Megabyte-Base64
    # doppelt decodiert und gehasht.
    resolved: Dict[tuple, Optional[str]] = {}
    result: List[Any] = []
    for role in roles:
        if not isinstance(role, dict):
            result.append(role)
            continue
        item = dict(role)
        for field in _ROLE_AVATAR_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value.startswith("data:image"):
                continue
            key = (str(item.get("id") or ""), value)
            if key not in resolved:
                resolved[key] = materialize_data_uri_avatar(key[0], value)
            if resolved[key]:
                item[field] = resolved[key]
        result.append(item)
    return result


# Rueckweg: /static-Pfad -> data:-URI (Schutz gegen den Rundlauf GET -> POST).
# Nur Dateinamen direkt unter static/avatars, keine Verzeichniswechsel.
_STATIC_AVATAR_RE = re.compile(r"^/static/avatars/[A-Za-z0-9_.-]+$")


def restore_data_uri_avatars(roles: Any, stored: Any = None) -> Any:
    """Dreht nur die selbst materialisierten Avatare vor dem Speichern zurueck.

    `GET /api/roles` liefert materialisierte Pfade; das Frontend postet die
    Antwort unveraendert zurueck (`prompt_studio.js`: loadRolesFromServer ->
    saveRolesToServer). Ohne Umkehrung stuende nach dem ersten Speichern im UI
    der Pfad in `roles.json` und die data-URI — fuer Rollen ohne eigenes Profil
    die einzige Kopie des Bildes — waere verloren.

    Die Regel ist selbstbegrenzend: zurueckgedreht wird nur, wenn der eingehende
    Pfad **genau** der ist, den `materialize_data_uri_avatar` aus dem aktuell
    gespeicherten data-URI derselben Rolle erzeugt. Damit bleiben die rund 100
    `/static`-Pfade, die schon heute in der Datei stehen (geteilte Katalog-
    Avatare), unangetastet — sonst blaehte ein Speichern die Datei um ~3,7 MB
    auf Base64 auf.

    :param roles: eingehende Rollenliste (z. B. aus dem POST-Body).
    :param stored: aktuell gespeicherter Stand (dieselbe Datei, die geschrieben
                   wird). Ohne Vorlage wird nichts zurueckgedreht.
    """
    if not isinstance(roles, list):
        return roles
    vorlage: Dict[str, Dict[str, Any]] = {}
    if isinstance(stored, list):
        for eintrag in stored:
            if isinstance(eintrag, dict) and eintrag.get("id") is not None:
                vorlage[str(eintrag.get("id"))] = eintrag
    if not vorlage:
        return roles
    # Ein Bild steht zweimal drin (avatar + avatar_url): einmal pruefen genuegt.
    geprueft: Dict[tuple, bool] = {}
    result: List[Any] = []
    for role in roles:
        if not isinstance(role, dict):
            result.append(role)
            continue
        item = dict(role)
        role_id = str(item.get("id") or "")
        alt = vorlage.get(role_id)
        if alt is None:
            result.append(item)
            continue
        for field in _ROLE_AVATAR_FIELDS:
            wert = item.get(field)
            gespeichert = alt.get(field)
            if not isinstance(wert, str) or not _STATIC_AVATAR_RE.match(wert):
                continue
            if not (isinstance(gespeichert, str) and gespeichert.startswith("data:image")):
                continue
            key = (role_id, gespeichert)
            if key not in geprueft:
                geprueft[key] = materialize_data_uri_avatar(role_id, gespeichert) == wert
            if geprueft[key]:
                item[field] = gespeichert
        result.append(item)
    return result


def get_hermes_profiles_base_dirs() -> List[str]:
    """Liefert alle aktiven Hermes-Profil-Pfade (Container-Mounts und Host-Pfade)."""
    candidates = [
        HERMES_PROFILES_BASE,
        os.path.expanduser("~/.hermes/profiles"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "profiles")
    ]
    valid_dirs = []
    for c in candidates:
        if c and os.path.exists(c) and c not in valid_dirs:
            valid_dirs.append(c)
    if not valid_dirs:
        primary = HERMES_PROFILES_BASE if os.path.exists(OPT_DATA_DIR) else os.path.expanduser("~/.hermes/profiles")
        try:
            os.makedirs(primary, exist_ok=True)
        except Exception:
            pass
        valid_dirs.append(primary)
    return valid_dirs

def get_primary_hermes_profiles_dir() -> str:
    return get_hermes_profiles_base_dirs()[0]

_HERMES_PROFILES_CACHE = None
_HERMES_PROFILES_CACHE_TIME = 0.0
_HERMES_PROFILES_CACHE_MTIME = 0.0
_HERMES_PROFILES_CACHE_TTL = 300.0

def _compute_profiles_mtime() -> float:
    max_m = 0.0
    try:
        pdir = get_primary_hermes_profiles_dir()
        if os.path.exists(pdir):
            max_m = max(max_m, os.path.getmtime(pdir))
        ap_file = os.path.join(APP_ROOT, "agent_profiles.json")
        if os.path.exists(ap_file):
            max_m = max(max_m, os.path.getmtime(ap_file))
    except Exception:
        pass
    return max_m

try:
    _init_pfile = os.path.join(APP_ROOT, "agent_profiles.json")
    if os.path.exists(_init_pfile):
        with open(_init_pfile, "r", encoding="utf-8") as _f_init:
            _init_data = json.load(_f_init)
            if isinstance(_init_data, list) and len(_init_data) > 0:
                _HERMES_PROFILES_CACHE = _init_data
                _HERMES_PROFILES_CACHE_TIME = time.time()
                logger.info(f"[Profiles] Fast pre-warm cache loaded {len(_HERMES_PROFILES_CACHE)} profiles.")
except Exception as _e_init:
    logger.warning(f"[Profiles] Fast pre-warm warning: {_e_init}")

def invalidate_hermes_profiles_cache():
    global _HERMES_PROFILES_CACHE, _HERMES_PROFILES_CACHE_TIME, _HERMES_PROFILES_CACHE_MTIME
    _HERMES_PROFILES_CACHE = None
    _HERMES_PROFILES_CACHE_TIME = 0.0
    _HERMES_PROFILES_CACHE_MTIME = 0.0

def api_get_hermes_profiles():
    global _HERMES_PROFILES_CACHE, _HERMES_PROFILES_CACHE_TIME, _HERMES_PROFILES_CACHE_MTIME
    now = time.time()
    cur_mtime = _compute_profiles_mtime()
    if (
        _HERMES_PROFILES_CACHE is not None
        and (now - _HERMES_PROFILES_CACHE_TIME) < _HERMES_PROFILES_CACHE_TTL
        and (_HERMES_PROFILES_CACHE_MTIME == 0.0 or cur_mtime <= _HERMES_PROFILES_CACHE_MTIME)
    ):
        return _HERMES_PROFILES_CACHE

    HERMES_PROFILES_DIR = get_primary_hermes_profiles_dir()
    os.makedirs(HERMES_PROFILES_DIR, exist_ok=True)

    # F-20: lokale _APP_ROOT-Schattenkopie entfernt — der Mirror landete so in
    # archon/core/agent_profiles.json (im git versioniert), statt in der SSOT
    # agent_profiles.json im Repo-Root (APP_ROOT aus archon.core.runtime).
    json_fallback_map = {}
    for cand in [os.path.join(APP_ROOT, "agent_profiles.json"), "agent_profiles.json"]:
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    j_data = json.load(f)
                    if isinstance(j_data, list):
                        for item in j_data:
                            if isinstance(item, dict) and item.get("id"):
                                json_fallback_map[item["id"]] = item
                    break
            except Exception as e:
                logger.warning(f"[Profiles] Error loading fallback {cand}: {e}")

    # 2. Live-Verzeichnisse aus HERMES_PROFILES_DIR scannen (SSOT)
    subdirs = []
    if os.path.exists(HERMES_PROFILES_DIR):
        subdirs = [
            d for d in os.listdir(HERMES_PROFILES_DIR)
            if os.path.isdir(os.path.join(HERMES_PROFILES_DIR, d)) and not d.startswith(".")
        ]

    # SSOT: Wenn Verzeichnisse auf Disk existieren, bestimmen ausschließlich diese die aktiven Profile.
    if subdirs:
        active_profile_ids = subdirs
    else:
        active_profile_ids = list(json_fallback_map.keys())

    enriched_profiles = []
    for p_id in active_profile_ids:
        prof_dir = os.path.join(HERMES_PROFILES_DIR, p_id)
        os.makedirs(prof_dir, exist_ok=True)

        ydata = {}
        yaml_path = os.path.join(prof_dir, "profile.yaml")
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f) or {}
            except Exception as e:
                logger.warning(f"[Profiles] Error reading {yaml_path}: {e}")

        cdata = {}
        cfg_path = os.path.join(prof_dir, "config.yaml")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cdata = yaml.safe_load(f) or {}
            except Exception:
                pass

        soul_prompt = ""
        soul_path = os.path.join(prof_dir, "SOUL.md")
        if os.path.exists(soul_path):
            try:
                with open(soul_path, "r", encoding="utf-8", errors="ignore") as f:
                    soul_prompt = f.read().strip()
            except Exception:
                pass

        # Skills auflösen: Wenn profile.yaml explizit 'skills' definiert, ist das der SSOT
        skills_sub = os.path.join(prof_dir, "skills")
        fallback = json_fallback_map.get(p_id, {})
        active_skills = []
        if "skills" in ydata and isinstance(ydata.get("skills"), list):
            active_skills = list(ydata["skills"])
        else:
            if os.path.exists(skills_sub):
                discovered_in_folder = [
                    d for d in os.listdir(skills_sub)
                    if os.path.isdir(os.path.join(skills_sub, d)) and not d.startswith(".")
                ]
                discovered_files = [
                    os.path.splitext(f)[0] for f in os.listdir(skills_sub)
                    if os.path.isfile(os.path.join(skills_sub, f)) and f.endswith(".md") and not f.startswith(".")
                ]
                active_skills.extend(discovered_in_folder + discovered_files)
            if isinstance(fallback.get("skills"), list):
                active_skills.extend(fallback["skills"])
        active_skills = list(dict.fromkeys([s for s in active_skills if s]))

        # Attribute auflösen (YAML -> Disk -> JSON Fallback -> Defaults)
        name = ydata.get("name") or fallback.get("name") or p_id.replace("_", " ").title()
        person_name = ydata.get("person_name") or fallback.get("person_name") or fallback.get("display_name") or ydata.get("name") or fallback.get("name") or p_id
        category = ydata.get("category") or fallback.get("category") or "1. Strategie, Führung & Lebensplanung"
        description = ydata.get("description") or fallback.get("description") or (soul_prompt[:140] + "..." if soul_prompt else "")
        prompt = soul_prompt or ydata.get("prompt") or fallback.get("prompt") or fallback.get("system_prompt") or f"Du bist {person_name} ({name})."
        tools = ydata.get("tools") or fallback.get("tools") or DEFAULT_HERMES_TOOLS
        # Avatar-Auflösung. Vorrang hat der Eintrag im profile.yaml (er ist die
        # Quelle der Wahrheit und war faktisch schon vorher maßgeblich, weil die
        # Datei-Erkennung ins Leere lief); die Datei-Erkennung ist nur noch der
        # Fallback fuer Profile ohne Avatar-Eintrag.
        avatar_val = None
        cand_y = ydata.get("avatar") or ydata.get("avatar_url")
        cand_fb = fallback.get("avatar") or fallback.get("avatar_url")
        if cand_y:
            # Ein data:-URI ist der neueste Upload: er wird als Datei materialisiert,
            # statt 1,25 MB Base64 in jede Listen-Antwort zu legen. Schlaegt das fehl,
            # bleibt der Originalwert stehen (nie stillschweigend ein anderes Bild).
            avatar_val = materialize_data_uri_avatar(p_id, cand_y) or (
                cand_y if "dicebear.com" not in cand_y else None)
        if not avatar_val and cand_fb and "dicebear.com" not in cand_fb:
            avatar_val = cand_fb
        if not avatar_val:
            # Automatische Erkennung vorhandener Custom-Avatare: Laufzeitverzeichnis
            # zuerst, dann der versionierte Altbestand (resolve_avatar_file).
            for _ext in [".png", ".jpg", ".jpeg", ".webp"]:
                if resolve_avatar_file(f"custom_{p_id}{_ext}"):
                    avatar_val = f"/static/avatars/custom_{p_id}{_ext}"
                    break
        if not avatar_val:
            # Z-19: Deterministischer Fallback aus dem Katalog via SHA256 (PYTHONHASHSEED-unabhaengig)
            _h = int(hashlib.sha256(str(p_id).encode("utf-8")).hexdigest(), 16) % 108 + 1
            if _h == 1:
                _h = 2
            avatar_val = f"/static/avatars/avatar_{_h:03d}.jpg"
        
        provider = ydata.get("provider") or (cdata.get("model", {}).get("provider") if isinstance(cdata.get("model"), dict) else None) or fallback.get("provider", "omniroute")
        model = ydata.get("model") or (cdata.get("model", {}).get("default") if isinstance(cdata.get("model"), dict) else None) or fallback.get("model", "auto/best-free")
        reasoning_level = ydata.get("reasoning_level") or (ydata.get("llm", {}).get("reasoning_level") if isinstance(ydata.get("llm"), dict) else None) or fallback.get("reasoning_level", "high")
        status_val = ydata.get("status") or fallback.get("status", "active")
        is_fav = bool(ydata.get("is_favorite") if "is_favorite" in ydata else fallback.get("is_favorite", (p_id in ["default", "micha"])))
        callsign = ydata.get("callsign") or fallback.get("callsign") or ""
        if not callsign:
            if p_id == "executive_decision_architect":
                callsign = "robert"
            elif p_id in ("founder", "micha"):
                callsign = "micha"
        callsign = str(callsign).strip().lower()

        # Sonderbehandlung für default & micha
        if p_id in ["default", "hermes_default"]:
            p_id = "default"
            name = name or "Hermes Default (Root Engine)"
            person_name = person_name or "Hermes Orchestrator"
            is_fav = True
            if not (avatar_val and "avatar_" in avatar_val and "avatar_001.jpg" not in avatar_val):
                avatar_val = "/static/avatars/hermes_default_avatar.png"
            if not soul_prompt:
                prompt = prompt or "You are Hermes Agent, an intelligent AI assistant created by Nous Research. You are helpful, knowledgeable, and direct. You assist users with a wide range of tasks including answering questions, writing and editing code, analyzing information, creative work, and executing actions via your tools."
        elif p_id in ("founder", "micha"):
            name = name or "Michael Keller (Strategischer Leiter)"
            person_name = person_name or "Michael Keller"
            is_fav = True
            if not soul_prompt:
                prompt = prompt or "Du bist Michael Keller, der strategische Leiter und Architekt von Archon OS. Deine Aufgabe ist die strategische Gesamtausrichtung, Festlegung von Prioritäten und Koordination aller operativen Fachagenten."

        # Dateisystem auf Disk synchron halten
        if not os.path.exists(soul_path):
            try:
                with open(soul_path, "w", encoding="utf-8") as f:
                    f.write(prompt + "\n")
            except Exception:
                pass

        if not os.path.exists(yaml_path):
            try:
                y_payload = {
                    "name": name,
                    "person_name": person_name,
                    "category": category,
                    "description": description,
                    "role_id": p_id,
                    "avatar": avatar_val,
                    "avatar_url": avatar_val,
                    "tools": tools,
                    "skills": active_skills,
                    "status": status_val,
                    "is_favorite": is_fav,
                    "provider": provider,
                    "model": model
                }
                with open(yaml_path, "w", encoding="utf-8") as f:
                    yaml.dump(y_payload, f, allow_unicode=True, sort_keys=False)
            except Exception:
                pass

        profile_data = dict(fallback)
        profile_data.update({
            "id": p_id,
            "name": name,
            "person_name": person_name,
            "callsign": callsign,
            "category": category,
            "description": description,
            "prompt": prompt,
            "skills": active_skills,
            "tools": tools,
            "avatar": avatar_val,
            "avatar_url": avatar_val,
            "provider": provider,
            "model": model,
            "reasoning_level": reasoning_level,
            "status": status_val,
            "is_favorite": is_fav
        })
        enriched_profiles.append(profile_data)

    # Sortierung: default zuerst, micha als zweiter, danach alphabetisch nach Kategorie & Name
    def _sort_key(p):
        pid = p.get("id", "")
        if pid == "default":
            return (0, "")
        if pid == "micha":
            return (1, "")
        return (2, p.get("category", "") + "_" + p.get("name", ""))

    enriched_profiles.sort(key=_sort_key)

    _HERMES_PROFILES_CACHE = enriched_profiles
    _HERMES_PROFILES_CACHE_TIME = now

    # D-01: Der Leser darf den SSOT nicht bei jedem GET überschreiben und dabei
    # Felder wie current_task_id oder system_prompt verwerfen. Nur wenn die SSOT-Datei
    # gar nicht existiert, wird sie initial aus den Profilen angelegt.
    try:
        _ssot = os.path.join(APP_ROOT, "agent_profiles.json")
        if not os.path.exists(_ssot):
            new_json_str = json.dumps(enriched_profiles, indent=2, ensure_ascii=False)
            create_rolling_backup(_ssot, max_backups=3)
            with open(_ssot, "w", encoding="utf-8") as f:
                f.write(new_json_str)
        _HERMES_PROFILES_CACHE_MTIME = _compute_profiles_mtime()
    except Exception as e:
        logger.warning(f"[Profiles] Error initializing agent_profiles.json: {e}")

    return enriched_profiles

def create_rolling_backup(filepath: str, max_backups: int = 3):
    """
    Creates a rolling backup chain for filepath:
    .bak.2 -> .bak.3
    .bak.1 -> .bak.2
    .bak   -> .bak.1
    filepath -> .bak
    """
    if not filepath or not os.path.exists(filepath):
        return
    try:
        for i in range(max_backups - 1, 0, -1):
            src_bak = f"{filepath}.bak.{i}"
            dst_bak = f"{filepath}.bak.{i+1}"
            if os.path.exists(src_bak):
                try:
                    shutil.copy2(src_bak, dst_bak)
                except Exception:
                    pass
        primary_bak = f"{filepath}.bak"
        if os.path.exists(primary_bak):
            try:
                shutil.copy2(primary_bak, f"{filepath}.bak.1")
            except Exception:
                pass
        shutil.copy2(filepath, primary_bak)
    except Exception as e:
        logger.warning(f"[Rolling Backup] Could not create backup for {filepath}: {e}")


from pydantic import BaseModel

ALL_HERMES_TOOLS = [
    "web_search", "browser", "terminal", "filesystem", "execute_code", "vision_analyze",
    "video_analyze", "image_generate", "video_generate", "bfl_flux3", "x_search", "text_to_speech",
    "speech_to_text", "skills", "task_planning", "memory", "context_engine", "session_search",
    "clarify", "delegate_task", "cronjob", "home_assistant", "spotify", "discord",
    "discord_admin", "yuanbao", "computer_use", "a2a"
]


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


def save_all_agent_profiles(profiles_list: List[Dict[str, Any]]):
    import tempfile
    invalidate_hermes_profiles_cache()
    written_realpaths = set()

    def _atomic_write_json(target_path: str):
        abs_t = os.path.abspath(target_path)
        real_t = os.path.realpath(abs_t)
        if real_t in written_realpaths:
            return
        d = os.path.dirname(real_t)
        if d:
            os.makedirs(d, exist_ok=True)
        create_rolling_backup(real_t, max_backups=3)
        fd, tmp_p = tempfile.mkstemp(dir=d or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(profiles_list, f, indent=2, ensure_ascii=False)
            os.replace(tmp_p, real_t)
            written_realpaths.add(real_t)
        except Exception:
            if os.path.exists(tmp_p):
                os.unlink(tmp_p)
            raise

    # SSOT: Projekt-Wurzel immer primär schreiben.
    try:
        _ssot = os.path.join(APP_ROOT, "agent_profiles.json")
        _atomic_write_json(_ssot)
    except Exception as e:
        logger.error(f"[Save Profiles] Error writing SSOT agent_profiles.json: {e}")

    candidates = [
        os.path.join(MEMORY_DIR, "agent_profiles.json"),
        os.path.join(MEMORY_DIR, "roles.json"),
        "agent_profiles.json",
        "roles.json",
        "/app/agent_profiles.json",
        "/app/roles.json",
        os.path.join(APP_ROOT, "agent_workspace", "agent_profiles.json"),
        os.path.join(APP_ROOT, "agent_workspace", "roles.json"),
    ]
    for cand in candidates:
        try:
            _atomic_write_json(cand)
        except Exception:
            pass


__all__ = [
    "DEFAULT_HERMES_TOOLS", "ALL_HERMES_TOOLS", "AgentProfileValidationSchema",
    "get_hermes_profiles_base_dirs", "get_primary_hermes_profiles_dir",
    "invalidate_hermes_profiles_cache", "api_get_hermes_profiles",
    "create_rolling_backup", "save_all_agent_profiles", "_HERMES_PROFILES_CACHE",
]
