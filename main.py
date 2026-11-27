import base64 as base64
import csv as csv
import datetime as datetime
import json
import logging
import os
import re as re
import secrets as secrets
import shutil as shutil
import socket as socket
import subprocess as subprocess
import sys
import tempfile as tempfile
import time
import uuid as uuid
from typing import Any, Dict, List, Optional

import httpx as httpx
import yaml as yaml
from fastapi import BackgroundTasks as BackgroundTasks
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi import File as File
from fastapi import Form as Form
from fastapi import Query as Query
from fastapi import UploadFile as UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    Response,
)
from fastapi.responses import HTMLResponse as HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import core_dispatcher
from archon.core.cache import invalidate as invalidate_ttl_cache
from archon.core.cache import ttl_cache
from archon.core.constants import (
    _AUTH_API_PREFIXES,
    _AUTH_PROTECTED_PREFIXES,
    _AUTH_PUBLIC_PREFIXES,
)
from archon.core.constants import _DECISION_TYPEN as _DECISION_TYPEN
from archon.core.constants import DELEGATION_PROTOCOL_PROMPT as DELEGATION_PROTOCOL_PROMPT
from archon.core.constants import STUDIO_BG_UPLOAD_DIR as STUDIO_BG_UPLOAD_DIR
from archon.core.delegation import DELEGATION_ALIAS_MAP as DELEGATION_ALIAS_MAP
from archon.core.delegation import _build_kader_roster_summary as _build_kader_roster_summary
from archon.core.delegation import _check_delegation_permission as _check_delegation_permission
from archon.core.delegation import _execute_delegation as _execute_delegation
from archon.core.delegation import _get_delegation_prompt_for as _get_delegation_prompt_for
from archon.core.delegation import _load_org_hierarchy_map as _load_org_hierarchy_map
from archon.core.delegation import _parse_delegation_blocks as _parse_delegation_blocks
from archon.core.delegation import _resolve_target_agent_id as _resolve_target_agent_id
from archon.core.delegation import (
    _trigger_autonomous_orchestrator_followup as _trigger_autonomous_orchestrator_followup,
)
from archon.core.delegation import configure as _delegation_configure
from archon.core.mission_control import (
    _MC_ASYNC_LOCK,
    _load_mission_control_data,
    _save_mission_control_data,
    _write_mc_atomic,
    update_mission_control_data,
)
from archon.core.mission_control import _MC_DATA_LOCK as _MC_DATA_LOCK
from archon.core.mission_control import _MC_STATE_CACHE as _MC_STATE_CACHE
from archon.core.mission_control import MISSION_CONTROL_FILE as MISSION_CONTROL_FILE
from archon.core.orchestration import (
    _fan_in_maybe_start_synthesis as _orch_fan_in_maybe_start_synthesis,
)
from archon.core.paths import _SKILL_INDEX_DISK_PATH as _SKILL_INDEX_DISK_PATH
from archon.core.paths import (
    AGENTS_FILE,
    COUPLED_AGENTS_FILE,
    FRAMEWORKS_FILE,
    HERMES_PROFILES_DIR,
    MEMORY_FILE,
    QUICKCHAT_SESSIONS_DIR,
    ROLES_FILE,
    SERVICES_FILE,
    THEME_FILE,
)
from archon.core.paths import BOARDROOM_HISTORY_FILE as BOARDROOM_HISTORY_FILE
from archon.core.paths import CONFIG_FILE as CONFIG_FILE
from archon.core.paths import GATEWAY_CONFIG_FILE as GATEWAY_CONFIG_FILE
from archon.core.paths import KANBAN_CARDS_FILE as KANBAN_CARDS_FILE
from archon.core.paths import KANBAN_FILE as KANBAN_FILE
from archon.core.paths import SETTINGS_FILE as SETTINGS_FILE
from archon.core.paths import THEME_LIVE_FILE as THEME_LIVE_FILE
from archon.core.paths import THEMES_DIR as THEMES_DIR
from archon.core.permissions import PERMISSION_GATES_FILE as PERMISSION_GATES_FILE
from archon.core.permissions import create_permission_gate as create_permission_gate
from archon.core.permissions import load_permission_gates as load_permission_gates
from archon.core.permissions import save_permission_gates as save_permission_gates
from archon.core.permissions import set_decision_factory as _set_decision_factory
from archon.core.profiles import ALL_HERMES_TOOLS as ALL_HERMES_TOOLS
from archon.core.profiles import DEFAULT_HERMES_TOOLS as DEFAULT_HERMES_TOOLS
from archon.core.profiles import AgentProfileValidationSchema as AgentProfileValidationSchema
from archon.core.profiles import (
    api_get_hermes_profiles,
    create_rolling_backup,
    invalidate_hermes_profiles_cache,
    resolve_avatar_file,
    restore_data_uri_avatars,
    save_all_agent_profiles,
)
from archon.core.profiles import get_hermes_profiles_base_dirs as get_hermes_profiles_base_dirs
from archon.core.profiles import get_primary_hermes_profiles_dir as get_primary_hermes_profiles_dir
from archon.core.profiles import materialize_role_avatars as materialize_role_avatars
from archon.core.roles_data import DEFAULT_ROLES as DEFAULT_ROLES
from archon.core.roles_data import load_default_roles
from archon.core.runtime import _SSE_SUB_LOCK as _SSE_SUB_LOCK
from archon.core.runtime import _SSE_SUBSCRIBERS as _SSE_SUBSCRIBERS
from archon.core.runtime import DATA_DIR as DATA_DIR
from archon.core.runtime import (
    MEMORY_DIR,
    OBSIDIAN_VAULT_DIR,
    WORKSPACE_DIR,
    _load_json,
    _save_json,
    add_ticker,
    broadcast_event,
)
from archon.core.runtime import atomic_write_json as atomic_write_json
from archon.core.runtime import resolve_obsidian_vault_path as resolve_obsidian_vault_path
from archon.core.runtime import ticker_entries as ticker_entries
from archon.core.settings_state import (
    DEFAULT_AGENTS,
    DEFAULT_SERVICES,
    GHOST_AGENT_IDS,
    SYSTEM_INTERNAL_IDS,
)
from archon.core.state_db import STATE_DB_PATH, _get_state_db
from archon.core.state_db import ClosingConnection as ClosingConnection
from archon.core.state_db import _get_profile_state_db as _get_profile_state_db
from archon.middleware.auth_gate import AuthGateDeps as _AuthGateDeps
from archon.middleware.auth_gate import run_auth_gate_middleware as _run_auth_gate_middleware
from archon.middleware.auth_gate import (
    run_tenant_context_middleware as _run_tenant_context_middleware,
)
from archon.middleware.auth_policy import _AUTH_PUBLIC_EXACT as _AUTH_PUBLIC_EXACT
from archon.middleware.auth_policy import RAG_API_KEY_ENV as RAG_API_KEY_ENV
from archon.middleware.auth_policy import MissingRagApiKeyError as MissingRagApiKeyError
from archon.middleware.auth_policy import _auth_unavailable_response as _auth_unavailable_response
from archon.middleware.auth_policy import _check_rag_api_key_config as _check_rag_api_key_config
from archon.middleware.auth_policy import _get_rag_api_key as _get_rag_api_key
from archon.routers import LateRouterDeps as _LateRouterDeps
from archon.routers import register_late_routers as _register_late_routers
from archon.routers import register_router as _register_router
from archon.routers import register_special_routers as _register_special_routers
from archon.routers._rbac import require_admin_or_503
from archon.routers.agent_chat import DirectAgentChatRequest as DirectAgentChatRequest
from archon.routers.agent_chat import RunRequest as RunRequest
from archon.routers.agent_chat import api_direct_agent_chat as api_direct_agent_chat
from archon.routers.agent_chat import api_run_parallel as api_run_parallel
from archon.routers.agent_chat import fetch_agent_response_api as fetch_agent_response_api
from archon.routers.agent_chat import load_profiles_list as load_profiles_list
from archon.routers.agent_chat import router as _agent_chat_router
from archon.routers.auth import api_auth_change_password as api_auth_change_password
from archon.routers.auth import api_auth_create_user as api_auth_create_user
from archon.routers.auth import api_auth_delete_user as api_auth_delete_user
from archon.routers.auth import api_auth_list_users as api_auth_list_users
from archon.routers.auth import api_auth_login as api_auth_login
from archon.routers.auth import api_auth_logout as api_auth_logout
from archon.routers.auth import api_auth_me as api_auth_me
from archon.routers.auth import api_auth_status as api_auth_status
from archon.routers.auth import api_auth_toggle as api_auth_toggle
from archon.routers.auth import api_auth_update_user as api_auth_update_user
from archon.routers.auth import configure as _auth_configure
from archon.routers.auth import get_current_user_from_request as get_current_user_from_request
from archon.routers.auth import require_admin
from archon.routers.auth import router as _auth_router
from archon.routers.autonomy_settings import (
    api_get_autonomy_modules_settings as api_get_autonomy_modules_settings,
)
from archon.routers.autonomy_settings import api_get_model_routing as api_get_model_routing
from archon.routers.autonomy_settings import api_optimize_role_prompt as api_optimize_role_prompt
from archon.routers.autonomy_settings import api_resolve_model_routing as api_resolve_model_routing
from archon.routers.autonomy_settings import (
    api_run_eval_regression_suite as api_run_eval_regression_suite,
)
from archon.routers.autonomy_settings import (
    api_save_autonomy_modules_settings as api_save_autonomy_modules_settings,
)
from archon.routers.autonomy_settings import api_save_model_routing as api_save_model_routing
from archon.routers.autonomy_settings import api_semantic_cache_clear as api_semantic_cache_clear
from archon.routers.autonomy_settings import api_semantic_cache_lookup as api_semantic_cache_lookup
from archon.routers.autonomy_settings import api_semantic_cache_stats as api_semantic_cache_stats
from archon.routers.autonomy_settings import api_semantic_cache_store as api_semantic_cache_store
from archon.routers.autonomy_settings import router as _autonomy_settings_router
from archon.routers.brain import api_brain_galaxy_data as api_brain_galaxy_data
from archon.routers.brain import api_brain_vault_file as api_brain_vault_file
from archon.routers.brain import api_get_quartz_config as api_get_quartz_config
from archon.routers.brain import api_library_book_content as api_library_book_content
from archon.routers.brain import api_library_books as api_library_books
from archon.routers.brain import api_library_ingest as api_library_ingest
from archon.routers.brain import api_library_upload as api_library_upload
from archon.routers.brain import api_save_quartz_config as api_save_quartz_config
from archon.routers.brain import configure as _brain_configure
from archon.routers.brain import router as _brain_router
from archon.routers.chat import ChatStreamRequest as ChatStreamRequest
from archon.routers.chat import ImageGenerateToolRequest as ImageGenerateToolRequest
from archon.routers.chat import RenameSessionRequest as RenameSessionRequest
from archon.routers.chat import SetProfileModelRequest as SetProfileModelRequest
from archon.routers.chat import _ensure_session_exists, _save_message_to_db
from archon.routers.chat import _ensure_state_session as _ensure_state_session
from archon.routers.chat import _load_state_history as _load_state_history
from archon.routers.chat import _quickchat_state_session_id as _quickchat_state_session_id
from archon.routers.chat import _record_session_model_usage as _record_session_model_usage
from archon.routers.chat import _warn_price_lookup_once as _warn_price_lookup_once
from archon.routers.chat import api_chat_stream as api_chat_stream
from archon.routers.chat import api_chat_upload as api_chat_upload
from archon.routers.chat import api_get_chat_session_messages as api_get_chat_session_messages
from archon.routers.chat import api_get_chat_sessions as api_get_chat_sessions
from archon.routers.chat import api_rename_chat_session as api_rename_chat_session
from archon.routers.chat import api_tool_image_generate as api_tool_image_generate
from archon.routers.chat import configure as _chat_configure
from archon.routers.chat import record_task_tokens as record_task_tokens
from archon.routers.chat import router as _chat_router
from archon.routers.container_ops import ContainerExecRequest as ContainerExecRequest
from archon.routers.container_ops import abort_agent_endpoint as abort_agent_endpoint
from archon.routers.container_ops import exec_container_command_api as exec_container_command_api
from archon.routers.container_ops import router as _container_ops_router
from archon.routers.container_ops import send_prompt_to_agent as send_prompt_to_agent
from archon.routers.containers import ContainerActionRequest as ContainerActionRequest
from archon.routers.containers import _container_stats_payload as _container_stats_payload
from archon.routers.containers import _docker_container_stats as _docker_container_stats
from archon.routers.containers import configure as _containers_configure
from archon.routers.containers import docker_socket_request as docker_socket_request
from archon.routers.containers import get_all_container_logs_api as get_all_container_logs_api
from archon.routers.containers import get_container_file_content as get_container_file_content
from archon.routers.containers import get_container_files_api as get_container_files_api
from archon.routers.containers import get_container_logs_api as get_container_logs_api
from archon.routers.containers import get_container_metrics_api as get_container_metrics_api
from archon.routers.containers import get_container_settings as get_container_settings
from archon.routers.containers import get_hermes_profile_logs_api as get_hermes_profile_logs_api
from archon.routers.containers import inject_container_config as inject_container_config
from archon.routers.containers import load_agent_configs as load_agent_configs
from archon.routers.containers import router as _containers_router
from archon.routers.containers import run_container_action as run_container_action
from archon.routers.containers import save_agent_config as save_agent_config
from archon.routers.containers import save_container_settings as save_container_settings
from archon.routers.content_machine import router as _content_machine_router
from archon.routers.context_help import HELP_CONTEXT_DATA as HELP_CONTEXT_DATA
from archon.routers.context_help import router as _context_help_router
from archon.routers.context_meter import router as _context_meter_router
from archon.routers.core_settings import api_get_agents as api_get_agents
from archon.routers.core_settings import api_get_roles as api_get_roles
from archon.routers.core_settings import api_save_agents as api_save_agents
from archon.routers.core_settings import api_save_roles as api_save_roles
from archon.routers.core_settings import api_save_settings as api_save_settings
from archon.routers.core_settings import api_test_jev as api_test_jev
from archon.routers.core_settings import clear_ticker as clear_ticker
from archon.routers.core_settings import get_settings as get_settings
from archon.routers.core_settings import get_ticker as get_ticker
from archon.routers.core_settings import router as _core_settings_router
from archon.routers.deals import router as _deals_router
from archon.routers.decisions import _antwort_grund as _antwort_grund
from archon.routers.decisions import _decision_followup as _decision_followup
from archon.routers.decisions import _decision_kanban_status as _decision_kanban_status
from archon.routers.decisions import _decision_self_api as _decision_self_api
from archon.routers.decisions import _folge_nicht as _folge_nicht
from archon.routers.decisions import _followup_mission_start as _impl_followup_mission_start
from archon.routers.decisions import _followup_permission_gate as _impl_followup_permission_gate
from archon.routers.decisions import _followup_synthesis as _impl_followup_synthesis
from archon.routers.decisions import _pruefe_gate_antwort as _pruefe_gate_antwort
from archon.routers.decisions import _pruefe_gate_persistiert as _pruefe_gate_persistiert
from archon.routers.decisions import _pruefe_move_antwort as _pruefe_move_antwort
from archon.routers.decisions import _pruefe_synthese_beleg as _pruefe_synthese_beleg
from archon.routers.decisions import _sync_org_hierarchy_node, create_decision, register_decision
from archon.routers.decisions import _synthese_parent as _synthese_parent
from archon.routers.decisions import api_decide_decision as api_decide_decision
from archon.routers.decisions import api_decide_permission_gate as api_decide_permission_gate
from archon.routers.decisions import router as _decisions_router
from archon.routers.docker_services import _services_config_fallback as _services_config_fallback
from archon.routers.docker_services import api_docker_start as api_docker_start
from archon.routers.docker_services import api_docker_stop as api_docker_stop
from archon.routers.docker_services import api_get_models as api_get_models
from archon.routers.docker_services import api_get_models_v1 as api_get_models_v1
from archon.routers.docker_services import api_get_services as api_get_services
from archon.routers.docker_services import api_save_services as api_save_services
from archon.routers.docker_services import detect_container_port, post_docker_container_action
from archon.routers.docker_services import (
    get_docker_containers_from_socket as get_docker_containers_from_socket,
)
from archon.routers.docker_services import router as _docker_services_router
from archon.routers.documents import _resolve_parser_input as _resolve_parser_input
from archon.routers.documents import api_extract_tables as api_extract_tables
from archon.routers.documents import api_parse_document as api_parse_document
from archon.routers.documents import router as _documents_router
from archon.routers.email_settings import api_save_smtp_settings as api_save_smtp_settings
from archon.routers.email_settings import api_test_smtp_settings as api_test_smtp_settings
from archon.routers.email_settings import router as _email_settings_router
from archon.routers.gateway import _get_all_installed_profiles as _get_all_installed_profiles
from archon.routers.gateway import _load_gateway_config as _load_gateway_config
from archon.routers.gateway import _parse_gateway_list as _parse_gateway_list
from archon.routers.gateway import _run_docker_exec as _run_docker_exec
from archon.routers.gateway import _save_gateway_config as _save_gateway_config
from archon.routers.gateway import _update_profile_status as _update_profile_status
from archon.routers.gateway import api_gateway_autostart as api_gateway_autostart
from archon.routers.gateway import api_gateway_list as api_gateway_list
from archon.routers.gateway import api_gateway_start as api_gateway_start
from archon.routers.gateway import api_gateway_stop as api_gateway_stop
from archon.routers.gateway import api_gateway_stop_all as api_gateway_stop_all
from archon.routers.gateway import api_get_gateway_config as api_get_gateway_config
from archon.routers.gateway import (
    api_save_gateway_config_endpoint as api_save_gateway_config_endpoint,
)
from archon.routers.gateway import router as _gateway_router
from archon.routers.guardian import _GUARDIAN_ALLOWED_TIMEFRAMES as _GUARDIAN_ALLOWED_TIMEFRAMES
from archon.routers.guardian import _GUARDIAN_CACHE_MAX_ENTRIES as _GUARDIAN_CACHE_MAX_ENTRIES
from archon.routers.guardian import _GUARDIAN_CACHE_TTL as _GUARDIAN_CACHE_TTL
from archon.routers.guardian import api_clear_guardian_cache as api_clear_guardian_cache
from archon.routers.guardian import api_get_guardian_config as api_get_guardian_config
from archon.routers.guardian import api_get_guardian_stats as api_get_guardian_stats
from archon.routers.guardian import api_get_plugin_config as api_get_plugin_config
from archon.routers.guardian import api_save_guardian_config as api_save_guardian_config
from archon.routers.guardian import api_save_plugin_config as api_save_plugin_config
from archon.routers.guardian import api_toggle_guardian_plugin as api_toggle_guardian_plugin
from archon.routers.guardian import router as _guardian_router
from archon.routers.hermes_config import _get_hermes_config_paths as _get_hermes_config_paths
from archon.routers.hermes_config import api_get_hermes_form_config as api_get_hermes_form_config
from archon.routers.hermes_config import api_get_hermes_raw_config as api_get_hermes_raw_config
from archon.routers.hermes_config import api_save_hermes_form_config as api_save_hermes_form_config
from archon.routers.hermes_config import api_save_hermes_raw_config as api_save_hermes_raw_config
from archon.routers.hermes_config import configure as _hermes_config_configure
from archon.routers.hermes_config import router as _hermes_config_router
from archon.routers.hermes_ops import _get_hermes_config_path as _get_hermes_config_path
from archon.routers.hermes_ops import api_get_hermes_config as api_get_hermes_config
from archon.routers.hermes_ops import api_hermes_memory_purge as api_hermes_memory_purge
from archon.routers.hermes_ops import api_save_hermes_config as api_save_hermes_config
from archon.routers.hermes_ops import router as _hermes_ops_router
from archon.routers.hermes_proxy import _PROXY_WRITE_METHODS as _PROXY_WRITE_METHODS
from archon.routers.hermes_proxy import _hermes_proxy_token as _hermes_proxy_token
from archon.routers.hermes_proxy import forward_to_hermes as forward_to_hermes
from archon.routers.hermes_proxy import proxy_hermes_api_endpoints as proxy_hermes_api_endpoints
from archon.routers.hermes_proxy import proxy_web_ui as proxy_web_ui
from archon.routers.hermes_proxy import router as _hermes_proxy_router
from archon.routers.hr import LogActivityReq as LogActivityReq
from archon.routers.hr import SavePersonalakteReq as SavePersonalakteReq
from archon.routers.hr import SaveSoulReq as SaveSoulReq
from archon.routers.hr import api_get_hermes_soul as api_get_hermes_soul
from archon.routers.hr import api_get_personalakte as api_get_personalakte
from archon.routers.hr import api_log_personalakte_activity as api_log_personalakte_activity
from archon.routers.hr import api_save_hermes_soul as api_save_hermes_soul
from archon.routers.hr import api_save_personalakte as api_save_personalakte
from archon.routers.hr import router as _hr_router
from archon.routers.inbox_tools import api_create_tool_proposal as api_create_tool_proposal
from archon.routers.inbox_tools import api_resolve_tool_proposal as api_resolve_tool_proposal
from archon.routers.inbox_tools import (
    api_save_inbox_watcher_config as api_save_inbox_watcher_config,
)
from archon.routers.inbox_tools import router as _inbox_tools_router
from archon.routers.kanban import api_get_kanban as api_get_kanban
from archon.routers.kanban import api_save_kanban as api_save_kanban
from archon.routers.kanban import router as _kanban_router
from archon.routers.llm_providers import get_llm_prices as get_llm_prices
from archon.routers.marketplace import api_assign_skill_to_profile as api_assign_skill_to_profile
from archon.routers.marketplace import api_get_marketplace_sources as api_get_marketplace_sources
from archon.routers.marketplace import (
    api_get_marketplace_template_detail as api_get_marketplace_template_detail,
)
from archon.routers.marketplace import (
    api_get_marketplace_templates as api_get_marketplace_templates,
)
from archon.routers.marketplace import api_get_skill_detail as api_get_skill_detail
from archon.routers.marketplace import api_get_skill_sources as api_get_skill_sources
from archon.routers.marketplace import api_get_skills_list as api_get_skills_list
from archon.routers.marketplace import api_marketplace_recruit as api_marketplace_recruit
from archon.routers.marketplace import configure as _marketplace_configure
from archon.routers.marketplace import router as _marketplace_router
from archon.routers.memory_ops import api_consolidate_memory as api_consolidate_memory
from archon.routers.memory_ops import api_evict_stale_memory as api_evict_stale_memory
from archon.routers.memory_ops import api_get_agent_real_stats as api_get_agent_real_stats
from archon.routers.memory_ops import api_get_memory_stats as api_get_memory_stats
from archon.routers.memory_ops import api_memory_context as api_memory_context
from archon.routers.memory_ops import api_memory_learning as api_memory_learning
from archon.routers.memory_ops import api_memory_profile as api_memory_profile
from archon.routers.memory_ops import api_memory_vault_summary as api_memory_vault_summary
from archon.routers.memory_ops import clear_chat_history_api as clear_chat_history_api
from archon.routers.memory_ops import get_chat_history_api as get_chat_history_api
from archon.routers.memory_ops import router as _memory_ops_router
from archon.routers.mesh import api_accept_handoff as api_accept_handoff
from archon.routers.mesh import api_analyze_vision as api_analyze_vision
from archon.routers.mesh import api_approve_skill_proposal as api_approve_skill_proposal
from archon.routers.mesh import api_browse_and_capture as api_browse_and_capture
from archon.routers.mesh import api_check_task_budget as api_check_task_budget
from archon.routers.mesh import api_create_handoff as api_create_handoff
from archon.routers.mesh import api_diff_preview as api_diff_preview
from archon.routers.mesh import api_execute_sandbox as api_execute_sandbox
from archon.routers.mesh import api_get_concurrency_status as api_get_concurrency_status
from archon.routers.mesh import api_get_consensus_history as api_get_consensus_history
from archon.routers.mesh import (
    api_get_memory_consolidation_settings as api_get_memory_consolidation_settings,
)
from archon.routers.mesh import api_get_war_room_history as api_get_war_room_history
from archon.routers.mesh import api_ingest_inbound_event as api_ingest_inbound_event
from archon.routers.mesh import api_list_event_history as api_list_event_history
from archon.routers.mesh import api_list_skill_proposals as api_list_skill_proposals
from archon.routers.mesh import api_query_rag as api_query_rag
from archon.routers.mesh import api_review_task_consensus as api_review_task_consensus
from archon.routers.mesh import api_run_council_vote as api_run_council_vote
from archon.routers.mesh import api_run_war_room as api_run_war_room
from archon.routers.mesh import api_save_concurrency_config as api_save_concurrency_config
from archon.routers.mesh import (
    api_save_memory_consolidation_settings as api_save_memory_consolidation_settings,
)
from archon.routers.mesh import api_scan_inbox_directory as api_scan_inbox_directory
from archon.routers.mesh import router as _mesh_router
from archon.routers.notebooks import api_attach_vault_source as api_attach_vault_source
from archon.routers.notebooks import api_create_notebook as api_create_notebook
from archon.routers.notebooks import api_delete_notebook as api_delete_notebook
from archon.routers.notebooks import api_delete_notebook_source as api_delete_notebook_source
from archon.routers.notebooks import api_get_notebook_chat as api_get_notebook_chat
from archon.routers.notebooks import api_get_notebook_sources as api_get_notebook_sources
from archon.routers.notebooks import api_get_notebooks as api_get_notebooks
from archon.routers.notebooks import api_query_notebook as api_query_notebook
from archon.routers.notebooks import api_sync_notebook_obsidian as api_sync_notebook_obsidian
from archon.routers.notebooks import api_upload_notebook_source as api_upload_notebook_source
from archon.routers.notebooks import router as _notebooks_router
from archon.routers.oracle_seo import api_get_oracle_feed as api_get_oracle_feed
from archon.routers.oracle_seo import api_run_oracle_cycle as api_run_oracle_cycle
from archon.routers.oracle_seo import api_seo_articles as api_seo_articles
from archon.routers.oracle_seo import api_seo_generate as api_seo_generate
from archon.routers.oracle_seo import api_triage_oracle_signal as api_triage_oracle_signal
from archon.routers.oracle_seo import router as _oracle_seo_router
from archon.routers.prompts import PromptOptimizeRequest as PromptOptimizeRequest
from archon.routers.prompts import TemplateSaveRequest as TemplateSaveRequest
from archon.routers.prompts import optimize_prompt_endpoint as optimize_prompt_endpoint
from archon.routers.prompts import router as _prompts_router
from archon.routers.prompts import upload_prompt_studio_context as upload_prompt_studio_context
from archon.routers.proxies import _get_n8n_proxy as _get_n8n_proxy
from archon.routers.proxies import _get_omniroute_proxy as _get_omniroute_proxy
from archon.routers.proxies import _get_shared_proxy_client as _get_shared_proxy_client
from archon.routers.proxies import forward_to_n8n as forward_to_n8n
from archon.routers.proxies import forward_to_omniroute as forward_to_omniroute
from archon.routers.proxies import n8n_assets_proxy as n8n_assets_proxy
from archon.routers.proxies import n8n_proxy as n8n_proxy
from archon.routers.proxies import n8n_rest_proxy as n8n_rest_proxy
from archon.routers.proxies import omniroute_next_assets as omniroute_next_assets
from archon.routers.proxies import omniroute_proxy as omniroute_proxy
from archon.routers.proxies import router as _proxies_router
from archon.routers.quickchat import QuickchatSendRequest as QuickchatSendRequest
from archon.routers.quickchat import _load_quickchat_session as _load_quickchat_session
from archon.routers.quickchat import _quickchat_session_path as _quickchat_session_path
from archon.routers.quickchat import _save_quickchat_session as _save_quickchat_session
from archon.routers.quickchat import api_delete_quickchat_session as api_delete_quickchat_session
from archon.routers.quickchat import api_get_quickchat_session as api_get_quickchat_session
from archon.routers.quickchat import api_quickchat_send as api_quickchat_send
from archon.routers.quickchat import router as _quickchat_router
from archon.routers.research import api_get_research_dossier as api_get_research_dossier
from archon.routers.research import api_get_research_history as api_get_research_history
from archon.routers.research import api_get_research_providers as api_get_research_providers
from archon.routers.research import api_get_research_sources as api_get_research_sources
from archon.routers.research import api_run_research_mission as api_run_research_mission
from archon.routers.research import router as _research_router
from archon.routers.resilience import api_heal_service as api_heal_service
from archon.routers.resilience import api_restore_snapshot as api_restore_snapshot
from archon.routers.resilience import router as _resilience_router
from archon.routers.security_scanner import router as _security_scanner_router
from archon.routers.telegram import TelegramSendPayload as TelegramSendPayload
from archon.routers.telegram import _redact_telegram_secrets as _redact_telegram_secrets
from archon.routers.telegram import api_telegram_relay as api_telegram_relay
from archon.routers.telegram import api_telegram_send as api_telegram_send
from archon.routers.telegram import api_telegram_voice_relay as api_telegram_voice_relay
from archon.routers.telegram import router as _telegram_router
from archon.routers.telemetry import _count_running_containers as _count_running_containers
from archon.routers.telemetry import api_get_agent_activity as api_get_agent_activity
from archon.routers.telemetry import api_get_agent_projects as api_get_agent_projects
from archon.routers.telemetry import api_telemetry_dashboard as api_telemetry_dashboard
from archon.routers.telemetry import get_hud_telemetry as get_hud_telemetry
from archon.routers.telemetry import router as _telemetry_router
from archon.routers.theme import DESIGN_THEMES_TARGETS as DESIGN_THEMES_TARGETS
from archon.routers.theme import api_bake_theme_into_main_design as api_bake_theme_into_main_design
from archon.routers.theme import api_delete_design_theme as api_delete_design_theme
from archon.routers.theme import api_delete_theme_by_name as api_delete_theme_by_name
from archon.routers.theme import api_delete_theme_live_overrides as api_delete_theme_live_overrides
from archon.routers.theme import api_get_design_themes as api_get_design_themes
from archon.routers.theme import api_get_theme as api_get_theme
from archon.routers.theme import api_get_theme_by_name as api_get_theme_by_name
from archon.routers.theme import api_get_theme_live_overrides as api_get_theme_live_overrides
from archon.routers.theme import api_get_themes as api_get_themes
from archon.routers.theme import api_save_design_themes as api_save_design_themes
from archon.routers.theme import api_save_theme as api_save_theme
from archon.routers.theme import api_save_theme_by_name as api_save_theme_by_name
from archon.routers.theme import api_save_theme_live_overrides as api_save_theme_live_overrides
from archon.routers.theme import api_upload_theme_background as api_upload_theme_background
from archon.routers.theme import router as _theme_router
from archon.routers.ui import FullHtmlSaveRequest as FullHtmlSaveRequest
from archon.routers.ui import TextReplacementItem as TextReplacementItem
from archon.routers.ui import TextReplacementsRequest as TextReplacementsRequest
from archon.routers.ui import _full_html_target_files as _full_html_target_files
from archon.routers.ui import api_save_full_html as api_save_full_html
from archon.routers.ui import api_save_text_replacements as api_save_text_replacements
from archon.routers.ui import api_studio_upload_bg as api_studio_upload_bg
from archon.routers.ui import get_hud_page as get_hud_page
from archon.routers.ui import get_index as get_index
from archon.routers.ui import get_index_v2 as get_index_v2
from archon.routers.ui import get_manifest as get_manifest
from archon.routers.ui import get_mobile_cockpit as get_mobile_cockpit
from archon.routers.ui import router as _ui_router
from archon.routers.updater import api_hermes_update_apply as api_hermes_update_apply
from archon.routers.updater import api_hermes_update_check as api_hermes_update_check
from archon.routers.updater import router as _updater_router
from archon.routers.v2_capabilities import router as _v2_capabilities_router
from archon.routers.vault import _VAULT_FILES_CACHE as _VAULT_FILES_CACHE
from archon.routers.vault import api_delete_vault_file_direct as api_delete_vault_file_direct
from archon.routers.vault import api_edit_vault_file_direct as api_edit_vault_file_direct
from archon.routers.vault import api_generate_vault_index as api_generate_vault_index
from archon.routers.vault import api_get_vault_files as api_get_vault_files
from archon.routers.vault import api_get_vault_list as api_get_vault_list
from archon.routers.vault import api_read_vault_file_direct as api_read_vault_file_direct
from archon.routers.vault import router as _vault_router
from archon.routers.watchdog import (
    acknowledge_watchdog_alarm_endpoint as acknowledge_watchdog_alarm_endpoint,
)
from archon.routers.watchdog import api_get_watchdog_config as api_get_watchdog_config
from archon.routers.watchdog import api_save_watchdog_config as api_save_watchdog_config
from archon.routers.watchdog import api_trigger_watchdog_run as api_trigger_watchdog_run
from archon.routers.watchdog import api_watchdog_dispatch_action as api_watchdog_dispatch_action
from archon.routers.watchdog import get_watchdog_alarms_endpoint as get_watchdog_alarms_endpoint
from archon.routers.watchdog import router as _watchdog_router
from archon.routers.watchdog import (
    trigger_test_watchdog_alarm_endpoint as trigger_test_watchdog_alarm_endpoint,
)
from archon.services import profiles_service
from archon.services.background_loops import (
    _ANCHOR_WRITE_LOCK as _ANCHOR_WRITE_LOCK,
)
from archon.services.background_loops import (
    _BACKGROUND_TASKS as _BACKGROUND_TASKS,
)
from archon.services.background_loops import (
    _DB_MAINTENANCE_STATUS as _DB_MAINTENANCE_STATUS,
)
from archon.services.background_loops import (
    _FAILED_CANCELS as _FAILED_CANCELS,
)
from archon.services.background_loops import (
    _RAG_SYNC_LOCK as _RAG_SYNC_LOCK,
)
from archon.services.background_loops import (
    _STARTUP_RECOVERY_FAILED as _STARTUP_RECOVERY_FAILED,
)
from archon.services.background_loops import (
    _WATCHDOG_STOP_FAILED as _WATCHDOG_STOP_FAILED,
)
from archon.services.background_loops import (
    BackgroundLoopDeps as _BackgroundLoopDeps,
)
from archon.services.background_loops import (
    _cancel_background_tasks as _cancel_background_tasks,
)
from archon.services.background_loops import (
    _db_maintenance_loop as _db_maintenance_loop,
)
from archon.services.background_loops import (
    _deadlock_supervisor_loop as _deadlock_supervisor_loop,
)
from archon.services.background_loops import (
    _email_imap_background_loop as _email_imap_background_loop,
)
from archon.services.background_loops import (
    _fleet_self_healing_loop as _fleet_self_healing_loop,
)
from archon.services.background_loops import (
    _record_failed_cancel as _record_failed_cancel,
)
from archon.services.background_loops import (
    _spawn_background as _spawn_background,
)
from archon.services.background_loops import (
    _start_gateway_idle_loop as _start_gateway_idle_loop,
)
from archon.services.background_loops import (
    register_background_loop_deps_provider as _register_background_loop_deps_provider,
)
from archon.services.background_loops import (
    reset_loops_started as _reset_loops_started,
)
from archon.services.health_probes import (
    _DEPENDENCY_PROBE_CACHE as _DEPENDENCY_PROBE_CACHE,
)
from archon.services.health_probes import (
    _DEPENDENCY_PROBE_TTL as _DEPENDENCY_PROBE_TTL,
)
from archon.services.health_probes import (
    _READINESS_PROBE_READY as _READINESS_PROBE_READY,
)
from archon.services.health_probes import (
    HealthProbeDeps as _HealthProbeDeps,
)
from archon.services.health_probes import (
    _probe_external_dependency as _probe_external_dependency,
)
from archon.services.health_probes import (
    _readiness_probe_targets as _readiness_probe_targets,
)
from archon.services.health_probes import (
    init_readiness_probe_table as _init_readiness_probe_table_impl,
)
from archon.services.health_probes import (
    run_liveness_check as _run_liveness_check,
)
from archon.services.health_probes import (
    run_readiness_check as _run_readiness_check,
)
from archon.services.health_probes import (
    run_readiness_sync_checks as _run_readiness_sync_checks,
)
from archon.services.mission_sync import _LIVE_TELEMETRY_CACHE as _LIVE_TELEMETRY_CACHE
from archon.services.mission_sync import _get_live_telemetry_metrics, _sync_task_to_obsidian
from archon.services.mission_sync import _slugify as _slugify
from archon.services.orchestration_bridge import (
    OrchestrationBridgeDeps as _OrchestrationBridgeDeps,
)
from archon.services.orchestration_bridge import (
    _execute_mission_control_task as _execute_mission_control_task,
)
from archon.services.orchestration_bridge import (
    _fan_in_maybe_start_synthesis as _fan_in_maybe_start_synthesis,
)
from archon.services.orchestration_bridge import (
    _finalize_synthesis_after_approval as _finalize_synthesis_after_approval,
)
from archon.services.orchestration_bridge import (
    _paperclip_hire_profile_by_id as _paperclip_hire_profile_by_id,
)
from archon.services.orchestration_bridge import (
    _run_synthesis_cascade as _run_synthesis_cascade,
)
from archon.services.orchestration_bridge import (
    _set_agent_profile_status as _set_agent_profile_status,
)
from archon.services.orchestration_bridge import (
    _tg_ping_synthesis as _tg_ping_synthesis,
)
from archon.services.orchestration_bridge import (
    _trigger_sandy_staffing_nomination as _trigger_sandy_staffing_nomination,
)
from archon.services.orchestration_bridge import (
    register_orchestration_bridge_deps_provider as _register_orchestration_bridge_deps_provider,
)
from archon.services.profiles_service import delete_profile as delete_profile
from archon.services.profiles_service import save_profile as save_profile
from archon.services.runtime_endpoints import (
    HealingAttemptPayload as HealingAttemptPayload,
)
from archon.services.runtime_endpoints import (
    RuntimeEndpointsDeps as _RuntimeEndpointsDeps,
)
from archon.services.runtime_endpoints import (
    TraceContextMiddleware as TraceContextMiddleware,
)
from archon.services.runtime_endpoints import (
    _assert_router_health as _assert_router_health,
)
from archon.services.runtime_endpoints import (
    _cancel_tracked_tasks as _cancel_tracked_tasks,
)
from archon.services.runtime_endpoints import (
    _warm_hermes_skill_caches as _warm_hermes_skill_caches,
)
from archon.services.runtime_endpoints import (
    install_cors_middleware as _install_cors_middleware_impl,
)
from archon.services.runtime_endpoints import (
    install_rate_limit_middleware as _install_rate_limit_middleware_impl,
)
from archon.services.runtime_endpoints import (
    on_shutdown_graceful as on_shutdown_graceful,
)
from archon.services.runtime_endpoints import (
    on_startup_drain_recovery as on_startup_drain_recovery,
)
from archon.services.runtime_endpoints import (
    register_runtime_endpoints_deps_provider as _register_runtime_endpoints_deps_provider,
)
from archon.services.runtime_endpoints import (
    run_task_healing as _run_task_healing,
)
from archon.services.runtime_endpoints import (
    sse_events_stream as sse_events_stream,
)
from archon.services.shutdown_clients import (
    _N8N_STARTUP_STATUS as _N8N_STARTUP_STATUS,
)
from archon.services.shutdown_clients import (
    _close_all_http_clients as _close_all_http_clients,
)
from archon.services.shutdown_clients import (
    _close_dispatcher_clients as _close_dispatcher_clients,
)
from archon.services.shutdown_clients import (
    _close_proxy_clients as _close_proxy_clients,
)
from archon.services.shutdown_clients import (
    _ensure_zero_egress_worker_networks as _ensure_zero_egress_worker_networks,
)
from archon.services.shutdown_clients import (
    _harden_secret_permissions as _harden_secret_permissions,
)
from archon.services.shutdown_clients import (
    _import_n8n_workflows_on_startup as _import_n8n_workflows_on_startup,
)
from archon.services.startup_security import (
    _AUDIT_COMPROMISED as _AUDIT_COMPROMISED,
)
from archon.services.startup_security import (
    _AUDIT_COMPROMISED_LOCK as _AUDIT_COMPROMISED_LOCK,
)
from archon.services.startup_security import (
    _LOCAL_BINDS as _LOCAL_BINDS,
)
from archon.services.startup_security import (
    AUDIT_COMPROMISED as AUDIT_COMPROMISED,
)
from archon.services.startup_security import (
    StartupSecurityDeps as _StartupSecurityDeps,
)
from archon.services.startup_security import (
    _assert_api_key_pepper as _assert_api_key_pepper,
)
from archon.services.startup_security import (
    _assert_audit_hmac as _assert_audit_hmac,
)
from archon.services.startup_security import (
    _assert_audit_integrity as _assert_audit_integrity,
)
from archon.services.startup_security import (
    _assert_auth_on_nonloopback_bind as _assert_auth_on_nonloopback_bind,
)
from archon.services.startup_security import (
    _audit_integrity_enforced as _audit_integrity_enforced,
)
from archon.services.startup_security import (
    _mark_audit_compromised as _mark_audit_compromised,
)
from archon.services.startup_security import (
    _must_force_auth as _must_force_auth,
)
from archon.services.startup_security import (
    _nonloopback_bind_detected as _nonloopback_bind_detected,
)
from archon.services.startup_security import (
    _verify_all_audit_chains as _verify_all_audit_chains,
)
from archon.services.startup_security import (
    register_startup_security_deps_provider as _register_startup_security_deps_provider,
)
from backend.auth_service import auth_service as auth_service
from backend.platform_paths import HERMES_HOME as HERMES_HOME
from backend.platform_paths import OBSIDIAN_VAULT as OBSIDIAN_VAULT
from backend.platform_paths import OBSIDIAN_VAULT_ALT as OBSIDIAN_VAULT_ALT
from backend.platform_paths import PERSONALAKTEN_DIR as PERSONALAKTEN_DIR
from backend.platform_paths import PROJEKTE_DIR as PROJEKTE_DIR
from backend.platform_paths import agent_log_path as agent_log_path
from backend.platform_paths import profile_dir as profile_dir
from backend.platform_paths import soul_path as soul_path
from backend.post_task_pipeline import project_folder_name
from dossier_builder import build_dossier_from_report
from telegram_notify import send_telegram_document, send_telegram_message
from utils.docker_client import DockerError as DockerError
from utils.docker_client import docker_client as docker_client
from utils.docker_client import parse_docker_stream as parse_docker_stream
from utils.docker_client import parse_docker_stream_bytes as parse_docker_stream_bytes

