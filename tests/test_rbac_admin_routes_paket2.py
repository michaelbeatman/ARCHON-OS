"""RBAC Paket 2 — Rollenzaun auf den restlichen destruktiven Routen.

Grundlage: ``docs/GRUENDPRUEFUNG`` §4.2 (78 schreibende Admin-nahe Routen, 6
geschuetzt) und ``docs/HANDOVER_2026-11-07_session2.md`` §7 (Prio 1). Dieser
Test deckt **jede** in Paket 2 neu geschuetzte Route ab.

Je Route zwei Zusagen:

* ``operator``/``viewer`` -> **403** mit Hinweis auf "Administratoren", und
  zwar bevor die erste fachliche Anweisung laeuft (der Zaun steht vorne).
* ``admin`` -> der Zaun **laesst durch**. Nachgewiesen ueber eine
  Sonde: die injizierte Prueffunktion ruft die *echte* ``require_admin`` auf
  und wirft bei Erfolg 418. Damit ist belegt, dass die Route den Zaun
  erreicht und die Rollenlogik greift, **ohne** dass Fachcode laeuft — kein
  Test loest Docker-Aktionen, Dateischreibvorgaenge oder LLM-Aufrufe aus.

Die Routen werden direkt als Funktion aufgerufen (kein HTTP-Stack): der
Request-Body wird dadurch nicht validiert und die Tests bleiben nebenwirkungsfrei.

Dazu die Durchlaessigkeits-Belege auf der gemeinsamen Prueffunktion
(Service-Token, ``auth.enabled = false``, Admin-Session) sowie der
fail-closed-Nachweis fuer das gemeinsame Router-Modul.
"""

import asyncio
import inspect
import os
import sys

