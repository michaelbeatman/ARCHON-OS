from fastapi import Depends as _ArchonDepends
from archon.routers._rbac import forbid_viewer_writes as _forbid_viewer_writes
"""
Hermes Config & Live-Editor Router fuer Archon OS.
Verwaltet /api/hermes/settings und /api/hermes/raw_config (792 Zeilen).
Extrahiert aus main.py zur Modularisierung.
"""

import os
import sys
import json
import shutil
import yaml
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Body, Request
from archon.routers._rbac import require_admin_or_503
from archon.core.runtime import add_ticker, logger
from archon.core.paths import (
    HERMES_CONFIG_YAML,
    HERMES_PROFILES_BASE,
    HERMES_PROFILES_DIR,
    OPT_DATA_DIR,
    SETTINGS_FILE,
)
from archon.core.profiles import invalidate_hermes_profiles_cache
from backend.platform_paths import HERMES_HOME
from utils.path_jail import safe_path, PathJailError

_DEPS: Dict[str, Any] = {}

def configure(**deps: Any) -> None:
    """Registriert Dependencies (z.B. _sync_org_hierarchy_node)."""
    _DEPS.update(deps)

router = APIRouter(dependencies=[_ArchonDepends(_forbid_viewer_writes)], tags=["hermes-config"])


def _get_hermes_config_paths():
    base_dirs = [
        OPT_DATA_DIR,
        os.path.expanduser("~/.hermes"),
        HERMES_HOME
    ]
    found_configs = []
    active_path = None
    
    for b in base_dirs:
        if not os.path.exists(b):
            continue
            
        # 1. Global config is primary default
        glob_yaml = os.path.join(b, "config.yaml")
        if os.path.exists(glob_yaml):
            if glob_yaml not in found_configs:
                found_configs.append(glob_yaml)
            if not active_path:
                active_path = glob_yaml

        # 2. Profiles (default first, then others)
        prof_dir = os.path.join(b, "profiles")
        if os.path.exists(prof_dir):
            try:
                def_prof = os.path.join(prof_dir, "default", "config.yaml")
                if os.path.exists(def_prof) and def_prof not in found_configs:
                    found_configs.append(def_prof)
                for entry in sorted(os.listdir(prof_dir)):
                    pyaml = os.path.join(prof_dir, entry, "config.yaml")
                    if os.path.exists(pyaml) and pyaml not in found_configs:
                        found_configs.append(pyaml)
            except Exception:
                pass

    if not active_path and found_configs:
        active_path = found_configs[0]
    return active_path, found_configs


def _safe_config_target(path: Optional[str]) -> Optional[str]:
    """Validiert einen Hermes-Config-Pfad gegen das Konfig-Jail.

    Hermes-Konfigurationen duerfen ausschliesslich unter /opt/data, /app oder
    ~/.hermes liegen - nie irgendwo sonst im Dateisystem.
    """
    if not path:
        return None
    try:
        return safe_path(
            path,
            allow_write=True,
            allow_dirs=False,
            extra_roots=[OPT_DATA_DIR, "/app", os.path.expanduser("~/.hermes"), "/root/.hermes"],
        )
    except PathJailError as e:
        raise HTTPException(status_code=403, detail={"code": "hermes_config_path_not_allowed", "params": {"error": str(e)}})