_create_permission_gate = create_permission_gate
_load_permission_gates = load_permission_gates
_save_permission_gates = save_permission_gates

# --- A5-Etappe 1: unveraenderliche Modul-Konstanten ausgelagert ------------
# Quelle ist jetzt archon/core/constants.py (ein Ort, keine Kopie). Mutabler
# State und Pfad-Konstanten bleiben bewusst in dieser Datei (Fallstrick 24 / B10).

# Orchestration functions (extracted to archon.core.orchestration)

# W3: Log-Level zur Laufzeit konfigurierbar (Incidents brauchen DEBUG ohne
# Code-Änderung/Neustart).
_LOG_LEVEL_NAME = os.getenv("ARCHON_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")).strip().upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL_NAME, logging.INFO))
logger = logging.getLogger("archon_os")

# W3: Promtail mountet ./data/logs und erwartet *.log im Format
# "timestamp - logger - level - message". Vorher schrieb die App nur auf
# stderr — Loki/Grafana waren für App-Logs komplett blind. Rotierend, damit
# im Non-Container-Betrieb keine unbegrenzte Logdatei entsteht.
try:
    from logging.handlers import RotatingFileHandler as _RotatingFileHandler
    _log_dir = os.getenv("ARCHON_LOG_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "logs"
    )
    os.makedirs(_log_dir, exist_ok=True)
    _file_handler = _RotatingFileHandler(
        os.path.join(_log_dir, "archon.log"), maxBytes=20_000_000, backupCount=5, encoding="utf-8"
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))
    logging.getLogger().addHandler(_file_handler)