import pytest
from fastapi import HTTPException
from starlette.requests import Request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("ARCHON_ROOT") or os.path.dirname(_HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

ADMIN = {"id": "usr_admin", "username": "admin", "role": "admin", "permissions": {},
         "is_service": False}
OPERATOR = {"id": "usr_op", "username": "lisa", "role": "operator", "permissions": {}}
VIEWER = {"id": "usr_vw", "username": "max", "role": "viewer", "permissions": {}}
SERVICE = {"id": "usr_service", "username": "service", "role": "admin",
           "permissions": ["service"], "is_service": True}

GUARD_PASSED = 418

# (Methode, Modul, Pfad, Funktionsname, Datei, test-id)
NEW_ADMIN_ROUTES = [
    pytest.param('POST', 'archon.routers.boardroom', '/api/boardroom/frameworks', 'api_save_boardroom_frameworks', 'archon/routers/boardroom.py', id='post-api-boardroom-frameworks'),
    pytest.param('POST', 'archon.routers.boardroom', '/api/boardroom/frameworks/reset', 'api_reset_boardroom_frameworks', 'archon/routers/boardroom.py', id='post-api-boardroom-frameworks-reset'),
    pytest.param('POST', 'archon.routers.governance', '/api/governance/ai-act/reclassify/{agent_id}', 'api_ai_act_reclassify', 'archon/routers/governance.py', id='post-api-governance-ai-act-reclassify-agent-id'),
    pytest.param('POST', 'archon.routers.governance', '/api/v1/governance/ai-act/reclassify/{agent_id}', 'api_ai_act_reclassify', 'archon/routers/governance.py', id='post-api-v1-governance-ai-act-reclassify-agent-id'),
    pytest.param('POST', 'archon.routers.hermes_profiles', '/api/hermes/profiles', 'api_save_hermes_profile', 'archon/routers/hermes_profiles.py', id='post-api-hermes-profiles'),
    pytest.param('DELETE', 'archon.routers.hermes_profiles', '/api/hermes/profiles/{profile_id}', 'api_delete_hermes_profile', 'archon/routers/hermes_profiles.py', id='delete-api-hermes-profiles-profile-id'),
    pytest.param('POST', 'archon.routers.hermes_profiles', '/api/hermes/profiles/{profile_id}/fire-paperclip', 'api_fire_hermes_profile_paperclip', 'archon/routers/hermes_profiles.py', id='post-api-hermes-profiles-profile-id-fire-paperclip'),
    pytest.param('POST', 'archon.routers.hermes_profiles', '/api/hermes/profiles/{profile_id}/hire-paperclip', 'api_hire_hermes_profile_paperclip', 'archon/routers/hermes_profiles.py', id='post-api-hermes-profiles-profile-id-hire-paperclip'),
    pytest.param('POST', 'archon.routers.hermes_profiles', '/api/hermes/profiles/{profile_id}/model', 'api_set_hermes_profile_model', 'archon/routers/hermes_profiles.py', id='post-api-hermes-profiles-profile-id-model'),
    pytest.param('POST', 'archon.routers.hermes_profiles', '/api/hermes/profiles/{profile_id}/status', 'api_update_hermes_profile_status', 'archon/routers/hermes_profiles.py', id='post-api-hermes-profiles-profile-id-status'),
    pytest.param('POST', 'archon.routers.llm_providers', '/api/llm-providers/privacy-routing', 'api_save_privacy_routing', 'archon/routers/llm_providers.py', id='post-api-llm-providers-privacy-routing'),
    pytest.param('POST', 'archon.routers.llm_providers', '/api/llm-providers/save-key', 'save_llm_provider_key', 'archon/routers/llm_providers.py', id='post-api-llm-providers-save-key'),
    pytest.param('POST', 'archon.routers.llm_providers', '/api/llm-providers/select', 'select_llm_provider', 'archon/routers/llm_providers.py', id='post-api-llm-providers-select'),
    pytest.param('POST', 'archon.routers.plugins', '/api/v1/plugins/tools/execute', 'api_execute_plugin_tool', 'archon/routers/plugins.py', id='post-api-v1-plugins-tools-execute'),
    pytest.param('POST', 'archon.routers.plugins', '/api/v1/plugins/{plugin_id}/config', 'api_save_plugin_settings', 'archon/routers/plugins.py', id='post-api-v1-plugins-plugin-id-config'),
    pytest.param('POST', 'archon.routers.plugins', '/api/v1/plugins/{plugin_id}/reload', 'api_reload_plugin', 'archon/routers/plugins.py', id='post-api-v1-plugins-plugin-id-reload'),
    pytest.param('POST', 'archon.routers.plugins', '/api/v1/plugins/{plugin_id}/toggle', 'api_toggle_plugin', 'archon/routers/plugins.py', id='post-api-v1-plugins-plugin-id-toggle'),
    pytest.param('POST', 'archon.routers.skills', '/api/hermes/skills/{skill_id}', 'api_save_single_hermes_skill', 'archon/routers/skills.py', id='post-api-hermes-skills-skill-id'),
    pytest.param('POST', 'archon.routers.skills', '/api/hermes/skills/{skill_id}/reset', 'api_reset_single_hermes_skill', 'archon/routers/skills.py', id='post-api-hermes-skills-skill-id-reset'),
    pytest.param('POST', 'archon.routers.skills', '/api/v1/skills/docker/restart', 'api_skills_docker_restart', 'archon/routers/skills.py', id='post-api-v1-skills-docker-restart'),
    pytest.param('POST', 'archon.routers.skills', '/api/v1/skills/git/commit', 'api_skills_git_commit', 'archon/routers/skills.py', id='post-api-v1-skills-git-commit'),
    pytest.param('POST', 'archon.routers.skills', '/api/v1/skills/git/pytest', 'api_skills_git_pytest', 'archon/routers/skills.py', id='post-api-v1-skills-git-pytest'),
    pytest.param('POST', 'archon.routers.skills', '/api/v1/skills/mcp/connect', 'api_skills_mcp_connect', 'archon/routers/skills.py', id='post-api-v1-skills-mcp-connect'),
    pytest.param('POST', 'archon.routers.skills', '/api/v1/skills/mcp/execute', 'api_skills_mcp_execute', 'archon/routers/skills.py', id='post-api-v1-skills-mcp-execute'),
    pytest.param('POST', 'archon.routers.swarm', '/api/swarm/spawn-ephemeral-team', 'api_spawn_ephemeral_team', 'archon/routers/swarm.py', id='post-api-swarm-spawn-ephemeral-team'),
    pytest.param('POST', 'archon.routers.system', '/api/system/backup-db', 'api_backup_databases', 'archon/routers/system.py', id='post-api-system-backup-db'),
    pytest.param('POST', 'archon.routers.system', '/api/system/drain/cancel', 'api_cancel_drain', 'archon/routers/system.py', id='post-api-system-drain-cancel'),
    pytest.param('POST', 'archon.routers.system', '/api/system/drain/execute-shutdown', 'api_execute_shutdown', 'archon/routers/system.py', id='post-api-system-drain-execute-shutdown'),
    pytest.param('POST', 'archon.routers.system', '/api/system/drain/start', 'api_start_drain', 'archon/routers/system.py', id='post-api-system-drain-start'),
    pytest.param('POST', 'archon.routers.system', '/api/system/hermes/restart', 'api_system_hermes_restart', 'archon/routers/system.py', id='post-api-system-hermes-restart'),
    pytest.param('POST', 'archon.routers.system', '/api/system/language', 'set_system_language', 'archon/routers/system.py', id='post-api-system-language'),
    pytest.param('POST', 'archon.routers.system', '/api/system/optimize-db', 'api_optimize_db', 'archon/routers/system.py', id='post-api-system-optimize-db'),
    pytest.param('POST', 'archon.routers.system', '/api/v1/system/drain/cancel', 'api_cancel_drain', 'archon/routers/system.py', id='post-api-v1-system-drain-cancel'),
    pytest.param('POST', 'archon.routers.system', '/api/v1/system/drain/execute-shutdown', 'api_execute_shutdown', 'archon/routers/system.py', id='post-api-v1-system-drain-execute-shutdown'),
    pytest.param('POST', 'archon.routers.system', '/api/v1/system/drain/start', 'api_start_drain', 'archon/routers/system.py', id='post-api-v1-system-drain-start'),
    pytest.param('POST', 'archon.routers.system', '/api/v1/system/update/backup', 'api_system_update_backup', 'archon/routers/system.py', id='post-api-v1-system-update-backup'),
    pytest.param('POST', 'archon.routers.system', '/api/v1/system/update/push', 'api_system_update_push', 'archon/routers/system.py', id='post-api-v1-system-update-push'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/approvals/policies', 'api_update_approval_policy', 'backend/operations_api.py', id='post-api-operations-approvals-policies'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/autonomy/evolve-tool', 'trigger_tool_evolution', 'backend/operations_api.py', id='post-api-operations-autonomy-evolve-tool'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/autonomy/jit-persona/execute', 'execute_jit_persona_task', 'backend/operations_api.py', id='post-api-operations-autonomy-jit-persona-execute'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/backup/restore-test', 'api_trigger_restore_test', 'backend/operations_api.py', id='post-api-operations-backup-restore-test'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/bot-screen/abort', 'abort_bot_screen_execution', 'backend/operations_api.py', id='post-api-operations-bot-screen-abort'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/bot-screen/interact', 'interact_with_bot_screen', 'backend/operations_api.py', id='post-api-operations-bot-screen-interact'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/bot-screen/takeover/request', 'request_human_takeover', 'backend/operations_api.py', id='post-api-operations-bot-screen-takeover-request'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/bot-screen/takeover/resume', 'resume_from_human_takeover', 'backend/operations_api.py', id='post-api-operations-bot-screen-takeover-resume'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/chaos/run', 'api_chaos_run', 'backend/operations_api.py', id='post-api-operations-chaos-run'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/gdpr/erase', 'api_gdpr_erase', 'backend/operations_api.py', id='post-api-operations-gdpr-erase'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/gdpr/export', 'api_gdpr_export', 'backend/operations_api.py', id='post-api-operations-gdpr-export'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/governance/concurrency', 'update_concurrency_settings', 'backend/operations_api.py', id='post-api-operations-governance-concurrency'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/keys', 'api_create_key', 'backend/operations_api.py', id='post-api-operations-keys'),
    pytest.param('DELETE', 'backend.operations_api', '/api/operations/keys/{key_id}', 'api_delete_key', 'backend/operations_api.py', id='delete-api-operations-keys-key-id'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/keys/{key_id}/revoke', 'api_revoke_key', 'backend/operations_api.py', id='post-api-operations-keys-key-id-revoke'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/mcp/call', 'api_call_mcp_tool', 'backend/operations_api.py', id='post-api-operations-mcp-call'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/notifications/policy', 'api_update_notification_policy', 'backend/operations_api.py', id='post-api-operations-notifications-policy'),
    pytest.param('DELETE', 'backend.operations_api', '/api/operations/org-hierarchy', 'reset_org_hierarchy', 'backend/operations_api.py', id='delete-api-operations-org-hierarchy'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/org-hierarchy', 'save_org_hierarchy', 'backend/operations_api.py', id='post-api-operations-org-hierarchy'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/prompts/{agent_id}/canary', 'api_set_prompt_canary', 'backend/operations_api.py', id='post-api-operations-prompts-agent-id-canary'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/prompts/{agent_id}/promote', 'api_promote_prompt_canary', 'backend/operations_api.py', id='post-api-operations-prompts-agent-id-promote'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/prompts/{agent_id}/rollback', 'api_rollback_prompt_version', 'backend/operations_api.py', id='post-api-operations-prompts-agent-id-rollback'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/prompts/{agent_id}/versions', 'api_save_prompt_version', 'backend/operations_api.py', id='post-api-operations-prompts-agent-id-versions'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/security/break-glass/create', 'api_create_break_glass_vault', 'backend/operations_api.py', id='post-api-operations-security-break-glass-create'),
    pytest.param('POST', 'backend.operations_api', '/api/operations/security/trusted-sources/toggle', 'api_toggle_trusted_source', 'backend/operations_api.py', id='post-api-operations-security-trusted-sources-toggle'),
    pytest.param('POST', 'main', '/api/agents', 'api_save_agents', 'main.py', id='post-api-agents'),
    pytest.param('POST', 'main', '/api/browser/browse-and-capture', 'api_browse_and_capture', 'main.py', id='post-api-browser-browse-and-capture'),
    pytest.param('POST', 'main', '/api/concurrency/config', 'api_save_concurrency_config', 'main.py', id='post-api-concurrency-config'),
    pytest.param('POST', 'main', '/api/evolution/optimize-prompt', 'api_optimize_role_prompt', 'main.py', id='post-api-evolution-optimize-prompt'),
    pytest.param('POST', 'main', '/api/fleet/heal/{service_name}', 'api_heal_service', 'main.py', id='post-api-fleet-heal-service-name'),
    pytest.param('POST', 'main', '/api/guardian/config', 'api_save_guardian_config', 'main.py', id='post-api-guardian-config'),
    pytest.param('POST', 'main', '/api/guardian/plugin/toggle', 'api_toggle_guardian_plugin', 'main.py', id='post-api-guardian-plugin-toggle'),
    pytest.param('POST', 'main', '/api/guardian/plugins/toggle', 'api_toggle_guardian_plugin', 'main.py', id='post-api-guardian-plugins-toggle'),
    pytest.param('POST', 'main', '/api/guardian/plugins/{plugin_id}/config', 'api_save_plugin_config', 'main.py', id='post-api-guardian-plugins-plugin-id-config'),
    pytest.param('POST', 'main', '/api/hermes/config', 'api_save_hermes_config', 'main.py', id='post-api-hermes-config'),
    pytest.param('POST', 'main', '/api/hermes/memory/purge', 'api_hermes_memory_purge', 'main.py', id='post-api-hermes-memory-purge'),
    pytest.param('POST', 'main', '/api/hermes/raw_config', 'api_save_hermes_raw_config', 'main.py', id='post-api-hermes-raw-config'),
    pytest.param('POST', 'main', '/api/hermes/settings', 'api_save_hermes_form_config', 'main.py', id='post-api-hermes-settings'),
    pytest.param('POST', 'main', '/api/inbox-watcher/config', 'api_save_inbox_watcher_config', 'main.py', id='post-api-inbox-watcher-config'),
    pytest.param('POST', 'main', '/api/marketplace/recruit', 'api_marketplace_recruit', 'main.py', id='post-api-marketplace-recruit'),
    pytest.param('POST', 'main', '/api/marketplace/skills/assign', 'api_assign_skill_to_profile', 'main.py', id='post-api-marketplace-skills-assign'),
    pytest.param('POST', 'main', '/api/permission-gates/{gate_id}/decide', 'api_decide_permission_gate', 'main.py', id='post-api-permission-gates-gate-id-decide'),
    pytest.param('POST', 'main', '/api/roles', 'api_save_roles', 'main.py', id='post-api-roles'),
    pytest.param('POST', 'main', '/api/sandbox', 'api_run_python_sandbox', 'main.py', id='post-api-sandbox'),
    pytest.param('POST', 'main', '/api/settings', 'api_save_settings', 'main.py', id='post-api-settings'),
    pytest.param('POST', 'main', '/api/settings/autonomy-modules', 'api_save_autonomy_modules_settings', 'main.py', id='post-api-settings-autonomy-modules'),
    pytest.param('POST', 'main', '/api/settings/memory-consolidation', 'api_save_memory_consolidation_settings', 'main.py', id='post-api-settings-memory-consolidation'),
    pytest.param('POST', 'main', '/api/settings/model-routing', 'api_save_model_routing', 'main.py', id='post-api-settings-model-routing'),
    pytest.param('POST', 'main', '/api/skills/proposals/{proposal_id}/approve', 'api_approve_skill_proposal', 'main.py', id='post-api-skills-proposals-proposal-id-approve'),
    pytest.param('POST', 'main', '/api/snapshots/{snapshot_id}/restore', 'api_restore_snapshot', 'main.py', id='post-api-snapshots-snapshot-id-restore'),
    pytest.param('POST', 'main', '/api/tools/proposals', 'api_create_tool_proposal', 'main.py', id='post-api-tools-proposals'),
    pytest.param('POST', 'main', '/api/tools/proposals/{permission_id}/resolve', 'api_resolve_tool_proposal', 'main.py', id='post-api-tools-proposals-permission-id-resolve'),
    pytest.param('POST', 'main', '/api/v1/container/action', 'run_container_action', 'main.py', id='post-api-v1-container-action'),
    pytest.param('POST', 'main', '/api/v1/container/inject_config', 'inject_container_config', 'main.py', id='post-api-v1-container-inject-config'),
    pytest.param('POST', 'main', '/api/v1/container/settings', 'save_container_settings', 'main.py', id='post-api-v1-container-settings'),
    pytest.param('POST', 'main', '/api/v1/gateway/autostart', 'api_gateway_autostart', 'main.py', id='post-api-v1-gateway-autostart'),
    pytest.param('POST', 'main', '/api/v1/gateway/config', 'api_save_gateway_config_endpoint', 'main.py', id='post-api-v1-gateway-config'),
    pytest.param('POST', 'main', '/api/v1/gateway/start', 'api_gateway_start', 'main.py', id='post-api-v1-gateway-start'),
    pytest.param('POST', 'main', '/api/v1/gateway/stop', 'api_gateway_stop', 'main.py', id='post-api-v1-gateway-stop'),
    pytest.param('POST', 'main', '/api/v1/gateway/stop-all', 'api_gateway_stop_all', 'main.py', id='post-api-v1-gateway-stop-all'),
    pytest.param('POST', 'main', '/api/v1/hermes/soul/{agent_id}', 'api_save_hermes_soul', 'main.py', id='post-api-v1-hermes-soul-agent-id'),
    pytest.param('POST', 'main', '/api/v1/services', 'api_save_services', 'main.py', id='post-api-v1-services'),
    pytest.param('POST', 'main', '/api/v1/settings/smtp', 'api_save_smtp_settings', 'main.py', id='post-api-v1-settings-smtp'),
    pytest.param('POST', 'main', '/api/v1/settings/smtp/test', 'api_test_smtp_settings', 'main.py', id='post-api-v1-settings-smtp-test'),
    pytest.param('POST', 'main', '/api/v1/ui/save-full-html', 'api_save_full_html', 'main.py', id='post-api-v1-ui-save-full-html'),
    pytest.param('POST', 'main', '/api/v1/ui/save-text-replacements', 'api_save_text_replacements', 'main.py', id='post-api-v1-ui-save-text-replacements'),
    pytest.param('POST', 'main', '/api/v1/watchdog/config', 'api_save_watchdog_config', 'main.py', id='post-api-v1-watchdog-config'),
    pytest.param('POST', 'main', '/api/v1/watchdog/dispatch_action', 'api_watchdog_dispatch_action', 'main.py', id='post-api-v1-watchdog-dispatch-action'),
    pytest.param('POST', 'main', '/api/v1/watchdog/run_now', 'api_trigger_watchdog_run', 'main.py', id='post-api-v1-watchdog-run-now'),
    pytest.param('POST', 'main', '/api/v1/watchdog/test-alarm', 'trigger_test_watchdog_alarm_endpoint', 'main.py', id='post-api-v1-watchdog-test-alarm'),
    pytest.param('POST', 'views_core', '/api/views/showroom/file/delete', 'delete_showroom_file', 'views_core.py', id='post-api-views-showroom-file-delete'),
    pytest.param('POST', 'views_core', '/api/views/showroom/file/purge', 'purge_showroom_file', 'views_core.py', id='post-api-views-showroom-file-purge'),
    pytest.param('POST', 'views_core', '/api/views/showroom/file/restore', 'restore_showroom_file', 'views_core.py', id='post-api-views-showroom-file-restore'),
    pytest.param('POST', 'views_core', '/api/views/showroom/run-code', 'run_showroom_code', 'views_core.py', id='post-api-views-showroom-run-code'),
    # Nachtrag Router-Nachpruefung (2026-11-07): zwei Klasse-A-Routen, die die
    # Inventur des Paket-2-Laufs uebersehen hatte — Container-Exec bzw. Config-Write.
    pytest.param('POST', 'archon.routers.governance', '/api/governance/promptfoo/run-eval', 'api_run_promptfoo_eval', 'archon/routers/governance.py', id='post-api-governance-promptfoo-run-eval'),
    pytest.param('POST', 'main', '/api/v1/brain/quartz-config', 'api_save_quartz_config', 'main.py', id='post-api-v1-brain-quartz-config'),
]


def _app():
    import main  # noqa: PLC0415  (spaeter Import: ~1 s Modulaufbau)
    return main


def _fake_request(method, path, headers=None):
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or [])],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "app": _app().app,
    })


