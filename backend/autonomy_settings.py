"""
backend/autonomy_settings.py
Zentrale Konfigurations- & Schwellenwert-Verwaltung für alle autonomen Archon OS Module (Batch 1–10).
Stellt sicher, dass sämtliche Schutz-, Resilienz-, Sandbox-, Governance- und Wartungs-Mechaniken
über settings.json und das System Control Center (UI) ein-/ausgeschaltet und feinjustiert werden können.
"""

import os
import json
from typing import Dict, Any

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(WORKSPACE_DIR, "settings.json")

DEFAULT_AUTONOMY_SETTINGS: Dict[str, Dict[str, Any]] = {
    # Gruppe 1: Concurrency & Deadlock-Supervisor
    "concurrency": {
        "max_concurrent_agents": 4,
        "queue_timeout_seconds": 60,
        "auto_deadlock_recovery": True,
        "stagnation_threshold_seconds": 45
    },
    # Gruppe 2: Circuit Breaker, Loop-Killer & Token-Clipper
    "circuit_breaker": {
        "loop_detection_enabled": True,
        "max_identical_turns": 3,
        "jaccard_similarity_threshold": 0.90,
        "max_steps_per_task": 15,
        "budget_downgrade_threshold_pct": 80,
        "token_clipper_enabled": True
    },
    # Gruppe 3: Autonome Task-Selbstheilung & Git-Rollback
    "task_self_healer": {
        "enabled": True,
        # F2/N-12: Rollback ist opt-in (Default aus). Ein automatisches
        # `git checkout` im Multi-Agenten-Repo verwirft fremde Arbeit.
        "auto_git_rollback": False,
        "max_attempts": 3,
        "escalation_model": "deepseek/deepseek-chat"
    },
    # Gruppe 4: Ephemeral Docker Sandbox
    "ephemeral_sandbox": {
        "enabled": True,
        "memory_limit_mb": 512,
        "cpu_limit": 1.0,
        "timeout_seconds": 30,
        "network_enabled": False
    },
    # Gruppe 5: Replay, Time-Travel Debugger & Pre-Write Snapshots
    "time_travel_snapshots": {
        "tracing_enabled": True,
        "auto_pre_write_snapshots": True,
        "max_snapshots": 50,
        "max_trace_steps": 100
    },
    # Gruppe 6: Konsens-Gate & Tri-Agent Schiedsgericht
    "consensus_gate": {
        "enabled": True,
        "min_priority": 3,
        "mode": "tri_agent_council",
        "majority_rule": "two_thirds",
        "default_model": "deepseek/deepseek-chat"
    },
    # Gruppe 7: Virtueller War-Room & Pre-Mortem Simulation
    "war_room": {
        "enabled": True,
        "auto_pre_mortem": False,
        "block_threshold": "HIGH",
        "default_model": "deepseek/deepseek-chat"
    },
    # Gruppe 8: SLA-Verträge & Handoff-Desk
    "sla_contracts": {
        "enabled": True,
        "min_content_length": 100,
        "max_turnaround_minutes": 60,
        "auto_reject_incomplete": True
    },
    # Gruppe 9: Inbox-Watcher, Event-Mesh & Proaktives Morgen-Standup
    "inbox_watcher": {
        "enabled": True,
        "watch_folder": os.path.join(WORKSPACE_DIR, "agent_workspace", "test_inbox_watch"),
        "processed_folder": os.path.join(WORKSPACE_DIR, "agent_workspace", "test_inbox_watch", "processed"),
        "interval_seconds": 5,
        "standup_enabled": True,
        "standup_time": "08:00"
    },
    # Gruppe 10: Fleet Self-Healing, DB-Backups, Secret-Masking & Visueller Browser
    "fleet_and_hygiene": {
        "auto_container_restart": True,
        "secret_masking_enabled": True,
        "visual_browser_audit": True,
        "db_backup_keep_days": 7
    },
    # Bereits vorhandene Gruppe: Nächtliche Gedächtnis-Konsolidierung
    "memory_consolidation": {
        "enabled": True,
        "schedule_time": "03:00",
        "retention_days": 14,
        "archive_threshold_similarity": 0.92,
        "auto_prune_temporary_logs": True,
        "last_run": None,
        "last_pruned_records_count": 0
    },
    # Paket 1 (Feature 1): Semantisches Prompt- & Response-Caching
    "semantic_cache": {
        "enabled": True,
        "similarity_threshold": 0.95,
        "ttl_hours": 24,
        "max_entries": 500
    },
    # Paket 1 (Feature 2): Paralleles Map-Reduce Sub-Tasking (Fan-Out / Fan-In)
    "map_reduce": {
        "enabled": True,
        "max_parallel_workers": 4,
        "chunk_timeout_seconds": 30,
        "auto_fan_out_min_items": 3
    },
    # Paket 1 (Feature 3): Speculative Fast-Routing & Latenz-Hedging
    "speculative_hedger": {
        "enabled": True,
        "hedge_delay_seconds": 2.5,
        "fallback_model": "deepseek/deepseek-chat",
        "max_hedged_calls_per_minute": 20
    },
    # Paket 1 (Feature 4): Dynamisches Context-Compaction & Hierarchisches Summarizing
    "context_compactor": {
        "enabled": True,
        "trigger_token_threshold": 6000,
        "keep_recent_turns": 4,
        "target_compression_ratio": 0.30
    },
    # Paket 1 (Feature 5): SQLite Connection-Pool & Async Write-Batching
    "write_batcher": {
        "enabled": True,
        "batch_size": 25,
        "flush_interval_seconds": 2.0,
        "max_queue_size": 1000
    },
    # Paket 2 (Feature 6): Hybrid-Search (BM25 FTS5 + Vektor-RAG + Reciprocal Rank Fusion)
    "hybrid_search": {
        "enabled": True,
        "rrf_k": 60,
        "bm25_weight": 0.5,
        "vector_weight": 0.5,
        "top_k": 5
    },
    # Paket 2 (Feature 7): Lokaler Knowledge-Graph (Entitäten- & Beziehungs-Tripel)
    "knowledge_graph": {
        "enabled": True,
        "auto_extract_triples": True,
        "max_traversal_hops": 2,
        "min_confidence": 0.70
    },
    # Paket 2 (Feature 8): Agentic Corrective RAG (CRAG / Selbstkorrigierende Wissensabfrage)
    "corrective_rag": {
        "enabled": True,
        "relevance_threshold": 0.45,
        "auto_query_rewrite": True,
        "max_rewrite_attempts": 2
    },
    # Paket 2 (Feature 9): 2-Stufen Core-Memory nach MemGPT/Letta-Vorbild (Pinned Working Memory)
    "core_memory_tier": {
        "enabled": True,
        "max_pinned_blocks": 10,
        "max_chars_per_block": 800,
        "auto_inject_into_system_prompt": True
    },
    # Paket 2 (Feature 10): Automatisches Citation- & Quellen-Pinning
    "citation_pinning": {
        "enabled": True,
        "require_inline_citations": True,
        "min_citation_coverage_pct": 60,
        "auto_append_sources_footer": True
    },
    # Paket 3 (Feature 11): Structured Outputs & JSON-Schema-Garantie
    "structured_outputs": {
        "enabled": True,
        "auto_repair_json": True,
        "strict_schema_validation": True,
        "max_repair_attempts": 2
    },
    # Paket 3 (Feature 12): Durable Execution Checkpointing (Pause / Resume)
    "durable_checkpointing": {
        "enabled": True,
        "checkpoint_every_n_steps": 1,
        "auto_resume_on_boot": True,
        "retention_days": 14
    },
    # Paket 3 (Feature 13): Idempotency-Keys & Tool-Call-Deduplizierung
    "idempotency_guard": {
        "enabled": True,
        "ttl_hours": 24,
        "block_duplicate_side_effects": True
    },
    # Paket 3 (Feature 14): Dry-Run / Shadow-Mode für Agenten-Aufträge
    "dry_run_shadow": {
        "enabled": False,
        "intercept_write_tools": True,
        "intercept_external_apis": True,
        "log_simulated_diffs": True
    },
    # Paket 3 (Feature 15): Dead-Letter-Queue (DLQ) mit Auto-Replay-Manager
    "dead_letter_queue": {
        "enabled": True,
        "max_replay_retries": 3,
        "backoff_base_seconds": 10,
        "auto_replay_enabled": True
    },
    # Paket 4 (Feature 16): Bidirektionaler PII-Scrubber & Re-Hydration (DSGVO)
    "pii_scrubber": {
        "enabled": True,
        "scrub_emails": True,
        "scrub_phones": True,
        "scrub_ibans": True,
        "auto_rehydrate_response": True
    },
    # Paket 4 (Feature 17): Egress-Firewall & Domain-Allowlisting für Agenten
    "egress_firewall": {
        "enabled": True,
        "default_policy": "allowlist_only",
        "allowed_domains": [
            "openrouter.ai", "api.openai.com", "generativelanguage.googleapis.com",
            "api.anthropic.com", "api.groq.com", "github.com", "localhost", "127.0.0.1"
        ],
        "block_raw_ip_egress": True
    },
    # Paket 4 (Feature 18): Granulare Agenten-RBAC & Datei-Scope-Jails
    "agent_rbac_jail": {
        "enabled": True,
        "enforce_path_jail": True,
        "block_dotenv_access": True,
        "block_system_dirs": True
    },
    # Paket 4 (Feature 19): Deterministischer Output-Linter & Policy-Checker
    "output_policy_linter": {
        "enabled": True,
        "strip_ai_slop_phrases": True,
        "block_destructive_commands": True,
        "auto_clean_output": True
    },
    # Paket 4 (Feature 20): Manipulationssichere Kosten- & Entscheidungs-Quittungen (Execution Receipts)
    "execution_receipts": {
        "enabled": True,
        "hash_algorithm": "sha256",
        "chain_receipts": True,
        "include_cost_breakdown": True
    },
    # Paket 5 (Feature 21): Automatischer Prompt-Optimizer (DSPy / TextGrad-Prinzip)
    "prompt_optimizer": {
        "enabled": True,
        "min_failures_to_trigger": 3,
        "auto_apply_patches": False,
        "max_rules_appended": 5
    },
    # Paket 5 (Feature 22): Gold-Standard Regression-Test-Suite (Eval-Dataset Runner)
    "eval_regression_suite": {
        "enabled": True,
        "min_pass_rate_pct": 90,
        "block_deploy_on_regression": True
    },
    # Paket 5 (Feature 23): Dynamisches Modell-Routing nach Echtzeit-Telemetrie (Bandit-Router)
    "bandit_router": {
        "enabled": True,
        "exploration_epsilon": 0.15,
        "latency_weight": 0.40,
        "success_weight": 0.60
    },
    # Paket 5 (Feature 24): Dynamisches Ephemeral-Team-Spawning (Ad-hoc Task-Force)
    "ephemeral_teams": {
        "enabled": True,
        "max_team_size": 4,
        "auto_dissolve_on_complete": True
    },
    # Paket 5 (Feature 25): Live-Ressourcen-Protector (Host CPU/RAM/Disk-Backpressure)
    "resource_backpressure": {
        "enabled": True,
        "max_cpu_pct": 85,
        "max_ram_pct": 85,
        "min_free_disk_gb": 2.0,
        "throttle_action": "pause_low_priority"
    },
    # Benachrichtigungs-Einstellungen und Ruhezeiten (Quiet Hours / Digest)
    "notification_policy": {
        "quiet_hours_enabled": True,
        "quiet_hours_start": "22:00",
        "quiet_hours_end": "07:00",
        "timezone": "Europe/Berlin",
        "allow_emergency_during_quiet": True,
        "digest_enabled": True,
        "digest_delivery_time": "08:00",
        "min_severity": "low"
    },
    # Selbst-Evolution & Voyager-Paradigma (Feature 6)
    "self_evolving_tooling": {
        "enabled": True,
        "max_repair_iterations": 3,
        "auto_sandbox_verification": True,
        "auto_register_skills": True
    },
    # MCTS Action Trajectories & Deep Reasoning Gate (Feature 8)
    "mcts_reasoning": {
        "enabled": False,
        "default_depth": 3,
        "rollout_budget": 4,
        "exploration_weight": 1.414,
        "min_task_complexity_score": 75
    },
    # Speculative Action & Resource Pre-fetching (Feature 10)
    "speculative_prefetcher": {
        "enabled": True,
        "ttl_seconds": 180,
        "prefetch_crm": True,
        "prefetch_erp": True,
        "prefetch_learnings": True
    },
    # Just-in-Time Ephemeral Persona Induction (Feature 13)
    "jit_persona_induction": {
        "enabled": True,
        "ephemeral_lifespan_minutes": 15,
        "auto_purge_on_completion": True,
        "allow_graduation_to_cadre": True
    }
}


def load_all_settings() -> Dict[str, Any]:
    """Lädt die gesamte settings.json und ergänzt fehlende Standardblöcke verlustfrei."""
    data: Dict[str, Any] = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
        except Exception:
            pass

    for section, defaults in DEFAULT_AUTONOMY_SETTINGS.items():
        if section not in data or not isinstance(data.get(section), dict):
            data[section] = dict(defaults)
        else:
            merged = dict(defaults)
            merged.update(data[section])
            data[section] = merged

    return data


load_autonomy_settings = load_all_settings


def get_module_config(section: str) -> Dict[str, Any]:
    """Gibt den Konfigurationsblock für ein spezifisches Modul zurück."""
    all_cfg = load_all_settings()
    return all_cfg.get(section, dict(DEFAULT_AUTONOMY_SETTINGS.get(section, {})))


def save_autonomy_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Aktualisiert einen oder mehrere Modul-Blöcke in settings.json und gibt den neuen Gesamtstand zurück."""
    current = load_all_settings()
    for key, val in updates.items():
        if isinstance(val, dict) and isinstance(current.get(key), dict):
            current[key].update(val)
        else:
            current[key] = val

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)

    return current