except Exception as _log_exc:
    logger.debug("[Logging] File-Handler nicht verfügbar: %s", _log_exc)

# Fail-closed: fehlgeschlagene Router-Imports werden gesammelt und
# beim Start in Produktion hart abgebrochen (siehe _assert_router_health).
_ROUTER_LOAD_ERRORS: List[str] = []

# ---------------------------------------------------------------------------
# Ein einziger, geordneter Startup/Shutdown-Pfad.
# Vorher: 3x @app.on_event("startup") + 2x ("shutdown") — deprecated und in
# unbestimmter Reihenfolge ausgefuehrt. Jetzt: explizite Registrierung in
# _STARTUP_HOOKS / _SHUTDOWN_HOOKS am Dateiende, Ausfuehrung im Lifespan.
# ---------------------------------------------------------------------------
_STARTUP_HOOKS: List[Any] = []
_SHUTDOWN_HOOKS: List[Any] = []

# KRITISCH (Audit 23.11.2026): Sicherheits-Hooks duerfen niemals nur geloggt
# werden. Ein fehlgeschlagener Router-Health- oder Audit-HMAC-Check muss den
# Start abbrechen — sonst laeuft die Anwendung mit fälschbarer Revisionskette
# bzw. still 404-enden Router weiter.
_FAIL_FAST_HOOKS = {
    "_assert_router_health",
    "_assert_audit_hmac",
    "_assert_audit_integrity",
    "_assert_auth_on_nonloopback_bind",
    "_assert_api_key_pepper",
}
# M2: _N8N_STARTUP_STATUS, _AUDIT_COMPROMISED/AUDIT_COMPROMISED und die
# Startup-Sicherheits-Gates liegen in archon/services/startup_security.py bzw.
# archon/services/shutdown_clients.py (X-as-X Re-Exports am Modulkopf).
_register_startup_security_deps_provider(
    lambda: _StartupSecurityDeps(
        verify_all_audit_chains=_verify_all_audit_chains,
        audit_integrity_enforced=_audit_integrity_enforced,
        mark_audit_compromised=_mark_audit_compromised,
        must_force_auth=_must_force_auth,
        nonloopback_bind_detected=_nonloopback_bind_detected,
    )
)