@router.get("/api/hermes/settings")
def api_get_hermes_form_config(path: Optional[str] = None):
    import yaml
    active_path, all_configs = _get_hermes_config_paths()
    if path:
        target_path = _safe_config_target(path)
    else:
        target_path = active_path
    
    parsed = {}
    content = ""
    if target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
            parsed = yaml.safe_load(content) or {}
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception as e:
            logger.error(f"Fehler beim Parsen von {target_path}: {e}")
            parsed = {}

    model_obj = parsed.get("model", {}) if isinstance(parsed.get("model"), dict) else {}
    agent_obj = parsed.get("agent", {}) if isinstance(parsed.get("agent"), dict) else {}
    disp_obj = parsed.get("display", {}) if isinstance(parsed.get("display"), dict) else {}
    dash_obj = parsed.get("dashboard", {}) if isinstance(parsed.get("dashboard"), dict) else {}
    stream_obj = parsed.get("streaming", {}) if isinstance(parsed.get("streaming"), dict) else {}
    gw_obj = parsed.get("gateway", {}) if isinstance(parsed.get("gateway"), dict) else {}
    plat_obj = parsed.get("platforms", {}) if isinstance(parsed.get("platforms"), dict) else {}
    a2a_obj = plat_obj.get("a2a", {}) if isinstance(plat_obj.get("a2a"), dict) else {}
    tg_obj = plat_obj.get("telegram", {}) if isinstance(plat_obj.get("telegram"), dict) else {}
    wh_obj = plat_obj.get("webhook", {}) if isinstance(plat_obj.get("webhook"), dict) else {}
    api_srv_obj = plat_obj.get("api_server", {}) if isinstance(plat_obj.get("api_server"), dict) else {}
    stt_obj = parsed.get("stt", {}) if isinstance(parsed.get("stt"), dict) else {}
    stt_groq = stt_obj.get("groq", {}) if isinstance(stt_obj.get("groq"), dict) else {}
    stt_openai = stt_obj.get("openai", {}) if isinstance(stt_obj.get("openai"), dict) else {}
    stt_local = stt_obj.get("local", {}) if isinstance(stt_obj.get("local"), dict) else {}
    voice_obj = parsed.get("voice", {}) if isinstance(parsed.get("voice"), dict) else {}
    term_obj = parsed.get("terminal", {}) if isinstance(parsed.get("terminal"), dict) else {}
    code_obj = parsed.get("code_execution", {}) if isinstance(parsed.get("code_execution"), dict) else {}
    loop_obj = parsed.get("tool_loop_guardrails", {}) if isinstance(parsed.get("tool_loop_guardrails"), dict) else {}
    warn_after = loop_obj.get("warn_after", {}) if isinstance(loop_obj.get("warn_after"), dict) else {}
    stop_after = loop_obj.get("hard_stop_after", {}) if isinstance(loop_obj.get("hard_stop_after"), dict) else {}
    comp_obj = parsed.get("compression", {}) if isinstance(parsed.get("compression"), dict) else {}
    pcache_obj = parsed.get("prompt_caching", {}) if isinstance(parsed.get("prompt_caching"), dict) else {}
    mem_obj = parsed.get("memory", {}) if isinstance(parsed.get("memory"), dict) else {}
    sreset_obj = parsed.get("session_reset", {}) if isinstance(parsed.get("session_reset"), dict) else {}
    skills_obj = parsed.get("skills", {}) if isinstance(parsed.get("skills"), dict) else {}
    deleg_obj = parsed.get("delegation", {}) if isinstance(parsed.get("delegation"), dict) else {}
    moa_obj = parsed.get("moa", {}) if isinstance(parsed.get("moa"), dict) else {}
    moa_agg = moa_obj.get("aggregator", {}) if isinstance(moa_obj.get("aggregator"), dict) else {}
    aux_obj = parsed.get("auxiliary", {}) if isinstance(parsed.get("auxiliary"), dict) else {}
    aux_vis = aux_obj.get("vision", {}) if isinstance(aux_obj.get("vision"), dict) else {}
    aux_web = aux_obj.get("web_extract", {}) if isinstance(aux_obj.get("web_extract"), dict) else {}
    brow_obj = parsed.get("browser", {}) if isinstance(parsed.get("browser"), dict) else {}
    tools_obj = parsed.get("tools", {}) if isinstance(parsed.get("tools"), dict) else {}
    tsearch_obj = tools_obj.get("tool_search", {}) if isinstance(tools_obj.get("tool_search"), dict) else {}
    upd_obj = parsed.get("updates", {}) if isinstance(parsed.get("updates"), dict) else {}

    settings = {
        # Sektion 1: Modell & Provider
        "model_default": model_obj.get("default", "z-ai/glm-5.3"),
        "model_provider": model_obj.get("provider", "openrouter"),
        "base_url": model_obj.get("base_url", ""),
        # Sektion 2: Agenten-Kognition & Limits
        "reasoning_effort": agent_obj.get("reasoning_effort", "medium"),
        "max_context_tokens": agent_obj.get("max_context_tokens", 32000),
        "max_history_messages": agent_obj.get("max_history_messages", 20),
        "task_timeout_seconds": agent_obj.get("task_timeout_seconds", 60),
        "max_turns": agent_obj.get("max_turns", 60),
        "verify_on_stop": agent_obj.get("verify_on_stop", False),
        "verbose": agent_obj.get("verbose", False),
        # Sektion 3: Anzeige, Streaming & Dashboard
        "language": disp_obj.get("language", "de"),
        "reasoning_full": disp_obj.get("reasoning_full", disp_obj.get("show_reasoning", True)),
        "show_cost": disp_obj.get("show_cost", True),
        "timestamps": disp_obj.get("timestamps", True),
        "bell_on_complete": disp_obj.get("bell_on_complete", True),
        "compact": disp_obj.get("compact", True),
        "streaming_enabled": disp_obj.get("streaming", stream_obj.get("enabled", True)),
        "busy_input_mode": disp_obj.get("busy_input_mode", "interrupt"),
        "interim_assistant_messages": disp_obj.get("interim_assistant_messages", True),
        "background_process_notifications": disp_obj.get("background_process_notifications", "all"),
        "tool_progress": disp_obj.get("tool_progress", "all"),
        "long_running_notifications": disp_obj.get("long_running_notifications", True),
        "cleanup_progress": disp_obj.get("cleanup_progress", False),
        "timestamp_format": disp_obj.get("timestamp_format", "%H:%M:%S"),
        "skin": disp_obj.get("skin", "coffee-shop"),
        "dashboard_theme": dash_obj.get("theme", disp_obj.get("dashboard_theme", "boring-light")),
        # Sektion 4: Gateway, Multiplexing & Plattformen
        "multiplex_profiles": gw_obj.get("multiplex_profiles", True),
        "a2a_enabled": a2a_obj.get("enabled", True),
        "telegram_enabled": tg_obj.get("enabled", True),
        "webhook_enabled": wh_obj.get("enabled", True),
        "api_server_enabled": api_srv_obj.get("enabled", False),
        "group_sessions_per_user": parsed.get("group_sessions_per_user", True),
        # Sektion 5: Befehls-Allowlist & Code-Execution
        "command_allowlist": parsed.get("command_allowlist", ["script execution via heredoc", "execute_code"]) if isinstance(parsed.get("command_allowlist"), list) else [],
        "code_max_tool_calls": code_obj.get("max_tool_calls", 50),
        "code_timeout": code_obj.get("timeout", 300),
        # Sektion 6: Terminal-Backend & Container-Grenzwerte
        "terminal_backend": term_obj.get("backend", "local"),
        "terminal_cwd": term_obj.get("cwd", "."),
        "terminal_timeout": term_obj.get("timeout", 180),
        "terminal_home_mode": term_obj.get("home_mode", "auto"),
        "terminal_container_cpu": term_obj.get("container_cpu", 1),
        "terminal_container_memory": term_obj.get("container_memory", 5120),
        "terminal_container_disk": term_obj.get("container_disk", 51200),
        "terminal_container_persistent": term_obj.get("container_persistent", True),
        "terminal_docker_mount_cwd": term_obj.get("docker_mount_cwd_to_workspace", False),
        "terminal_lifetime_seconds": term_obj.get("lifetime_seconds", 300),
        # Sektion 7: Native Tool-Loop-Guardrails
        "loop_warnings_enabled": loop_obj.get("warnings_enabled", True),
        "loop_hard_stop_enabled": loop_obj.get("hard_stop_enabled", False),
        "warn_exact_failure": warn_after.get("exact_failure", 2),
        "warn_same_tool_failure": warn_after.get("same_tool_failure", 3),
        "warn_idempotent_no_progress": warn_after.get("idempotent_no_progress", 2),
        "stop_exact_failure": stop_after.get("exact_failure", 5),
        "stop_same_tool_failure": stop_after.get("same_tool_failure", 8),
        "stop_idempotent_no_progress": stop_after.get("idempotent_no_progress", 5),
        # Sektion 8: Kontext-Kompression & Prompt-Caching
        "compression_enabled": comp_obj.get("enabled", True),
        "compression_threshold": comp_obj.get("threshold", 0.5),
        "compression_target_ratio": comp_obj.get("target_ratio", 0.2),
        "compression_protect_last_n": comp_obj.get("protect_last_n", 20),
        "compression_protect_first_n": comp_obj.get("protect_first_n", 3),
        "compression_codex_autoraise": comp_obj.get("codex_gpt55_autoraise", True),
        "prompt_cache_ttl": pcache_obj.get("cache_ttl", "5m"),
        # Sektion 9: Hermes Memory, Session-Reset & Skill-Synthese
        "memory_enabled": mem_obj.get("memory_enabled", True),
        "user_profile_enabled": mem_obj.get("user_profile_enabled", True),
        "memory_char_limit": mem_obj.get("memory_char_limit", 2200),
        "user_char_limit": mem_obj.get("user_char_limit", 1375),
        "memory_flush_min_turns": mem_obj.get("flush_min_turns", 6),
        "memory_nudge_interval": mem_obj.get("nudge_interval", 10),
        "session_reset_mode": sreset_obj.get("mode", "both"),
        "session_reset_at_hour": sreset_obj.get("at_hour", 4),
        "session_reset_idle_minutes": sreset_obj.get("idle_minutes", 1440),
        "skills_creation_nudge_interval": skills_obj.get("creation_nudge_interval", 15),
        # Sektion 10: Subagenten-Delegation & Mixture-of-Agents (MoA)
        "delegation_max_iterations": deleg_obj.get("max_iterations", 50),
        "delegation_max_concurrent_children": deleg_obj.get("max_concurrent_children", 5),
        "moa_enabled": moa_obj.get("enabled", True),
        "moa_fanout": moa_obj.get("fanout", "user_turn"),
        "moa_max_tokens": moa_obj.get("max_tokens", 4096),
        "moa_degraded_policy": moa_obj.get("degraded_reference_policy", "loud"),
        "moa_aggregator_provider": moa_agg.get("provider", "custom:omniroute:20128"),
        "moa_aggregator_model": moa_agg.get("model", "auto/best-free"),
        # Sektion 11: Hilfsmodelle (Vision & Web-Extract)
        "aux_vision_provider": aux_vis.get("provider", "custom:Omniroute:20128"),
        "aux_vision_model": aux_vis.get("model", ""),
        "aux_web_provider": aux_web.get("provider", "auto"),
        "aux_web_model": aux_web.get("model", ""),
        # Sektion 12: Browser-Engine & Dynamische Tool-Suche
        "browser_inactivity_timeout": brow_obj.get("inactivity_timeout", 120),
        "browser_cloud_provider": brow_obj.get("cloud_provider", "local"),
        "browser_use_gateway": brow_obj.get("use_gateway", False),
        "tool_search_enabled": str(tsearch_obj.get("enabled", "on")),
        "tool_search_threshold_pct": tsearch_obj.get("threshold_pct", 0),
        "tool_search_limit": tsearch_obj.get("search_default_limit", 5),
        "tool_search_listing": str(tsearch_obj.get("listing", "off")),
        # Sektion 13: Sprachausgabe (Voice / TTS) & Spracherkennung (STT)
        "stt_enabled": stt_obj.get("enabled", True),
        "stt_provider": stt_obj.get("provider", "groq"),
        "stt_language": stt_obj.get("language", "de"),
        "stt_groq_model": stt_groq.get("model", "whisper-large-v3"),
        "stt_openai_model": stt_openai.get("model", "whisper-1"),
        "stt_local_model": stt_local.get("model", "base"),
        "voice_auto_tts": voice_obj.get("auto_tts", False),
        # Sektion 14: Update-Sicherheit & Konfigurations-Backups
        "updates_pre_backup": upd_obj.get("pre_update_backup", False),
        "updates_backup_keep": upd_obj.get("backup_keep", 5),
        "updates_local_changes": upd_obj.get("non_interactive_local_changes", "stash")
    }

    try:
        from utils.secret_files import mask_yaml_secrets
        _masked_raw = mask_yaml_secrets(content)
    except Exception:
        _masked_raw = content
    return {
        "active_path": active_path,
        "loaded_path": target_path,
        "available_configs": all_configs,
        "settings": settings,
        "raw_yaml": _masked_raw,
        "secrets_masked": _masked_raw != content
    }

