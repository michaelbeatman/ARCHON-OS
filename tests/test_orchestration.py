"""
Unit-Tests für archon.core.orchestration — isolierte Tests aller 8 Funktionen.

Alle externen Dependencies werden per Mock/Fake injiziert.
Kein Dateisystem, kein Netzwerk, kein Telegram, kein Docker, kein core_dispatcher.
"""

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Import NUR aus archon.core.orchestration (nicht main.py)
from archon.core.orchestration import (  # noqa: E402
    _execute_mission_control_task,
    _paperclip_hire_profile_by_id,
    _set_agent_profile_status,
    _trigger_sandy_staffing_nomination,
    _finalize_synthesis_after_approval,
    _fan_in_maybe_start_synthesis,
    _tg_ping_synthesis,
    _run_synthesis_cascade,
)


# ============================================================================
# Test-Fixtures & Helpers — ALLE als Mock-Objekte
# ============================================================================

@pytest.fixture
def mock_dispatcher():
    """Mock core_dispatcher mit dispatch_to_omniroute_or_container und trigger_n8n_execution."""
    dispatcher = AsyncMock()
    dispatcher.dispatch_to_omniroute_or_container = AsyncMock(return_value={"content": "OK"})
    dispatcher.trigger_n8n_execution = AsyncMock(return_value={"status": "ok"})
    return dispatcher


@pytest.fixture
def mock_load_mc():
    """Mock _load_mission_control_data — gibt leere Mission-Control-Daten zurück."""
    m = Mock()
    m.return_value = {"tasks": [], "metrics": {}, "audit_logs": []}
    return m


@pytest.fixture
def mock_save_mc():
    """Mock _save_mission_control_data — tut nichts, zeichnet aber Aufrufe auf."""
    return Mock()


@pytest.fixture
def mock_ticker():
    """Mock add_ticker — zeichnet Aufrufe auf."""
    return Mock()


@pytest.fixture
def mock_get_profiles():
    """Mock api_get_hermes_profiles — gibt Test-Profile zurück."""
    m = Mock()
    m.return_value = [
        {"id": "micha", "person_name": "Michael Keller", "model": "test-model", "system_prompt": "Test"},
        {"id": "sandy", "person_name": "Sandy Hooks", "model": "test-model", "system_prompt": "Test"},
        {"id": "lisa", "person_name": "Lisa", "model": "test-model", "system_prompt": "Test"},
        {"id": "robert", "person_name": "Robert", "model": "test-model", "system_prompt": "Test"},
        {"id": "agent-a", "person_name": "Agent A", "model": "test-model"},
        {"id": "agent-b", "person_name": "Agent B", "model": "test-model"},
        {"id": "aggregation_lisa", "person_name": "Lisa", "model": "test-model", "system_prompt": "Lisa"},
        {"id": "executive_decision_architect", "person_name": "Robert", "model": "test-model", "system_prompt": "Robert"},
        {"id": "gpts_critical_reviewer", "person_name": "Reviewer", "model": "test-model", "system_prompt": "Reviewer"},
        {"id": "labor_law_hr_governance", "person_name": "Sandy Hooks", "model": "test-model", "system_prompt": "Sandy"},
    ]
    return m


@pytest.fixture
def mock_sync_obsidian():
    """Mock _sync_task_to_obsidian — gibt Fake-Pfad zurück."""
    m = Mock()
    m.return_value = "/fake/obsidian/task.md"
    return m


@pytest.fixture
def mock_trigger_sandy():
    """Mock _trigger_sandy_staffing_nomination — AsyncMock."""
    return AsyncMock()


@pytest.fixture
def mock_fan_in():
    """Mock _fan_in_maybe_start_synthesis — AsyncMock."""
    return AsyncMock()


@pytest.fixture
def mock_paths():
    """Pfad-Konfiguration für Tests."""
    return {"OBSIDIAN_VAULT_DIR": "/fake/obsidian", "WORKSPACE_DIR": "/fake/workspace"}


@pytest.fixture
def mock_folder_namer():
    """Mock project_folder_name — gibt leeren String zurück."""
    m = Mock()
    m.return_value = ""
    return m


@pytest.fixture
def mock_set_status():
    """Mock _set_agent_profile_status — tut nichts."""
    return Mock()


@pytest.fixture
def mock_invalidate_profiles():
    """Mock invalidate_hermes_profiles_cache — tut nichts."""
    return Mock()


@pytest.fixture
def mock_rolling_backup():
    """Mock create_rolling_backup — tut nichts."""
    return Mock()


@pytest.fixture
def mock_tg_send_doc():
    """Mock send_telegram_document — gibt True zurück."""
    m = Mock()
    m.return_value = True
    return m


@pytest.fixture
def mock_tg_send_msg():
    """Mock send_telegram_message — gibt None zurück."""
    return Mock()


@pytest.fixture
def mock_build_dossier():
    """Mock build_dossier_from_report — gibt Fake-Pfad zurück."""
    m = Mock()
    m.return_value = "/fake/dossier.pdf"
    return m


@pytest.fixture
def mock_create_decision():
    """Mock create_decision — gibt Fake-Decision zurück."""
    m = Mock()
    m.return_value = {"task_id": "dec-123"}
    return m


@pytest.fixture
def mock_finalize_approval():
    """Mock _finalize_synthesis_after_approval — AsyncMock."""
    return AsyncMock()


