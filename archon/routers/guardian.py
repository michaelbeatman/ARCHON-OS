"""
Guardian Router für Archon OS.
Aggregiert Telemetrie, Token-Statistiken, Plugin-Toggles und Guardian-Konfiguration.
Extrahiert aus main.py (1157 Zeilen).
"""

import os
import sys
import json
import glob
import time
import datetime
import sqlite3
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Body, Request
from archon.routers._rbac import require_admin_or_503
from archon.core.runtime import add_ticker, logger, MEMORY_DIR
from archon.core.paths import SETTINGS_FILE, HERMES_PROFILES_DIR
from backend.db_paths import get_db_connection

router = APIRouter(tags=["guardian"])

# D-21: Der Cache war unbeschaenzt und der Schluessel ein freier
# Query-Parameter. Jeder neue ``?timeframe=``-Wert erzeugte einen
# dauerhaft gehaltenen Eintrag und loeste einen Vollscan ueber alle
# Profil-DBs im Request aus. Jetzt: nur definierte Timeframes, Cache mit
# TTL und fester Groessengrenze.
_GUARDIAN_ALLOWED_TIMEFRAMES = ("all", "24h", "7d", "30d")
_GUARDIAN_CACHE_TTL = 10.0
_GUARDIAN_CACHE_MAX_ENTRIES = len(_GUARDIAN_ALLOWED_TIMEFRAMES)
_GUARDIAN_STATS_CACHE: Dict[str, Any] = {}