def _endpoint(module_name, func_name):
    module = __import__(module_name, fromlist=["*"])
    fn = getattr(module, func_name, None)
    assert fn is not None, f"{module_name}.{func_name} nicht gefunden"
    return fn


def _call(module_name, func_name, request):
    """Ruft den Handler mit Dummy-Argumenten auf; der Zaun wirft vorher."""
    fn = _endpoint(module_name, func_name)
    kwargs = {"request": request}
    for name, param in inspect.signature(fn).parameters.items():
        if name == "request" or param.default is not inspect.Parameter.empty:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        kwargs[name] = "probe"
    if asyncio.iscoroutinefunction(fn):
        # asyncio.run statt get_event_loop(): andere Tests schliessen den
        # Default-Loop, dann gaebe es hier "no current event loop".
        return asyncio.run(fn(**kwargs))
    return fn(**kwargs)


@pytest.fixture()
def guards(monkeypatch):
    """Verdrahtet die Sonde in alle drei Injektionswege (main, _rbac, system._DEPS)."""
    from archon.routers import _rbac as rbac_module
    import archon.routers.system as system_router

    main = _app()
    real = main.require_admin
    state = {"role": ADMIN}

    def probe(request):
        # echte Rollenlogik mit gesteuerter Identitaet
        monkeypatch.setattr(main, "get_current_user_from_request",
                            lambda r: dict(state["role"]))
        real(request)
        raise HTTPException(status_code=GUARD_PASSED, detail="RBAC_GUARD_PASSED")

    def use(role):
        state["role"] = role

    monkeypatch.setattr(main, "require_admin", probe)
    previous = rbac_module._checker
    rbac_module.configure(require_admin=probe)
    monkeypatch.setitem(system_router._DEPS, "require_admin", probe)
    try:
        yield use
    finally:
        rbac_module._checker = previous