@pytest.fixture
def mock_tg_ping():
    """Mock _tg_ping_synthesis — tut nichts."""
    return Mock()


@pytest.fixture
def mock_paperclip_hire():
    """Mock _paperclip_hire_profile_by_id — gibt True zurück."""
    m = Mock()
    m.return_value = True
    return m


@pytest.fixture
def mock_write_mc_atomic():
    """Mock _write_mc_atomic — tut nichts."""
    return Mock()


@pytest.fixture
def mock_run_cascade():
    """Mock _run_synthesis_cascade — AsyncMock."""
    return AsyncMock()


# ============================================================================
# 1. _execute_mission_control_task
# ============================================================================

class TestExecuteMissionControlTask:
    """Tests für _execute_mission_control_task."""

    @pytest.mark.asyncio
    async def test_happy_path_existing_task(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_sync_obsidian, mock_trigger_sandy, mock_fan_in
    ):
        """Happy Path: Task existiert, Dispatcher liefert Antwort, Task wird completed."""
        # Setup: Task in Store
        task_id = "task-123"
        mock_load_mc.return_value = {
            "tasks": [{
                "id": task_id,
                "title": "Test Task",
                "agent_id": "micha",
                "agent_name": "Michael Keller",
                "capture_input": "Do something",
                "status": "approval",
            }],
            "metrics": {},
            "audit_logs": []
        }
        mock_dispatcher.dispatch_to_omniroute_or_container.return_value = {"content": "Done"}

        await _execute_mission_control_task(
            task_id,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            sync_obsidian=mock_sync_obsidian,
            trigger_sandy=mock_trigger_sandy,
            fan_in=mock_fan_in,
        )

        # Assertions
        mock_load_mc.assert_called()
        assert mock_save_mc.call_count >= 2  # einmal vor Dispatch, einmal im finally
        # Task sollte completed sein
        saved_data = mock_save_mc.call_args_list[-1][0][0]  # letzter save_mc call
        task = next(t for t in saved_data["tasks"] if t["id"] == task_id)
        assert task["status"] == "completed"
        assert task["result_summary"] == "Done"
        mock_ticker.assert_called()

    @pytest.mark.asyncio
    async def test_task_not_found_returns_early(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_sync_obsidian, mock_trigger_sandy, mock_fan_in
    ):
        """Failure Path: Task-ID existiert nicht — Funktion kehrt still zurück, kein Dispatch."""
        mock_load_mc.return_value = {"tasks": [], "metrics": {}, "audit_logs": []}

        await _execute_mission_control_task(
            "nonexistent",
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            sync_obsidian=mock_sync_obsidian,
            trigger_sandy=mock_trigger_sandy,
            fan_in=mock_fan_in,
        )

        # Dispatcher darf NICHT aufgerufen werden
        mock_dispatcher.dispatch_to_omniroute_or_container.assert_not_called()
        # save_mc wird NICHT aufgerufen (early return vor try-block)
        mock_save_mc.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatcher_raises_exception_task_marked_failed(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_sync_obsidian, mock_trigger_sandy, mock_fan_in
    ):
        """Failure Path: Dispatcher wirft Exception — Task wird failed, NICHT stillschweigend completed."""
        task_id = "task-456"
        mock_load_mc.return_value = {
            "tasks": [{
                "id": task_id,
                "title": "Fail Task",
                "agent_id": "micha",
                "agent_name": "Michael Keller",
                "capture_input": "Will fail",
                "status": "approval",
            }],
            "metrics": {},
            "audit_logs": []
        }
        mock_dispatcher.dispatch_to_omniroute_or_container.side_effect = Exception("Network down")

        await _execute_mission_control_task(
            task_id,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            sync_obsidian=mock_sync_obsidian,
            trigger_sandy=mock_trigger_sandy,
            fan_in=mock_fan_in,
        )

        # Task muss failed sein, NICHT completed
        saved_data = mock_save_mc.call_args_list[-1][0][0]
        task = next(t for t in saved_data["tasks"] if t["id"] == task_id)
        assert task["status"] == "failed"
        assert "Fehler" in task["result_summary"]
        # ticker muss Fehler geloggt haben
        error_ticks = [c for c in mock_ticker.call_args_list if "fehlgeschlagen" in str(c)]
        assert len(error_ticks) >= 1

    @pytest.mark.asyncio
    async def test_dispatcher_returns_error_content_task_marked_failed(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_sync_obsidian, mock_trigger_sandy, mock_fan_in
    ):
        """Failure Path: Dispatcher liefert 'Fehler' im Content — Task wird failed."""
        task_id = "task-789"
        mock_load_mc.return_value = {
            "tasks": [{
                "id": task_id,
                "title": "Error Task",
                "agent_id": "micha",
                "agent_name": "Michael Keller",
                "capture_input": "Error",
                "status": "approval",
            }],
            "metrics": {},
            "audit_logs": []
        }
        mock_dispatcher.dispatch_to_omniroute_or_container.return_value = {"content": "Fehler: Model unavailable"}

        await _execute_mission_control_task(
            task_id,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            sync_obsidian=mock_sync_obsidian,
            trigger_sandy=mock_trigger_sandy,
            fan_in=mock_fan_in,
        )

        saved_data = mock_save_mc.call_args_list[-1][0][0]
        task = next(t for t in saved_data["tasks"] if t["id"] == task_id)
        assert task["status"] == "failed"


# ============================================================================
# 2. _paperclip_hire_profile_by_id
# ============================================================================