async def _archon_lifespan(_app_instance):
    # 2b/S2: der Startup-/Shutdown-Pfad ist 1:1 nach
    # archon/services/lifecycle.py gewandert. Die Facade bleibt bewusst ein
    # asynchroner Generator mit yield (gleiche Form fuer FastAPI).
    #
    # Alle stabilen Contracts bleiben PHYSISCH in dieser Datei und werden zur
    # AUFRUFZEIT uebergeben (S3, kein Modul-Level-Rueckimport):
    # _STARTUP_HOOKS inkl. der 5 insert(0, ...)-Stellen, _SHUTDOWN_HOOKS
    # (reversed() im Modul), _FAIL_FAST_HOOKS (raise statt Log),
    # _init_readiness_probe_table (D08/H-08-2).
    from archon.services.lifecycle import lifespan_context

    async with lifespan_context(
        startup_hooks=list(_STARTUP_HOOKS),
        shutdown_hooks=list(_SHUTDOWN_HOOKS),
        fail_fast_hooks=_FAIL_FAST_HOOKS,
        init_readiness_probe_table=_init_readiness_probe_table,
    ):
        yield

# Begrenzter Graceful-Shutdown: sonst blockiert uvicorn --reload bei jeder
# Code-Änderung unbegrenzt auf offene Streams und der Server friert ein.
try:
    from backend.uvicorn_shutdown_guard import install as _install_shutdown_guard
    _install_shutdown_guard()