@pytest.mark.parametrize("role", [OPERATOR, VIEWER], ids=["operator", "viewer"])
@pytest.mark.parametrize("method,module,path,func,file_id", NEW_ADMIN_ROUTES)
def test_non_admin_get_403(guards, role, method, module, path, func, file_id):
    """Nicht-Admin: 403 aus dem Zaun, vor jeder fachlichen Anweisung."""
    guards(role)

    with pytest.raises(HTTPException) as exc:
        _call(module, func, _fake_request(method, path))

    assert exc.value.status_code == 403, (
        f"{method} {path} ({file_id}:{func}) sperrte nicht: {exc.value.status_code} "
        f"{exc.value.detail}"
    )
    assert "Administratoren" in str(exc.value.detail)


@pytest.mark.parametrize("method,module,path,func,file_id", NEW_ADMIN_ROUTES)
def test_admin_passes_guard(guards, method, module, path, func, file_id):
    """Admin: der Zaun laesst durch (Sonde 418) — kein Fachcode, keine Nebenwirkung."""
    guards(ADMIN)

    with pytest.raises(HTTPException) as exc:
        _call(module, func, _fake_request(method, path))

    assert exc.value.status_code == GUARD_PASSED, (
        f"{method} {path} ({file_id}:{func}) erreichte den Zaun nicht oder liess "
        f"Admin nicht durch: {exc.value.status_code} {exc.value.detail}"
    )