@router.get("/api/guardian/stats")
def api_get_guardian_stats(timeframe: str = "all"):
    """Aggregiert Token-, Kosten- und Verlaufsstatistiken aller Profile aus SQLite state.db."""
    import sqlite3, glob, datetime

    # D-21: Freier Query-Parameter -> unbeschaenkter Cache + Vollscan pro Miss.
    if timeframe not in _GUARDIAN_ALLOWED_TIMEFRAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unbekannter Timeframe '{timeframe}'. Erlaubt: {', '.join(_GUARDIAN_ALLOWED_TIMEFRAMES)}.",
        )

    now_ts = datetime.datetime.now().timestamp()
    cached = _GUARDIAN_STATS_CACHE.get(timeframe)
    if cached and (now_ts - cached["ts"]) < _GUARDIAN_CACHE_TTL:
        return cached["data"]
    
    profiles_stats = []
    models_stats = {}
    daily_trend = {}
    all_sessions_list = []
    grand_total_tokens = 0
    grand_cache_tokens = 0
    grand_total_cost = 0.0
    grand_total_calls = 0
    max_overall_ts = 0
    
    min_ts = 0
    if timeframe == "24h":
        min_ts = now_ts - 86400
    elif timeframe == "7d":
        min_ts = now_ts - (7 * 86400)
    elif timeframe == "30d":
        min_ts = now_ts - (30 * 86400)
    
    state_dbs = sorted(glob.glob('/opt/data/profiles/*/state.db') + ['/opt/data/state.db'])
    if not state_dbs:
        state_dbs = sorted(glob.glob(os.path.expanduser('~/.hermes/profiles/*/state.db')) + [os.path.expanduser('~/.hermes/state.db')])
    
    for db in state_dbs:
        con = None
        try:
            prof_name = db.split('/')[-2] if 'profiles' in db else 'root'
            con = get_db_connection(db, timeout=5.0)
            
            # Hole Einzelzeilen für Zeitfilterung und Tages-Trend
            query = '''
                SELECT session_id, model, api_call_count, input_tokens, output_tokens, cache_read_tokens, estimated_cost_usd, first_seen, last_seen
                FROM session_model_usage
            '''
            rows = con.execute(query).fetchall()
            
            p_tokens = 0
            p_cache = 0
            p_cost = 0.0
            p_calls = 0
            p_models = {}
            
            for r in rows:
                session_id, model_name, calls, inp, out, cache, cost, f_seen, l_seen = r[0], r[1], r[2] or 0, r[3] or 0, r[4] or 0, r[5] or 0.0, r[6] or 0.0, r[7], r[8]
                ts = l_seen or f_seen or 0
                if ts > max_overall_ts:
                    max_overall_ts = ts
                
                # Filter nach Zeitraum
                if min_ts > 0 and ts < min_ts:
                    continue
                
                tot = inp + out  # Cache-Lesezugriffe sind keine neuen Tokens
                # Plausibilitäts-Korrektur: Verhindere 1M-Faktor-Pricing-Bugs (z.B. OpenRouter 0.75$/1M als 0.75$/Token)
                if tot > 0 and (cost / tot) > 0.001:
                    cost = cost / 1_000_000.0
                p_tokens += tot
                p_cache += cache
                p_cost += cost
                p_calls += calls
                
                # Session Details für den zweiten Reiter
                first_date_str = datetime.datetime.fromtimestamp(f_seen).strftime('%d.%m.%Y %H:%M') if f_seen else "-"
                last_date_str = datetime.datetime.fromtimestamp(l_seen).strftime('%d.%m.%Y %H:%M') if l_seen else "-"
                
                all_sessions_list.append({
                    "session_id": session_id or "unbekannt",
                    "profile": prof_name,
                    "model": model_name,
                    "calls": calls,
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_tokens": cache,
                    "total_tokens": tot,
                    "cost": round(cost, 4),
                    "first_seen": first_date_str,
                    "last_seen": last_date_str,
                    "last_seen_ts": ts
                })
                
                # Daily Trend Aggregation
                if ts:
                    d_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                else:
                    d_str = "Unbekannt"
                if d_str not in daily_trend:
                    daily_trend[d_str] = {"tokens": 0, "cost": 0.0, "calls": 0}
                daily_trend[d_str]["tokens"] += tot
                daily_trend[d_str]["cost"] += cost
                daily_trend[d_str]["calls"] += calls
                
                if model_name not in p_models:
                    p_models[model_name] = {"model": model_name, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_tokens": 0, "total_tokens": 0, "cost": 0.0}
                p_models[model_name]["calls"] += calls
                p_models[model_name]["input_tokens"] += inp
                p_models[model_name]["output_tokens"] += out
                p_models[model_name]["cache_tokens"] += cache
                p_models[model_name]["total_tokens"] += tot
                p_models[model_name]["cost"] += cost
                
                if model_name not in models_stats:
                    models_stats[model_name] = {"calls": 0, "total_tokens": 0, "cost": 0.0}
                models_stats[model_name]["calls"] += calls
                models_stats[model_name]["total_tokens"] += tot
                models_stats[model_name]["cost"] += cost
            
            if p_calls > 0:
                grand_total_tokens += p_tokens
                grand_cache_tokens += p_cache
                grand_total_cost += p_cost
                grand_total_calls += p_calls
                profiles_stats.append({
                    "profile": prof_name,
                    "total_tokens": p_tokens,
                    "cache_read_tokens": p_cache,
                    "total_with_cache": p_tokens + p_cache,
                    "total_cost": round(p_cost, 4),
                    "total_calls": p_calls,
                    "models": list(p_models.values())
                })
        except Exception as e:
            pass
        finally:
            if con:
                con.close()
            
    profiles_stats.sort(key=lambda x: x["total_tokens"], reverse=True)
    models_list = [{"model": k, "calls": v["calls"], "total_tokens": v["total_tokens"], "cost": round(v["cost"], 4)} for k, v in models_stats.items()]
    models_list.sort(key=lambda x: x["total_tokens"], reverse=True)
    all_sessions_list.sort(key=lambda x: x["total_tokens"], reverse=True)
    
    # Sortierte Trend-Liste
    sorted_trend = []
    for d in sorted(daily_trend.keys()):
        if d != "Unbekannt":
            sorted_trend.append({
                "date": d,
                "tokens": daily_trend[d]["tokens"],
                "cost": round(daily_trend[d]["cost"], 4),
                "calls": daily_trend[d]["calls"]
            })
            
    # Ungenutzte Zeit / Inaktivitätsdauer berechnen
    idle_seconds = max(0, int(now_ts - max_overall_ts)) if max_overall_ts > 0 else 0
    if idle_seconds >= 86400:
        days = idle_seconds // 86400
        hours = (idle_seconds % 86400) // 3600
        idle_str = f"{days} Tag{'e' if days != 1 else ''}, {hours} Std."
    elif idle_seconds >= 3600:
        hours = idle_seconds // 3600
        mins = (idle_seconds % 3600) // 60
        idle_str = f"{hours} Std., {mins} Min."
    elif idle_seconds >= 60:
        mins = idle_seconds // 60
        idle_str = f"{mins} Min."
    else:
        idle_str = f"{idle_seconds} Sek."
        
    last_activity_str = datetime.datetime.fromtimestamp(max_overall_ts).strftime('%d.%m.%Y %H:%M') if max_overall_ts > 0 else "Keine Aktivität"
    checked_at_str = datetime.datetime.now().strftime('%H:%M:%S')
    
    result = {
        "status": "success",
        "timeframe": timeframe,
        "grand_total_tokens": grand_total_tokens,
        "grand_cache_read_tokens": grand_cache_tokens,
        "window_note": "Zeitraum filtert Sitzungen nach letzter Aktivitaet; Token-Summen umfassen die gesamte Sitzung.",
        "grand_total_cost": round(grand_total_cost, 2),
        "grand_total_calls": grand_total_calls,
        "max_last_seen": max_overall_ts,
        "last_activity_str": last_activity_str,
        "idle_seconds": idle_seconds,
        "idle_str": idle_str,
        "checked_at": checked_at_str,
        "profiles": profiles_stats,
        "models": models_list,
        "sessions": all_sessions_list,
        "trend": sorted_trend
    }
    # D-21: Cache-Groesse bleibt begrenzt (nur definierte Timeframes).
    _GUARDIAN_STATS_CACHE[timeframe] = {"ts": now_ts, "data": result}
    if len(_GUARDIAN_STATS_CACHE) > _GUARDIAN_CACHE_MAX_ENTRIES:
        # aelteste Eintraege verwerfen
        for key in sorted(
            _GUARDIAN_STATS_CACHE,
            key=lambda k: _GUARDIAN_STATS_CACHE[k]["ts"],
        )[: len(_GUARDIAN_STATS_CACHE) - _GUARDIAN_CACHE_MAX_ENTRIES]:
            _GUARDIAN_STATS_CACHE.pop(key, None)
    return result

@router.get("/api/guardian/config")
def api_get_guardian_config():
    """Liest die aktuellen Wächter-Einstellungen und ALLE registrierten Plugins dynamisch aus."""
    import yaml, glob
    config_file = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_file):
        config_file = "/opt/data/config.yaml"
        
    cfg = {}
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass
            
    plugins_cfg = cfg.get("plugins", {})
    enabled_plugins = plugins_cfg.get("enabled", [])
    if not isinstance(enabled_plugins, list):
        enabled_plugins = []
    
    # Cost budget json
    cost_budget_file = os.path.expanduser("~/.hermes/cost-budget.json")
    if not os.path.exists(cost_budget_file):
        cost_budget_file = "/opt/data/cost-budget.json"
    budget_data = {"daily_budget": 2.0, "task_budget": 0.5}
    if os.path.exists(cost_budget_file):
        try:
            with open(cost_budget_file, "r", encoding="utf-8") as f:
                budget_data = json.load(f)
        except Exception:
            pass

    # Guardian limits json & config.yaml sync
    limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
    agent_cfg = cfg.get("agent", {})
    limits = {
        "max_context_tokens": agent_cfg.get("max_context_tokens", 32000),
        "max_history_messages": agent_cfg.get("max_history_messages", 20),
        "max_steps_per_task": 15,
        "session_timeout_seconds": 60,
        "loop_detection_enabled": True,
        "cache_ttl_hours": 24,
        "max_cache_entries": 100,
        "watchdog_interval_seconds": 30
    }
    if os.path.exists(limits_file):
        try:
            with open(limits_file, "r", encoding="utf-8") as f:
                limits.update(json.load(f))
        except Exception:
            pass

    # Dynamische Plugin-Erkennung aus allen Plugin-Ordnern
    plugins_dir = os.path.expanduser("~/.hermes/plugins")
    if not os.path.exists(plugins_dir):
        plugins_dir = "/opt/data/plugins"
        
    discovered_plugins = []
    category_map = {
        "evey-cost-guard": "Sicherheit & Wächter",
        "evey-session-guard": "Sicherheit & Wächter",
        "evey-email-guard": "Sicherheit & Wächter",
        "evey-watchdog": "Sicherheit & Wächter",
        "evey-cache": "Performance & Cache",
        "evey-telemetry": "Monitoring & Analytics",
        "evey-status": "Monitoring & Analytics",
        "evey-delegation-score": "Monitoring & Analytics",
        "evey-autonomy": "Agenten-Intelligenz",
        "evey-council": "Agenten-Intelligenz",
        "evey-reflect": "Agenten-Intelligenz",
        "evey-learner": "Agenten-Intelligenz",
        "evey-identity": "Agenten-Intelligenz",
        "evey-habits": "Agenten-Intelligenz",
        "evey-proactive": "Agenten-Intelligenz",
        "evey-goals": "Planung & Tasks",
        "evey-scheduler": "Planung & Tasks",
        "evey-bridge": "Brücken & Schnittstellen",
        "evey-mqtt": "Brücken & Schnittstellen",
        "evey-moltbook": "Brücken & Schnittstellen",
        "evey-telegram-ux": "Brücken & Schnittstellen",
        "evey-github": "Brücken & Schnittstellen",
        "evey-research": "Tools & Recherche",
        "evey-news": "Tools & Recherche",
        "evey-digest": "Tools & Recherche",
        "evey-sandbox": "Tools & Execution",
        "evey-rag": "Gedächtnis & Wissen",
        "evey-memory-adaptive": "Gedächtnis & Wissen",
        "evey-memory-consolidate": "Gedächtnis & Wissen",
        "evey-wallet": "Finanzen & Web3",
        "evey-validate": "Qualität & Ausführung",
        "evey-verification": "Qualität & Ausführung",
        "evey-delegate-model": "Qualität & Ausführung",
        "disk-cleanup": "System-Wartung"
    }

    icon_map = {
        "evey-cost-guard": "coins",
        "evey-session-guard": "shield-check",
        "evey-email-guard": "shield-alert",
        "evey-watchdog": "activity",
        "evey-cache": "zap",
        "evey-telemetry": "gauge",
        "evey-status": "heart-pulse",
        "evey-delegation-score": "award",
        "evey-autonomy": "cpu",
        "evey-council": "users",
        "evey-reflect": "sparkles",
        "evey-learner": "graduation-cap",
        "evey-identity": "user-check",
        "evey-habits": "calendar-clock",
        "evey-proactive": "bell-ring",
        "evey-goals": "target",
        "evey-scheduler": "clock",
        "evey-bridge": "network",
        "evey-mqtt": "radio",
        "evey-moltbook": "book-open",
        "evey-telegram-ux": "send",
        "evey-github": "git-branch",
        "evey-research": "search",
        "evey-news": "newspaper",
        "evey-digest": "file-text",
        "evey-sandbox": "box",
        "evey-rag": "database",
        "evey-memory-adaptive": "brain",
        "evey-memory-consolidate": "layers",
        "evey-wallet": "wallet",
        "evey-validate": "check-check",
        "evey-verification": "file-check",
        "evey-delegate-model": "share-2",
        "disk-cleanup": "trash-2"
    }

    # Bidirektionale Brücke zwischen Plugin-Registry und nativen Archon-OS-Modulen (settings.json)
    from backend.autonomy_settings import load_autonomy_settings
    aut_settings = load_autonomy_settings()

    plugin_autonomy_bridge = {
        "evey-cost-guard": ("budget_guard", "auto_downgrade_on_limit"),
        "evey-session-guard": ("durable_execution", "enabled"),
        "evey-email-guard": ("pii_scrubber", "enabled"),
        "evey-watchdog": ("resource_backpressure", "enabled"),
        "evey-cache": ("semantic_cache", "enabled"),
        "evey-telemetry": ("time_travel", "enabled"),
        "evey-status": ("execution_receipts", "enabled"),
        "evey-delegation-score": ("model_benchmarker", "enabled"),
        "evey-autonomy": ("ephemeral_teams", "enabled"),
        "evey-council": ("consensus_gate", "enabled"),
        "evey-reflect": ("self_healing", "enabled"),
        "evey-learner": ("skill_synthesizer", "enabled"),
        "evey-identity": ("core_memory", "enabled"),
        "evey-proactive": ("inbox_watcher", "enabled"),
        "evey-goals": ("map_reduce", "enabled"),
        "evey-scheduler": ("dead_letter_queue", "enabled"),
        "evey-research": ("corrective_rag", "enabled"),
        "evey-digest": ("inbox_watcher", "standup_enabled"),
        "evey-sandbox": ("ephemeral_sandbox", "enabled"),
        "evey-rag": ("hybrid_search", "enabled"),
        "evey-memory-adaptive": ("citation_pinner", "enabled"),
        "evey-memory-consolidate": ("memory_consolidation", "enabled"),
        "evey-validate": ("sla_enforcer", "enabled"),
        "evey-verification": ("egress_firewall", "enabled"),
        "evey-delegate-model": ("speculative_hedging", "enabled"),
    }

    if os.path.exists(plugins_dir):
        for p_yaml in sorted(glob.glob(os.path.join(plugins_dir, "*/plugin.yaml"))):
            try:
                folder_name = os.path.basename(os.path.dirname(p_yaml))
                if folder_name.startswith("_"):
                    continue
                with open(p_yaml, "r", encoding="utf-8") as pf:
                    p_info = yaml.safe_load(pf) or {}
                p_id = p_info.get("name", folder_name)
                p_name = p_info.get("display_name") or p_id.replace("evey-", "").replace("-", " ").title()
                p_desc = p_info.get("description", "")
                p_cat = p_info.get("category") or category_map.get(p_id, "Weitere Module")
                p_tools = p_info.get("provides_tools", []) or p_info.get("tools", []) or []
                p_icon = icon_map.get(p_id, p_info.get("icon", "puzzle"))

                if p_id in plugin_autonomy_bridge:
                    grp, key = plugin_autonomy_bridge[p_id]
                    is_enabled = bool(aut_settings.get(grp, {}).get(key, True))
                else:
                    is_enabled = (p_id in enabled_plugins) or (p_id == "evey-telegram-ux")

                discovered_plugins.append({
                    "id": p_id,
                    "name": p_name,
                    "desc": p_desc,
                    "problem": p_info.get("problem", ""),
                    "solution": p_info.get("solution", ""),
                    "tradeoff": p_info.get("tradeoff", ""),
                    "when_to_disable": p_info.get("when_to_disable", ""),
                    "category": p_cat,
                    "tools": p_tools,
                    "icon": p_icon,
                    "version": str(p_info.get("version", "2.6.0")),
                    "enabled": is_enabled
                })
            except Exception:
                pass

    try:
        from backend.plugin_manager import get_plugin_manager
        pm = get_plugin_manager()
        for p in pm.plugins.values():
            tools_list = [t.get("name") for t in p.get_tools() if "name" in t]
            discovered_plugins.append({
                "id": p.id,
                "name": p.name,
                "desc": p.description,
                "problem": p.manifest.get("problem", "Fehlende Überwachung oder fehlende modulare Werkzeuge."),
                "solution": p.manifest.get("solution", p.description),
                "tradeoff": p.manifest.get("tradeoff", "Geringe Latenz beim Hook-Durchlauf."),
                "when_to_disable": p.manifest.get("when_to_disable", "Wenn dieses Modul vorübergehend nicht aktiv sein soll."),
                "category": "Tools & Execution" if p.category == "tool" else "Sicherheit & Wächter",
                "tools": tools_list,
                "icon": "shield-check" if p.category == "security" else "cpu",
                "version": p.version,
                "enabled": p.enabled,
                "is_modular_plugin": True
            })
    except Exception as e:
        print(f"[GuardianConfig] PluginManager integration error: {e}")

    return {
        "status": "success",
        "plugins": discovered_plugins,
        "budget": budget_data,
        "limits": limits
    }