@router.post("/api/hermes/settings")
def api_save_hermes_form_config(request: Request, payload: dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import yaml, shutil
    target_path = payload.get("config_path")
    settings = payload.get("settings", {})
    
    if not target_path:
        active_path, _ = _get_hermes_config_paths()
        target_path = active_path

    if not target_path:
        raise HTTPException(status_code=400, detail={"code": "hermes_config_no_path", "params": {}})

    target_path = _safe_config_target(target_path)
    if not target_path:
        raise HTTPException(status_code=400, detail={"code": "hermes_config_invalid_path", "params": {}})

    existing_data = {}
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                existing_data = yaml.safe_load(f.read()) or {}
                if not isinstance(existing_data, dict):
                    existing_data = {}
        except Exception:
            existing_data = {}

    def _ensure_dict(parent: dict, key: str) -> dict:
        if not isinstance(parent.get(key), dict):
            parent[key] = {}
        return parent[key]

    # Sektion 1: Modell
    m_dict = _ensure_dict(existing_data, "model")
    if "model_default" in settings:
        m_dict["default"] = str(settings["model_default"]).strip()
    if "model_provider" in settings:
        m_dict["provider"] = str(settings["model_provider"]).strip()
    if "base_url" in settings:
        b_url = str(settings["base_url"]).strip()
        if b_url:
            m_dict["base_url"] = b_url
        elif "base_url" in m_dict:
            del m_dict["base_url"]

    # Sektion 2: Agent
    a_dict = _ensure_dict(existing_data, "agent")
    if "reasoning_effort" in settings:
        a_dict["reasoning_effort"] = str(settings["reasoning_effort"]).strip()
    for int_key in ("max_context_tokens", "max_history_messages", "task_timeout_seconds", "max_turns"):
        if int_key in settings:
            try:
                a_dict[int_key] = int(settings[int_key])
            except Exception:
                pass
    for bool_key in ("verify_on_stop", "verbose"):
        if bool_key in settings:
            a_dict[bool_key] = bool(settings[bool_key])

    # Sektion 3: Display, Streaming & Dashboard
    d_dict = _ensure_dict(existing_data, "display")
    for str_key in ("language", "busy_input_mode", "background_process_notifications", "tool_progress", "timestamp_format", "skin"):
        if str_key in settings:
            d_dict[str_key] = str(settings[str_key]).strip()
    for bool_key in ("reasoning_full", "show_cost", "timestamps", "bell_on_complete", "compact", "interim_assistant_messages", "long_running_notifications", "cleanup_progress"):
        if bool_key in settings:
            d_dict[bool_key] = bool(settings[bool_key])
    if "reasoning_full" in settings:
        d_dict["show_reasoning"] = bool(settings["reasoning_full"])
    if "streaming_enabled" in settings:
        d_dict["streaming"] = bool(settings["streaming_enabled"])
        _ensure_dict(existing_data, "streaming")["enabled"] = bool(settings["streaming_enabled"])
    if "dashboard_theme" in settings:
        d_dict["dashboard_theme"] = str(settings["dashboard_theme"]).strip()
        _ensure_dict(existing_data, "dashboard")["theme"] = str(settings["dashboard_theme"]).strip()

    # Sektion 4: Gateway & Plattformen
    gw_dict = _ensure_dict(existing_data, "gateway")
    if "multiplex_profiles" in settings:
        gw_dict["multiplex_profiles"] = bool(settings["multiplex_profiles"])
    pl_dict = _ensure_dict(existing_data, "platforms")
    if "a2a_enabled" in settings:
        _ensure_dict(pl_dict, "a2a")["enabled"] = bool(settings["a2a_enabled"])
    if "telegram_enabled" in settings:
        _ensure_dict(pl_dict, "telegram")["enabled"] = bool(settings["telegram_enabled"])
    if "webhook_enabled" in settings:
        _ensure_dict(pl_dict, "webhook")["enabled"] = bool(settings["webhook_enabled"])
    if "api_server_enabled" in settings:
        _ensure_dict(pl_dict, "api_server")["enabled"] = bool(settings["api_server_enabled"])
    if "group_sessions_per_user" in settings:
        existing_data["group_sessions_per_user"] = bool(settings["group_sessions_per_user"])

    # Sektion 5: Allowlist & Code-Execution
    if "command_allowlist" in settings and isinstance(settings["command_allowlist"], list):
        existing_data["command_allowlist"] = settings["command_allowlist"]
    ce_dict = _ensure_dict(existing_data, "code_execution")
    if "code_max_tool_calls" in settings:
        try:
            ce_dict["max_tool_calls"] = int(settings["code_max_tool_calls"])
        except Exception:
            pass
    if "code_timeout" in settings:
        try:
            ce_dict["timeout"] = int(settings["code_timeout"])
        except Exception:
            pass

    # Sektion 6: Terminal & Container
    t_dict = _ensure_dict(existing_data, "terminal")
    for s_k, y_k in (("terminal_backend", "backend"), ("terminal_cwd", "cwd"), ("terminal_home_mode", "home_mode")):
        if s_k in settings:
            t_dict[y_k] = str(settings[s_k]).strip()
    for s_k, y_k in (("terminal_timeout", "timeout"), ("terminal_container_memory", "container_memory"), ("terminal_container_disk", "container_disk"), ("terminal_lifetime_seconds", "lifetime_seconds")):
        if s_k in settings:
            try:
                t_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    if "terminal_container_cpu" in settings:
        try:
            t_dict["container_cpu"] = float(settings["terminal_container_cpu"])
        except Exception:
            pass
    if "terminal_container_persistent" in settings:
        t_dict["container_persistent"] = bool(settings["terminal_container_persistent"])
    if "terminal_docker_mount_cwd" in settings:
        t_dict["docker_mount_cwd_to_workspace"] = bool(settings["terminal_docker_mount_cwd"])

    # Sektion 7: Tool-Loop-Guardrails
    lg_dict = _ensure_dict(existing_data, "tool_loop_guardrails")
    if "loop_warnings_enabled" in settings:
        lg_dict["warnings_enabled"] = bool(settings["loop_warnings_enabled"])
    if "loop_hard_stop_enabled" in settings:
        lg_dict["hard_stop_enabled"] = bool(settings["loop_hard_stop_enabled"])
    wa_dict = _ensure_dict(lg_dict, "warn_after")
    for s_k, y_k in (("warn_exact_failure", "exact_failure"), ("warn_same_tool_failure", "same_tool_failure"), ("warn_idempotent_no_progress", "idempotent_no_progress")):
        if s_k in settings:
            try:
                wa_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    sa_dict = _ensure_dict(lg_dict, "hard_stop_after")
    for s_k, y_k in (("stop_exact_failure", "exact_failure"), ("stop_same_tool_failure", "same_tool_failure"), ("stop_idempotent_no_progress", "idempotent_no_progress")):
        if s_k in settings:
            try:
                sa_dict[y_k] = int(settings[s_k])
            except Exception:
                pass

    # Sektion 8: Kontext-Kompression & Prompt-Caching
    cp_dict = _ensure_dict(existing_data, "compression")
    if "compression_enabled" in settings:
        cp_dict["enabled"] = bool(settings["compression_enabled"])
    for s_k, y_k in (("compression_threshold", "threshold"), ("compression_target_ratio", "target_ratio")):
        if s_k in settings:
            try:
                cp_dict[y_k] = float(settings[s_k])
            except Exception:
                pass
    for s_k, y_k in (("compression_protect_last_n", "protect_last_n"), ("compression_protect_first_n", "protect_first_n")):
        if s_k in settings:
            try:
                cp_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    if "compression_codex_autoraise" in settings:
        cp_dict["codex_gpt55_autoraise"] = bool(settings["compression_codex_autoraise"])
    if "prompt_cache_ttl" in settings:
        _ensure_dict(existing_data, "prompt_caching")["cache_ttl"] = str(settings["prompt_cache_ttl"]).strip()

    # Sektion 9: Memory, Session-Reset & Skills
    mm_dict = _ensure_dict(existing_data, "memory")
    for s_k in ("memory_enabled", "user_profile_enabled"):
        if s_k in settings:
            mm_dict[s_k] = bool(settings[s_k])
    for s_k, y_k in (("memory_char_limit", "memory_char_limit"), ("user_char_limit", "user_char_limit"), ("memory_flush_min_turns", "flush_min_turns"), ("memory_nudge_interval", "nudge_interval")):
        if s_k in settings:
            try:
                mm_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    sr_dict = _ensure_dict(existing_data, "session_reset")
    if "session_reset_mode" in settings:
        sr_dict["mode"] = str(settings["session_reset_mode"]).strip()
    for s_k, y_k in (("session_reset_at_hour", "at_hour"), ("session_reset_idle_minutes", "idle_minutes")):
        if s_k in settings:
            try:
                sr_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    if "skills_creation_nudge_interval" in settings:
        try:
            _ensure_dict(existing_data, "skills")["creation_nudge_interval"] = int(settings["skills_creation_nudge_interval"])
        except Exception:
            pass

    # Sektion 10: Delegation & MoA
    dl_dict = _ensure_dict(existing_data, "delegation")
    for s_k, y_k in (("delegation_max_iterations", "max_iterations"), ("delegation_max_concurrent_children", "max_concurrent_children")):
        if s_k in settings:
            try:
                dl_dict[y_k] = int(settings[s_k])
            except Exception:
                pass
    moa_dict = _ensure_dict(existing_data, "moa")
    if "moa_enabled" in settings:
        moa_dict["enabled"] = bool(settings["moa_enabled"])
    if "moa_fanout" in settings:
        moa_dict["fanout"] = str(settings["moa_fanout"]).strip()
    if "moa_max_tokens" in settings:
        try:
            moa_dict["max_tokens"] = int(settings["moa_max_tokens"])
        except Exception:
            pass
    if "moa_degraded_policy" in settings:
        moa_dict["degraded_reference_policy"] = str(settings["moa_degraded_policy"]).strip()
    moa_agg_dict = _ensure_dict(moa_dict, "aggregator")
    if "moa_aggregator_provider" in settings:
        moa_agg_dict["provider"] = str(settings["moa_aggregator_provider"]).strip()
    if "moa_aggregator_model" in settings:
        moa_agg_dict["model"] = str(settings["moa_aggregator_model"]).strip()

    # Sektion 11: Auxiliary (Vision & Web)
    aux_dict = _ensure_dict(existing_data, "auxiliary")
    vis_dict = _ensure_dict(aux_dict, "vision")
    if "aux_vision_provider" in settings:
        vis_dict["provider"] = str(settings["aux_vision_provider"]).strip()
    if "aux_vision_model" in settings:
        vis_dict["model"] = str(settings["aux_vision_model"]).strip()
    web_dict = _ensure_dict(aux_dict, "web_extract")
    if "aux_web_provider" in settings:
        web_dict["provider"] = str(settings["aux_web_provider"]).strip()
    if "aux_web_model" in settings:
        web_dict["model"] = str(settings["aux_web_model"]).strip()

    # Sektion 12: Browser & Tool-Search
    br_dict = _ensure_dict(existing_data, "browser")
    if "browser_inactivity_timeout" in settings:
        try:
            br_dict["inactivity_timeout"] = int(settings["browser_inactivity_timeout"])
        except Exception:
            pass
    if "browser_cloud_provider" in settings:
        br_dict["cloud_provider"] = str(settings["browser_cloud_provider"]).strip()
    if "browser_use_gateway" in settings:
        br_dict["use_gateway"] = bool(settings["browser_use_gateway"])
    ts_dict = _ensure_dict(_ensure_dict(existing_data, "tools"), "tool_search")
    if "tool_search_enabled" in settings:
        ts_dict["enabled"] = str(settings["tool_search_enabled"]).strip()
    if "tool_search_threshold_pct" in settings:
        try:
            ts_dict["threshold_pct"] = int(settings["tool_search_threshold_pct"])
        except Exception:
            pass
    if "tool_search_limit" in settings:
        try:
            ts_dict["search_default_limit"] = int(settings["tool_search_limit"])
        except Exception:
            pass
    if "tool_search_listing" in settings:
        ts_dict["listing"] = str(settings["tool_search_listing"]).strip()

    # Sektion 13: STT & Voice
    stt_dict = _ensure_dict(existing_data, "stt")
    if "stt_enabled" in settings:
        stt_dict["enabled"] = bool(settings["stt_enabled"])
    if "stt_provider" in settings:
        stt_dict["provider"] = str(settings["stt_provider"]).strip()
    if "stt_language" in settings:
        stt_dict["language"] = str(settings["stt_language"]).strip()
        _ensure_dict(stt_dict, "groq")["language"] = str(settings["stt_language"]).strip()
    if "stt_groq_model" in settings:
        _ensure_dict(stt_dict, "groq")["model"] = str(settings["stt_groq_model"]).strip()
    if "stt_openai_model" in settings:
        _ensure_dict(stt_dict, "openai")["model"] = str(settings["stt_openai_model"]).strip()
    if "stt_local_model" in settings:
        _ensure_dict(stt_dict, "local")["model"] = str(settings["stt_local_model"]).strip()
    if "voice_auto_tts" in settings:
        _ensure_dict(existing_data, "voice")["auto_tts"] = bool(settings["voice_auto_tts"])

    # Sektion 14: Updates
    up_dict = _ensure_dict(existing_data, "updates")
    if "updates_pre_backup" in settings:
        up_dict["pre_update_backup"] = bool(settings["updates_pre_backup"])
    if "updates_backup_keep" in settings:
        try:
            up_dict["backup_keep"] = int(settings["updates_backup_keep"])
        except Exception:
            pass
    if "updates_local_changes" in settings:
        up_dict["non_interactive_local_changes"] = str(settings["updates_local_changes"]).strip()

    # BIDIREKTIONALE SYNCHRONISATION: Hermes (config.yaml) -> Archon Autonomie-Module (settings.json)
    try:
        from backend.autonomy_settings import save_autonomy_settings
        aut_sync = {}
        if "delegation_max_concurrent_children" in settings or "task_timeout_seconds" in settings:
            aut_sync["concurrency"] = {}
            if "delegation_max_concurrent_children" in settings:
                aut_sync["concurrency"]["max_concurrent_agents"] = int(settings["delegation_max_concurrent_children"])
            if "task_timeout_seconds" in settings:
                aut_sync["concurrency"]["queue_timeout_seconds"] = int(settings["task_timeout_seconds"])
        if "stop_exact_failure" in settings or "max_turns" in settings or "loop_warnings_enabled" in settings:
            aut_sync["circuit_breaker"] = {}
            if "loop_warnings_enabled" in settings:
                aut_sync["circuit_breaker"]["loop_detection_enabled"] = bool(settings["loop_warnings_enabled"])
            if "stop_exact_failure" in settings:
                aut_sync["circuit_breaker"]["max_identical_turns"] = int(settings["stop_exact_failure"])
            if "max_turns" in settings:
                aut_sync["circuit_breaker"]["max_steps_per_task"] = int(settings["max_turns"])
        if "terminal_container_cpu" in settings or "terminal_timeout" in settings:
            aut_sync["ephemeral_sandbox"] = {}
            if "terminal_container_cpu" in settings:
                aut_sync["ephemeral_sandbox"]["cpu_limit"] = float(settings["terminal_container_cpu"])
            if "terminal_timeout" in settings:
                aut_sync["ephemeral_sandbox"]["timeout_seconds"] = int(settings["terminal_timeout"])
        if "compression_enabled" in settings or "compression_protect_last_n" in settings:
            aut_sync["context_compactor"] = {}
            if "compression_enabled" in settings:
                aut_sync["context_compactor"]["enabled"] = bool(settings["compression_enabled"])
            if "compression_protect_last_n" in settings:
                aut_sync["context_compactor"]["keep_recent_turns"] = int(settings["compression_protect_last_n"])
        if "moa_enabled" in settings:
            aut_sync["consensus_gate"] = {"enabled": bool(settings["moa_enabled"])}
        if aut_sync:
            save_autonomy_settings(aut_sync)
    except Exception as e_sync:
        logger.warning(f"[Hermes -> Archon Sync] {e_sync}")

    try:
        if os.path.exists(target_path):
            shutil.copy2(target_path, target_path + ".bak")
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.dump(existing_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Wenn die globale Basis-Konfiguration (HERMES_CONFIG_YAML) gespeichert wird,
        # synchronisiere model.default & model.provider auch nach default/config.yaml
        if os.path.abspath(target_path) == os.path.abspath(HERMES_CONFIG_YAML):
            def_prof_cfg = os.path.join(HERMES_PROFILES_BASE, "default", "config.yaml")
            if os.path.exists(def_prof_cfg):
                try:
                    with open(def_prof_cfg, "r", encoding="utf-8") as f_dp:
                        dp_data = yaml.safe_load(f_dp.read()) or {}
                    if isinstance(dp_data, dict):
                        dp_m = _ensure_dict(dp_data, "model")
                        if "model_default" in settings and str(settings["model_default"]).strip():
                            dp_m["default"] = str(settings["model_default"]).strip()
                        if "model_provider" in settings and str(settings["model_provider"]).strip():
                            dp_m["provider"] = str(settings["model_provider"]).strip()
                        if "base_url" in settings:
                            b_u = str(settings["base_url"]).strip()
                            if b_u:
                                dp_m["base_url"] = b_u
                            elif "base_url" in dp_m:
                                del dp_m["base_url"]
                        with open(def_prof_cfg, "w", encoding="utf-8") as f_dp:
                            yaml.dump(dp_data, f_dp, default_flow_style=False, allow_unicode=True, sort_keys=False)
                except Exception as dp_err:
                    logger.warning(f"[Hermes Settings] Default profile sync warning: {dp_err}")
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "hermes_config_save_failed", "params": {"error": str(e)}})

    # Wenn target_path zu einem spezifischen Agenten-Profil gehört, synchronisiere profile.yaml, agent_profiles.json & Org-Chart
    try:
        prof_dir = os.path.dirname(os.path.abspath(target_path))
        prof_yaml = os.path.join(prof_dir, "profile.yaml")
        prof_id = os.path.basename(prof_dir)
        m_def = str(settings.get("model_default", "")).strip()
        m_prov = str(settings.get("model_provider", "")).strip()
        r_eff = str(settings.get("reasoning_effort", "")).strip().lower()
        if os.path.exists(prof_yaml) and (m_def or m_prov or r_eff):
            with open(prof_yaml, "r", encoding="utf-8") as fy:
                pdata = yaml.safe_load(fy) or {}
            if m_def:
                pdata["model"] = m_def
            if m_prov:
                pdata["provider"] = m_prov
            if r_eff:
                pdata["reasoning_level"] = r_eff
            if not isinstance(pdata.get("llm"), dict):
                pdata["llm"] = {}
            if m_def:
                pdata["llm"]["model"] = m_def
            if m_prov:
                pdata["llm"]["provider"] = m_prov
            if r_eff:
                pdata["llm"]["reasoning_level"] = r_eff
            with open(prof_yaml, "w", encoding="utf-8") as fy:
                yaml.dump(pdata, fy, allow_unicode=True, sort_keys=False)
            # agent_profiles.json nachziehen
            ap_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_profiles.json")
            if os.path.exists(ap_file):
                with open(ap_file, "r", encoding="utf-8") as fap:
                    ap_list = json.load(fap)
                if isinstance(ap_list, list):
                    for item in ap_list:
                        if isinstance(item, dict) and item.get("id") == prof_id:
                            if m_def:
                                item["model"] = m_def
                            if m_prov:
                                item["provider"] = m_prov
                            if r_eff:
                                item["reasoning_level"] = r_eff
                            break
                    # F-06: Vorher stand hier ein Toter Zweig
                    # (``json.dump(ap_list, f, ...) if False else None``) in
                    # einem zweiten ``open(ap_file, "w")`` — der truncate
                    # LEERTE die Profildatei, geschrieben wurde nichts, und
                    # erst der folgende Write fuellte sie wieder. Crash oder
                    # volle Platte in diesem Fenster = 0-Byte-Profildatei.
                    # Jetzt: EIN atomarer Write (tmp + os.replace).
                    ap_tmp = f"{ap_file}.tmp.{os.getpid()}"
                    try:
                        with open(ap_tmp, "w", encoding="utf-8") as fap:
                            json.dump(ap_list, fap, indent=2, ensure_ascii=False)
                            fap.flush()
                            os.fsync(fap.fileno())
                        os.replace(ap_tmp, ap_file)
                    finally:
                        if os.path.exists(ap_tmp):
                            try:
                                os.unlink(ap_tmp)
                            except OSError:
                                pass
            _sync_fn = _DEPS.get("_sync_org_hierarchy_node")
            if _sync_fn:
                _sync_fn(prof_id, provider=m_prov or None, model=m_def or None, reasoning_level=r_eff or None)
            invalidate_hermes_profiles_cache()
    except Exception as sync_err:
        logger.warning(f"[Hermes Settings] Global profile sync warning: {sync_err}")

    try:
        add_ticker("Hermes Core", f"Einstellungen gespeichert für: {os.path.basename(target_path)}")
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Hermes-Einstellungen für '{os.path.basename(target_path)}' erfolgreich gespeichert.",
        "path": target_path
    }