# ------------------------------------------- Durchlaessigkeit (echte Pruefung)
#
# Diese Tests gehen durch `main.get_current_user_from_request` — nicht durch
# eine Attrappe. Nur die Datenquellen (Session-Store, Service-Token,
# auth-Schalter) sind gesteuert, die Entscheidung faellt im echten Code.

def test_admin_session_passes(monkeypatch):
    """Admin-Session (Bearer) passiert den echten Zaun."""
    main = _app()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(ADMIN))

    request = _fake_request("POST", "/api/roles", headers=[("authorization", "Bearer tok_admin")])
    result = main.require_admin(request)

    assert result["role"] == "admin"
    assert result["id"] == "usr_admin"


def test_service_token_passes(monkeypatch):
    """X-Archon-Service-Token (interne Automaten) passiert den echten Zaun."""
    main = _app()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main, "_get_service_token", lambda: "tok-service-test")

    request = _fake_request("POST", "/api/roles",
                            headers=[("x-archon-service-token", "tok-service-test")])
    result = main.require_admin(request)

    assert result["role"] == "admin"
    assert result["id"] == "usr_service"


def test_wrong_service_token_grants_nothing(monkeypatch):
    """Ein falscher Service-Token ist kein Freifahrtschein."""
    main = _app()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main, "_get_service_token", lambda: "tok-service-test")

    request = _fake_request("POST", "/api/roles",
                            headers=[("x-archon-service-token", "tok-falsch")])
    with pytest.raises(HTTPException) as exc:
        main.require_admin(request)

    assert exc.value.status_code == 403


