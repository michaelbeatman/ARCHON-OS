"""
api_provider.py — Hermes-nativer API-Provider-Manager für AgenticOS.

Kerngedanke (abgestimmt mit dem Benutzer):
    "Hermes Agent hat bereits die Mechanik — alle relevanten Provider und
     Keys stecken in seiner eigenen Konfiguration und seinen Caches. Eine
     separate Registry wäre Redundanz."

Deshalb liest dieses Modul die Provider & Modelle AUSSCHLIESSLICH aus
Hermes' eigenen Quellen (Source of Truth) und schreibt Konfig-Änderungen
über den kanonischen `hermes config set`-Mechanismus zurück:

  Provider/Modell-Katalog:
    - $HERMES_DATA/models_dev_cache.json      → ~190 Provider (id, name, env, api, models)
    - $HERMES_DATA/provider_models_cache.json → live geladene Modellliste je Provider
  Aktive Konfiguration (Source of Truth):
    - <profil>/config.yaml  (Modell: {default, provider, base_url})  ← wie `hermes config`
  Keys:
    - <profil>/.env (Secrets)

Der Mehrwert dieser Komponente gegenüber direktem `hermes config`:
  1. Ein Panel (Frontend) zum Ansehen & Umschalten von Provider/Modell.
  2. Die Verteilung der gefundenen Keys in ALLE Profil-".env"-Dateien
     (der eigentliche Paperclip-Fix: isolierte Sub-Shells finden Keys,
     weil sie in jedem Profilverzeichnis liegen) — dedupliciert & idempotent.
  3. Eine `hermes`-konforme Verifikation des gleichen "No API key"-Fehlers.

Nur stdlib → Import in main.py ODER eigenständiges CLI:

    python3 api_provider.py --providers
    python3 api_provider.py --models openrouter
    python3 api_provider.py --resolve "deepseek/deepseek-v4-flash-0731"
    python3 api_provider.py --status
    python3 api_provider.py --deploy --dry-run
    python3 api_provider.py --deploy
    python3 api_provider.py --set-provider openrouter --model "deepseek/deepseek-v4-flash-0731"
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# 0. Pfade
# ---------------------------------------------------------------------------

def _home() -> str:
    return os.environ.get("HERMES_HOME") or os.path.expanduser("~")

HOME = _home()

def _data_dir() -> str:
    env = os.environ.get("HERMES_DATA_DIR")
    if env:
        return env
    if os.path.isdir("/opt/data"):
        return "/opt/data"
    return os.path.join(HOME, ".hermes")

HERMES_DATA = _data_dir()

def _profiles_dir() -> str:
    env = os.environ.get("HERMES_PROFILES_DIR")
    if env:
        return env
    if os.path.isdir("/opt/data/profiles"):
        return "/opt/data/profiles"
    return os.path.join(HERMES_DATA, "profiles")

PROFILES_DIR = _profiles_dir()

def _hermes_cli() -> str:
    env = os.environ.get("HERMES_BIN")
    if env and os.path.exists(env):
        return env
    for cand in ("/opt/hermes/bin/hermes", "/opt/hermes-agent/hermes", shutil.which("hermes")):
        if cand and os.path.exists(cand):
            return cand
    return "hermes"

HERMES_CLI = _hermes_cli()

# Zentraler (aktueller) Profil-Config-Pfad — Hermes-typisch profilgebunden
def _active_config_path() -> str:
    env = os.environ.get("HERMES_CONFIG_YAML")
    if env:
        return env
    # 1) hermes_default-Profil (das, das gerade "aktiv" laut config show ist)
    cand = os.path.join(PROFILES_DIR, "hermes_default", "config.yaml")
    if os.path.exists(cand):
        return cand
    # 2) root config.yaml
    if os.path.exists(os.path.join(HERMES_DATA, "config.yaml")):
        return os.path.join(HERMES_DATA, "config.yaml")
    return cand

def _active_env_path() -> str:
    env = os.environ.get("HERMES_ENV_PATH")
    if env:
        return env
    return os.path.join(PROFILES_DIR, "hermes_default", ".env")

CONFIG_PATH = _active_config_path()
ENV_PATH = _active_env_path()

# ---------------------------------------------------------------------------
# 1. Hermes Caches lesen (Provider-Definitionen & Modelllisten)
# ---------------------------------------------------------------------------

def _load_json(path: str) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def load_provider_catalog() -> Dict[str, Any]:
    """models_dev_cache.json → ~190 Provider: {id: {id,name,env,api,models:{...}}}."""
    return _load_json(os.path.join(HERMES_DATA, "models_dev_cache.json"))


def load_provider_models() -> Dict[str, Dict[str, Any]]:
    """provider_models_cache.json → {provider: {fp, at, models:[...]}} (live geladen)."""
    return _load_json(os.path.join(HERMES_DATA, "provider_models_cache.json"))


def search_provider(pid: str) -> Optional[Dict[str, Any]]:
    return load_provider_catalog().get(pid) or None


def list_providers(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Plastik-list mit name/env/api/model_count für die UI (alphabetisch)."""
    cat = load_provider_catalog()
    out = []
    for pid, v in cat.items():
        if not isinstance(v, dict):
            continue
        out.append({
            "id": pid,
            "name": v.get("name", pid),
            "env": list(v.get("env", []) or []),
            "api": v.get("api"),
            "model_count": len(v.get("models", {}) or {}),
        })
    out.sort(key=lambda x: x["name"].lower())
    if limit:
        out = out[:limit]
    return out