@router.get("/api/hermes/raw_config")
def api_get_hermes_raw_config(request: Request, path: Optional[str] = None):
    require_admin_or_503(request)  # RBAC: Admin-Sache (R-11)
    import yaml
    active_path, all_configs = _get_hermes_config_paths()
    if path:
        target_path = _safe_config_target(path)
    else:
        target_path = active_path
    
    content = ""
    parsed = {}
    if target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"# Fehler beim Lesen von {target_path}:\n# {str(e)}"
            
    # Secrets nie im Klartext ausliefern: API-Keys/Tokens in der YAML maskieren
    try:
        from utils.secret_files import mask_yaml_secrets
        _masked_content = mask_yaml_secrets(content)
    except Exception:
        _masked_content = content

    try:
        parsed = yaml.safe_load(_masked_content) or {}
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception:
        parsed = {}

    return {
        "active_path": active_path,
        "loaded_path": target_path,
        "available_configs": all_configs,
        "yaml_content": _masked_content,
        "parsed": parsed,
        "secrets_masked": _masked_content != content
    }

@router.post("/api/hermes/raw_config")
def api_save_hermes_raw_config(request: Request, payload: dict = Body(...)):
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import yaml, shutil
    target_path = payload.get("config_path")
    yaml_content = payload.get("yaml_content", "")
    
    if not target_path:
        active_path, _ = _get_hermes_config_paths()
        target_path = active_path

    if not target_path:
        raise HTTPException(status_code=400, detail={"code": "hermes_config_no_path_2", "params": {}})

    target_path = _safe_config_target(target_path)
    if not target_path:
        raise HTTPException(status_code=400, detail={"code": "hermes_config_invalid_path_2", "params": {}})

    # 1. Syntax-Validierung
    try:
        parsed = yaml.safe_load(yaml_content)
        if not isinstance(parsed, dict):
            raise ValueError("YAML muss ein gültiges Dictionary / Mapping auf oberster Ebene sein.")
    except Exception as e:
        raise HTTPException(status_code=400, detail={"code": "hermes_config_yaml_syntax_error", "params": {"error": str(e)}})
        
    # 1b. Vom Editor zurueckgeschickte Masken durch die echten Werte ersetzen
    try:
        from utils.secret_files import restore_masked_values
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as _f_orig:
                _orig_yaml = _f_orig.read()
            yaml_content = restore_masked_values(_orig_yaml, yaml_content)
    except Exception as _restore_err:
        logger.warning(f"[Hermes Settings] Masken-Restore fehlgeschlagen: {_restore_err}")

    # 2. Backup erstellen
    try:
        if os.path.exists(target_path):
            shutil.copy2(target_path, target_path + ".bak")
            
        # 3. Datei schreiben
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(yaml_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail={"code": "hermes_config_write_failed", "params": {"error": str(e)}})
        
    # 4. Hermes Daemon Ticker
    try:
        add_ticker("Hermes Core", f"Hermes-Konfiguration aktualisiert: {os.path.basename(target_path)}")
    except Exception:
        pass
        
    return {
        "status": "success",
        "message": "Konfiguration erfolgreich validiert und gespeichert.",
        "path": target_path
    }