def test_auth_disabled_stays_open(monkeypatch):
    """auth.enabled=false: Fallback-Admin, das Einzelnutzer-System bleibt bedienbar."""
    main = _app()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(main.auth_service, "get_fallback_admin",
                        lambda: dict(ADMIN, is_fallback=True))

    result = main.require_admin(_fake_request("POST", "/api/roles"))

    assert result["role"] == "admin"
    assert result.get("is_fallback") is True


@pytest.mark.parametrize("user", [OPERATOR, VIEWER], ids=["operator", "viewer"])
def test_session_without_admin_role_is_blocked(monkeypatch, user):
    """Eine gueltige Session ohne Admin-Rolle wird gesperrt (401 waere Auth, 403 ist Autorisation)."""
    main = _app()
    monkeypatch.setattr(main.auth_service, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(main.auth_service, "verify_session", lambda tok: dict(user))

    request = _fake_request("POST", "/api/roles", headers=[("authorization", "Bearer tok_user")])
    with pytest.raises(HTTPException) as exc:
        main.require_admin(request)

    assert exc.value.status_code == 403
    assert user["role"] in str(exc.value.detail)


# --------------------------------------------------------- Router fail-closed

def test_shared_router_guard_fails_closed(monkeypatch):
    """Ohne Injektion sperrt das gemeinsame Router-Modul (503), nicht offen."""
    from archon.routers import _rbac as rbac_module

    monkeypatch.setattr(rbac_module, "_checker", None)

    with pytest.raises(HTTPException) as exc:
        rbac_module.require_admin_or_503(_fake_request("POST", "/api/roles"))

    assert exc.value.status_code == 503
    assert "nicht verdrahtet" in str(exc.value.detail)


def test_shared_router_guard_is_wired_in_app():
    """Die App verdrahtet den gemeinsamen Zaun beim Start (main -> _rbac)."""
    from archon.routers import _rbac as rbac_module

    _app()

    assert rbac_module.is_configured(), (
        "main.py hat _rbac.configure(require_admin=...) nicht aufgerufen — "
        "alle geschuetzten Router-Routen wuerden fail-closed sperren (503)"
    )