except Exception as _shutdown_guard_err:
    logger.warning(f"[Startup] Shutdown-Guard nicht aktiv: {_shutdown_guard_err}")

app = FastAPI(title="Agent OS Control Panel", lifespan=_archon_lifespan)
_APP_START_TS = time.time()

app.add_middleware(GZipMiddleware, minimum_size=1000)


# M4: TraceContextMiddleware, CORS- & Rate-Limit-Installer liegen in
# archon/services/runtime_endpoints.py (Re-Export am Modulkopf).
def _install_cors_middleware() -> None:
    _install_cors_middleware_impl(app)


def _install_rate_limit_middleware() -> None:
    _install_rate_limit_middleware_impl(app)

# --- Locale Middleware (Etappe 4): Accept-Language -> request.state.lang ---
try:
    from archon.core.locale_middleware import LocaleMiddleware
    app.add_middleware(LocaleMiddleware)
    logger.info("[i18n] LocaleMiddleware aktiv")
except Exception as _err_lm:
    logger.warning(f"[i18n] LocaleMiddleware nicht aktiv: {_err_lm}")

# --- Demo Mode Middleware (M47): Read-only sandbox for live showcases ---
try:
    from backend.demo_mode import DemoModeMiddleware
    app.add_middleware(DemoModeMiddleware)
    logger.info("[DemoMode] DemoModeMiddleware aktiv")
except Exception as _err_dm:
    logger.warning(f"[DemoMode] DemoModeMiddleware nicht aktiv: {_err_dm}")

# --- Exception-Handler (Etappe 4): code+params Format für API-Fehler ---
try:
    from archon.core.exceptions import register_exception_handlers
    register_exception_handlers(app)
    logger.info("[i18n] Exception-Handler registriert (code+params)")
except Exception as _err_eh:
    logger.warning(f"[i18n] Exception-Handler nicht aktiv: {_err_eh}")

