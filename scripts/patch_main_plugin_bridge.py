# -*- coding: utf-8 -*-
"""
Verbindet api_get_guardian_config, api_toggle_guardian_plugin, api_get_plugin_config
und api_save_plugin_config in main.py bidirektional mit backend/autonomy_settings.py (settings.json).
"""

MAIN_PATH = "/app/main.py"

OLD_DISCOVERY = """    if os.path.exists(plugins_dir):
        for p_yaml in sorted(glob.glob(os.path.join(plugins_dir, "*/plugin.yaml"))):
            try:
                folder_name = os.path.basename(os.path.dirname(p_yaml))
                with open(p_yaml, "r", encoding="utf-8") as pf:
                    p_info = yaml.safe_load(pf) or {}
                p_id = p_info.get("name", folder_name)
                p_desc = p_info.get("description", "")
                p_cat = category_map.get(p_id, "Weitere Module")
                p_tools = p_info.get("provides_tools", []) or p_info.get("tools", []) or []
                p_icon = icon_map.get(p_id, p_info.get("icon", "puzzle"))
                discovered_plugins.append({
                    "id": p_id,
                    "name": p_id.replace("evey-", "").replace("-", " ").title(),
                    "desc": p_desc,
                    "category": p_cat,
                    "tools": p_tools,
                    "icon": p_icon,
                    "version": str(p_info.get("version", "1.0.0")),
                    "enabled": p_id in enabled_plugins
                })
            except Exception:
                pass"""

NEW_DISCOVERY = """    # Bidirektionale Brücke zwischen Plugin-Registry und nativen Archon-OS-Modulen (settings.json)
    from backend.autonomy_settings import load_autonomy_settings
    aut_settings = load_autonomy_settings()
    sys_settings = _load_settings()

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
                elif p_id == "evey-memory-consolidate":
                    is_enabled = bool(sys_settings.get("memory_consolidation", {}).get("enabled", True))
                else:
                    is_enabled = (p_id in enabled_plugins) or (p_id == "evey-telegram-ux")

                discovered_plugins.append({
                    "id": p_id,
                    "name": p_name,
                    "desc": p_desc,
                    "category": p_cat,
                    "tools": p_tools,
                    "icon": p_icon,
                    "version": str(p_info.get("version", "2.6.0")),
                    "enabled": is_enabled
                })
            except Exception:
                pass"""

OLD_TOGGLE = """        cfg["plugins"]["enabled"] = enabled_list
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False)
            
        add_ticker("Guardian", f"Plugin '{plugin_id}' {'aktiviert' if enable else 'deaktiviert'}.")
        return {"status": "success", "plugin_id": plugin_id, "enabled": enable}"""

NEW_TOGGLE = """        cfg["plugins"]["enabled"] = enabled_list
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, default_flow_style=False)

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
            "evey-validate": ("sla_enforcer", "enabled"),
            "evey-verification": ("egress_firewall", "enabled"),
            "evey-delegate-model": ("speculative_hedging", "enabled"),
        }
        if plugin_id in plugin_autonomy_bridge:
            from backend.autonomy_settings import save_autonomy_settings
            grp, key = plugin_autonomy_bridge[plugin_id]
            save_autonomy_settings({grp: {key: bool(enable)}})
        elif plugin_id == "evey-memory-consolidate":
            s_cur = _load_settings()
            if "memory_consolidation" not in s_cur or not isinstance(s_cur["memory_consolidation"], dict):
                s_cur["memory_consolidation"] = {}
            s_cur["memory_consolidation"]["enabled"] = bool(enable)
            _save_settings(s_cur)

        add_ticker("Guardian", f"Modul '{plugin_id}' {'aktiviert' if enable else 'deaktiviert'} (settings.json synchronisiert).")
        return {"status": "success", "plugin_id": plugin_id, "enabled": bool(enable)}"""

OLD_GET_CFG_END = """    return {"status": "success", "plugin_id": plugin_id, "config": data}"""

NEW_GET_CFG_END = """    # 4. Überlagere mit echten Live-Schwellenwerten aus backend/autonomy_settings.py (settings.json)
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

    return {"status": "success", "plugin_id": plugin_id, "config": data}"""

OLD_SAVE_CFG_END = """        add_ticker("Guardian", f"Einstellungen für Plugin '{plugin_id}' gespeichert.")
        return {"status": "success", "plugin_id": plugin_id, "message": "Gespeichert", "config": cfg}"""

NEW_SAVE_CFG_END = """        # 3. Synchronisiere geänderte Schwellenwerte direkt zurück in backend/autonomy_settings.py (settings.json)
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
        return {"status": "success", "plugin_id": plugin_id, "message": "Gespeichert", "config": cfg}"""

with open(MAIN_PATH, "r", encoding="utf-8") as f:
    raw = f.read()

norm = raw.replace("\r\n", "\n")
assert OLD_DISCOVERY in norm, "OLD_DISCOVERY nicht gefunden"
assert OLD_TOGGLE in norm, "OLD_TOGGLE nicht gefunden"
assert OLD_GET_CFG_END in norm, "OLD_GET_CFG_END nicht gefunden"
assert OLD_SAVE_CFG_END in norm, "OLD_SAVE_CFG_END nicht gefunden"

norm = norm.replace(OLD_DISCOVERY, NEW_DISCOVERY, 1)
norm = norm.replace(OLD_TOGGLE, NEW_TOGGLE, 1)
norm = norm.replace(OLD_GET_CFG_END, NEW_GET_CFG_END, 1)
norm = norm.replace(OLD_SAVE_CFG_END, NEW_SAVE_CFG_END, 1)

with open(MAIN_PATH, "w", encoding="utf-8") as f:
    f.write(norm)

print("main.py erfolgreich mit bidirektionaler Plugin-Autonomie-Brücke gepatcht.")