@router.post("/api/guardian/config")
def api_save_guardian_config(request: Request, payload: dict):
    """Speichert Budget-Limits, Session-Schranken und Wächter-Einstellungen."""
    # Speichere Budget
    require_admin_or_503(request)  # RBAC: Admin-Sache
    cost_budget_file = os.path.expanduser("~/.hermes/cost-budget.json")
    if not os.path.exists(cost_budget_file):
        cost_budget_file = "/opt/data/cost-budget.json"
    
    if "daily_budget" in payload or "task_budget" in payload:
        b_data = {
            "daily_budget": float(payload.get("daily_budget", 2.0)),
            "task_budget": float(payload.get("task_budget", 0.5))
        }
        try:
            with open(cost_budget_file, "w", encoding="utf-8") as f:
                json.dump(b_data, f, indent=2)
        except Exception as e:
            print(f"Error saving cost budget: {e}")

    # Speichere Limits
    limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
    try:
        cur_limits = {}
        if os.path.exists(limits_file):
            with open(limits_file, "r", encoding="utf-8") as f:
                cur_limits = json.load(f)
        for k in ["max_context_tokens", "max_history_messages", "max_steps_per_task", "session_timeout_seconds", "loop_detection_enabled", "cache_ttl_hours", "max_cache_entries", "watchdog_interval_seconds"]:
            if k in payload:
                cur_limits[k] = payload[k]
        with open(limits_file, "w", encoding="utf-8") as f:
            json.dump(cur_limits, f, indent=2)
            
        # Aktualisiere auch config.yaml für Hermes Core
        config_file = os.path.expanduser("~/.hermes/config.yaml")
        if not os.path.exists(config_file):
            config_file = "/opt/data/config.yaml"
        if os.path.exists(config_file):
            import yaml
            with open(config_file, "r", encoding="utf-8") as f:
                h_cfg = yaml.safe_load(f) or {}
            if "agent" not in h_cfg:
                h_cfg["agent"] = {}
            if "max_context_tokens" in payload:
                h_cfg["agent"]["max_context_tokens"] = int(payload["max_context_tokens"])
            if "max_history_messages" in payload:
                h_cfg["agent"]["max_history_messages"] = int(payload["max_history_messages"])
            if "session_timeout_seconds" in payload:
                h_cfg["agent"]["task_timeout_seconds"] = int(payload["session_timeout_seconds"])
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(h_cfg, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        print(f"Error saving guardian limits: {e}")

    add_ticker("Guardian", "Wächter-, Budget- und Kontext-Schranken aktualisiert.")
    return {"status": "success", "message": "Konfiguration gespeichert"}

@router.post("/api/guardian/plugins/toggle")
@router.post("/api/guardian/plugin/toggle")
def api_toggle_guardian_plugin(request: Request, payload: dict):
    """Aktiviert oder deaktiviert ein Plugin in Hermes."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import yaml
    plugin_id = payload.get("plugin_id") or payload.get("id")
    enable = payload.get("enable")
    if enable is None:
        enable = payload.get("enabled", True)
    
    if not plugin_id:
        return {"status": "error", "message": "plugin_id fehlt"}
        
    config_file = os.path.expanduser("~/.hermes/config.yaml")
    if not os.path.exists(config_file):
        config_file = "/opt/data/config.yaml"
        
    try:
        cfg = {}
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                
        if "plugins" not in cfg or not isinstance(cfg["plugins"], dict):
            cfg["plugins"] = {"enabled": [], "disabled": []}
            
        enabled_list = cfg["plugins"].get("enabled", [])
        if not isinstance(enabled_list, list):
            enabled_list = []
            
        if enable:
            if plugin_id not in enabled_list:
                enabled_list.append(plugin_id)
        else:
            if plugin_id in enabled_list:
                enabled_list.remove(plugin_id)
                
        cfg["plugins"]["enabled"] = enabled_list
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False)

        try:
            from backend.plugin_manager import get_plugin_manager
            pm = get_plugin_manager()
            if plugin_id in pm.plugins:
                if enable:
                    pm.enable_plugin(plugin_id)
                else:
                    pm.disable_plugin(plugin_id)
        except Exception as e:
            print(f"[PluginToggle] Error updating plugin manager: {e}")

        # Synchronisiere Schalter direkt mit backend/autonomy_settings.py (settings.json)
        plugin_autonomy_bridge = {
            "evey-cost-guard": ("budget_guard", "auto_downgrade_on_limit"),
            "evey-session-guard": ("durable_execution", "enabled"),
            "evey-email-guard": ("pii_scrubber", "enabled"),
            "evey-watchdog": ("resource_backpressure", "enabled"),
            "evey-cache": ("semantic_cache", "enabled"),
            "evey-telemetry": ("time_travel", "enabled"),
            "evey-status": ("execution_receipts", "enabled"),
            "evey-delegation-score": ("model_benchmarker", "enabled"),
            "evey-autonomy": ("ephemeral_teams", "enabled"),
            "evey-council": ("consensus_gate", "enabled"),
            "evey-reflect": ("self_healing", "enabled"),
            "evey-learner": ("skill_synthesizer", "enabled"),
            "evey-identity": ("core_memory", "enabled"),
            "evey-proactive": ("inbox_watcher", "enabled"),
            "evey-goals": ("map_reduce", "enabled"),
            "evey-scheduler": ("dead_letter_queue", "enabled"),
            "evey-research": ("corrective_rag", "enabled"),
            "evey-digest": ("inbox_watcher", "standup_enabled"),
            "evey-sandbox": ("ephemeral_sandbox", "enabled"),
            "evey-rag": ("hybrid_search", "enabled"),
            "evey-memory-adaptive": ("citation_pinner", "enabled"),
            "evey-memory-consolidate": ("memory_consolidation", "enabled"),
            "evey-validate": ("sla_enforcer", "enabled"),
            "evey-verification": ("egress_firewall", "enabled"),
            "evey-delegate-model": ("speculative_hedging", "enabled"),
        }
        if plugin_id in plugin_autonomy_bridge:
            from backend.autonomy_settings import save_autonomy_settings
            grp, key = plugin_autonomy_bridge[plugin_id]
            save_autonomy_settings({grp: {key: bool(enable)}})

        add_ticker("Guardian", f"Modul '{plugin_id}' {'aktiviert' if enable else 'deaktiviert'} (settings.json synchronisiert).")
        return {"status": "success", "plugin_id": plugin_id, "enabled": bool(enable)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

DEFAULT_PLUGIN_CONFIGS = {
    "evey-cost-guard": {
        "daily_budget": 2.0,
        "task_budget": 0.5,
        "alert_threshold_percent": 85,
        "hard_stop": True
    },
    "evey-cache": {
        "cache_ttl_hours": 24,
        "max_cache_entries": 100,
        "semantic_match": False
    },
    "evey-autonomy": {
        "operator_name": "Michael",
        "timezone": "Europe/Berlin",
        "heavy_model": "claude-sonnet-4-6",
        "cheap_model": "claude-haiku-4-5",
        "cooldown_minutes": 30,
        "max_cycles_per_day": 24
    },
    "evey-watchdog": {
        "silent_threshold_minutes": 120,
        "work_hours_start": 9,
        "work_hours_end": 21,
        "alert_channel": "ntfy",
        "auto_restart_stalled": True
    },
    "evey-proactive": {
        "max_messages_per_day": 5,
        "cooldown_minutes": 45,
        "allowed_start_hour": 9,
        "allowed_end_hour": 20
    },
    "evey-sandbox": {
        "allowed_folders": ["/opt/data/workspace", "/tmp"],
        "allowed_folders_str": "/opt/data/workspace, /tmp",
        "max_exec_seconds": 60,
        "pii_filter": True
    },
    "evey-wallet": {
        "btc_address": "",
        "eth_address": "",
        "sol_address": ""
    },
    "evey-email-guard": {
        "sensitivity_level": "standard",
        "max_attachment_mb": 15,
        "safe_domains_whitelist": "gmail.com, googlemail.com, posteo.de",
        "quarantine_suspicious": True
    },
    "evey-session-guard": {
        "max_session_hours": 24,
        "idle_timeout_minutes": 60,
        "max_tokens_per_session": 64000,
        "strict_context_isolation": True
    },
    "evey-telemetry": {
        "log_level": "INFO",
        "prometheus_port": 9090,
        "retention_days": 14
    },
    "evey-status": {
        "healthcheck_interval_seconds": 30,
        "cpu_threshold_percent": 85,
        "heartbeat_webhook_url": ""
    },
    "evey-delegation-score": {
        "min_confidence_score": 0.75,
        "penalty_factor": 0.5,
        "fallback_mode": "ask_operator"
    },
    "evey-council": {
        "debate_rounds": 2,
        "consensus_rule": "majority",
        "judge_model": "claude-sonnet-4-6",
        "anonymize_votes": False
    },
    "evey-reflect": {
        "reflect_frequency_tasks": 5,
        "reflect_depth": "deep",
        "save_to_vault": True
    },
    "evey-learner": {
        "min_quality_score": 0.85,
        "auto_extract_lessons": True,
        "auto_index_skills": True
    },
    "evey-identity": {
        "persona_name": "Archon",
        "default_language": "de-DE",
        "tone_of_voice": "direct_pragmatic"
    },
    "evey-habits": {
        "morning_briefing_time": "08:30",
        "evening_recap_time": "18:45",
        "auto_daily_cleanup": True
    },
    "evey-goals": {
        "review_cadence": "weekly",
        "max_active_okrs": 5,
        "auto_breakdown_epics": True
    },
    "evey-scheduler": {
        "worker_concurrency": 4,
        "max_retry_attempts": 3
    },
    "evey-bridge": {
        "bridge_endpoint_url": "http://localhost:4000/bridge",
        "api_bearer_token": "",
        "timeout_seconds": 60
    },
    "evey-mqtt": {
        "broker_host": "localhost",
        "broker_port": 1883,
        "topic_prefix": "archon/events"
    },
    "evey-moltbook": {
        "vault_path": "/opt/data/obsidian",
        "sync_interval_minutes": 30
    },
    "evey-telegram-ux": {
        "bot_token": "",
        "allowed_chat_ids": "",
        "silent_notifications": False
    },
    "evey-github": {
        "default_repo": "michaelbeatman/Agentic-Archon-Os",
        "github_pat": "",
        "default_branch": "main"
    },
    "evey-research": {
        "search_depth": 3,
        "max_sources": 8,
        "excluded_domains": "spam.com, ads.net"
    },
    "evey-news": {
        "fetch_interval_minutes": 120,
        "keyword_filter": "AI, Agentic, LLM, Linux, Security"
    },
    "evey-digest": {
        "daily_digest_time": "07:45",
        "destination_channel": "ui_dashboard"
    },
    "evey-rag": {
        "top_k_results": 5,
        "similarity_threshold": 0.70,
        "embedding_model": "text-embedding-3-small"
    },
    "evey-memory-adaptive": {
        "half_life_days": 14,
        "eviction_threshold": 0.10,
        "max_injected_lessons": 3
    },
    "evey-memory-consolidate": {
        "schedule": "nightly",
        "deduplicate_facts": True
    },
    "evey-validate": {
        "gate_strictness": "strict",
        "syntax_type_check": True
    },
    "evey-verification": {
        "gate_strictness": "strict",
        "syntax_type_check": True
    },
    "evey-delegate-model": {
        "routing_strategy": "quality_optimal",
        "max_latency_ms": 5000
    },
    "disk-cleanup": {
        "log_retention_days": 7,
        "max_disk_usage_percent": 85
    },
    "browser-browser-use": {
        "api_key": "",
        "headless": True,
        "timeout_seconds": 30,
        "max_steps_per_run": 20
    }
}

@router.get("/api/guardian/plugins/{plugin_id}/config")
def api_get_plugin_config(plugin_id: str):
    """Gibt die gespeicherten oder Standard-Einstellungen für jedes Plugin zurück."""
    import yaml
    
    # 1. Basis-Konfiguration aus Defaults
    data = dict(DEFAULT_PLUGIN_CONFIGS.get(plugin_id, {}))

    # 2. Spezifische Live-Systemdateien prüfen und überlagern
    if plugin_id == "evey-cost-guard":
        path = os.path.expanduser("~/.hermes/cost-budget.json")
        if not os.path.exists(path):
            path = "/opt/data/cost-budget.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-cache":
        limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
        if os.path.exists(limits_file):
            try:
                with open(limits_file, "r", encoding="utf-8") as f:
                    cur = json.load(f)
                    if "cache_ttl_hours" in cur:
                        data["cache_ttl_hours"] = cur["cache_ttl_hours"]
                    if "max_cache_entries" in cur:
                        data["max_cache_entries"] = cur["max_cache_entries"]
            except Exception:
                pass

    elif plugin_id == "evey-autonomy":
        path = os.path.expanduser("~/.hermes/evey-autonomy.json")
        if not os.path.exists(path):
            path = "/opt/data/evey-autonomy.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-watchdog":
        path = os.path.expanduser("~/.hermes/workspace/watchdog-state.json")
        if not os.path.exists(path):
            path = "/opt/data/workspace/watchdog-state.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-proactive":
        path = os.path.expanduser("~/.hermes/workspace/manager/proactive-state.json")
        if not os.path.exists(path):
            path = "/opt/data/workspace/manager/proactive-state.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-sandbox":
        path = os.path.expanduser("~/.hermes/config/sandbox.yaml")
        if not os.path.exists(path):
            path = "/opt/data/config/sandbox.yaml"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    ydata = yaml.safe_load(f)
                    if isinstance(ydata, dict):
                        data["allowed_folders"] = ydata.get("allowed_folders", data.get("allowed_folders", []))
                        data["pii_filter"] = ydata.get("pii", {}).get("enabled", True)
            except Exception:
                pass
        if isinstance(data.get("allowed_folders"), list):
            data["allowed_folders_str"] = ", ".join(data["allowed_folders"])

    elif plugin_id == "evey-wallet":
        path = os.path.expanduser("~/.hermes/wallet-balances.json")
        if not os.path.exists(path):
            path = "/opt/data/wallet-balances.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data.update(json.load(f))
            except Exception:
                pass

    elif plugin_id == "evey-telegram-ux":
        # Synchronisiere mit echter Telegram-Bot-Umgebung wenn vorhanden
        tg_env = "/opt/data/profiles/telegram_bot/.env"
        if os.path.exists(tg_env):
            try:
                with open(tg_env, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("TELEGRAM_BOT_TOKEN="):
                            # Niemals im Klartext ans Frontend: maskiert anzeigen,
                            # beim Speichern wird der Maskenwert als "unveraendert" behandelt.
                            _tok = line.split("=", 1)[1].strip()
                            try:
                                from utils.secret_files import mask_secret
                                data["bot_token"] = mask_secret(_tok)
                            except Exception:
                                data["bot_token"] = "••••••••" if _tok else ""
                            data["bot_token_set"] = bool(_tok)
                        elif line.startswith("TELEGRAM_ALLOWED_USERS="):
                            data["allowed_chat_ids"] = line.split("=", 1)[1].strip()
            except Exception:
                pass

    # 3. Gespeicherte individuelle Plugin-Konfiguration laden
    generic_dir = os.path.join(MEMORY_DIR, "plugins_config")
    os.makedirs(generic_dir, exist_ok=True)
    gfile = os.path.join(generic_dir, f"{plugin_id}.json")
    if os.path.exists(gfile):
        try:
            with open(gfile, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    data.update(saved)
        except Exception:
            pass

    # 4. Überlagere mit echten Live-Schwellenwerten aus backend/autonomy_settings.py (settings.json)
    try:
        from backend.autonomy_settings import load_autonomy_settings
        aut = load_autonomy_settings()
        if plugin_id == "evey-rag":
            data["top_k_results"] = aut.get("hybrid_search", {}).get("top_k", 5)
            data["similarity_threshold"] = aut.get("corrective_rag", {}).get("min_relevance_score", 0.45)
        elif plugin_id == "evey-cache":
            data["cache_ttl_hours"] = max(1, int(aut.get("semantic_cache", {}).get("ttl_seconds", 86400) // 3600))
            data["max_cache_entries"] = aut.get("semantic_cache", {}).get("max_entries", 500)
            data["semantic_match"] = aut.get("semantic_cache", {}).get("enabled", True)
        elif plugin_id == "evey-sandbox":
            data["max_exec_seconds"] = aut.get("ephemeral_sandbox", {}).get("timeout_seconds", 30)
            data["pii_filter"] = aut.get("pii_scrubber", {}).get("enabled", True)
        elif plugin_id == "evey-council":
            data["debate_rounds"] = aut.get("consensus_gate", {}).get("council_size", 3)
        elif plugin_id == "evey-reflect":
            data["reflect_frequency_tasks"] = aut.get("self_healing", {}).get("max_retries", 2)
        elif plugin_id == "evey-learner":
            data["min_quality_score"] = aut.get("sla_enforcer", {}).get("min_quality_score", 0.75)
            data["auto_index_skills"] = aut.get("skill_synthesizer", {}).get("enabled", True)
        elif plugin_id == "evey-scheduler":
            data["worker_concurrency"] = aut.get("concurrency", {}).get("max_concurrent_agents", 4)
            data["max_retry_attempts"] = aut.get("dead_letter_queue", {}).get("max_replay_attempts", 3)
        elif plugin_id == "evey-digest":
            data["daily_digest_time"] = aut.get("inbox_watcher", {}).get("standup_hour", "07:30")
        elif plugin_id == "evey-status":
            data["cpu_threshold_percent"] = int(aut.get("resource_backpressure", {}).get("max_cpu_percent", 85))
    except Exception:
        pass

    return {"status": "success", "plugin_id": plugin_id, "config": data}

@router.post("/api/guardian/plugins/{plugin_id}/config")
def api_save_plugin_config(request: Request, plugin_id: str, payload: dict):
    """Speichert Konfigurationsänderungen für ein Plugin und synchronisiert sie mit Systemdateien."""
    require_admin_or_503(request)  # RBAC: Admin-Sache
    import yaml
    cfg = payload.get("config", payload)
    if not isinstance(cfg, dict):
        cfg = {}

    try:
        # 1. Immer in plugins_config/{plugin_id}.json persistieren
        generic_dir = os.path.join(MEMORY_DIR, "plugins_config")
        os.makedirs(generic_dir, exist_ok=True)
        gfile = os.path.join(generic_dir, f"{plugin_id}.json")
        with open(gfile, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

        # Auch unter /opt/data spiegeln falls Container-Volume aktiv
        if os.path.exists("/opt/data") and os.path.isdir("/opt/data"):
            opt_dir = "/opt/data/plugins_config"
            os.makedirs(opt_dir, exist_ok=True)
            with open(os.path.join(opt_dir, f"{plugin_id}.json"), "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)

        # 2. Spezifische Live-Systemdateien synchronisieren
        if plugin_id == "evey-cost-guard":
            path = os.path.expanduser("~/.hermes/cost-budget.json")
            if not os.path.exists(path) and os.path.exists("/opt/data"):
                path = "/opt/data/cost-budget.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            b_data = {
                "daily_budget": float(cfg.get("daily_budget", 2.0)),
                "task_budget": float(cfg.get("task_budget", 0.5))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(b_data, f, indent=2)

        elif plugin_id == "evey-cache":
            limits_file = os.path.join(MEMORY_DIR, "guardian_limits.json")
            os.makedirs(os.path.dirname(os.path.abspath(limits_file)), exist_ok=True)
            cur = {}
            if os.path.exists(limits_file):
                try:
                    with open(limits_file, "r", encoding="utf-8") as f:
                        cur = json.load(f)
                except Exception:
                    pass
            cur["cache_ttl_hours"] = int(cfg.get("cache_ttl_hours", 24))
            cur["max_cache_entries"] = int(cfg.get("max_cache_entries", 100))
            with open(limits_file, "w", encoding="utf-8") as f:
                json.dump(cur, f, indent=2)

        elif plugin_id == "evey-autonomy":
            path = os.path.expanduser("~/.hermes/evey-autonomy.json")
            if not os.path.exists(path) and os.path.exists("/opt/data"):
                path = "/opt/data/evey-autonomy.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "operator_name": str(cfg.get("operator_name", "Michael")),
                "timezone": str(cfg.get("timezone", "Europe/Berlin")),
                "heavy_model": str(cfg.get("heavy_model", "claude-sonnet-4-6")),
                "cheap_model": str(cfg.get("cheap_model", "claude-haiku-4-5")),
                "cooldown_minutes": int(cfg.get("cooldown_minutes", 30))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-watchdog":
            path = os.path.expanduser("~/.hermes/workspace/watchdog-state.json")
            if not os.path.exists(path) and os.path.exists("/opt/data/workspace"):
                path = "/opt/data/workspace/watchdog-state.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "silent_threshold_minutes": int(cfg.get("silent_threshold_minutes", 120)),
                "work_hours_start": int(cfg.get("work_hours_start", 9)),
                "work_hours_end": int(cfg.get("work_hours_end", 21)),
                "alert_channel": str(cfg.get("alert_channel", "ntfy"))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-proactive":
            path = os.path.expanduser("~/.hermes/workspace/manager/proactive-state.json")
            if not os.path.exists(path) and os.path.exists("/opt/data/workspace/manager"):
                path = "/opt/data/workspace/manager/proactive-state.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "max_messages_per_day": int(cfg.get("max_messages_per_day", 5)),
                "cooldown_minutes": int(cfg.get("cooldown_minutes", 45)),
                "allowed_start_hour": int(cfg.get("allowed_start_hour", 9)),
                "allowed_end_hour": int(cfg.get("allowed_end_hour", 20))
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-sandbox":
            path = os.path.expanduser("~/.hermes/config/sandbox.yaml")
            if not os.path.exists(path) and os.path.exists("/opt/data/config"):
                path = "/opt/data/config/sandbox.yaml"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            raw_folders = cfg.get("allowed_folders_str", "")
            folders = [f.strip() for f in raw_folders.split(",") if f.strip()] if isinstance(raw_folders, str) else cfg.get("allowed_folders", [])
            data = {
                "allowed_folders": folders,
                "pii": {"enabled": bool(cfg.get("pii_filter", True))}
            }
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False)

        elif plugin_id == "evey-wallet":
            path = os.path.expanduser("~/.hermes/wallet-balances.json")
            if not os.path.exists(path) and os.path.exists("/opt/data"):
                path = "/opt/data/wallet-balances.json"
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            data = {
                "btc_address": str(cfg.get("btc_address", "")).strip(),
                "eth_address": str(cfg.get("eth_address", "")).strip(),
                "sol_address": str(cfg.get("sol_address", "")).strip()
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        elif plugin_id == "evey-telegram-ux":
            tg_env = "/opt/data/profiles/telegram_bot/.env"
            if os.path.exists(tg_env) and ("bot_token" in cfg or "allowed_chat_ids" in cfg):
                try:
                    with open(tg_env, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    new_lines = []
                    for l in lines:
                        if l.startswith("TELEGRAM_BOT_TOKEN=") and "bot_token" in cfg and cfg["bot_token"]:
                            _new = str(cfg["bot_token"]).strip()
                            if "•" in _new:  # maskierter Platzhalter -> alten Wert behalten
                                new_lines.append(l)
                            else:
                                new_lines.append(f"TELEGRAM_BOT_TOKEN={_new}\n")
                        elif l.startswith("TELEGRAM_ALLOWED_USERS=") and "allowed_chat_ids" in cfg and cfg["allowed_chat_ids"]:
                            new_lines.append(f"TELEGRAM_ALLOWED_USERS={cfg['allowed_chat_ids'].strip()}\n")
                        else:
                            new_lines.append(l)
                    try:
                        from utils.secret_files import write_secret_file
                        write_secret_file(tg_env, "".join(new_lines))
                    except Exception:
                        with open(tg_env, "w", encoding="utf-8") as f:
                            f.writelines(new_lines)
                except Exception as ex:
                    print(f"Failed to sync telegram .env: {ex}")

        # 3. Synchronisiere geänderte Schwellenwerte direkt zurück in backend/autonomy_settings.py (settings.json)
        try:
            from backend.autonomy_settings import save_autonomy_settings
            if plugin_id == "evey-rag":
                save_autonomy_settings({
                    "hybrid_search": {"top_k": int(cfg.get("top_k_results", 5))},
                    "corrective_rag": {"min_relevance_score": float(cfg.get("similarity_threshold", 0.45))}
                })
            elif plugin_id == "evey-cache":
                save_autonomy_settings({
                    "semantic_cache": {
                        "ttl_seconds": int(cfg.get("cache_ttl_hours", 24)) * 3600,
                        "max_entries": int(cfg.get("max_cache_entries", 500)),
                        "enabled": bool(cfg.get("semantic_match", True))
                    }
                })
            elif plugin_id == "evey-sandbox":
                save_autonomy_settings({
                    "ephemeral_sandbox": {"timeout_seconds": int(cfg.get("max_exec_seconds", 30))},
                    "pii_scrubber": {"enabled": bool(cfg.get("pii_filter", True))}
                })
            elif plugin_id == "evey-council":
                save_autonomy_settings({
                    "consensus_gate": {"council_size": int(cfg.get("debate_rounds", 3))}
                })
            elif plugin_id == "evey-reflect":
                save_autonomy_settings({
                    "self_healing": {"max_retries": int(cfg.get("reflect_frequency_tasks", 2))}
                })
            elif plugin_id == "evey-learner":
                save_autonomy_settings({
                    "sla_enforcer": {"min_quality_score": float(cfg.get("min_quality_score", 0.75))},
                    "skill_synthesizer": {"enabled": bool(cfg.get("auto_index_skills", True))}
                })
            elif plugin_id == "evey-scheduler":
                save_autonomy_settings({
                    "concurrency": {"max_concurrent_agents": int(cfg.get("worker_concurrency", 4))},
                    "dead_letter_queue": {"max_replay_attempts": int(cfg.get("max_retry_attempts", 3))}
                })
            elif plugin_id == "evey-digest":
                save_autonomy_settings({
                    "inbox_watcher": {"standup_hour": str(cfg.get("daily_digest_time", "07:30"))}
                })
            elif plugin_id == "evey-status":
                save_autonomy_settings({
                    "resource_backpressure": {"max_cpu_percent": float(cfg.get("cpu_threshold_percent", 85.0))}
                })
        except Exception as sync_err:
            print(f"Warnung bei Autonomy-Settings-Sync ({plugin_id}): {sync_err}")

        add_ticker("Guardian", f"Einstellungen für Modul '{plugin_id}' gespeichert (settings.json synchronisiert).")
        return {"status": "success", "plugin_id": plugin_id, "message": "Gespeichert", "config": cfg}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/api/guardian/cache/clear")
def api_clear_guardian_cache():
    """Leert den Delegation- und Prompt-Cache."""
    cache_file = os.path.expanduser("~/.hermes/workspace/orchestrator/delegation-cache.json")
    if not os.path.exists(cache_file):
        cache_file = "/opt/data/workspace/orchestrator/delegation-cache.json"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({}, f)
        except Exception:
            pass
    add_ticker("Guardian", "Delegations- & Prompt-Cache geleert.")
    return {"status": "success", "message": "Cache erfolgreich geleert"}