@app.middleware("http")
async def add_no_cache_for_avatars(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/avatars/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# --- Auth-Gate (wirkt nur, wenn settings.auth.enabled = true) --------------
# 2c/S2: _AUTH_PUBLIC_EXACT, RAG_API_KEY_ENV, MissingRagApiKeyError,
# _get_rag_api_key, _check_rag_api_key_config und _auth_unavailable_response
# liegen jetzt in archon/middleware/auth_policy.py und werden oben per
# X-as-X re-exportiert. Bewusst IN main.py belassen: _SERVICE_TOKEN_CACHE,
# _get_service_token (nutzt __file__ fuer den Repo-Root) und
# _request_has_service_token (stabiler Contract D2 §295).

# Nicht-/api-Pfade, die trotzdem geschuetzt sein muessen: eingebettete
# Admin-Oberflaechen (n8n-Editor, OmniRoute-Konsole) und App-Shells.

_SERVICE_TOKEN_CACHE: Dict[str, Any] = {"ts": 0.0, "token": ""}


def _get_service_token() -> str:
    """Service-Token für interne Automaten (n8n, Adapter). Env hat Vorrang, sonst Datei."""
    now = time.time()
    if _SERVICE_TOKEN_CACHE["token"] and (now - _SERVICE_TOKEN_CACHE["ts"]) < 30.0:
        return _SERVICE_TOKEN_CACHE["token"]
    tok = (os.environ.get("ARCHON_SERVICE_TOKEN") or "").strip()
    if not tok:
        # FRUEHER: relativer CWD-Pfad — ein Angreifer mit Schreibzugriff auf
        # einen Jail-Root konnte die Token-Datei ueberschreiben und bekam
        # Vollzugriff. Jetzt: nur absolute, vertrauenswuerdige Pfade.
        _repo_root = os.path.dirname(os.path.abspath(__file__))
        for path in ("/app/data/.archon_service_token", os.path.join(_repo_root, "data", ".archon_service_token")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    tok = f.read().strip()
                if tok:
                    break
            except Exception:
                continue
    _SERVICE_TOKEN_CACHE.update({"ts": now, "token": tok})
    return tok


def _request_has_service_token(request: Request) -> bool:
    expected = _get_service_token()
    provided = request.headers.get("x-archon-service-token", "")
    if not expected or not provided:
        return False
    import hmac
    return hmac.compare_digest(provided, expected)


def _build_auth_gate_deps() -> _AuthGateDeps:
    return _AuthGateDeps(
        request_has_service_token=_request_has_service_token,
        auth_unavailable_response=_auth_unavailable_response,
        auth_public_exact=_AUTH_PUBLIC_EXACT,
        auth_public_prefixes=_AUTH_PUBLIC_PREFIXES,
        auth_api_prefixes=_AUTH_API_PREFIXES,
        auth_protected_prefixes=_AUTH_PROTECTED_PREFIXES,
    )


@app.middleware("http")
async def tenant_context_middleware(request: Request, call_next):
    """Bindet optionalen Mandanten-Header (X-Tenant-Id / X-Company-Id) request-lokal via ContextVar."""
    return await _run_tenant_context_middleware(request, call_next, _build_auth_gate_deps())


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Blockt API-Aufrufe ohne gültige Session, sobald Multi-User aktiv ist (fail-closed)."""
    return await _run_auth_gate_middleware(request, call_next, _build_auth_gate_deps())


# CORS und Rate-Limit MUESSEN nach allen @app.middleware-Definitionen
# installiert werden, sonst liegen sie innen und 401/403/429 tragen keine
# CORS-Header bzw. unauthentifizierte Requests umgehen den Limiter.
_install_rate_limit_middleware()
_install_cors_middleware()

# D16/HIGH: TraceContext als LETZTE Middleware registrieren => aeusserste
# Schicht. Damit laeuft sie vor Auth/RateLimit/CORS und setzt X-Trace-Id
# auch auf 401/403/429/503. (Die Klasse ist oben definiert.)
app.add_middleware(TraceContextMiddleware)


def _init_readiness_probe_table() -> None:
    """DDL einmalig (Lifespan) — nicht mehr pro Healthcheck-Scrape."""
    _init_readiness_probe_table_impl(_get_state_db)


def _readiness_sync_checks() -> list:
    """Alle blockierenden Readiness-Checks gebuendelt im Worker-Thread."""
    return _run_readiness_sync_checks(_get_state_db)


def _build_health_probe_deps() -> _HealthProbeDeps:
    return _HealthProbeDeps(
        get_state_db=_get_state_db,
        router_load_errors=_ROUTER_LOAD_ERRORS,
        audit_compromised=_AUDIT_COMPROMISED,
        failed_cancels=_FAILED_CANCELS,
        watchdog_stop_failed=_WATCHDOG_STOP_FAILED,
        startup_recovery_failed=_STARTUP_RECOVERY_FAILED,
        n8n_startup_status=_N8N_STARTUP_STATUS,
        db_maintenance_status=_DB_MAINTENANCE_STATUS,
        probe_external_dependency=_probe_external_dependency,
        readiness_sync_checks=_readiness_sync_checks,
    )


@app.get("/livez")
async def liveness_check():
    """Liveness: Event-Loop-Heartbeat, Loop-Lag + Watchdog-Thread (503 bei blockiertem Loop)."""
    return await _run_liveness_check()


@app.get("/readyz")
async def readiness_check():
    """Readiness: echte Dependency-Pruefung. Liefert 503, solange nicht bereit."""
    return await _run_readiness_check(_build_health_probe_deps(), _readiness_probe_targets())


@app.get("/health")
async def health_check():
    """D08/H-08-2: /health spiegelt jetzt /livez (reine Loop-Lebendigkeit).

    Vorher rief /health readiness_check() auf und uebernahm damit dessen
    blockierende DDL-/Config-Arbeit. Dependency-Probes gehören ausschliesslich
    in /readyz; ein staller Event-Loop muss ueber /health sofort sichtbar
    werden. Der Response-Status "ok" bleibt fuer bestehende Consumer erhalten.
    """
    live = await liveness_check()
    if isinstance(live, JSONResponse) and live.status_code == 503:
        return live
    return {"status": "ok", "timestamp": time.time(), "liveness": live}

@app.get("/metrics")
def prometheus_metrics():
    """Prometheus-konformer Metriken-Endpoint fuer Scraping und Monitoring."""
    try:
        from backend.metrics_collector import metrics_collector
        return Response(
            content=metrics_collector.generate_prometheus_metrics(),
            # OpenMetrics erlaubt Exemplare (`# {trace_id=...,span_id=...}`);
            # Prometheus ist mit exemplar-storage konfiguriert.
            media_type="application/openmetrics-text; version=1.0.0; charset=utf-8"
        )
    except Exception as e:
        return Response(content=f"# Error collecting metrics: {e}\n", status_code=500, media_type="text/plain")


_register_router(app, _telemetry_router, '_telemetry_router')



# Pfade + Laufzeit-Helfer kommen aus app.core.runtime (gemeinsame Basis für
# main.py und die ausgelagerten Router; dort zyklenfrei definiert).

# --- A5-Etappe 4b: Pfad-Konstanten ausgelagert -----------------------------
# Quelle ist archon/core/paths.py; alle Pfade leiten sich aus den Basis-
# Verzeichnissen oben ab (keine zweite __file__-Wahrheit). main.py importiert
# nur noch — die Werte sind per scripts/path_constants_snapshot.py belegt.

# Kostenanzeige im Chat-Stream braucht die Preisliste des Providers-Routers.

# Gate-Ausfuehrung ruft den Service, nicht die HTTP-Endpunkte: die Endpunkte
# brauchen einen Request (require_admin_or_503) und waren hier nie importiert.

# --- Pfad-Jail: jeder dateibasierte Endpunkt bleibt in erlaubten Wurzeln ---
try:
    from utils.path_jail import (
        PathJailError,
        allowed_roots,
        safe_filename,
        safe_path,
        safe_path_within,
    )
except Exception as _pj_err:  # pragma: no cover - darf den Start nie blockieren
    print(f"[PathJail] Konnte utils.path_jail nicht laden: {_pj_err}", file=sys.stderr)

    class PathJailError(PermissionError):  # type: ignore[no-redef]
        pass

    def safe_path(candidate, **kwargs):  # type: ignore[misc]
        raise PathJailError("PathJail subsystem unavailable (fail-closed)")

    def safe_path_within(candidate, roots, **kwargs):  # type: ignore[misc]
        raise PathJailError("PathJail subsystem unavailable (fail-closed)")

    def safe_filename(name):  # type: ignore[misc]
        clean = os.path.basename(str(name or "").replace("\\", "/"))
        if not clean or clean in (".", ".."):
            raise PathJailError(f"Ungueltiger Dateiname: {name!r}")
        return clean

    def allowed_roots(extra=None):  # type: ignore[misc]
        return []

# --- Rollenzaun fuer die in main.py verbliebenen schreibenden Routen ---------
# Ein Injektionspunkt (archon/routers/_rbac.py): `main.py` registriert seine
# require_admin-Funktion am Dateiende per configure(); hier wird nur der
# Aufrufpfad importiert. Fehlt die Injektion, sperrt der Zaun (503) statt
# still durchzulassen — fail-closed.

os.makedirs(OBSIDIAN_VAULT_DIR, exist_ok=True)
os.makedirs(os.path.join(WORKSPACE_DIR, "sandbox"), exist_ok=True)
os.makedirs(MEMORY_DIR, exist_ok=True)

try:
    from core_skills_engine import CoreSkillsEngine
    skills_engine = CoreSkillsEngine(
        vault_dir=OBSIDIAN_VAULT_DIR,
        rag_db_dir=os.path.join(WORKSPACE_DIR, "chroma_db")
    )
except Exception as e:
    print(f"Failed to import core_skills_engine: {e}", file=sys.stderr)
    skills_engine = None  # type: ignore[assignment]

try:
    from backend.db_paths import resolve_db as _resolve_db_path
    from local_memory_bridge import LocalMemoryBridge
    memory_bridge = LocalMemoryBridge(
        db_path=_resolve_db_path("agentic_memory.db"),
        vault_path=OBSIDIAN_VAULT_DIR
    )
except Exception as e:
    print(f"Failed to import local_memory_bridge: {e}", file=sys.stderr)
    memory_bridge = None  # type: ignore[assignment]

watchdog_runner = None


def _start_watchdog_daemon():
    """Watchdog erst beim App-Start starten - nicht beim Import.

    Vorher lief der Supervisor-Thread bereits bei `import main`, also auch in
    jedem Test-, CLI- oder Analyseprozess.
    """
    global watchdog_runner
    if watchdog_runner is not None:
        logger.warning("[Startup] Watchdog laeuft bereits — kein zweiter Start.")
        return
    try:
        from watchdog_daemon import start_background_watchdog
        watchdog_runner = start_background_watchdog()
    except Exception as e:
        print(f"Failed to start watchdog_daemon: {e}", file=sys.stderr)
        watchdog_runner = None

# ROLES_FILE/SERVICES_FILE: effektiv gilt die spaetere Definition unter
# WORKSPACE_DIR (Z. ~2520) — die MEMORY_DIR-Variante war wirkungslos.
os.makedirs(QUICKCHAT_SESSIONS_DIR, exist_ok=True)

# Ticker/SSE/Broadcast leben in app.core.runtime (siehe Import oben).


# =====================================================================
# PERSISTENZ-HELFER (Basic UI Configuration State)
# =====================================================================


def load_agents() -> List[Dict]:
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    if os.path.exists(agents_root):
        loaded = _load_json(agents_root, DEFAULT_AGENTS)
    elif os.path.exists(AGENTS_FILE):
        loaded = _load_json(AGENTS_FILE, DEFAULT_AGENTS)
    else:
        loaded = DEFAULT_AGENTS
    cleaned = [a for a in loaded if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    return cleaned if len(cleaned) > 0 else DEFAULT_AGENTS

def save_agents(agents: List[Dict]):
    existing = load_agents()
    incoming_ids = {str(a.get("id")) for a in agents if a.get("id")}
    preserved = [
        a for a in existing
        if str(a.get("id")) not in incoming_ids and (
            a.get("active") is False or str(a.get("id", "")).lower() in SYSTEM_INTERNAL_IDS
        )
    ]
    merged = preserved + list(agents)
    cleaned = [a for a in merged if str(a.get("id", "")).lower() not in GHOST_AGENT_IDS]
    agents_root = os.path.join(WORKSPACE_DIR, "agents.json")
    _save_json(agents_root, cleaned)
    _save_json(AGENTS_FILE, cleaned)

    try:
        from archon.core.profiles import invalidate_hermes_profiles_cache
        from archon.core.runtime import APP_ROOT, atomic_write_json
        ssot_file = os.path.join(APP_ROOT, "agent_profiles.json")
        if os.path.exists(ssot_file):
            with open(ssot_file, "r", encoding="utf-8") as f:
                p_list = json.load(f)
            if isinstance(p_list, list):
                incoming_map = {str(a.get("id")): a for a in agents if a.get("id")}
                updated = False
                for p in p_list:
                    pid = str(p.get("id"))
                    if pid in incoming_map:
                        inc = incoming_map[pid]
                        for fld in ("name", "role", "model", "provider", "system_prompt"):
                            if fld in inc and inc[fld]:
                                p[fld] = inc[fld]
                                updated = True
                if updated:
                    atomic_write_json(ssot_file, p_list)
                    invalidate_hermes_profiles_cache()
    except Exception as exc:
        logger.warning(f"[Agents] SSoT-Profile-Sync fehlgeschlagen: {exc}")

@ttl_cache(seconds=60)
def load_roles() -> List[Dict]:
    # A8-DELEGATED: SSOT-Projektion aus agent_profiles.json statt statischem
    # Import-Snapshot. DEFAULT_ROLES bleibt nur als Import-Kompatibilitaet
    # (container_ops.py liest app_main.DEFAULT_ROLES) erhalten.
    return _load_json(ROLES_FILE, load_default_roles())

def save_roles(roles: List[Dict]):
    vorher = _load_json(ROLES_FILE, [])
    _save_json(ROLES_FILE, restore_data_uri_avatars(roles, vorher))
    invalidate_ttl_cache(load_roles)

def load_services() -> List[Dict]:
    if os.path.exists(COUPLED_AGENTS_FILE):
        return _load_json(COUPLED_AGENTS_FILE, DEFAULT_SERVICES)
    return _load_json(SERVICES_FILE, DEFAULT_SERVICES)

def save_services(services: List[Dict]):
    _save_json(SERVICES_FILE, services)
    os.makedirs(os.path.join(WORKSPACE_DIR, "config"), exist_ok=True)
    _save_json(COUPLED_AGENTS_FILE, services)

def load_memory() -> List[Dict]: return _load_json(MEMORY_FILE, [])
def save_memory(memory_data: List[Dict]): _save_json(MEMORY_FILE, memory_data)

def load_theme() -> Dict: return _load_json(THEME_FILE, {})
def save_theme(theme_data: Dict): _save_json(THEME_FILE, theme_data)

# =====================================================================
# REST ENDPOINTS
# =====================================================================


_register_router(app, _core_settings_router, '_core_settings_router')


_register_router(app, _oracle_seo_router, '_oracle_seo_router')

# --- THEME & DESIGN ROUTER (ausgelagert nach archon.routers.theme) ---

_register_router(app, _theme_router, '_theme_router')



_register_router(app, _docker_services_router, '_docker_services_router')


_register_router(app, _agent_chat_router, '_agent_chat_router')


def load_boardroom_frameworks():
    fw = _load_json(FRAMEWORKS_FILE, None)
    if fw:
        core_dispatcher.CATEGORIZED_FRAMEWORKS = fw
    else:
        _save_json(FRAMEWORKS_FILE, core_dispatcher.CATEGORIZED_FRAMEWORKS)
    return core_dispatcher.CATEGORIZED_FRAMEWORKS

# =====================================================================
# GATEWAY MANAGER — Hermes Profile Start/Stop/Autostart/Idle-Timeout
# =====================================================================



_register_router(app, _gateway_router, '_gateway_router')


# =====================================================================
# INTERNET WATCHDOG (SÄULE 4 DER KOGNITION: AUTONOMER WEB-RADAR)
# =====================================================================


_register_router(app, _watchdog_router, '_watchdog_router')


# M1: Hintergrund-Loops, Task-Registry & Shutdown-Abbruch nach
# archon/services/background_loops.py ausgelagert (S3 Call-Time-Deps).
_idle_stop_running = False
_RAG_SYNC_PROCESS = None


async def _gateway_idle_stop_loop():
    global _idle_stop_running
    if _idle_stop_running:
        logger.warning("[GatewayManager] Idle-Stop-Loop laeuft bereits - kein zweiter Start.")
        return
    _idle_stop_running = True
    try:
        from archon.routers.gateway import _gateway_idle_stop_loop as _impl
        await _impl()
    finally:
        _idle_stop_running = False


def _is_rag_sync_running() -> bool:
    """Prueft, ob aktuell ein RAG-Sync-Prozess aktiv ist (Re-06)."""
    global _RAG_SYNC_PROCESS
    return _RAG_SYNC_PROCESS is not None and _RAG_SYNC_PROCESS.poll() is None


def _set_rag_sync_process(proc: Any) -> None:
    global _RAG_SYNC_PROCESS
    _RAG_SYNC_PROCESS = proc


def _build_background_loop_deps() -> _BackgroundLoopDeps:
    return _BackgroundLoopDeps(
        load_mission_control_data=_load_mission_control_data,
        update_mission_control_data=update_mission_control_data,
        mc_async_lock=_MC_ASYNC_LOCK,
        run_synthesis_cascade=_run_synthesis_cascade,
        orch_fan_in_maybe_start_synthesis=_orch_fan_in_maybe_start_synthesis,
        verify_all_audit_chains=_verify_all_audit_chains,
        mark_audit_compromised=_mark_audit_compromised,
        get_service_token=_get_service_token,
        get_rag_sync_process=lambda: _RAG_SYNC_PROCESS,
        set_rag_sync_process=_set_rag_sync_process,
        gateway_idle_stop_loop=_gateway_idle_stop_loop,
    )


_register_background_loop_deps_provider(_build_background_loop_deps)


_register_router(app, _quickchat_router, '_quickchat_router')
_register_router(app, _ui_router, '_ui_router')

# Kontext-Meter & Session-Compaction (M73, Teil 1+2)

_register_router(app, _context_meter_router, '_context_meter_router')


# ============================================================================
# BRAIN & ARCHIV ROUTER (ausgelagert nach archon.routers.brain)
# ============================================================================

_brain_configure(
    _spawn_background=_spawn_background,
    _get_rag_api_key=_get_rag_api_key,
    _is_rag_sync_running=_is_rag_sync_running,
    _RAG_SYNC_LOCK=_RAG_SYNC_LOCK,
    post_docker_container_action=post_docker_container_action,
)
_register_router(app, _brain_router, '_brain_router')

# --- NOTEBOOKLM STUDIO & GROUNDED RETRIEVAL API (ausgelagert nach archon.routers.notebooks) ---

_register_router(app, _notebooks_router, '_notebooks_router')


def _build_rag_sync_cmd(sync_script: str) -> list:
    """Baut das Befehls-Array fuer den AnythingLLM Vault-Sync."""
    return [sys.executable, sync_script, "--api-key", _get_rag_api_key(), "--all"]


os.makedirs(HERMES_PROFILES_DIR, exist_ok=True)
_HERMES_SKILLS_CACHE = None
_HERMES_SKILLS_CACHE_TIME = 0

# M4: _warm_hermes_skill_caches liegt in archon/services/runtime_endpoints.py.



_register_router(app, _telegram_router, '_telegram_router')



# =========================================================================
# ZENTRALER ENTSCHEIDUNGS-SERVICE (ausgelagert nach archon.routers.decisions)
# =========================================================================

_register_router(app, _decisions_router, '_decisions_router')
_set_decision_factory(create_decision)

# Statik-Guard AST Wrapper fuer tests/test_decision_followup_beleg.py
async def _followup_mission_start(ref: str) -> str:
    """Wrapper delegating to _impl_followup_mission_start; retains _pruefe_move_antwort."""
    return await _impl_followup_mission_start(ref)  # _pruefe_move_antwort

async def _followup_permission_gate(ref: str, proof_token: str = "", proof_uid: str = "") -> str:
    """Wrapper delegating to _impl_followup_permission_gate; retains _pruefe_gate_antwort."""
    # HITL: Proof und uid der Decision unveraendert an den Gate-Followup durchreichen.
    return await _impl_followup_permission_gate(ref, proof_token, proof_uid)  # _pruefe_gate_antwort

async def _followup_synthesis(pid: str, dossier: str, dec: dict) -> str:
    """Wrapper delegating to _impl_followup_synthesis; retains _pruefe_synthese_beleg."""
    return await _impl_followup_synthesis(pid, dossier, dec)  # _pruefe_synthese_beleg

class ProfileStatusUpdate(BaseModel):
    status: Optional[str] = "active"


# 
# SYSTEM HEALTH, HERMES CONFIG & CONTAINER LIFECYCLE MANAGEMENT
# 



_register_router(app, _hermes_ops_router, '_hermes_ops_router')

# ============================================================================
# CHAT ROUTER & DELEGATION (ausgelagert nach archon.routers.chat)
# ============================================================================
# D-12: Default Fallback Modell für OmniRoute / Chat Stream
model = "auto/best-coding"

_chat_configure(create_decision=create_decision)
_register_router(app, _chat_router, '_chat_router')

# ============================================================================
# DELEGATION ENGINE v2 (ausgelagert nach archon.core.delegation)
# ============================================================================

_delegation_configure(
    api_get_hermes_profiles=api_get_hermes_profiles,
    _get_state_db=_get_state_db,
    _ensure_session_exists=_ensure_session_exists,
    _save_message_to_db=_save_message_to_db,
    _spawn_background=_spawn_background,
    register_decision=register_decision,
    fan_in=lambda pid: _fan_in_maybe_start_synthesis(pid),
)

_GUARDIAN_STATS_CACHE: Dict[str, Any] = {}
# --- GUARDIAN ROUTER (ausgelagert nach archon.routers.guardian, 1157 Zeilen) ---

_register_router(app, _guardian_router, '_guardian_router')

# --- HERMES RAW CONFIG & LIVE EDITOR ENDPOINTS ---
# --- HERMES CONFIG ROUTER (ausgelagert nach archon.routers.hermes_config, 792 Zeilen) ---

_hermes_config_configure(_sync_org_hierarchy_node=_sync_org_hierarchy_node)
_register_router(app, _hermes_config_router, '_hermes_config_router')

# --- KONTEXT-HILFE (ausgelagert nach archon.routers.context_help) ---

_register_router(app, _context_help_router, '_context_help_router')

# --- MEILENSTEIN 4: MULTI-USER & RBAC ENDPOINTS (ausgelagert nach archon.routers.auth) ---

_auth_configure(
    _load_json=_load_json,
    _save_json=_save_json,
    _request_has_service_token=_request_has_service_token,
)
_register_router(app, _auth_router, '_auth_router')


_PAPERCLIP_AGENTS_CACHE = None
_PAPERCLIP_AGENTS_CACHE_TIME = 0.0

def invalidate_paperclip_agents_cache():
    global _PAPERCLIP_AGENTS_CACHE, _PAPERCLIP_AGENTS_CACHE_TIME
    _PAPERCLIP_AGENTS_CACHE = None
    _PAPERCLIP_AGENTS_CACHE_TIME = 0.0

@app.get("/api/paperclip/agents")
def api_get_paperclip_agents():
    # C21: bisher `status: success` mit leerer Liste — ein totes Endpoint,
    # das eine funktionierende Integration vortaeuschte.
    return {
        "status": "not_configured",
        "agents": [],
        "message": "Paperclip-Integration ist nicht angebunden; es werden keine Agenten gemeldet.",
    }


# --- TALENT- & SKILL-MARKTPLATZ ENDPOINTS (ausgelagert nach archon.routers.marketplace) ---

_marketplace_configure(save_all_agent_profiles=save_all_agent_profiles)
_register_router(app, _marketplace_router, '_marketplace_router')


_register_router(app, _memory_ops_router, '_memory_ops_router')


_register_router(app, _email_settings_router, '_email_settings_router')


_register_router(app, _security_scanner_router, '_security_scanner_router')


_register_router(app, _research_router, '_research_router')



# --- SYSTEM UPDATE & RELEASE-LIFECYCLE (MEILENSTEIN 1) ---


# --- HERMES AGENT CORE UPDATE (NousResearch/hermes-agent) ---

_register_router(app, _updater_router, '_updater_router')

# --- VERTRAGS- & FRISTENMANAGEMENT (t-0a2171) ---


# --- SAUBERES HERUNTERFAHREN & TASK-DRAINING (t-12113b) ---
# M4: on_startup_drain_recovery & on_shutdown_graceful liegen in
# archon/services/runtime_endpoints.py (S3 Call-Time-Deps).
_register_runtime_endpoints_deps_provider(
    lambda: _RuntimeEndpointsDeps(
        startup_recovery_failed=_STARTUP_RECOVERY_FAILED,
        router_load_errors=_ROUTER_LOAD_ERRORS,
        reset_loops_started=_reset_loops_started,
    )
)


# --- EU AI ACT COMPLIANCE & KI-INVENTAR (t-1aa5e9) ---


# --- AUTOMATISCHE DATENKLASSIFIZIERUNG (t-53315b) ---


# --- DOKUMENTEN-PARSING & TABELLENEXTRAKTION (t-539b65) ---

_register_router(app, _documents_router, '_documents_router')


# --- DEAL-PIPELINE & FORECAST-ENGINE (ausgelagert nach archon.routers.deals) ---

_register_router(app, _deals_router, '_deals_router')


# --- PLUGIN SYSTEM & EXTENSIBILITY (MEILENSTEIN 5) ---





# --- OBSIDIAN VAULT ROUTER (ausgelagert nach archon.routers.vault) ---

_register_router(app, _vault_router, '_vault_router')

@app.post("/api/sandbox")
def api_run_python_sandbox(request: Request, payload: Dict = Body(...)):
    # NOTBREMSE S6: Nutzer-Code-Ausführung mit Host-Python deaktiviert.
    # Isolierte Ausführung: POST /api/sandbox/execute (backend/ephemeral_sandbox, Docker, --network none).
    require_admin(request)  # RBAC: Admin-Sache
    raise HTTPException(
        status_code=501,
        detail="Sandbox deaktiviert (S6-Hardening). Nutze POST /api/sandbox/execute für isolierte Ausführung."
    )


# --- KANBAN PERSISTENZ ROUTER (ausgelagert nach archon.routers.kanban) ---

_register_router(app, _kanban_router, '_kanban_router')

# --- ARCHON V2 CAPABILITIES ROUTER (M32-M94) ---

_register_router(app, _v2_capabilities_router, '_v2_capabilities_router')

_register_router(app, _content_machine_router, '_content_machine_router')

# --- DOCKER CONTAINER MANAGEMENT ROUTER (ausgelagert nach archon.routers.containers) ---

_containers_configure(
    detect_container_port=detect_container_port,
    post_docker_container_action=post_docker_container_action,
)
_register_router(app, _containers_router, '_containers_router')


_register_router(app, _container_ops_router, '_container_ops_router')



_register_router(app, _hermes_proxy_router, '_hermes_proxy_router')








_register_router(app, _hr_router, '_hr_router')




# 🚀 MISSION CONTROL 3-ZONEN-COCKPIT & HITL KANBAN API
# =====================================================================




class OSKanbanTaskStatusUpdate(BaseModel):
    status: str

# Mission-Control-Store -> archon.core.mission_control (Import oben)



# M4: sse_events_stream und die 8 Orchestration-Wrapper liegen in
# archon/services/runtime_endpoints.py bzw. archon/services/orchestration_bridge.py.
app.add_api_route("/api/v1/events/stream", sse_events_stream, methods=["GET"])


def _build_orchestration_bridge_deps() -> _OrchestrationBridgeDeps:
    return _OrchestrationBridgeDeps(
        dispatcher=core_dispatcher,
        load_mc=_load_mission_control_data,
        save_mc=_save_mission_control_data,
        update_mc=update_mission_control_data,
        write_mc_atomic=_write_mc_atomic,
        mc_async_lock=_MC_ASYNC_LOCK,
        ticker=add_ticker,
        get_profiles=api_get_hermes_profiles,
        sync_obsidian=_sync_task_to_obsidian,
        rolling_backup=create_rolling_backup,
        invalidate_profiles=invalidate_hermes_profiles_cache,
        paths={"OBSIDIAN_VAULT_DIR": OBSIDIAN_VAULT_DIR, "WORKSPACE_DIR": WORKSPACE_DIR},
        folder_namer=project_folder_name,
        build_dossier=build_dossier_from_report,
        create_decision=create_decision,
        send_doc=send_telegram_document,
        send_msg=send_telegram_message,
        set_status=_set_agent_profile_status,
        paperclip_hire=_paperclip_hire_profile_by_id,
        trigger_sandy=_trigger_sandy_staffing_nomination,
        fan_in=_fan_in_maybe_start_synthesis,
        tg_ping=_tg_ping_synthesis,
        finalize_approval=_finalize_synthesis_after_approval,
        run_cascade=_run_synthesis_cascade,
    )


_register_orchestration_bridge_deps_provider(_build_orchestration_bridge_deps)




# (Prompt Templates & Studio Variablen in archon.routers.templates)



_register_router(app, _prompts_router, '_prompts_router')



_register_router(app, _proxies_router, '_proxies_router')



# 2d/1: die zwei Sonderbloecke (views_core + operations) sind 1:1 nach
# archon/routers/__init__.py gewandert. Die Aufrufstelle bleibt exakt hier,
# damit die Registrierungsreihenfolge (Pfad-Praezedenz, INVARIANTS #7)
# unveraendert ist. _ROUTER_LOAD_ERRORS wird als IDENTISCHE Liste
# uebergeben — kein Rebind, _assert_router_health() liest das Original.
_register_special_routers(app, _ROUTER_LOAD_ERRORS)

# Avatare: eigener Lesezugriff VOR dem /static-Mount (Registration Order = Match
# Order). Die Laufzeit-Avatare liegen ausserhalb des Repos (avatars_dir, z. B.
# /opt/data/webui/static_avatars), der Katalog avatar_NNN.jpg weiterhin in
# APP_ROOT/static/avatars. Die Route bildet die Zwei-Quellen-Kette ab: erst
# Laufzeit, dann versionierter Bestand. Ein eigener StaticFiles-Mount auf
# /static/avatars scheidet aus, er wuerde den Katalog verdecken. Die URL
# (/static/avatars/<name>) bleibt unveraendert -> kein API-Vertrag beruehrt.
@app.get("/static/avatars/{filename}")
def get_static_avatar(filename: str):
    resolved = resolve_avatar_file(filename)
    if not resolved:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(resolved)

app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists("static_v2"):
    app.mount("/static_v2", StaticFiles(directory="static_v2"), name="static_v2")

# reload trigger

@app.get("/api/debug-db")
def debug_db(request: Request):
    require_admin_or_503(request)
    try:
        with _get_state_db() as conn:
            return {"db_path": STATE_DB_PATH, "msg_count": conn.execute("SELECT count(*) FROM messages").fetchone()[0]}
    except Exception as exc:
        logger.error("[DebugDB] Fehler: %s", exc)
        raise HTTPException(status_code=500, detail="Interner Datenbankfehler")


# =====================================================================
# PROAKTIVER MORGEN-STANDUP & AUTONOMER WECKDIENST (Pillar 1 & 7)
# =====================================================================



_register_router(app, _inbox_tools_router, '_inbox_tools_router')



_register_router(app, _resilience_router, '_resilience_router')
_register_router(app, _mesh_router, '_mesh_router')
_register_router(app, _autonomy_settings_router, '_autonomy_settings_router')


@app.post("/api/healing/attempt")
async def api_attempt_task_healing(request: Request, payload: HealingAttemptPayload):
    require_admin_or_503(request)
    return await _run_task_healing(request, payload)


# (Features 23-25, Corporate, ERP & CRM in archon/routers/ modularisiert)


# =========================================================================
# LIFESPAN-REGISTRIERUNG (ersetzt die frueheren @app.on_event-Handler)
# Reihenfolge ist explizit und damit reproduzierbar.
# =========================================================================
_STARTUP_HOOKS.extend([
    _start_watchdog_daemon,      # 1. Watchdog/Supervisor
    on_startup_drain_recovery,   # 2. Task-Recovery nach Absturz
    _harden_secret_permissions,  # 3. Secret-Dateien auf 600 setzen
    _ensure_zero_egress_worker_networks,  # 3b. Isolierte Docker-Worker-Netze (--internal, keine Internet-Route)
    _import_n8n_workflows_on_startup,  # 3c. D06: opt-in n8n-Import/Aktivierung (default not_configured)
    _start_gateway_idle_loop,    # 4. IMAP/Inbox/Internet-Watchdog-Loops
    _warm_hermes_skill_caches,   # 4. Skills-Cache vorwärmen (Thread)
    _check_rag_api_key_config,   # 5. RAG-Key vorhanden? Fehlt er -> ERROR-Zeile
])

def _stop_watchdog_daemon():
    """Watchdog-Supervisor (Prozess ODER Thread) beim Shutdown verifiziert stoppen."""
    global watchdog_runner
    if watchdog_runner is None:
        return
    runner = watchdog_runner
    watchdog_runner = None
    try:
        stopped = runner.stop()  # Event setzen + join + terminate/kill-Fallback
        if stopped is False:
            _WATCHDOG_STOP_FAILED.append({"reason": "stop() returned False", "ts": time.time()})
            logger.error("[Shutdown] Watchdog-Supervisor konnte nicht verifiziert gestoppt werden.")
    except Exception as exc:
        # F-042: frueher nur DEBUG -> der NameError im stop() war im Produktivlog
        # unsichtbar und der Thread lief beim Reload weiter.
        _WATCHDOG_STOP_FAILED.append({"reason": str(exc), "ts": time.time()})
        logger.error(f"[Shutdown] Watchdog-Stop fehlgeschlagen: {type(exc).__name__}: {exc}")


# M4: _cancel_tracked_tasks liegt in archon/services/runtime_endpoints.py.


# Lifespan fuehrt Shutdown-Hooks in REVERSED order aus. Reihenfolge hier:
# zuerst Clients schliessen, Tasks canceln, Loops stoppen — und ON_SHUTDOWN_GRACEFUL
# als LETZTES Element, damit es in reversed() ZUERST laeuft: Drain/Checkpoint
# muss stattfinden, BEVOR Tasks und HTTP-Clients abgebrochen werden.
_SHUTDOWN_HOOKS.extend([
    _close_dispatcher_clients,   # reversed: zuletzt (Clients zuerst zu machen waere falsch)
    _close_proxy_clients,        # F-054: Proxy-HTTP-Clients (id(loop)) schliessen
    _cancel_tracked_tasks,       # TaskRegistry-Cascades abbrechen
    _stop_watchdog_daemon,       # Watchdog-Thread stoppen
    _cancel_background_tasks,    # Hintergrund-Loops stoppen
    _close_all_http_clients,     # reversed: frueh — alle HTTP-Pools vor Cancel schliessen
    on_shutdown_graceful,        # reversed: ZUERST — Drain & Checkpoint vor Cancel
])


# ==========================================================================
# AUSGELAGERTE ROUTER (Modularisierung: archon/routers/*.py)
# Reihenfolge = Registrierungsreihenfolge; entspricht der frueheren
# Reihenfolge in main.py, damit Pfad-Praezedenz erhalten bleibt.
# ==========================================================================

# Rollenzaun fuer alle ausgelagerten Router: ein Injektionspunkt. Fehlt er
# (Import-Fehler), sperren die geschuetzten Router-Routen fail-closed (503).
try:
    from archon.routers import _rbac as _rbac_mod
    from archon.routers import auth as _auth_mod
    from archon.routers._rbac import configure as _rbac_configure
    from backend.rbac_guards import configure as _guards_configure
    _rbac_configure(require_admin=require_admin)
    # F2: backend/** darf archon.routers nicht importieren. Die Registry haelt
    # die ORIGINAL-Guards (A1-Injektion), damit _checker/configure in _rbac.py
    # und alle Test-Patch-Ziele 1:1 erhalten bleiben.
    _guards_configure(
        forbid_viewer_writes=_rbac_mod.forbid_viewer_writes,
        require_admin_or_503=_rbac_mod.require_admin_or_503,
        require_session_actor=_rbac_mod.require_session_actor,
        get_current_user_from_request=_auth_mod.get_current_user_from_request,
    )
except Exception as _e_rbac:
    logger.error(f"[RBAC] Rollenzaun nicht verdrahtet — geschuetzte Routen sperren: {_e_rbac}")
# 2d/2: 29 try/except-Router-Bloecke (30 include_router) sind 1:1 nach
# archon/routers/__init__.py gewandert. Die Aufrufstelle bleibt exakt hier
# (nach dem RBAC-Rollenzaun, vor _assert_router_health), damit die
# Registrierungsreihenfolge = Pfad-Praezedenz erhalten bleibt (INVARIANTS #7).
# Die 19 Abhaengigkeiten werden als Callables zur Aufrufzeit uebergeben —
# kein Rueckimport auf main (S3-Muster, Kartierung §6c). Der
# profiles_service.configure-Block liegt bewusst weiterhin im Span.
_late_router_deps = _LateRouterDeps(
    load_mission_control_data=_load_mission_control_data,
    save_mission_control_data=_save_mission_control_data,
    api_get_hermes_profiles=api_get_hermes_profiles,
    load_boardroom_frameworks=load_boardroom_frameworks,
    load_roles=load_roles,
    save_all_agent_profiles=save_all_agent_profiles,
    sync_org_hierarchy_node=_sync_org_hierarchy_node,
    invalidate_paperclip_agents_cache=invalidate_paperclip_agents_cache,
    profiles_service=profiles_service,
    load_json=_load_json,
    save_json=_save_json,
    broadcast_event=broadcast_event,
    require_admin=require_admin,
    skills_engine=skills_engine,
    get_live_telemetry_metrics=_get_live_telemetry_metrics,
    sync_task_to_obsidian=_sync_task_to_obsidian,
    execute_mission_control_task=_execute_mission_control_task,
    finalize_approval=_finalize_synthesis_after_approval,
    fan_in=_fan_in_maybe_start_synthesis,
)
_register_late_routers(app, _ROUTER_LOAD_ERRORS, _late_router_deps)

# W4-C (D15-H3): audited Pflicht-Bestaetigung für haftungsrelevante Rollen.
# Der Router liegt bewusst bei der Helper-SSOT in archon.core.profiles; ohne
# Registrierung bleibt der Prompt-Gate fail-closed (keine Bestaetigung).
try:
    from archon.core.profiles import get_liability_router as _get_liability_router

    app.include_router(_get_liability_router())
except Exception as _e_liability:
    _ROUTER_LOAD_ERRORS.append(f"liability_router: {_e_liability}")
    logger.error(f"[Router] Liability-Router nicht registriert: {_e_liability}")


# M4: _assert_router_health liegt in archon/services/runtime_endpoints.py.
_STARTUP_HOOKS.insert(0, _assert_router_health)

# M2: _assert_audit_hmac, _verify_all_audit_chains, _audit_integrity_enforced
# und _assert_audit_integrity liegen in archon/services/startup_security.py.
_STARTUP_HOOKS.insert(0, _assert_audit_hmac)
_STARTUP_HOOKS.insert(0, _assert_audit_integrity)

# B (Auth-Fail-Open): Nicht-Loopback-Bind ohne Auth muss den Start abbrechen.
_STARTUP_HOOKS.insert(0, _assert_auth_on_nonloopback_bind)

# D04/H-04-2: Produktion ohne API-Key-Pepper darf nicht starten.
_STARTUP_HOOKS.insert(0, _assert_api_key_pepper)