def list_provider_models(pid: str) -> List[str]:
    """Gib dynamische oder gecachte Modelllisten für den ausgewählten Provider zurück."""
    norm_pid = (pid or "").strip().lower()

    if norm_pid == "omniroute":
        # 1. Live-Abfrage an lokalen OmniRoute-Container
        for url in ["http://omniroute:20128/v1/models", "http://127.0.0.1:20128/v1/models", "http://host.docker.internal:20128/v1/models"]:
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "ArchonOS"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        raw_models = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
                        # Bereinigen von kryptischen Guards
                        clean_models = [m for m in raw_models if "session-guard" not in m.lower()]
                        if clean_models:
                            # Priorisiere auto/* Router-Modelle nach oben
                            auto_routers = [m for m in clean_models if m.startswith("auto/") or m.startswith("omniroute/")]
                            other_models = [m for m in clean_models if not (m.startswith("auto/") or m.startswith("omniroute/"))]
                            return auto_routers + sorted(other_models)
            except Exception:
                pass
        return [
            "auto/best-coding", "auto/best-reasoning", "auto/best-vision", "auto/best-fast", "auto/best-chat",
            "deepseek-ai/DeepSeek-V4-Pro", "qwen/Qwen3.6-27B", "google/gemma-4-31B-it",
            "meta-llama/Llama-4-Scout-17B-16E-Instruct", "CohereLabs/command-a-vision-07-2025"
        ]

    # Bekannte Top-Modelle für Provider (inkl. Bild- und Vision-Modelle)
    popular_extras = {
        "openrouter": [
            "google/gemini-2.5-flash-image",
            "google/gemini-3.1-flash-image",
            "google/gemini-3-pro-image",
            "google/gemini-3.1-flash-lite-image",
            "openai/gpt-image-2",
            "openai/gpt-image-2.5-sunburst",
            "bytedance/seedream-4.5",
            "anthropic/claude-3.7-sonnet",
            "anthropic/claude-3.5-sonnet",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "deepseek/deepseek-chat",
            "meta-llama/llama-3.3-70b-instruct"
        ],
        "google": [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-image",
            "gemini-2.0-flash",
            "gemini-1.5-pro"
        ],
        "groq": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768"
        ],
        "openai": [
            "gpt-4o",
            "gpt-4o-mini",
            "o1",
            "o3-mini",
            "dall-e-3"
        ]
    }

    live = load_provider_models().get(norm_pid, {})
    live_models = list(live.get("models") or [])
    cat = load_provider_catalog().get(norm_pid, {})
    cat_models = list((cat.get("models") or {}).keys())

    combined_set = set(live_models + cat_models + popular_extras.get(norm_pid, []))
    if not combined_set and norm_pid in popular_extras:
        combined_set = set(popular_extras[norm_pid])

    # Wenn OpenRouter: Priorisiere beliebte Modelle + Bildmodelle an den Anfang
    if norm_pid == "openrouter":
        extras = popular_extras.get("openrouter", [])
        top_list = [m for m in extras if m in combined_set]
        remainder = sorted(list(combined_set - set(top_list)))
        return top_list + remainder

    return sorted(list(combined_set))