class TestPaperclipHireProfileById:
    """Tests für _paperclip_hire_profile_by_id."""

    def test_happy_path_profile_found(
        self, mock_set_status, mock_ticker
    ):
        """Happy Path: Profil existiert, Status wird gesetzt, ticker gerufen."""
        profiles = [{"id": "agent-1", "person_name": "Agent One"}]
        result = _paperclip_hire_profile_by_id(
            "agent-1", profiles, "task-1",
            set_status=mock_set_status,
            ticker=mock_ticker,
        )
        assert result is True
        mock_set_status.assert_called_once_with("agent-1", "active", "task-1")
        mock_ticker.assert_called_once()
        assert "Agent One" in mock_ticker.call_args[0][1]

    def test_failure_profile_not_found(
        self, mock_set_status, mock_ticker
    ):
        """Failure Path: Profil-ID unbekannt — set_status wird trotzdem versucht, ticker nutzt ID als Namen."""
        profiles = [{"id": "other", "person_name": "Other"}]
        result = _paperclip_hire_profile_by_id(
            "unknown", profiles, "",
            set_status=mock_set_status,
            ticker=mock_ticker,
        )
        # Funktion gibt True zurück (set_status hat keine Exception geworfen)
        assert result is True
        mock_set_status.assert_called_once_with("unknown", "active", "")
        mock_ticker.assert_called_once()
        assert "unknown" in mock_ticker.call_args[0][1]

    def test_failure_set_status_raises_returns_false(
        self, mock_set_status, mock_ticker
    ):
        """Failure Path: set_status wirft Exception — Funktion gibt False zurück, warning geloggt."""
        mock_set_status.side_effect = Exception("FS error")
        profiles = [{"id": "agent-1", "person_name": "Agent One"}]

        result = _paperclip_hire_profile_by_id(
            "agent-1", profiles, "task-1",
            set_status=mock_set_status,
            ticker=mock_ticker,
        )
        assert result is False
        mock_ticker.assert_not_called()  # ticker nur im Erfolgsfall


# ============================================================================
# 3. _set_agent_profile_status
# ============================================================================

class TestSetAgentProfileStatus:
    """Tests für _set_agent_profile_status."""

    def test_happy_path_updates_status_and_backup(
        self, mock_rolling_backup, mock_invalidate_profiles, tmp_path
    ):
        """Happy Path: Profil existiert, Status wird aktualisiert, Backup erstellt, Cache invalidiert."""
        # Echte agent_profiles.json im tmp_path
        profiles_file = tmp_path / "agent_profiles.json"
        profiles_file.write_text(json.dumps([
            {"id": "agent-1", "status": "standby", "current_task_id": "old"}
        ]), encoding="utf-8")

        # Patch __file__ to point to tmp_path
        with patch("archon.core.orchestration.os.path.dirname", return_value=str(tmp_path)):
            _set_agent_profile_status(
                "agent-1", "active", "task-new",
                rolling_backup=mock_rolling_backup,
                invalidate_profiles=mock_invalidate_profiles,
            )

        # Prüfen: Datei aktualisiert
        updated = json.loads(profiles_file.read_text(encoding="utf-8"))
        assert updated[0]["status"] == "active"
        assert updated[0]["current_task_id"] == "task-new"
        mock_rolling_backup.assert_called_once()
        mock_invalidate_profiles.assert_called_once()

    def test_happy_path_standby_removes_task_id(
        self, mock_rolling_backup, mock_invalidate_profiles, tmp_path
    ):
        """Happy Path: Status auf standby — current_task_id wird entfernt."""
        profiles_file = tmp_path / "agent_profiles.json"
        profiles_file.write_text(json.dumps([
            {"id": "agent-1", "status": "active", "current_task_id": "task-1"}
        ]), encoding="utf-8")

        with patch("archon.core.orchestration.os.path.dirname", return_value=str(tmp_path)):
            _set_agent_profile_status(
                "agent-1", "standby", "",
                rolling_backup=mock_rolling_backup,
                invalidate_profiles=mock_invalidate_profiles,
            )

        updated = json.loads(profiles_file.read_text(encoding="utf-8"))
        assert updated[0]["status"] == "standby"
        assert "current_task_id" not in updated[0]

    def test_failure_file_not_exists_returns_early(
        self, mock_rolling_backup, mock_invalidate_profiles, tmp_path
    ):
        """Failure Path: agent_profiles.json existiert nicht — frühzeitiger Return, keine Side-Effects."""
        with patch("archon.core.orchestration.os.path.dirname", return_value=str(tmp_path)):
            _set_agent_profile_status(
                "agent-1", "active", "task-1",
                rolling_backup=mock_rolling_backup,
                invalidate_profiles=mock_invalidate_profiles,
            )

        mock_rolling_backup.assert_not_called()
        mock_invalidate_profiles.assert_not_called()

    def test_failure_profile_id_not_found_no_changes(
        self, mock_rolling_backup, mock_invalidate_profiles, tmp_path
    ):
        """Failure Path: Profil-ID nicht in Datei — keine Änderungen, keine Backups."""
        profiles_file = tmp_path / "agent_profiles.json"
        profiles_file.write_text(json.dumps([
            {"id": "other", "status": "standby"}
        ]), encoding="utf-8")

        with patch("archon.core.orchestration.os.path.dirname", return_value=str(tmp_path)):
            _set_agent_profile_status(
                "missing", "active", "task-1",
                rolling_backup=mock_rolling_backup,
                invalidate_profiles=mock_invalidate_profiles,
            )

        mock_rolling_backup.assert_not_called()
        mock_invalidate_profiles.assert_not_called()

    def test_failure_json_decode_error_warning(
        self, mock_rolling_backup, mock_invalidate_profiles, tmp_path, caplog
    ):
        """Failure Path: Korrupte JSON — Warning geloggt, keine Side-Effects."""
        profiles_file = tmp_path / "agent_profiles.json"
        profiles_file.write_text("not valid json", encoding="utf-8")

        with patch("archon.core.orchestration.os.path.dirname", return_value=str(tmp_path)):
            _set_agent_profile_status(
                "agent-1", "active", "task-1",
                rolling_backup=mock_rolling_backup,
                invalidate_profiles=mock_invalidate_profiles,
            )

        mock_rolling_backup.assert_not_called()
        assert any("Fehler beim Status-Update" in r.message for r in caplog.records)