def provider_env_vars(pid: str) -> List[str]:
    p = search_provider(pid)
    if p:
        return list(p.get("env", []) or [])
    return [pid.upper() + "_API_KEY"]


def provider_api_url(pid: str) -> Optional[str]:
    p = search_provider(pid)
    return p.get("api") if p else None


# ---------------------------------------------------------------------------
# 2. Hermes-Konfiguration lesen/schreiben
#    Source of Truth: CONFIG_PATH (z.B. .../hermes_default/config.yaml)
#    Struktur model: {default, provider, base_url}
# ---------------------------------------------------------------------------

def read_active_config() -> Dict[str, Any]:
    """Liest model.* + api_block aus der Hermes config.yaml (YAML + indent-sicheres Fallback)."""
    info: Dict[str, Any] = {
        "model": None, "provider": None, "base_url": None, "api_mode": None,
        "path": CONFIG_PATH,
    }
    if not os.path.exists(CONFIG_PATH):
        return info
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return info

    # 1. Primärer YAML-Parser (verhindert Fehl-Treffer in späteren Blöcken wie plugins.entries)
    try:
        import yaml
        parsed = yaml.safe_load(content) or {}
        if isinstance(parsed, dict):
            m_obj = parsed.get("model")
            if isinstance(m_obj, dict):
                info["model"] = m_obj.get("default") or m_obj.get("name")
                info["provider"] = m_obj.get("provider")
                info["base_url"] = m_obj.get("base_url")
                info["api_mode"] = m_obj.get("api_mode")
            elif isinstance(m_obj, str) and m_obj.strip():
                info["model"] = m_obj.strip()
            for topkey in ("provider", "base_url"):
                if not info.get(topkey) and isinstance(parsed.get(topkey), str):
                    info[topkey] = parsed.get(topkey)
            if info.get("model"):
                return info
    except Exception:
        pass

    # 2. Indent-sicherer Regex-Fallback (stoppt beim nächsten Top-Level-Key ohne Einrückung)
    m = re.search(r"^model:\s*$", content, re.MULTILINE)
    if m:
        block = content[m.end():]
        for line in block.splitlines():
            if not line.strip() or line.strip().startswith("#"):
                continue
            if not line.startswith((" ", "\t")):
                break
            l = line.strip()
            km = re.match(r"^([\w-]+)\s*:\s*(.*)$", l)
            if km:
                k, v = km.group(1), km.group(2).strip().strip(chr(39) + chr(34)).strip()
                if not v:
                    continue
                if k == "default":
                    info["model"] = v
                elif k in ("provider", "base_url", "api_mode"):
                    info[k] = v
    # top-level Fallbacks (wenn model-Block fehlt)
    if info["model"] is None:
        tvm = _yaml_top_val(content, "model")
        if tvm:
            info["model"] = tvm
    for topkey in ("provider", "base_url"):
        tv = _yaml_top_val(content, topkey)
        if tv and info[topkey] is None:
            info[topkey] = tv
    return info


def _yaml_top_val(content: str, key: str) -> Optional[str]:
    m = re.search(rf"^{re.escape(key)}\s*:\s*(.*?)\s*$", content, re.MULTILINE)
    if not m:
        return None
    v = m.group(1).strip()
    if not v or v.startswith("#"):
        return None
    return v.strip("'\"")


def write_config_key(path: str, key: str, value: str) -> bool:
    """Setzt einen Top-Level-Key im Hermes-Config (key: value), idempotent."""
    lines: List[str] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            lines = []
    replaced = False
    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            out.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if re.match(rf"^{re.escape(key)}\s*:", stripped):
            if indent == 0:
                out.append(f"{key}: {value}")
                replaced = True
                continue
        out.append(line)
    if not replaced:
        out.append(f"{key}: {value}")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + ("\n" if out else ""))
        return True
    except Exception as e:
        print(f"Fehler beim Schreiben {path}: {e}", file=sys.stderr)
        return False


def infer_provider_from_model(model: str) -> Optional[str]:
    """Findet den Provider, der dieses Modell am besten liefert.
    Reihenfolge:
      1) Aktiver Hermes-Provider, falls das Modell dem aktuell konfigurierten entspricht
      2) Bekannte Organisations-Prae fix -> Provider Zuordnung
      3) Exakte Modell-ID im Katalog (viele generische Router listen alles; nur als Fallback)
    """
    if not model:
        return None
    model_l = model.lower()

    # 1) aktiver Hermes-Provider, wenn das Modell das aktive ist
    cfg = read_active_config()
    if cfg.get("model") and cfg["model"].lower() == model_l and cfg.get("provider"):
        return cfg["provider"]

    # 2) Organisation->Provider (bekannte Zuordnung; deepseek laeuft via openrouter)
    org = model_l.split("/")[0] if "/" in model_l else None
    org_map = {
        "openai": "openai", "gpt": "openai", "o1": "openai", "o3": "openai", "o4": "openai",
        "anthropic": "anthropic", "claude": "anthropic",
        "deepseek": "openrouter", "google": "google", "gemini": "google",
        "meta-llama": "openrouter", "mistralai": "openrouter", "mistral": "mistral",
        "qwen": "openrouter", "z-ai": "zai", "glm": "zai",
        "moonshot": "kimi", "kimi": "kimi", "minimax": "minimax",
    }
    if org:
        if org in org_map:
            return org_map[org]
        # wenn organisation == provider-id
        if search_provider(org):
            return org
    # fuer bare-Namen (ohne org) auch praefix pruefen
    for prefix, prov in [("claude", "anthropic"), ("gpt", "openai"), ("glm", "zai"),
                          ("gemini", "google"), ("deepseek", "openrouter"), ("o1", "openai"),
                          ("o3", "openai"), ("o4", "openai"), ("kimi", "kimi"),
                          ("minimax", "minimax")]:
        if model_l.startswith(prefix):
            return prov

    # 3) exakte Modell-ID im Katalog (Fallback)
    cat = load_provider_catalog()
    for pid, v in cat.items():
        if not isinstance(v, dict):
            continue
        models = v.get("models") or {}
        if isinstance(models, dict) and model_l in {str(k).lower() for k in models.keys()}:
            return pid
        if model_l in {str(m).lower() for m in (models if isinstance(models, list) else [])}:
            return pid
    live = load_provider_models()
    for pid, v in live.items():
        ms = v.get("models") or []
        if isinstance(ms, list) and model_l in {str(m).lower() for m in ms}:
            return pid
    return None


def _set_model_block(model: str, provider: str, base_url: Optional[str] = None,
                     config_path: Optional[str] = None) -> bool:
    """
    Schreibt den model-Block in CONFIG_PATH als:
      model:
        default: <model>
        provider: <provider>
        base_url: <base_url>
    Ersetzt einen evtl. vorhandenen model:-Block komplett.
    """
    path = config_path or CONFIG_PATH
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    lines: List[str] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            lines = []

    block = ["model:", f"  default: {model}", f"  provider: {provider}"]
    if base_url:
        block.append(f"  base_url: {base_url}")

    # Entferne bestehenden model-Block (bis nächster top-level key)
    out: List[str] = []
    in_model = False
    for line in lines:
        stripped = line.strip()
        if in_model:
            pass
        if re.match(r"^model:\s*$", stripped):
            in_model = True
            continue
        if in_model:
            # Wir sind im Modell-Block: alle eingerückten Folgezeilen verwerfen,
            # bis eine nicht-eingerückte Zeile beginnt (neuer top-level).
            if stripped and not line.startswith((" ", "\t")):
                in_model = False
                out.append(line)
            continue
        out.append(line)

    out.extend(block)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        return True
    except Exception as e:
        print(f"Fehler beim Schreiben model-Block: {e}", file=sys.stderr)
        return False