# ============================================================================
# 4. _trigger_sandy_staffing_nomination
# ============================================================================

class TestTriggerSandyStaffingNomination:
    """Tests für _trigger_sandy_staffing_nomination."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_subtasks(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paperclip_hire
    ):
        """Happy Path: Sandy nominiert 2 Agenten, Subtasks werden angelegt."""
        parent_task = {"id": "parent-1", "title": "Parent Project", "result_summary": "Strategy"}
        profiles = [
            {"id": "sandy", "person_name": "Sandy Hooks", "model": "test"},
            {"id": "agent-a", "person_name": "Agent A"},
            {"id": "agent-b", "person_name": "Agent B"},
        ]
        # Parent-Task muss in den Daten sein, damit die Funktion sie findet
        mock_load_mc.return_value = {
            "tasks": [parent_task],
            "metrics": {},
            "audit_logs": []
        }
        mock_dispatcher.dispatch_to_omniroute_or_container.return_value = {
            "content": json.dumps({
                "project_title": "Parent Project",
                "nominated_agents": [
                    {"agent_id": "agent-a", "role": "Developer", "mandate": "Build it"},
                    {"agent_id": "agent-b", "role": "Designer", "mandate": "Design it"},
                ]
            })
        }

        await _trigger_sandy_staffing_nomination(
            parent_task, profiles,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paperclip_hire=mock_paperclip_hire,
        )

        # 2 Subtasks angelegt
        saved = mock_save_mc.call_args[0][0]
        subtasks = [t for t in saved["tasks"] if t.get("parent_project_id") == "parent-1"]
        assert len(subtasks) == 2
        assert all(s["status"] == "approval" for s in subtasks)
        # Parent hat subtask_ids und phase=staffing
        parent = next(t for t in saved["tasks"] if t["id"] == "parent-1")
        assert len(parent["subtask_ids"]) == 2
        assert parent["phase"] == "staffing"
        mock_paperclip_hire.assert_called()

    @pytest.mark.asyncio
    async def test_failure_dispatcher_exception_logged_no_subtasks(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paperclip_hire, caplog
    ):
        """Failure Path: Dispatcher wirft Exception — keine Subtasks, Warning geloggt."""
        mock_load_mc.return_value = {"tasks": [{"id": "parent-1", "title": "Parent"}], "metrics": {}, "audit_logs": []}
        mock_dispatcher.dispatch_to_omniroute_or_container.side_effect = Exception("API down")

        await _trigger_sandy_staffing_nomination(
            {"id": "parent-1", "title": "Parent"},
            [{"id": "sandy", "person_name": "Sandy"}],
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paperclip_hire=mock_paperclip_hire,
        )

        # save_mc wird im except-Block nicht aufgerufen (Exception wird geloggt und Funktion endet)
        # Prüfen dass Warning geloggt wurde
        assert any("Fehler bei Sandy-Staffing" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_failure_invalid_json_no_subtasks(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paperclip_hire
    ):
        """Failure Path: Sandy liefert ungültiges JSON — keine Subtasks."""
        mock_load_mc.return_value = {"tasks": [], "metrics": {}, "audit_logs": []}
        mock_dispatcher.dispatch_to_omniroute_or_container.return_value = {"content": "not json"}

        await _trigger_sandy_staffing_nomination(
            {"id": "parent-1", "title": "Parent"},
            [{"id": "sandy", "person_name": "Sandy"}],
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paperclip_hire=mock_paperclip_hire,
        )

        saved = mock_save_mc.call_args[0][0]
        assert len(saved["tasks"]) == 0

    @pytest.mark.asyncio
    async def test_failure_empty_nominated_agents_no_subtasks(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paperclip_hire
    ):
        """Failure Path: nominated_agents leer — keine Subtasks."""
        mock_load_mc.return_value = {"tasks": [], "metrics": {}, "audit_logs": []}
        mock_dispatcher.dispatch_to_omniroute_or_container.return_value = {
            "content": json.dumps({"project_title": "X", "nominated_agents": []})
        }

        await _trigger_sandy_staffing_nomination(
            {"id": "parent-1", "title": "Parent"},
            [{"id": "sandy", "person_name": "Sandy"}],
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paperclip_hire=mock_paperclip_hire,
        )

        saved = mock_save_mc.call_args[0][0]
        assert len(saved["tasks"]) == 0


# ============================================================================
# 5. _finalize_synthesis_after_approval
# ============================================================================

class TestFinalizeSynthesisAfterApproval:
    """Tests für _finalize_synthesis_after_approval."""

    @pytest.mark.asyncio
    async def test_happy_path_finalizes_parent(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_paths, mock_folder_namer, mock_set_status, mock_tg_ping, tmp_path
    ):
        """Happy Path: Parent existiert, wird finalisiert, Demobilisierung läuft."""
        parent_pid = "parent-1"
        draft_path = "/fake/draft.md"
        synthese = "Final synthesis"
        approver = "Robert: OK"

        # Setup: Parent + 2 Subtasks (einer Fachagent, einer Stammagent)
        mock_load_mc.return_value = {
            "tasks": [
                {"id": parent_pid, "title": "Parent", "status": "in_progress", "phase": "staffing",
                 "synthesis_draft_path": draft_path, "target_action": "deploy",
                 "parent_project_id": None, "parent_task_id": None},
                {"id": "sub-1", "title": "Sub 1", "agent_id": "agent-a", "agent_name": "Agent A",
                 "status": "completed", "parent_project_id": parent_pid, "artifact_path": "/fake/a.md"},
                {"id": "sub-2", "title": "Sub 2", "agent_id": "robert", "agent_name": "Robert",
                 "status": "completed", "parent_project_id": parent_pid},
            ],
            "metrics": {}, "audit_logs": []
        }
        mock_folder_namer.return_value = "project-folder"
        mock_dispatcher.trigger_n8n_execution.return_value = {"status": "ok"}

        await _finalize_synthesis_after_approval(
            parent_pid, draft_path, synthese, approver,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            set_status=mock_set_status,
            tg_ping=mock_tg_ping,
        )

        saved = mock_save_mc.call_args_list[-1][0][0]
        parent = next(t for t in saved["tasks"] if t["id"] == parent_pid)
        assert parent["status"] == "completed"
        assert parent["phase"] == "completed"
        assert parent["synthesis_finalized"] is True
        assert parent["artifact_path"].endswith("final_beschlussvorlage.md")
        # Demobilisierung: agent-a auf standby, robert NICHT
        mock_set_status.assert_called_with("agent-a", "standby")
        # n8n trigger
        mock_dispatcher.trigger_n8n_execution.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_parent_not_found_returns_early(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_paths, mock_folder_namer, mock_set_status, mock_tg_ping, caplog
    ):
        """Failure Path: Parent nicht gefunden — frühzeitiger Return, Warning."""
        mock_load_mc.return_value = {"tasks": [], "metrics": {}, "audit_logs": []}

        await _finalize_synthesis_after_approval(
            "missing", "/fake/draft.md", "synth", "note",
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            set_status=mock_set_status,
            tg_ping=mock_tg_ping,
        )

        assert any("Parent 'missing' beim Finalisieren nicht gefunden" in r.message for r in caplog.records)
        mock_dispatcher.trigger_n8n_execution.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_already_finalized_returns_early(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_paths, mock_folder_namer, mock_set_status, mock_tg_ping
    ):
        """Failure Path: Parent bereits finalisiert — frühzeitiger Return."""
        mock_load_mc.return_value = {
            "tasks": [{
                "id": "parent-1", "title": "Parent", "synthesis_finalized": True
            }],
            "metrics": {}, "audit_logs": []
        }

        await _finalize_synthesis_after_approval(
            "parent-1", "/fake/draft.md", "synth", "note",
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            set_status=mock_set_status,
            tg_ping=mock_tg_ping,
        )

        mock_dispatcher.trigger_n8n_execution.assert_not_called()
        # save_mc wird im finally trotzdem aufgerufen

    @pytest.mark.asyncio
    async def test_failure_n8n_exception_does_not_block(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_paths, mock_folder_namer, mock_set_status, mock_tg_ping, caplog
    ):
        """Failure Path: n8n wirft Exception — Finalisierung läuft trotzdem durch, Warning."""
        mock_load_mc.return_value = {
            "tasks": [{
                "id": "parent-1", "title": "Parent", "status": "in_progress", "phase": "staffing",
                "synthesis_draft_path": "/fake/draft.md", "target_action": "deploy",
                "parent_project_id": None, "parent_task_id": None,
            }],
            "metrics": {}, "audit_logs": []
        }
        mock_folder_namer.return_value = ""
        mock_dispatcher.trigger_n8n_execution.side_effect = Exception("n8n down")

        await _finalize_synthesis_after_approval(
            "parent-1", "/fake/draft.md", "synth", "note",
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            set_status=mock_set_status,
            tg_ping=mock_tg_ping,
        )

        saved = mock_save_mc.call_args_list[-1][0][0]
        parent = next(t for t in saved["tasks"] if t["id"] == "parent-1")
        assert parent["status"] == "completed"  # trotzdem finalisiert
        assert any("n8n Trigger fehlgeschlagen" in r.message for r in caplog.records)


# ============================================================================
# 6. _fan_in_maybe_start_synthesis
# ============================================================================

class TestFanInMaybeStartSynthesis:
    """Tests für _fan_in_maybe_start_synthesis."""

    @pytest.mark.asyncio
    async def test_happy_path_all_siblings_completed_starts_cascade(
        self, mock_load_mc, mock_write_mc_atomic, mock_run_cascade
    ):
        """Happy Path: Alle Geschwister completed — synthesis_started Flag gesetzt, Cascade gestartet."""
        parent_pid = "parent-1"
        mock_load_mc.return_value = {
            "tasks": [
                {"id": parent_pid, "title": "Parent", "synthesis_started": False},
                {"id": "sub-1", "title": "Sub 1", "parent_project_id": parent_pid, "status": "completed"},
                {"id": "sub-2", "title": "Sub 2", "parent_project_id": parent_pid, "status": "completed"},
            ],
            "metrics": {}, "audit_logs": []
        }

        await _fan_in_maybe_start_synthesis(
            parent_pid,
            load_mc=mock_load_mc,
            write_mc_atomic=mock_write_mc_atomic,
            mc_async_lock=asyncio.Lock(),
            run_cascade=mock_run_cascade,
        )

        # write_mc_atomic wurde mit gesetztem Flag aufgerufen
        mock_write_mc_atomic.assert_called()
        written = mock_write_mc_atomic.call_args[0][0]
        parent = next(t for t in written["tasks"] if t["id"] == parent_pid)
        assert parent["synthesis_started"] is True
        # Cascade gestartet
        mock_run_cascade.assert_called_once_with(parent_pid)

    @pytest.mark.asyncio
    async def test_failure_not_all_completed_no_cascade(
        self, mock_load_mc, mock_write_mc_atomic, mock_run_cascade
    ):
        """Failure Path: Ein Geschwister noch nicht completed — kein Cascade."""
        parent_pid = "parent-1"
        mock_load_mc.return_value = {
            "tasks": [
                {"id": parent_pid, "title": "Parent", "synthesis_started": False},
                {"id": "sub-1", "title": "Sub 1", "parent_project_id": parent_pid, "status": "completed"},
                {"id": "sub-2", "title": "Sub 2", "parent_project_id": parent_pid, "status": "in_progress"},  # NICHT completed
            ],
            "metrics": {}, "audit_logs": []
        }

        await _fan_in_maybe_start_synthesis(
            parent_pid,
            load_mc=mock_load_mc,
            write_mc_atomic=mock_write_mc_atomic,
            mc_async_lock=asyncio.Lock(),
            run_cascade=mock_run_cascade,
        )

        mock_write_mc_atomic.assert_not_called()
        mock_run_cascade.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_already_started_no_duplicate_cascade(
        self, mock_load_mc, mock_write_mc_atomic, mock_run_cascade
    ):
        """Failure Path: synthesis_started bereits True — kein doppelter Start."""
        parent_pid = "parent-1"
        mock_load_mc.return_value = {
            "tasks": [
                {"id": parent_pid, "title": "Parent", "synthesis_started": True},  # BEREITS GESTARTET
                {"id": "sub-1", "title": "Sub 1", "parent_project_id": parent_pid, "status": "completed"},
            ],
            "metrics": {}, "audit_logs": []
        }

        await _fan_in_maybe_start_synthesis(
            parent_pid,
            load_mc=mock_load_mc,
            write_mc_atomic=mock_write_mc_atomic,
            mc_async_lock=asyncio.Lock(),
            run_cascade=mock_run_cascade,
        )

        mock_write_mc_atomic.assert_not_called()
        mock_run_cascade.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_parent_missing_no_cascade(
        self, mock_load_mc, mock_write_mc_atomic, mock_run_cascade
    ):
        """Failure Path: Parent nicht in Tasks — frühzeitiger Return."""
        mock_load_mc.return_value = {
            "tasks": [
                {"id": "sub-1", "title": "Sub 1", "parent_project_id": "missing", "status": "completed"},
            ],
            "metrics": {}, "audit_logs": []
        }

        await _fan_in_maybe_start_synthesis(
            "missing",
            load_mc=mock_load_mc,
            write_mc_atomic=mock_write_mc_atomic,
            mc_async_lock=asyncio.Lock(),
            run_cascade=mock_run_cascade,
        )

        mock_write_mc_atomic.assert_not_called()
        mock_run_cascade.assert_not_called()

    @pytest.mark.asyncio
    async def test_failure_load_mc_exception_warning(
        self, mock_load_mc, mock_write_mc_atomic, mock_run_cascade, caplog
    ):
        """Failure Path: load_mc wirft Exception — Warning geloggt."""
        mock_load_mc.side_effect = Exception("DB error")

        await _fan_in_maybe_start_synthesis(
            "parent-1",
            load_mc=mock_load_mc,
            write_mc_atomic=mock_write_mc_atomic,
            mc_async_lock=asyncio.Lock(),
            run_cascade=mock_run_cascade,
        )

        assert any("Synthese-Check fehlgeschlagen" in r.message for r in caplog.records)


# ============================================================================
# 7. _tg_ping_synthesis
# ============================================================================

class TestTgPingSynthesis:
    """Tests für _tg_ping_synthesis."""

    def test_happy_path_sends_document(
        self, mock_tg_send_doc, mock_tg_send_msg, mock_build_dossier
    ):
        """Happy Path: Dossier existiert, send_telegram_document gibt True — message NICHT gesendet."""
        _tg_ping_synthesis(
            "Parent Title", "parent-1", "Synthesis text", "/fake/draft.md",
            app_id="app-123", dossier_dir="/fake/dossier",
            send_doc=mock_tg_send_doc,
            send_msg=mock_tg_send_msg,
            build_dossier=mock_build_dossier,
        )

        mock_build_dossier.assert_called_once()
        mock_tg_send_doc.assert_called_once()
        # send_msg NICHT aufgerufen, weil doc Erfolg
        mock_tg_send_msg.assert_not_called()

    def test_happy_path_doc_fails_falls_back_to_message(
        self, mock_tg_send_doc, mock_tg_send_msg, mock_build_dossier
    ):
        """Happy Path: send_telegram_document gibt False — Fallback auf send_telegram_message."""
        mock_tg_send_doc.return_value = False

        _tg_ping_synthesis(
            "Parent Title", "parent-1", "Synthesis text", "/fake/draft.md",
            app_id="app-123", dossier_dir="/fake/dossier",
            send_doc=mock_tg_send_doc,
            send_msg=mock_tg_send_msg,
            build_dossier=mock_build_dossier,
        )

        mock_tg_send_doc.assert_called_once()
        mock_tg_send_msg.assert_called_once()

    def test_failure_no_dossier_dir_sends_message_only(
        self, mock_tg_send_doc, mock_tg_send_msg, mock_build_dossier
    ):
        """Failure Path: Kein dossier_dir — nur Text-Message, kein Dokument."""
        _tg_ping_synthesis(
            "Parent Title", "parent-1", "Synthesis text", "/fake/draft.md",
            app_id=None, dossier_dir=None,
            send_doc=mock_tg_send_doc,
            send_msg=mock_tg_send_msg,
            build_dossier=mock_build_dossier,
        )

        mock_build_dossier.assert_not_called()
        mock_tg_send_doc.assert_not_called()
        mock_tg_send_msg.assert_called_once()

    def test_failure_build_dossier_exception_logged_fallback(
        self, mock_tg_send_doc, mock_tg_send_msg, mock_build_dossier, caplog
    ):
        """Failure Path: build_dossier wirft Exception — Warning, Fallback auf Text."""
        mock_build_dossier.side_effect = Exception("Dossier build failed")

        _tg_ping_synthesis(
            "Parent Title", "parent-1", "Synthesis text", "/fake/draft.md",
            app_id="app-123", dossier_dir="/fake/dossier",
            send_doc=mock_tg_send_doc,
            send_msg=mock_tg_send_msg,
            build_dossier=mock_build_dossier,
        )

        assert any("Dossier-Aufbau fehlgeschlagen" in r.message for r in caplog.records)
        mock_tg_send_msg.assert_called_once()


# ============================================================================
# 8. _run_synthesis_cascade
# ============================================================================

class TestRunSynthesisCascade:
    """Tests für _run_synthesis_cascade."""

    @pytest.mark.asyncio
    async def test_happy_path_lisa_robert_approve_finalizes(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paths, mock_folder_namer, mock_build_dossier,
        mock_create_decision, mock_finalize_approval, mock_tg_ping
    ):
        """Happy Path: Lisa liefert Synthese mit Marker, Robert FREIGABE -> finalize_approval."""
        parent_pid = "parent-1"
        mock_load_mc.return_value = {
            "tasks": [
                {"id": parent_pid, "title": "Parent Project", "capture_input": "Original requirement"},
                {"id": "sub-1", "title": "Sub 1", "agent_name": "Agent A", "parent_project_id": parent_pid,
                 "artifact_path": "/fake/a.md", "result_summary": "Result A", "status": "completed"},
                {"id": "sub-2", "title": "Sub 2", "agent_name": "Agent B", "parent_project_id": parent_pid,
                 "artifact_path": "/fake/b.md", "result_summary": "Result B", "status": "completed"},
            ],
            "metrics": {}, "audit_logs": []
        }
        mock_folder_namer.return_value = "project-folder"
        # 3 Calls: Lisa, Reviewer, Robert
        mock_dispatcher.dispatch_to_omniroute_or_container.side_effect = [
            # Lisa call
            {"content": "Synthesis result\nSYNTHESE-BEREIT"},
            # Reviewer call
            {"content": "OK"},
            # Robert call
            {"content": "FREIGABE\nLooks good"},
        ]
        mock_get_profiles.return_value = [
            {"id": "lisa", "person_name": "Lisa", "model": "test", "system_prompt": "Lisa"},
            {"id": "robert", "person_name": "Robert", "model": "test", "system_prompt": "Robert"},
            {"id": "aggregation_lisa", "person_name": "Lisa", "model": "test", "system_prompt": "Lisa"},
            {"id": "executive_decision_architect", "person_name": "Robert", "model": "test", "system_prompt": "Robert"},
            {"id": "gpts_critical_reviewer", "person_name": "Reviewer", "model": "test", "system_prompt": "Reviewer"},
        ]

        await _run_synthesis_cascade(
            parent_pid,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            build_dossier=mock_build_dossier,
            create_decision=mock_create_decision,
            finalize_approval=mock_finalize_approval,
            tg_ping=mock_tg_ping,
        )

        # finalize_approval aufgerufen
        mock_finalize_approval.assert_called_once()
        # Draft angelegt
        saved = mock_save_mc.call_args_list[-1][0][0]
        parent = next(t for t in saved["tasks"] if t["id"] == parent_pid)
        assert parent["synthesis_draft_path"] is not None

    @pytest.mark.asyncio
    async def test_failure_lisa_no_marker_retry_then_fallback(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paths, mock_folder_namer, mock_build_dossier,
        mock_create_decision, mock_finalize_approval, mock_tg_ping, caplog
    ):
        """Failure Path: Lisa ohne Marker, Repair fehlschlägt -> ungeprüft verwendet."""
        parent_pid = "parent-1"
        mock_load_mc.return_value = {
            "tasks": [
                {"id": parent_pid, "title": "Parent", "capture_input": "Req"},
                {"id": "sub-1", "title": "Sub 1", "agent_name": "A", "parent_project_id": parent_pid,
                 "result_summary": "R", "status": "completed"},
            ],
            "metrics": {}, "audit_logs": []
        }
        mock_folder_namer.return_value = ""
        # 4 Calls: Lisa (1), Lisa repair (2), Reviewer (3), Robert (4)
        mock_dispatcher.dispatch_to_omniroute_or_container.side_effect = [
            {"content": "Synthesis without marker"},
            {"content": "Still no marker"},
            {"content": "OK"},  # Reviewer
            {"content": "FREIGABE\nOK"},  # Robert
        ]
        mock_get_profiles.return_value = [
            {"id": "lisa", "person_name": "Lisa", "model": "test", "system_prompt": "Lisa"},
            {"id": "robert", "person_name": "Robert", "model": "test", "system_prompt": "Robert"},
            {"id": "aggregation_lisa", "person_name": "Lisa", "model": "test", "system_prompt": "Lisa"},
            {"id": "executive_decision_architect", "person_name": "Robert", "model": "test", "system_prompt": "Robert"},
            {"id": "gpts_critical_reviewer", "person_name": "Reviewer", "model": "test", "system_prompt": "Reviewer"},
        ]

        await _run_synthesis_cascade(
            parent_pid,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            build_dossier=mock_build_dossier,
            create_decision=mock_create_decision,
            finalize_approval=mock_finalize_approval,
            tg_ping=mock_tg_ping,
        )

        assert any("Synthese ohne SYNTHESE-BEREIT-Marker" in r.message for r in caplog.records)
        mock_finalize_approval.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_robert_unclear_creates_kanban_decision(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paths, mock_folder_namer, mock_build_dossier,
        mock_create_decision, mock_finalize_approval, mock_tg_ping
    ):
        """Failure Path: Robert Antwort unklar -> Kanban-Entscheidung, NICHT finalize_approval."""
        parent_pid = "parent-1"
        mock_load_mc.return_value = {
            "tasks": [
                {"id": parent_pid, "title": "Parent", "capture_input": "Req"},
                {"id": "sub-1", "title": "Sub 1", "agent_name": "A", "parent_project_id": parent_pid,
                 "result_summary": "R", "status": "completed"},
            ],
            "metrics": {}, "audit_logs": []
        }
        mock_folder_namer.return_value = ""
        # 3 Calls: Lisa, Reviewer, Robert
        mock_dispatcher.dispatch_to_omniroute_or_container.side_effect = [
            {"content": "Synthesis\nSYNTHESE-BEREIT"},
            {"content": "OK"},  # Reviewer
            {"content": "Maybe, let me think..."},  # Robert unklar
        ]
        mock_get_profiles.return_value = [
            {"id": "lisa", "person_name": "Lisa", "model": "test", "system_prompt": "Lisa"},
            {"id": "robert", "person_name": "Robert", "model": "test", "system_prompt": "Robert"},
            {"id": "aggregation_lisa", "person_name": "Lisa", "model": "test", "system_prompt": "Lisa"},
            {"id": "executive_decision_architect", "person_name": "Robert", "model": "test", "system_prompt": "Robert"},
            {"id": "gpts_critical_reviewer", "person_name": "Reviewer", "model": "test", "system_prompt": "Reviewer"},
        ]

        await _run_synthesis_cascade(
            parent_pid,
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            build_dossier=mock_build_dossier,
            create_decision=mock_create_decision,
            finalize_approval=mock_finalize_approval,
            tg_ping=mock_tg_ping,
        )

        # finalize_approval NICHT aufgerufen
        mock_finalize_approval.assert_not_called()
        # create_decision aufgerufen
        mock_create_decision.assert_called_once()
        # Draft angelegt
        saved = mock_save_mc.call_args_list[-1][0][0]
        parent = next(t for t in saved["tasks"] if t["id"] == parent_pid)
        assert parent["synthesis_draft_path"] is not None

    @pytest.mark.asyncio
    async def test_failure_parent_not_found_returns_early(
        self, mock_dispatcher, mock_load_mc, mock_save_mc, mock_ticker,
        mock_get_profiles, mock_paths, mock_folder_namer, mock_build_dossier,
        mock_create_decision, mock_finalize_approval, mock_tg_ping, caplog
    ):
        """Failure Path: Parent nicht gefunden — frühzeitiger Return, Warning."""
        mock_load_mc.return_value = {"tasks": [], "metrics": {}, "audit_logs": []}

        await _run_synthesis_cascade(
            "missing",
            dispatcher=mock_dispatcher,
            load_mc=mock_load_mc,
            save_mc=mock_save_mc,
            ticker=mock_ticker,
            get_profiles=mock_get_profiles,
            paths=mock_paths,
            folder_namer=mock_folder_namer,
            build_dossier=mock_build_dossier,
            create_decision=mock_create_decision,
            finalize_approval=mock_finalize_approval,
            tg_ping=mock_tg_ping,
        )

        assert any("Parent-Task missing nicht gefunden" in r.message for r in caplog.records)
        mock_finalize_approval.assert_not_called()


# ============================================================================
# Integration: Run all tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])