def set_provider_model(provider: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Set Provider + optional Modell im Hermes-Config (write model-block). Gibt Bericht."""
    if not model:
        # Modell nicht geändert → nur provider im model-block setzen
        cfg = read_active_config()
        model = cfg.get("model") or find_default_model_for_provider(provider)
    base_url = provider_api_url(provider)
    ok = _set_model_block(model or "", provider, base_url)
    return {"provider": provider, "model": model, "base_url": base_url, "ok": ok, "path": CONFIG_PATH}


def find_default_model_for_provider(pid: str) -> Optional[str]:
    """Wählt ein sinnvolles Standard-Modell für einen Provider (erstes aus Katalog/Livemodelle)."""
    live = list_provider_models(pid)
    return live[0] if live else None


# ---------------------------------------------------------------------------
# 3. Key-Management (Hermes-Env-Mapping; idempotent, Dedup)
# ---------------------------------------------------------------------------

def _format_env_path(path: str) -> str:
    return path

def read_env_value(path: str, key: str) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
    except Exception:
        return None
    return None


def set_env_value(path: str, key: str, value: str) -> bool:
    lines: List[str] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            lines = []
    replaced = False
    out: List[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            out.append(line)
            continue
        k, _, _ = s.partition("=")
        if k.strip() == key:
            if not replaced:
                out.append(f"{key}={value}")
                replaced = True
            continue  # Duplikate droppen
        out.append(line)
    if not replaced and value != "":
        out.append(f"{key}={value}")
        replaced = True
    if value == "":
        out = [l for l in out if not (l.strip().startswith(key + "="))]
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + ("\n" if out else ""))
        return True
    except Exception:
        return False


def dedupe_env_file(path: str) -> int:
    lines: List[str] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except Exception:
            return 0
    seen: set = set()
    removed = 0
    out: List[str] = []
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.partition("=")[0].strip()
            if k in seen:
                removed += 1
                continue
            seen.add(k)
        out.append(line)
    if removed:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(out) + ("\n" if out else ""))
        except Exception:
            pass
    return removed


def _read_flat_env(path: str) -> Dict[str, str]:
    """Alle KEY=value als dict (first wins)."""
    d: Dict[str, str] = {}
    if not path or not os.path.exists(path):
        return d
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                k = k.strip()
                if k and k not in d:
                    d[k] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return d


def collect_keys() -> Dict[str, str]:
    """env_var → Wert, Quelle: process env > zentrale .env > aktuelles profil-.env > profile-Sweep."""
    found: Dict[str, str] = {}
    # 1. process env / all provider env vars (best effort; wir sammeln nur was existiert)
    cat = load_provider_catalog()
    env_names = set()
    for pid, v in cat.items():
        if isinstance(v, dict):
            env_names.update(v.get("env", []) or [])
    for e in sorted(env_names):
        if os.environ.get(e):
            found[e] = os.environ[e]

    # 2. zentrale .env-Dateien
    for f in (os.path.join(HERMES_DATA, ".env"), os.path.join(HOME, ".env")):
        d = _read_flat_env(f)
        for k, v in d.items():
            if k.endswith(("_API_KEY", "_KEY", "_TOKEN")):
                found.setdefault(k, v)

    # 3. aktuelles Profil .env (höchste Relevanz)
    d = _read_flat_env(ENV_PATH)
    for k, v in d.items():
        if k.endswith(("_API_KEY", "_KEY", "_TOKEN")):
            found.setdefault(k, v)

    # 4. alle Profil-.env (wrongest → aber füllt fehlende)
    if os.path.isdir(PROFILES_DIR):
        for name in sorted(os.listdir(PROFILES_DIR)):
            ep = os.path.join(PROFILES_DIR, name, ".env")
            dd = _read_flat_env(ep)
            for k, v in dd.items():
                if k.endswith(("_API_KEY", "_KEY", "_TOKEN")):
                    found.setdefault(k, v)
    return found


def keys_for_provider(pid: str) -> Dict[str, str]:
    """Liefert die für einen Provider relevanten {env_var: wert}."""
    keys = collect_keys()
    vars_of = provider_env_vars(pid)
    return {v: keys[v] for v in vars_of if v in keys}


# ---------------------------------------------------------------------------
# 4. Verteiler (der eigentliche Paperclip-Fix)
# ---------------------------------------------------------------------------

def deploy_keys(dry_run: bool = True) -> Dict[str, Any]:
    """Verteilt alle gefundenen API-Keys in config + zentrale .env + ALLE Profil-.env."""
    keys = collect_keys()
    targets: List[str] = [ENV_PATH, os.path.join(HERMES_DATA, ".env")]
    if os.path.isdir(PROFILES_DIR):
        for name in sorted(os.listdir(PROFILES_DIR)):
            if os.path.isdir(os.path.join(PROFILES_DIR, name)):
                targets.append(os.path.join(PROFILES_DIR, name, ".env"))
    targets = list(dict.fromkeys(targets))  # dedupe

    report: Dict[str, Any] = {
        "status": "ok", "dry_run": dry_run,
        "keys_found": list(keys.keys()),
        "targets": len(targets),
        "writes": [],
    }
    if not keys:
        report["status"] = "no_keys_found"
        report["text"] = "Keine API-Keys im Hermes-Umfeld gefunden."
        return report

    for ep in targets:
        # config.yaml spielt hier keine Rolle; nur .env-Dateien
        for var, val in keys.items():
            set_env_value(ep, var, val)
        dedupe_env_file(ep)
        report["writes"].append({"path": ep, "keys": list(keys)})

    report["text"] = f"{len(keys)} Keys → {len(targets)} .env-Dateien verteilt."
    return report


# ---------------------------------------------------------------------------
# 5. Verifikation (Hermes-Check)
# ---------------------------------------------------------------------------

def verify_environment() -> Dict[str, Any]:
    """Reproduziert 'No API key' Check; Status + Prüfliste."""
    keys = collect_keys()
    cat = load_provider_catalog()
    # provider with at least one key
    providers_with: List[str] = []
    for pid, v in cat.items():
        if not isinstance(v, dict):
            continue
        envs = v.get("env", []) or []
        if any(keys.get(e) for e in envs):
            providers_with.append(v.get("name", pid))

    checks: List[Dict[str, Any]] = []
    if providers_with:
        checks.append({"level": "info", "code": "hermes_api_keys_found",
                       "message": "API keys found for: " + ", ".join(providers_with)})
    else:
        checks.append({"level": "warn", "code": "hermes_no_api_keys",
                       "message": "No LLM API keys found.", "hint": "Set keys in .env / Hermes config."})

    cfg = read_active_config()
    checks.append({"level": "info", "code": "hermes_model_config",
                   "message": f"model={cfg.get('model')}, provider={cfg.get('provider')}"})
    return {"status": "ok" if providers_with else "warn", "checks": checks,
            "keys_found": list(keys.keys()), "config": cfg}


# ---------------------------------------------------------------------------
# 6. CLI
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 8. Agent-Profil -> Modell-Kopplung (pro Hermes-Profil Modell setzen)
# ---------------------------------------------------------------------------



def list_real_hermes_profiles(profiles_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Listet die ECHTEN Hermes-Profile direkt aus den Profile-Ordnern (Source of Truth).

    Jedes Profil ist ein Ordner <profiles_dir>/<id>/ mit:
      - profile.yaml  -> name, category, description, role_id, avatar
      - config.yaml   -> model.{default, provider}
      - skills/       -> echte skill-Unterordner (ohne Verwaltungsdateien)
    Liefert sortiert nach name.
    """
    pd = profiles_dir or os.environ.get("HERMES_PROFILES_DIR") or os.path.join(HERMES_DATA, "profiles")
    if not pd or not os.path.isdir(pd):
        return []
    out: List[Dict[str, Any]] = []
    for entry in sorted(os.listdir(pd)):
        dpath = os.path.join(pd, entry)
        if not os.path.isdir(dpath) or entry.startswith("."):
            continue
        meta = {"name": entry, "person_name": "", "category": "", "description": "", "role_id": entry, "avatar": ""}
        py = os.path.join(dpath, "profile.yaml")
        if os.path.exists(py):
            try:
                with open(py, "r", encoding="utf-8") as f:
                    for line in f:
                        m = re.match(r'^(\w+)\s*:\s*(.*)$', line.strip())
                        if m:
                            k, v = m.group(1), m.group(2).strip().strip('"').strip("'")
                            if k in meta and v:
                                meta[k] = v
            except Exception:
                pass
        # Skills (echte Ordner, ohne "."-Dateien)
        sk = []
        skills_dir = os.path.join(dpath, "skills")
        if os.path.isdir(skills_dir):
            for e in sorted(os.listdir(skills_dir)):
                if not e.startswith(".") and os.path.isdir(os.path.join(skills_dir, e)):
                    sk.append(e)
        # config.yaml -> Modell
        cfg = read_profile_config(entry, pd)
        # description_long aus profile.yaml lesen (falls vorhanden) -> wird 'prompt'
        _dl = ""
        _ppy = py
        if os.path.exists(_ppy):
            try:
                with open(_ppy, "r", encoding="utf-8") as _f:
                    for _l in _f:
                        _m = re.match(r'^description_long\s*:\s*(.*)$', _l.strip())
                        if _m:
                            _dl = _m.group(1).strip().strip('"').strip("'")
            except Exception:
                pass
        pid = entry  # Ordnername ist der echte Profil-Ident (role_id kann kollidieren)
        out.append({
            "id": pid,
            "name": meta.get("name") or entry,
            "person_name": meta.get("person_name", ""),
            "category": meta.get("category", ""),
            "description": meta.get("description", ""),
            "skills": sk,
            "tools": ['web_search', 'browser', 'terminal', 'filesystem', 'execute_code', 'vision_analyze', 'image_generate', 'bfl_flux3', 'text_to_speech', 'speech_to_text', 'skills', 'task_planning', 'memory', 'session_search', 'clarify', 'delegate_task', 'cronjob', 'computer_use'],
            "prompt": _dl,
            "model": cfg.get("model"),
            "provider": cfg.get("provider"),
            "avatar": meta.get("avatar") or f"https://api.dicebear.com/7.x/notionists/svg?seed={pid}&backgroundColor=3b82f6",
        })
    return out



def profile_config_path(profile_id: str, profiles_dir: Optional[str] = None) -> str:
    """Pfad zur config.yaml eines Hermes-Profils (Profil-<id> unter PROFILES_DIR)."""
    if not profiles_dir:
        cand_dirs = [PROFILES_DIR, "/opt/data/profiles", os.path.join(HERMES_DATA, "profiles"), "/root/.hermes/profiles"]
        for cd in cand_dirs:
            if cd and os.path.isdir(os.path.join(cd, profile_id)):
                return os.path.join(cd, profile_id, "config.yaml")
    pd = profiles_dir or PROFILES_DIR
    return os.path.join(pd, profile_id, "config.yaml")


def read_profile_config(profile_id: str, profiles_dir: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Liest model/provider/base_url aus der config.yaml eines Profils (Hermes-Struktur)."""
    path = profile_config_path(profile_id, profiles_dir)
    info: Dict[str, Optional[str]] = {"model": None, "provider": None, "base_url": None,
                                      "path": path, "exists": os.path.exists(path)}
    if not os.path.exists(path):
        return info
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return info
    m = re.search(r"^model:\s*$", content, re.MULTILINE)
    if m:
        block = content[m.end():].split("\n\n")[0]
        for line in block.splitlines():
            l = line.strip()
            km = re.match(r"^(\w+)\s*:\s*(.*)$", l)
            if km:
                k, v = km.group(1), km.group(2).strip().strip(chr(39) + chr(34)).strip()
                if not v:
                    continue
                if k == "default":
                    info["model"] = v
                elif k in ("provider", "base_url"):
                    info[k] = v
    return info


def set_profile_model(profile_id: str, model: str, profiles_dir: Optional[str] = None, provider: Optional[str] = None) -> Dict[str, Any]:
    """Setzt das Modell (und Provider) fuer ein Hermes-Profil in dessen config.yaml."""
    path = profile_config_path(profile_id, profiles_dir)
    prov = provider or infer_provider_from_model(model)
    if not prov:
        prov = "openrouter"  # Fallback
    base_url = "http://omniroute:20128/v1" if prov == "omniroute" else provider_api_url(prov)
    # _set_model_block ist modul-global definiert (gleiche Datei)
    ok = _set_model_block(model, prov, base_url, config_path=path)
    return {"profile_id": profile_id, "model": model, "provider": prov,
            "base_url": base_url, "ok": ok, "path": path}


def list_profiles_with_model(agent_profiles_file: Optional[str] = None, use_real: bool = True) -> List[Dict[str, Any]]:
    """Liest Profil-Liste; mit use_real=True die ECHTEN Hermes-Profile aus den Ordnern."""
    if use_real and not agent_profiles_file:
        return list_real_hermes_profiles()

    # Kandidatenpfade: explizit, Projekt-CWD, MEMORY-Verzeichnis, /app
    candidates = []
    if agent_profiles_file:
        candidates.append(agent_profiles_file)
    base = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    candidates += [
        os.path.join(base, "agent_profiles.json"),
        os.path.join(os.getcwd(), "agent_profiles.json"),
        os.path.join(HERMES_DATA, "agent_profiles.json"),
        "agent_profiles.json",
        "/app/agent_profiles.json",
        os.path.join(HERMES_DATA, "roles.json"),
        os.path.join(base, "roles.json"),
    ]
    profiles: List[Dict[str, Any]] = []
    for cand in candidates:
        if os.path.exists(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list) and loaded:
                    profiles = loaded
                    break
            except Exception:
                continue
    out = []
    for pnt in profiles:
        pid = pnt.get("id", "")
        cfg = read_profile_config(pid)
        out.append({
            "id": pid,
            "name": pnt.get("name", pid),
            "person_name": pnt.get("person_name") or pnt.get("display_name") or "",
            "category": pnt.get("category", ""),
            "model": cfg.get("model"),
            "provider": cfg.get("provider"),
            "base_url": cfg.get("base_url"),
        })
    return out


def collect_profile_model_keys(agent_profiles_file: Optional[str] = None) -> Dict[str, Dict[str, Optional[str]]]:
    """Macht aus den Profilen ein dict id -> {model, provider}. Fuer CLI/UI."""
    return {p["id"]: {"model": p["model"], "provider": p["provider"]}
            for p in list_profiles_with_model(agent_profiles_file)}


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Hermes-nativer API Provider Manager")
    ap.add_argument("--providers", action="store_true", help="Liste Provider (aus models_dev_cache)")
    ap.add_argument("--models", metavar="PROVIDER", help="Modelle eines Providers")
    ap.add_argument("--status", action="store_true", help="Aktive Hermes-Config anzeigen")
    ap.add_argument("--resolve", metavar="MODEL", help="Modell → Provider auflösen")
    ap.add_argument("--deploy", action="store_true", help="Keys an alle .env verteilen")
    ap.add_argument("--dry-run", action="store_true", help="Simulation (default bei --deploy)")
    ap.add_argument("--no-dry-run", action="store_true", help="Echt schreiben")
    ap.add_argument("--set-provider", metavar="PROVIDER", help="Aktiven Provider setzen")
    ap.add_argument("--model", metavar="MODEL", help="Default-Modell (mit --set-provider)")
    args = ap.parse_args()

    if args.set_provider:
        r = set_provider_model(args.set_provider, args.model)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return

    if args.models:
        ms = list_provider_models(args.models)
        print(f"{args.models}: {len(ms)} Modelle")
        print("\n".join(ms[:30]))
        return

    if args.status:
        cfg = read_active_config()
        print(json.dumps({"config": cfg, "env_path": ENV_PATH, "config_path": CONFIG_PATH,
                          "cli": HERMES_CLI}, ensure_ascii=False, indent=2))
        return

    if args.providers:
        for p in list_providers():
            print(f"  {p['id']:<24} {p['name']:<28} env={','.join(p['env'])}  models={p['model_count']}")
        return

    if args.deploy:
        dry = not args.no_dry_run
        print(json.dumps(deploy_keys(dry_run=dry), ensure_ascii=False, indent=2))
        return

    # default: status
    print(json.dumps({"config": read_active_config()}, ensure_ascii=False, indent=2))
    return


if __name__ == "__main__":
    _cli()